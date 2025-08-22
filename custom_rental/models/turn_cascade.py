# -*- coding: utf-8 -*-
# custom_rental/models/turn_cascade.py
#
# Borrado en cascada de "Turnos" (rental.turn.param.line) -> Órdenes de renta -> Scheduler
# y enlace automático orden <-> turno.
#
# Odoo 18

from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging
from datetime import datetime, timedelta, time as dt_time
import pytz

_logger = logging.getLogger(__name__)

# Estados de sale.order que consideramos "seguros" para borrar directamente
SAFE_ORDER_STATES = (
    "draft", "sent", "quotation", "reserved", "cancel",
)

# Estados que bloquean el borrado del turno (debes tratarlos manualmente)
BLOCKED_ORDER_STATES = (
    "sale", "confirmed", "pickup", "pickedup", "return", "returned", "done",
    "invoiced", "cancelled_and_billed",
)


def _has_field(model, fname):
    return hasattr(model, "_fields") and fname in model._fields


def _float_to_time(v):
    """8.0 -> datetime.time(8,0) ; '08:30' -> 8:30 ; None -> 00:00"""
    if v in (None, False, ""):
        return dt_time(0, 0)
    if isinstance(v, dt_time):
        return v
    try:
        # float: horas decimales
        if isinstance(v, (int, float)):
            minutes = int(round(float(v) * 60))
            return dt_time((minutes // 60) % 24, minutes % 60)
        # str: 'HH:MM(:SS)'
        s = str(v).strip()
        if ":" in s:
            hh, mm, *rest = s.split(":")
            return dt_time(int(hh or 0) % 24, int(mm or 0))
        # str con decimal: '8.5'
        return _float_to_time(float(s))
    except Exception:
        return dt_time(0, 0)


# ------------------------------------------------------------------
# Enlaces de orden/línea con la línea de turno
# ------------------------------------------------------------------

class SaleOrder(models.Model):
    _inherit = "sale.order"

    turn_line_id = fields.Many2one(
        "rental.turn.param.line",
        string="Turno",
        ondelete="set null",
        index=True,
        help="Turno (línea de parámetros) que originó esta orden.",
    )


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    turn_line_id = fields.Many2one(
        "rental.turn.param.line",
        string="Turno",
        ondelete="set null",
        index=True,
        help="Turno (línea de parámetros) que originó esta línea.",
    )


# ------------------------------------------------------------------
# Extensión de rental.turn.param.line con borrado en cascada
# ------------------------------------------------------------------

class RentalTurnParamLine(models.Model):
    _inherit = "rental.turn.param.line"

    order_ids = fields.One2many("sale.order", "turn_line_id", string="Órdenes vinculadas")
    order_line_ids = fields.One2many("sale.order.line", "turn_line_id", string="Líneas vinculadas")

    # ---------- helpers privados ----------

    def _user_tz(self):
        tz_name = self.env.context.get("tz") or self.env.user.tz or "UTC"
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.UTC

    def _dt_utc_range(self):
        """Devuelve (start_utc_naive, end_utc_naive) para comparar con sale.order
        a partir de date + hour_from/hour_to (en Float o Char).
        """
        self.ensure_one()
        t_from = _float_to_time(getattr(self, "hour_from", 0.0))
        t_to   = _float_to_time(getattr(self, "hour_to", 0.0))
        d      = fields.Date.to_date(self.date)

        start_local = datetime.combine(d, t_from)
        end_local   = datetime.combine(d, t_to)
        if end_local <= start_local:
            # caso de franja que cruza medianoche
            end_local += timedelta(days=1)

        tz = self._user_tz()
        start_utc = tz.localize(start_local).astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc   = tz.localize(end_local).astimezone(pytz.UTC).replace(tzinfo=None)
        return start_utc, end_utc

    def _match_domain_for_orders(self):
        """Dominio para localizar órdenes que corresponden a este turno.

        1) Si sale.order tiene rental_start_date / rental_return_date (sale_renting) -> usar exact match.
        2) Además, si existen campos x_turn_* los añadimos.
        """
        self.ensure_one()
        Order = self.env["sale.order"]
        dom = []

        # 1) Dominio por rango exacto (si los campos existen)
        if _has_field(Order, "rental_start_date") and _has_field(Order, "rental_return_date"):
            start_utc, end_utc = self._dt_utc_range()
            dom += [("rental_start_date", "=", start_utc), ("rental_return_date", "=", end_utc)]

        # 2) Heurística adicional si tu flujo pobló campos auxiliares
        if _has_field(Order, "x_turn_slot"):
            dom += [("x_turn_slot", "=", True)]
        if _has_field(Order, "x_turn_date"):
            dom += [("x_turn_date", "=", self.date)]
        if _has_field(Order, "x_turn_hour_from"):
            dom += [("x_turn_hour_from", "=", getattr(self, "hour_from", 0.0))]
        if _has_field(Order, "x_turn_hour_to"):
            dom += [("x_turn_hour_to", "=", getattr(self, "hour_to", 0.0))]
        if _has_field(Order, "x_turn_yacht_id") and self.yacht_id:
            dom += [("x_turn_yacht_id", "=", self.yacht_id.id)]
        if _has_field(Order, "x_turn_season_id") and self.season_id:
            dom += [("x_turn_season_id", "=", self.season_id.id)]

        return dom

    def _link_related_records(self):
        """Idempotente: asegura que órdenes y líneas apunten al turno."""
        Order = self.env["sale.order"].sudo()

        for turn in self:
            dom = turn._match_domain_for_orders()
            orders = Order.search(dom) if dom else Order.browse()
            # filtrar por producto del turno
            prod_tmpl = turn.product_id
            if prod_tmpl:
                orders = orders.filtered(lambda o: any(
                    l.product_id and l.product_id.product_tmpl_id.id == prod_tmpl.id for l in o.order_line
                ))
            if orders:
                orders.write({"turn_line_id": turn.id})
                for o in orders:
                    rel_lines = o.order_line.filtered(
                        lambda l: l.product_id and l.product_id.product_tmpl_id.id == prod_tmpl.id
                    )
                    rel_lines.write({"turn_line_id": turn.id})

    def _unlink_related_schedules(self):
        """Elimina entradas auxiliares del scheduler si existen."""
        self.ensure_one()
        # rental.calendar.date
        try:
            Cal = self.env["rental.calendar.date"].sudo()
            Cal.search([("product_id", "=", self.product_id.id), ("date", "=", self.date)]).unlink()
        except Exception:
            pass
        # rental.availability (si coincide día, embarcación, etc.)
        try:
            Av = self.env["rental.availability"].sudo()
            dom = []
            if _has_field(Av, "date_from") and _has_field(Av, "date_to"):
                dom += [("date_from", "<=", self.date), ("date_to", ">=", self.date)]
            if self.yacht_id and _has_field(Av, "boat_id"):
                dom += [("boat_id", "=", self.yacht_id.id)]
            if dom:
                Av.search(dom).unlink()
        except Exception:
            pass

    def _resync_product_schedule(self, products):
        """Tras borrar turnos/órdenes, resincroniza bloqueos del producto (kanban/schedule)."""
        products = products.sudo()
        for prod in products:
            try:
                dates_left = [l.date.isoformat() for l in prod.turn_param_line_ids if l.date]
                prod._sync_blocked_periods_from_turn_dates(dates_left)
            except Exception:
                _logger.exception("Fallo resincronizando schedule del producto %s", prod.id)

    # ---------- override unlink ----------

    def unlink(self):
        """Borrado en cascada:

        - Vincula posibles órdenes/líneas a este turno (si no lo estaban).
        - Si hay órdenes en estados bloqueantes, impedir borrado y mostrar cuáles.
        - Cancelar (si aplica) y borrar órdenes en estados seguros.
        - Borrar líneas sueltas y entradas de scheduler.
        - Borrar la línea del turno y resincronizar schedule del producto.
        """
        Order = self.env["sale.order"].sudo()
        Line = self.env["sale.order.line"].sudo()

        # Aseguramos enlaces antes de operar
        self._link_related_records()

        products = self.mapped("product_id")  # para resync posterior

        for turn in self:
            # 1) Órdenes relacionadas (vía link o dominio)
            orders = turn.order_ids
            if not orders:
                dom = turn._match_domain_for_orders()
                orders = Order.search(dom) if dom else Order.browse()
                # filtro por producto del turno
                prod_tmpl = turn.product_id
                if prod_tmpl:
                    orders = orders.filtered(lambda o: any(
                        l.product_id and l.product_id.product_tmpl_id.id == prod_tmpl.id for l in o.order_line
                    ))

            # 2) Validar órdenes bloqueantes
            blocked = orders.filtered(lambda o: o.state in BLOCKED_ORDER_STATES)
            if blocked:
                lines = [f"{o.name} ({o.state})" for o in blocked]
                raise UserError(_("No se puede borrar el turno porque tiene órdenes comprometidas:\n%s")
                                % "\n".join(lines))

            # 3) Intentar cancelar y borrar órdenes seguras
            safe = orders.filtered(lambda o: o.state in SAFE_ORDER_STATES)
            for o in safe:
                try:
                    if hasattr(o, "action_cancel"):
                        o.action_cancel()
                except Exception:
                    _logger.warning("No se pudo cancelar la orden %s antes de borrar", o.name, exc_info=True)
            if safe:
                safe.unlink()

            # 4) Borrar líneas sueltas (por si quedaron)
            stray_lines = turn.order_line_ids
            if not stray_lines:
                # fallback por producto (sin fechas exactas)
                prod_tmpl = turn.product_id
                dom_lines = []
                if prod_tmpl:
                    dom_lines += [("product_id.product_tmpl_id", "=", prod_tmpl.id)]
                if _has_field(Line, "turn_line_id"):
                    dom_lines += [("turn_line_id", "=", turn.id)]
                stray_lines = Line.search(dom_lines) if dom_lines else Line.browse()
            if stray_lines:
                stray_lines.unlink()

            # 5) Eliminar entradas en scheduler auxiliares
            turn._unlink_related_schedules()

        # 6) Borrar la(s) línea(s) del turno
        res = super(RentalTurnParamLine, self).unlink()

        # 7) Resync de schedule/kanban del producto
        self._resync_product_schedule(products)
        return res


# ------------------------------------------------------------------
# Hook para enlazar órdenes recién creadas por tu lógica de turnos
# ------------------------------------------------------------------

class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _link_turn_orders(self, iso_dates):
        """Tras _ensure_turn_orders(iso_dates), enlaza sale.order/line al turno correspondiente."""
        Order = self.env["sale.order"].sudo()
        Turn = self.env["rental.turn.param.line"].sudo()

        for product in self:
            if not iso_dates:
                continue
            turns = Turn.search([("product_id", "=", product.id), ("date", "in", list(iso_dates))])
            for t in turns:
                dom = t._match_domain_for_orders()
                orders = Order.search(dom) if dom else Order.browse()
                if product:
                    orders = orders.filtered(lambda o: any(
                        l.product_id and l.product_id.product_tmpl_id.id == product.id for l in o.order_line
                    ))
                if orders:
                    orders.write({"turn_line_id": t.id})
                    for o in orders:
                        rel_lines = o.order_line.filtered(
                            lambda l: l.product_id and l.product_id.product_tmpl_id.id == product.id
                        )
                        rel_lines.write({"turn_line_id": t.id})

    def _ensure_turn_orders(self, iso_dates):
        """Envuelve al método original y luego enlaza las órdenes a sus turnos."""
        res = super()._ensure_turn_orders(iso_dates)
        try:
            self._link_turn_orders(iso_dates)
        except Exception:
            _logger.exception("No se pudo enlazar órdenes a turnos tras _ensure_turn_orders")
        return res
