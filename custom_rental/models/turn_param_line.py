
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging
from .schedule_states import SCHEDULE_STATE_SELECTION
_logger = logging.getLogger(__name__)

def _coerce_hhmm_to_float(v):
    if v in (None, False, ""): return 0.0
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        s = v.strip()
        if ":" in s:
            try:
                h, m, *_ = s.split(":")
                return int(h or 0) + (int(m or 0) / 60.0)
            except Exception:
                pass
        try:
            return float(s)
        except Exception:
            return 0.0
    return 0.0
class RentalTurnParamLine(models.Model):
    _name = "rental.turn.param.line"
    _description = "Turno parametrizado por fecha"
    _order = "date"

    product_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    date = fields.Date(string="Fecha", required=True, index=True)
    yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    season_id = fields.Many2one("rental.season", string="Temporada (Zona)")
    date       = fields.Date(required=True)
    def _time_selection(self):
        step, vals = 30, []
        for h in range(24):
            for m in range(0, 60, step):
                s = f"{h:02d}:{m:02d}"
                vals.append((s, s))
        return vals

    hour_from  = fields.Float(string="Desde", default=8.0)
    hour_to    = fields.Float(string="Hasta",  default=18.0)

    # Alias editable (misma selección). Es cómodo si en alguna vista prefieres llamar al campo schedule_state
    schedule_state = fields.Selection(
        selection=SCHEDULE_STATE_SELECTION,
        string="Schedule State",
        store=True,
        readonly=False,
    )

    quota = fields.Integer(string="Cuota", default=0)

    _sql_constraints = [
        ("uniq_prod_date", "unique(product_id, date)", "Ya existe un turno para esa fecha."),
    ]

    def unlink(self):
        products = self.mapped("product_id")
        res = super().unlink()
        for prod in products:
            try:
                iso_dates = sorted({l.date.isoformat() for l in prod.turn_param_line_ids if l.date})
                prod._sync_blocked_periods_from_turn_dates(iso_dates)
            except Exception:
                _logger.exception("Error sincronizando tras borrar líneas de turnos")
        return res
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "hour_from" in vals:
                vals["hour_from"] = _coerce_hhmm_to_float(vals["hour_from"])
            if "hour_to" in vals:
                vals["hour_to"] = _coerce_hhmm_to_float(vals["hour_to"])
        return super().create(vals_list)

    def write(self, vals):
        if "hour_from" in vals:
            vals["hour_from"] = _coerce_hhmm_to_float(vals["hour_from"])
        if "hour_to" in vals:
            vals["hour_to"] = _coerce_hhmm_to_float(vals["hour_to"])
        return super().write(vals)
