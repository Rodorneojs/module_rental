# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging
from .schedule_states import SCHEDULE_STATE_SELECTION

_logger = logging.getLogger(__name__)

def _coerce_hhmm_to_float(v):
    if v in (None, False, ""): return 0.0
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str) and ":" in v:
        h, m = v.split(":", 1)
        return int(h or 0) + int(m or 0) / 60.0
    try: return float(v)
    except Exception: return 0.0

class RentalTurnParamLine(models.Model):
    _name = "rental.turn.param.line"
    _description = "Turno parametrizado por fecha"
    _order = "date"

    product_id   = fields.Many2one("product.template", required=True, ondelete="cascade", index=True)
    date         = fields.Date(required=True, index=True)

    yacht_id     = fields.Many2one("fleet.vehicle", string="Embarcación")
    season_id    = fields.Many2one("rental.season", string="Temporada")

    # Usar float en horas para cálculos robustos; la UI puede renderizar HH:MM si quieres
    hour_from    = fields.Float(string="Desde (h)", default=8.0)
    hour_to      = fields.Float(string="Hasta (h)",  default=18.0)

    schedule_state = fields.Selection(SCHEDULE_STATE_SELECTION, string="Estados", default="available", index=True)
    quota          = fields.Integer(default=0)

    _sql_constraints = [
        ("uniq_prod_date", "unique(product_id, date)", "Ya existe un turno para esa fecha."),
    ]

    @api.constrains("hour_from", "hour_to")
    def _check_hours(self):
        for r in self:
            if r.hour_from >= r.hour_to:
                raise ValidationError(_("La 'Hora inicio' debe ser menor que la 'Hora final'."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if isinstance(vals.get("hour_from"), str): vals["hour_from"] = _coerce_hhmm_to_float(vals["hour_from"])
            if isinstance(vals.get("hour_to"),   str): vals["hour_to"]   = _coerce_hhmm_to_float(vals["hour_to"])
        return super().create(vals_list)

    def write(self, vals):
        if isinstance(vals.get("hour_from"), str): vals["hour_from"] = _coerce_hhmm_to_float(vals["hour_from"])
        if isinstance(vals.get("hour_to"),   str): vals["hour_to"]   = _coerce_hhmm_to_float(vals["hour_to"])
        return super().write(vals)

    def unlink(self):
        """No borra órdenes aquí; lo hace el mixin en turn_cascade.py.
        Aquí solo resincronizamos el producto tras borrar."""
        products = self.mapped("product_id")
        res = super().unlink()
        for prod in products.sudo():
            try:
                if hasattr(prod, "_sync_blocked_periods_from_turn_dates"):
                    iso = [l.date.isoformat() for l in prod.turn_param_line_ids if l.date]
                    prod._sync_blocked_periods_from_turn_dates(iso)
            except Exception:
                _logger.exception("Error sincronizando bloqueos después de borrar turnos")
        return res
