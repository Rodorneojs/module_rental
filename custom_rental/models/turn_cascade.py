# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta, time as dt_time
import pytz
import logging

_logger = logging.getLogger(__name__)

BLOCKED_ORDER_STATES = {"sale", "done"}       # comprometidas
SAFE_ORDER_STATES    = {"draft", "sent", "cancel"}  # se pueden cancelar/borrar

def _has_field(model, fname):
    return hasattr(model, "_fields") and fname in model._fields

def _float_to_time(v):
    if v in (None, False, ""): return dt_time(0, 0)
    try:
        if isinstance(v, (int, float)):
            minutes = int(round(float(v) * 60))
            return dt_time((minutes // 60) % 24, minutes % 60)
        s = str(v).strip()
        if ":" in s:
            hh, mm, *_ = s.split(":")
            return dt_time(int(hh or 0) % 24, int(mm or 0))
        return _float_to_time(float(s))
    except Exception:
        return dt_time(0, 0)


class RentalTurnParamLine(models.Model):
    _inherit = "rental.turn.param.line"

    order_ids      = fields.One2many("sale.order", "turn_line_id", string="Órdenes del turno")
    order_line_ids = fields.One2many("sale.order.line", "turn_line_id", string="Líneas del turno")

    # ---------- helpers ----------
    def _user_tz(self):
        tz_name = self.env.context.get("tz") or self.env.user.tz or "UTC"
        try: return pytz.timezone(tz_name)
        except Exception: return pytz.UTC

    def _utc_range_for_day(self):
        """Rango UTC [start, end) basado en date + hour_from/hour_to del turno."""
        self.ensure_one()
        d = self.date
        t_from = _float_to_time(getattr(self, "hour_from", 0.0))
        t_to   = _float_to_time(getattr(self, "hour_to",   23.99))
        start_local = datetime.combine(d, t_from)
        end_local   = datetime.combine(d, t_to)
        if end_local <= start_local:
            end_local += timedelta(days=1)
        tz = self._user_tz()
        return (
            tz.localize(start_local).astimezone(pytz.UTC).replace(tzinfo=None),
            tz.localize(end_local).astimezone(pytz.UTC).replace(tzinfo=None),
        )

    def _order_domains(self):
        """Dominios alternativos para encontrar órdenes del turno (según campos disponibles)."""
        self.ensure_one()
        Order = self.env["sale.order"]
        doms = []

        start_utc, end_utc = self._utc_range_for_day()

        # renting clásico
        if _has_field(Order, "rental_start_date") and _has_field(Order, "rental_return_date"):
            doms.append([
                ("rental_start_date", "=", start_utc),
                ("rental_return_date", "=", end_utc),
            ])
            # tolerancia ±5m (por posibles redondeos)
            doms.append([
                ("rental_start_date", ">=", start_utc - timedelta(minutes=5)),
                ("rental_start_date", "<=", start_utc + timedelta(minutes=5)),
                ("rental_return_date", ">=", end_utc - timedelta(minutes=5)),
                ("rental_return_date", "<=", end_utc + timedelta(minutes=5)),
            ])
        # variantes de campos
        elif _has_field(Order, "pickup_date") and _has_field(Order, "return_date"):
            doms.append([("pickup_date", "=", start_utc), ("return_date", "=", end_utc)])

        # filtros por metadatos del turno
        extra = [("company_id", "=", (self.product_id.company_id or self.env.company).id)]
        if _has_field(Order, "x_turn_date"):
            extra += [("x_turn_date", "=", self.date)]
        if _has_field(Order, "x_turn_hour_from"):
            extra += [("x_turn_hour_from", "=", getattr(self, "hour_from", 0.0))]
        if _has_field(Order, "x_turn_hour_to"):
            extra += [("x_turn_hour_to", "=", getattr(self, "hour_to", 0.0))]
        if _has_field(Order, "x_turn_yacht_id") and self.yacht_id:
            extra += [("x_turn_yacht_id", "=", self.yacht_id.id)]
        if _has_field(Order, "x_turn_season_id") and self.season_id:
            extra += [("x_turn_season_id", "=", self.season_id.id)]

        # adjunta extras
        return [d + list(extra) for d in doms] or [list(extra)]

    # ---------- core: borrado en cascada ----------
    def unlink(self):
        Order = self.env["sale.order"].sudo()
        products = self.mapped("product_id")

        for turn in self.sudo():
            # 1) localizar órdenes candidatas del turno
            orders = Order.browse()
            for d in turn._order_domains():
                tmp = Order.search(d)
                if tmp:
                    orders |= tmp

            # filtra por producto del turno (por si hay varias líneas en la orden)
            if orders:
                prod_tmpl = turn.product_id
                variant_id = prod_tmpl.product_variant_id.id if prod_tmpl else False
                def has_variant(o):
                    return any(l.product_id and l.product_id.id == variant_id for l in o.order_line)
                orders = orders.filtered(has_variant)

            # 2) impedir borrar si hay órdenes comprometidas
            blocked = orders.filtered(lambda o: o.state in BLOCKED_ORDER_STATES)
            if blocked:
                raise UserError(_("No se puede borrar el turno porque tiene órdenes comprometidas:\n%s") %
                                "\n".join(f"{o.name} ({o.state})" for o in blocked))

            # 3) cancelar y borrar seguras
            safe = orders.filtered(lambda o: o.state in SAFE_ORDER_STATES)
            for o in safe:
                try:
                    if hasattr(o, "action_cancel"):
                        o.action_cancel()
                except Exception:
                    _logger.warning("No se pudo cancelar la orden %s antes de borrar", o.name, exc_info=True)
            if safe:
                safe.unlink()

            # 4) cleanup schedules si el modelo existe
            try:
                S = self.env["sale.rental.schedule"].sudo()
                if S._name == "sale.rental.schedule" and orders:
                    S.search([("order_id", "in", orders.ids)]).unlink()
            except Exception:
                pass

            # 5) cleanup de disponibilidades custom si las usas
            try:
                Av = self.env["rental.availability"].sudo()
                if Av._name == "rental.availability":
                    Av.search([("date_from", "<=", turn.date), ("date_to", ">=", turn.date)]).unlink()
            except Exception:
                pass

        # 6) borra los turnos y resincroniza bloqueos del producto
        res = super().unlink()
        for prod in products.sudo():
            try:
                if hasattr(prod, "_sync_blocked_periods_from_turn_dates"):
                    iso = [l.date.isoformat() for l in prod.turn_param_line_ids if l.date]
                    prod._sync_blocked_periods_from_turn_dates(iso)
            except Exception:
                _logger.exception("Fallo resincronizando schedule del producto %s", prod.id)
        return res
