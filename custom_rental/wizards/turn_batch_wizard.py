# -*- coding: utf-8 -*-
import json
import logging
from datetime import time as dt_time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.schedule_states import SCHEDULE_STATE_SELECTION

_logger = logging.getLogger(__name__)

# -----------------------------
# Helpers de conversión de hora
# -----------------------------
def _coerce_hhmm_to_float(v):
    """Convierte '08:00'/'18:30'/8/8.5 -> float horas (8.0/18.5). None si no se puede."""
    if v in (None, False, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if ":" in s:
            try:
                h, m, *rest = s.split(":")
                h = int(h or 0)
                m = int(m or 0)
                return h + (m / 60.0)
            except Exception:
                pass
        try:
            return float(s)
        except Exception:
            return None
    return None


def _float_to_hhmm(v):
    """8.0 -> '08:00', 18.5 -> '18:30'"""
    if v in (None, False, ""):
        v = 0.0
    minutes = int(round(float(v) * 60))
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _adapt_hour_for(model_or_record, field_name, v, default=0.0):
    """
    Devuelve el valor de hora adecuado según el tipo del campo en el modelo destino:
    - Si el campo es Float -> float (8.0)
    - Si es Char/Selection/etc. -> 'HH:MM'
    """
    vv = v if v not in (None, False, "") else default
    fields_map = getattr(model_or_record, "_fields", {})
    f = fields_map.get(field_name)
    if f and f.type == "float":
        return float(vv)
    else:
        return _float_to_hhmm(vv)


def _to_time(val):
    """Acepta 8.0 / 18.5 / '08:00' / '18:30' / '07:30:00' / datetime.time -> datetime.time"""
    if val in (None, False, ""):
        return None
    if isinstance(val, dt_time):
        return val
    if isinstance(val, (int, float)):
        minutes = int(round(float(val) * 60))
        h = (minutes // 60) % 24
        m = minutes % 60
        return dt_time(h, m)
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            parts = s.split(":")
            h = int(parts[0] or 0) % 24
            m = int((parts[1] if len(parts) > 1 else 0) or 0)
            return dt_time(h, m)
        # si viene '7.5' como string
        try:
            return _to_time(float(s))
        except Exception:
            pass
    raise ValueError(f"Hora inválida: {val!r}")


class RentalTurnBatchWizard(models.TransientModel):
    _name = "rental.turn.batch.wizard"
    _description = "Wizard Registrar Fechas y Parámetros"

    product_id = fields.Many2one("product.template", required=True, string="Product", readonly=True)
    yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    season_id = fields.Many2one("rental.season", string="Temporada (Zona)")

    # Campos de hora como Float (input amigable con widget="float_time")
    hour_from = fields.Float(string="Hora desde", default=8.0)    # 8.0 = 08:00
    hour_to   = fields.Float(string="Hora hasta",  default=18.0)   # 18.0 = 18:00

    quota = fields.Integer(string="Cuota", default=0)

    # CSV de fechas seleccionadas por el usuario (el widget escribe aquí)
    wizard_available_dates = fields.Text(string="Calendario (selección)")
    # Vista auxiliar (no se muestra)
    line_ids = fields.One2many("rental.turn.batch.wizard.line", "wizard_id", string="Fechas seleccionadas")

    # NUEVO: JSON con días ocupados 'YYYY-MM-DD' para bloquear en UI y filtrar en backend
    disabled_dates_json = fields.Text(readonly=True)

    # -----------------------------
    # Utilidades para días ocupados
    # -----------------------------
    def _compute_disabled_days_list(self, prod_id, yacht_id, season_id, hf_float, ht_float):
        """Devuelve lista de strings YYYY-MM-DD a bloquear en UI para esa combinación."""
        Line = self.env["rental.turn.param.line"].sudo()
        recs = Line.search([("product_id", "=", prod_id)])
        days = set()
        for r in recs:
            # filtrar por embarcación/temporada si aplica
            if yacht_id and (r.yacht_id.id or False) != yacht_id:
                continue
            if season_id and (r.season_id.id or False) != season_id:
                continue
            # filtrar por horas si quieres unicidad por franja
            rf = _coerce_hhmm_to_float(r.hour_from) or 0.0
            rt = _coerce_hhmm_to_float(r.hour_to) or 0.0
            if hf_float is not None and rf != float(hf_float):
                continue
            if ht_float is not None and rt != float(ht_float):
                continue
            if r.date:
                days.add(r.date.isoformat())
        return sorted(days)

    # -----------------------------
    # Defaults
    # -----------------------------
    @api.model
    def default_get(self, fields_list):
        # 1) Sanea el context ANTES de llamar a super() para evitar el crash de Float
        ctx = dict(self.env.context or {})
        for key in ("hour_from", "hour_to", "break_from", "break_to"):
            dk = f"default_{key}"
            if dk in ctx:
                from_value = ctx.get(dk)
                coerced = _coerce_hhmm_to_float(from_value)
                if coerced is not None:
                    ctx[dk] = coerced
                else:
                    ctx.pop(dk, None)

        self_ctx = self.with_context(ctx)

        # 2) Llama a super() con el context ya corregido
        vals = super(RentalTurnBatchWizard, self_ctx).default_get(fields_list)

        # 3) Fechas sugeridas (lo que ya tenías)
        csv_ctx = self_ctx.env.context.get("default_wizard_available_dates")
        if csv_ctx:
            vals.setdefault("wizard_available_dates", csv_ctx)
        elif vals.get("product_id"):
            prod = self_ctx.env["product.template"].browse(vals["product_id"])
            csv_text = ", ".join([l.date.isoformat() for l in prod.turn_param_line_ids if l.date])
            vals.setdefault("wizard_available_dates", csv_text)

        # 4) NUEVO: días bloqueados por producto/filtros actuales
        prod_id = vals.get("product_id") or ctx.get("default_product_id")
        hf = vals.get("hour_from", ctx.get("default_hour_from", 8.0))
        ht = vals.get("hour_to",   ctx.get("default_hour_to", 18.0))
        yacht_id = vals.get("yacht_id") or ctx.get("default_yacht_id") or False
        season_id = vals.get("season_id") or ctx.get("default_season_id") or False

        if prod_id:
            days = self._compute_disabled_days_list(
                prod_id,
                yacht_id,
                season_id,
                _coerce_hhmm_to_float(hf),
                _coerce_hhmm_to_float(ht),
            )
            vals["disabled_dates_json"] = json.dumps(days)

        return vals

    # Recalcular bloqueos si cambian filtros
    @api.onchange("product_id", "yacht_id", "season_id", "hour_from", "hour_to")
    def _onchange_recompute_disabled(self):
        for wiz in self:
            if not wiz.product_id:
                wiz.disabled_dates_json = "[]"
                continue
            days = wiz._compute_disabled_days_list(
                wiz.product_id.id,
                wiz.yacht_id.id or False,
                wiz.season_id.id or False,
                _coerce_hhmm_to_float(wiz.hour_from),
                _coerce_hhmm_to_float(wiz.hour_to),
            )
            wiz.disabled_dates_json = json.dumps(days)

    # Si el usuario pega CSV a mano, quita los bloqueados
    @api.onchange("wizard_available_dates")
    def _onchange_wizard_available_dates(self):
        for wiz in self:
            csv = wiz.wizard_available_dates or ""
            try:
                disabled = set(json.loads(wiz.disabled_dates_json or "[]"))
            except Exception:
                disabled = set()
            all_dates = sorted({s.strip() for s in csv.split(",") if s.strip()})
            allowed_dates = [d for d in all_dates if d not in disabled]
            wiz.line_ids = [(5, 0, 0)] + [(0, 0, {"date": d}) for d in allowed_dates]

    # -----------------------------
    # Confirmar: A N E X A R sin borrar
    # -----------------------------
    def action_confirm(self):
        """AGREGAR turnos (append) sin borrar ni reemplazar los existentes."""
        self.ensure_one()
        prod = self.product_id.sudo()
        Line = self.env["rental.turn.param.line"].sudo()

        try:
            # 1) Persistir defaults en product.template (opcional, no afecta líneas)
            with self.env.cr.savepoint():
                prod.write({
                    "turn_yacht_id": self.yacht_id.id or False,
                    "nav_season_id": self.season_id.id or False,
                    "turn_hour_from": _adapt_hour_for(prod, "turn_hour_from", self.hour_from or 8.0, default=8.0),
                    "turn_hour_to":   _adapt_hour_for(prod, "turn_hour_to",   self.hour_to   or 18.0, default=18.0),
                    "turn_quota": self.quota or 0,
                })

            # 2) Construir fechas a crear, saltando bloqueadas y duplicados exactos
            selected_dates = sorted({fields.Date.to_date(l.date) for l in self.line_ids if l.date})
            if not selected_dates:
                raise UserError(_("Debes seleccionar al menos una fecha."))

            # Bloqueadas (UI) también en backend
            try:
                disabled_ui = set(json.loads(self.disabled_dates_json or "[]"))
            except Exception:
                disabled_ui = set()
            selected_dates = [d for d in selected_dates if d.isoformat() not in disabled_ui]

            wizard_hf = float(self.hour_from or 8.0)
            wizard_ht = float(self.hour_to   or 18.0)
            season_id = self.season_id.id or False
            yacht_id  = self.yacht_id.id  or False

            existing = Line.search([
                ("product_id", "=", prod.id),
                ("date", "in", selected_dates),
            ])
            existing_keys = {
                (
                    rec.date,
                    _coerce_hhmm_to_float(rec.hour_from) or 0.0,
                    _coerce_hhmm_to_float(rec.hour_to)   or 0.0,
                    rec.season_id.id or False,
                    rec.yacht_id.id  or False,
                )
                for rec in existing
            }

            vals_common = {
                "product_id": prod.id,
                "yacht_id": yacht_id,
                "season_id": season_id,
                "hour_from": _adapt_hour_for(Line, "hour_from", wizard_hf, default=8.0),
                "hour_to":   _adapt_hour_for(Line, "hour_to",   wizard_ht, default=18.0),
                "quota": self.quota or 0,
            }

            to_create = []
            for d in selected_dates:
                key = (d, wizard_hf, wizard_ht, season_id, yacht_id)
                if key in existing_keys:
                    continue
                to_create.append(dict(vals_common, date=d))

            if to_create:
                Line.create(to_create)

            # 3) Sincronizar (si aplica en tu módulo)
            iso_dates = [d.isoformat() for d in selected_dates]
            with self.env.cr.savepoint():
                prod._sync_blocked_periods_from_turn_dates(iso_dates)

            raw_tz = (self.env.user.tz or self.env.context.get('tz') or 'UTC')
            from ..utils.datetime_tools import normalize_tz_name as _norm
            user_tz = _norm(raw_tz)
            with self.env.cr.savepoint():
                prod.with_context(tz=user_tz)._ensure_turn_orders(iso_dates)

        except Exception as e:
            _logger.exception("Error general al confirmar el wizard de turnos")
            raise UserError(_("No se pudieron registrar los turnos.\nDetalle técnico: %s") % (str(e) or repr(e)))

        return {"type": "ir.actions.act_window_close"}


class RentalTurnBatchWizardLine(models.TransientModel):
    _name = "rental.turn.batch.wizard.line"
    _description = "Wizard - Fecha seleccionada"

    wizard_id = fields.Many2one("rental.turn.batch.wizard", required=True, ondelete="cascade")
    date = fields.Date(required=True)
