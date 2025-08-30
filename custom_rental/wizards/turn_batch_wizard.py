# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


# ----------------------------- Helpers de hora -----------------------------
def _coerce_hhmm_to_float(v):
    if v in (None, False, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if ":" in s:
        try:
            hh, mm = s.split(":", 1)
            return int(hh) + int(mm) / 60.0
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


def _float_to_hhmm(v):
    if v in (None, False, ""):
        return ""
    v = float(v)
    h = int(v)
    m = int(round((v - h) * 60.0))
    return f"{h:02d}:{m:02d}"


def _adapt_hour_for(model_or_record, field_name, v, default=None):
    fld = getattr(model_or_record, "_fields", {}).get(field_name)
    v_float = _coerce_hhmm_to_float(v)
    if v_float is None:
        v_float = _coerce_hhmm_to_float(default)
    if not fld:
        return v_float
    if fld.type in ("float", "monetary"):
        return v_float
    if fld.type in ("char", "selection", "text"):
        return _float_to_hhmm(v_float)
    return v_float


# ----------------------------- Wizard -----------------------------
class RentalTurnBatchWizard(models.TransientModel):
    _name = "rental.turn.batch.wizard"
    _description = "Wizard para crear turnos por fechas"

    product_id = fields.Many2one("product.template", required=True, readonly=True, string="Producto")
    yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    season_id = fields.Many2one("rental.season", string="Temporada (Zona)", required=True)

    hour_from = fields.Float(string="Hora inicio", default=8.0)
    hour_to   = fields.Float(string="Hora fin",    default=18.0)
    quota = fields.Integer(string="Cupo", default=0)

    wizard_available_dates = fields.Text(string="Fechas seleccionadas (CSV)")
    line_ids = fields.One2many("rental.turn.batch.wizard.line", "wizard_id", string="Fechas seleccionadas")

    disabled_dates_json = fields.Text(readonly=True)     # días ocupados por el producto
    allowed_start_date  = fields.Date(readonly=True)     # temporada: inicio
    allowed_end_date    = fields.Date(readonly=True)     # temporada: fin

    # -------- utilidades internas --------
    @staticmethod
    def _parse_csv(txt):
        txt = (txt or "").strip()
        if not txt:
            return []
        return [s.strip()[:10] for s in txt.split(",") if s.strip()]

    def _compute_disabled_days_list(self, prod_id):
        """Todas las fechas ya ocupadas por el producto (YYYY-MM-DD)."""
        Line = self.env["rental.turn.param.line"].sudo()
        busy = set()
        for rec in Line.search([("product_id", "=", prod_id)]):
            if rec.date:
                busy.add(fields.Date.to_string(rec.date))
        return sorted(busy)

    def _set_allowed_range_from_season(self, vals, ctx):
        season_id = vals.get("season_id") or ctx.get("default_season_id")
        if season_id:
            season = self.env["rental.season"].sudo().browse(season_id)
            if season and season.exists():
                vals["allowed_start_date"] = season.date_from
                vals["allowed_end_date"] = season.date_to

    # -------- defaults --------
    @api.model
    def default_get(self, fields_list):
        ctx = dict(self.env.context or {})
        for k in ("default_hour_from", "default_hour_to"):
            if k in ctx:
                coerced = _coerce_hhmm_to_float(ctx[k])
                if coerced is not None:
                    ctx[k] = coerced

        self_ctx = self.with_context(ctx)
        vals = super(RentalTurnBatchWizard, self_ctx).default_get(fields_list)

        vals["product_id"] = vals.get("product_id") or ctx.get("default_product_id")
        vals["hour_from"]  = vals.get("hour_from", ctx.get("default_hour_from", 8.0))
        vals["hour_to"]    = vals.get("hour_to",   ctx.get("default_hour_to",   18.0))
        vals["yacht_id"]   = vals.get("yacht_id") or ctx.get("default_yacht_id")
        vals["season_id"]  = vals.get("season_id") or ctx.get("default_season_id")

        prod_id = vals.get("product_id")

        # Nunca preseleccionar; el usuario empieza vacío
        vals["wizard_available_dates"] = ""

        # Deshabilitados (ocupados)
        vals["disabled_dates_json"] = json.dumps(self._compute_disabled_days_list(prod_id)) if prod_id else "[]"

        # Rango permitido
        self._set_allowed_range_from_season(vals, ctx)
        return vals

    # -------- onchange --------
    @api.onchange("product_id", "yacht_id", "season_id", "hour_from", "hour_to")
    def _onchange_recompute_disabled(self):
        for wiz in self:
            wiz.disabled_dates_json = json.dumps(
                wiz._compute_disabled_days_list(wiz.product_id.id)
            ) if wiz.product_id else "[]"

            if wiz.season_id:
                wiz.allowed_start_date = wiz.season_id.date_from
                wiz.allowed_end_date = wiz.season_id.date_to
            else:
                wiz.allowed_start_date = False
                wiz.allowed_end_date = False

            # nunca preseleccionar
            wiz.wizard_available_dates = ""
            wiz._onchange_wizard_available_dates()

    @api.onchange("wizard_available_dates")
    def _onchange_wizard_available_dates(self):
        """Sincroniza line_ids con el CSV, filtrando fuera de rango y días deshabilitados."""
        for wiz in self:
            csv_txt = (wiz.wizard_available_dates or "").strip()
            try:
                disabled = set(json.loads(wiz.disabled_dates_json or "[]"))
            except Exception:
                disabled = set()

            if not csv_txt:
                wiz.line_ids = [(5, 0, 0)]
                continue

            start = wiz.allowed_start_date and fields.Date.to_string(wiz.allowed_start_date)
            end   = wiz.allowed_end_date and fields.Date.to_string(wiz.allowed_end_date)

            def _allowed_and_free(iso):
                if not iso:
                    return False
                if start and iso < start:
                    return False
                if end and iso > end:
                    return False
                if iso in disabled:
                    return False
                return True

            dates = [d.strip() for d in csv_txt.split(",") if d.strip()]
            kept = sorted({d for d in dates if _allowed_and_free(d)})
            wiz.line_ids = [(5, 0, 0)] + [(0, 0, {"date": d}) for d in kept]

    # -------- confirm --------
    def action_confirm(self):
        self.ensure_one()
        prod = self.product_id.sudo()

        # 1) defaults en producto (opcionales)
        with self.env.cr.savepoint():
            vals_to_write = {}
            if "turn_yacht_id" in prod._fields:
                vals_to_write["turn_yacht_id"] = self.yacht_id.id or False
            if "nav_season_id" in prod._fields:
                vals_to_write["nav_season_id"] = self.season_id.id or False
            if "turn_hour_from" in prod._fields:
                vals_to_write["turn_hour_from"] = _adapt_hour_for(prod, "turn_hour_from", self.hour_from, 8.0)
            if "turn_hour_to" in prod._fields:
                vals_to_write["turn_hour_to"] = _adapt_hour_for(prod, "turn_hour_to", self.hour_to, 18.0)
            if "turn_quota" in prod._fields:
                vals_to_write["turn_quota"] = self.quota or 0
            if vals_to_write:
                prod.write(vals_to_write)

        # 2) fechas elegidas: lineas + CSV (fallback tras error previo)
        selected = set()
        for l in self.line_ids:
            if l.date:
                selected.add(fields.Date.to_string(l.date))
        for d in self._parse_csv(self.wizard_available_dates):
            selected.add(d)

        selected = sorted(selected)
        if not selected:
            raise models.UserError(_("Debes seleccionar al menos una fecha."))

        start = self.allowed_start_date and fields.Date.to_string(self.allowed_start_date)
        end   = self.allowed_end_date and fields.Date.to_string(self.allowed_end_date)

        # 3) filtrar fuera de rango y ocupados
        disabled = set(self._compute_disabled_days_list(prod.id))
        selected = [d for d in selected if (not start or d >= start) and (not end or d <= end) and (d not in disabled)]
        if not selected:
            raise models.UserError(_("Todas las fechas están fuera del rango o ya están ocupadas."))

        # 4) crear faltantes
        Line = self.env["rental.turn.param.line"].sudo()
        wizard_hf = _coerce_hhmm_to_float(self.hour_from)
        wizard_ht = _coerce_hhmm_to_float(self.hour_to)
        yacht_id  = self.yacht_id.id or False
        season_id = self.season_id.id or False

        existing = Line.search([
            ("product_id", "=", prod.id),
            ("yacht_id", "=", yacht_id),
            ("season_id", "=", season_id),
            ("date", "in", selected),
        ])
        existing_dates = set()
        for rec in existing:
            rf = _coerce_hhmm_to_float(rec.hour_from)
            rt = _coerce_hhmm_to_float(rec.hour_to)
            if rf == wizard_hf and rt == wizard_ht:
                existing_dates.add(fields.Date.to_string(rec.date))

        vals_common = {
            "product_id": prod.id,
            "yacht_id": yacht_id,
            "season_id": season_id,
            "hour_from": _adapt_hour_for(Line, "hour_from", wizard_hf, 8.0),
            "hour_to":   _adapt_hour_for(Line, "hour_to",   wizard_ht, 18.0),
            "quota": self.quota or 0,
        }
        to_create = [dict(vals_common, date=d) for d in selected if d not in existing_dates]
        if to_create:
            Line.create(to_create)

        # 5) sincronizaciones opcionales
        iso_dates = selected
        with self.env.cr.savepoint():
            sync = getattr(prod, "_sync_blocked_periods_from_turn_dates", None)
            if callable(sync):
                sync(iso_dates)
        with self.env.cr.savepoint():
            ensure_orders = getattr(prod.with_context(tz=(self.env.user.tz or "UTC")), "_ensure_turn_orders", None)
            if callable(ensure_orders):
                ensure_orders(iso_dates)

        return {"type": "ir.actions.act_window_close"}


class RentalTurnBatchWizardLine(models.TransientModel):
    _name = "rental.turn.batch.wizard.line"
    _description = "Línea de fecha seleccionada (wizard)"

    wizard_id = fields.Many2one("rental.turn.batch.wizard", required=True, ondelete="cascade")
    date = fields.Date(required=True)
