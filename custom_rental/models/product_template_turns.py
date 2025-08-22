# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, date
from ..utils.datetime_tools import (
    time_selection, hm_to_minutes, parse_hhmm, normalize_tz_name
)
import logging
_logger = logging.getLogger(__name__)

USE_TEMPLATE = False
TEMPLATE_NAME = "Rent Rooms"


# -----------------------------
# Helpers de horas (compatibilidad float/HH:MM)
# -----------------------------
def _coerce_hhmm_to_float(val, fallback=0.0):
    """Acepta 8, 8.0, '8', '08:00', '18:30' -> 8.0 / 18.5"""
    if val in (None, False, ""):
        return float(fallback)
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            try:
                h, m = s.split(":", 1)
                return int(h) + int(m) / 60.0
            except Exception:
                pass
        try:
            return float(s)
        except Exception:
            return float(fallback)
    return float(fallback)


def _float_to_hhmm(v):
    """8.0 -> '08:00', 18.5 -> '18:30'"""
    minutes = int(round(float(v or 0.0) * 60))
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _adapt_hour_for(model_or_record, field_name, value, fallback="00:00"):
    """
    Devuelve el valor de hora adecuado según el tipo del campo destino:
    - Si el campo es Float -> float horas (8.0)
    - Si es Char/Selection/Many2x/etc. -> 'HH:MM'
    """
    fields_map = getattr(model_or_record, "_fields", {})
    f = fields_map.get(field_name)
    if not f:
        return value if value not in (None, False, "") else fallback

    if f.type == "float":
        return _coerce_hhmm_to_float(value, fallback=0.0)
    else:
        if isinstance(value, (int, float)):
            return _float_to_hhmm(value)
        return value if value not in (None, False, "") else fallback


class ProductTemplate(models.Model):
    _inherit = "product.template"

    turn_param_line_ids = fields.One2many("rental.turn.param.line", "product_id", string="Parámetros")
    turn_yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    nav_season_id = fields.Many2one("rental.season", string="Temporada")

    turn_period_start = fields.Date(related="nav_season_id.date_from", store=True, readonly=True)
    turn_period_end = fields.Date(related="nav_season_id.date_to", store=True, readonly=True)

    def _get_time_selection(self):
        return time_selection()

    # Se mantienen como Selection (strings 'HH:MM')
    turn_hour_from = fields.Selection(selection=_get_time_selection, default="08:00", string="Hora inicio")
    turn_hour_to   = fields.Selection(selection=_get_time_selection, default="18:00", string="Hora final")

    calendar_date_ids = fields.One2many("rental.calendar.date", "product_id", string="Fechas")
    calendar_date_count = fields.Integer(compute="_compute_calendar_date_count", string="Nº de Fechas")

    turn_available_dates = fields.Text(string="Fechas disponibles")
    turn_available_dates_html = fields.Html(
        string="Fechas (resumen)", compute="_compute_turn_available_dates_html",
        sanitize=False, store=True,
    )

    turn_product_id = fields.Many2one("product.template", string="Producto", readonly=True)
    turn_quota = fields.Integer(string="Cuota", default=0)

    @staticmethod
    def _csv_to_list(csv_text):
        return sorted({s.strip() for s in (csv_text or "").split(",") if s.strip()})

    @api.depends("calendar_date_ids")
    def _compute_calendar_date_count(self):
        for rec in self:
            rec.calendar_date_count = len(rec.calendar_date_ids)

    @api.depends("turn_param_line_ids.date")
    def _compute_turn_available_dates_html(self):
        for rec in self:
            dates = sorted({l.date for l in rec.turn_param_line_ids if l.date})
            pills = "".join(f'<span class="kr-date-pill">{d.isoformat()}</span>' for d in dates)
            rec.turn_available_dates_html = f'<div class="kr-date-pill-wrap">{pills}</div>'

    @api.constrains("turn_hour_from", "turn_hour_to")
    def _check_times(self):
        for rec in self:
            f = hm_to_minutes(rec.turn_hour_from)
            t = hm_to_minutes(rec.turn_hour_to)
            if f is not None and t is not None and f >= t:
                raise ValidationError(_("La 'Hora inicio' debe ser menor que la 'Hora final'."))

    @api.onchange("turn_available_dates")
    def _onchange_turn_available_dates(self):
        return

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec, vals in zip(recs, vals_list):
            if not vals.get("turn_product_id"):
                rec.turn_product_id = rec.id
        return recs

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if not rec.turn_product_id:
                rec.turn_product_id = rec.id
        return res

    # ---------- Helpers internos ----------
    def _get_turn_partner(self, company):
        """DEPRECADO para los turnos: ahora usamos siempre Public user.
        Mantengo por compatibilidad si lo llamas desde otro lado."""
        Partner = self.env['res.partner'].sudo()
        partner = Partner.search([
            ('name', '=', 'Turn Slots'),
            ('company_id', 'in', [False, company.id]),
        ], limit=1)
        if not partner:
            Pricelist = self.env['product.pricelist'].sudo()
            pricelist = Pricelist.search([('company_id', 'in', [False, company.id])], limit=1)
            partner = Partner.create({
                'name': 'Turn Slots',
                'company_id': company.id,
                'customer_rank': 1,
                'property_product_pricelist': pricelist.id or False,
            })
        return partner

    def _get_rent_rooms_template(self):
        if not self.env.registry.get('sale.order.template'):
            return False
        return self.env['sale.order.template'].sudo().search(
            [('name', 'ilike', TEMPLATE_NAME)], limit=1
        )

    def _sync_blocked_periods_from_turn_dates(self, iso_dates):
        """Sincroniza rental.blocked.period con las fechas de turnos."""
        self.ensure_one()
        new_dates = set(iso_dates or [])
        try:
            if not self.env.registry.get("rental.blocked.period"):
                return
            Period = self.env["rental.blocked.period"].sudo()

            # helper para campos variables por addon
            def pick_field(model, candidates, types=None):
                for name in candidates:
                    if name in model._fields and (not types or model._fields[name].type in types):
                        return name
                return None

            prod_m2o = pick_field(Period, ['product_id', 'product_tmpl_id', 'product_template_id', 'rental_product_id'], types=['many2one'])
            prod_m2m = pick_field(Period, ['product_ids', 'product_tmpl_ids', 'rental_product_ids'], types=['many2many'])
            if not (prod_m2o or prod_m2m):
                return

            if prod_m2o:
                comodel = Period._fields[prod_m2o].comodel_name
                product_value = self.id if comodel == 'product.template' else self.product_variant_id.id
            else:
                comodel = Period._fields[prod_m2m].comodel_name
                product_value = self.id if comodel == 'product.template' else self.product_variant_id.id

            date_from_f = pick_field(Period, ['date_from', 'start_date', 'start', 'date_start'], types=['datetime', 'date'])
            date_to_f = pick_field(Period, ['date_to', 'end_date', 'stop', 'date_end'], types=['datetime', 'date'])
            if not (date_from_f and date_to_f):
                return
            is_dt = Period._fields[date_from_f].type == "datetime"
            has_flag = "turn_block" in Period._fields

            domain_obs = []
            if prod_m2o:
                domain_obs.append((prod_m2o, '=', product_value))
            else:
                domain_obs.append((prod_m2m, 'in', [product_value]))
            if has_flag:
                domain_obs.append(('turn_block', '=', True))

            with self.env.cr.savepoint():
                for ob in Period.search(domain_obs):
                    start_val = getattr(ob, date_from_f)
                    if not start_val:
                        continue
                    day_str = start_val.date().isoformat() if isinstance(start_val, datetime) else start_val.isoformat()
                    if day_str not in new_dates:
                        if prod_m2o:
                            ob.unlink()
                        else:
                            ob.write({prod_m2m: [(3, product_value)]})
                            if not getattr(ob, prod_m2m):
                                ob.unlink()

            t_from = parse_hhmm(self.turn_hour_from or "00:00")
            t_to = parse_hhmm(self.turn_hour_to or "23:59")

            # Crear/actualizar por cada fecha
            for iso in new_dates:
                y, m, d = [int(x) for x in iso.split("-")]
                if is_dt:
                    tz_name = normalize_tz_name(self.env.context.get("tz") or self.env.user.tz or "UTC")
                    import pytz
                    tz = pytz.timezone(tz_name)
                    from datetime import datetime as dt
                    local_start = dt(y, m, d, t_from.hour, t_from.minute, 0)
                    local_end = dt(y, m, d, t_to.hour, t_to.minute, 0)
                    try:
                        aware_s = tz.localize(local_start, is_dst=None)
                        aware_e = tz.localize(local_end, is_dst=None)
                    except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                        aware_s = tz.localize(local_start, is_dst=False)
                        aware_e = tz.localize(local_end, is_dst=False)
                    start_val = aware_s.astimezone(pytz.UTC).replace(tzinfo=None)
                    end_val = aware_e.astimezone(pytz.UTC).replace(tzinfo=None)
                else:
                    start_val = date(y, m, d)
                    end_val = date(y, m, d)

                domain = [(date_from_f, '=', start_val), (date_to_f, '=', end_val)]
                if prod_m2o:
                    domain.append((prod_m2o, '=', product_value))
                else:
                    domain.append((prod_m2m, 'in', [product_value]))
                if has_flag:
                    domain.append(('turn_block', '=', True))

                with self.env.cr.savepoint():
                    rec = Period.search(domain, limit=1)
                    vals = {date_from_f: start_val, date_to_f: end_val, "name": _("Bloqueo (Turnos)")}
                    if has_flag:
                        vals["turn_block"] = True
                    if prod_m2o:
                        vals[prod_m2o] = product_value
                    else:
                        vals[prod_m2m] = [(6, 0, [product_value])]

                    if rec:
                        if prod_m2o:
                            rec.write(vals)
                        else:
                            if product_value not in rec[prod_m2m].ids:
                                rec.write({prod_m2m: [(4, product_value)]})
                            rec.write({k: v for k, v in vals.items() if k != prod_m2m})
                    else:
                        Period.create(vals)
        except Exception:
            _logger.exception("Error sincronizando rental.blocked.period")

    def _ensure_turn_orders(self, iso_dates):
        """Crea/actualiza Sale Orders por cada fecha (cliente = Public user)."""
        self.ensure_one()
        if not iso_dates:
            return
        company = self.company_id or self.env.company

        Order = self.env['sale.order'].sudo()
        Line = self.env['sale.order.line'].sudo()

        rent_start_f = 'rental_start_date' if 'rental_start_date' in Order._fields else None
        rent_return_f = 'rental_return_date' if 'rental_return_date' in Order._fields else None
        pickup_f = 'pickup_date' if 'pickup_date' in Order._fields else None
        return_f = 'return_date' if 'return_date' in Order._fields else None

        line_rent_start_f = 'rental_start_date' if 'rental_start_date' in Line._fields else None
        line_rent_return_f = 'rental_return_date' if 'rental_return_date' in Line._fields else None
        line_pickup_f = 'pickup_date' if 'pickup_date' in Line._fields else None
        line_return_f = 'return_date' if 'return_date' in Line._fields else None

        pricelist_f = 'pricelist_id' if 'pricelist_id' in Order._fields else None
        warehouse_f = 'warehouse_id' if 'warehouse_id' in Order._fields and self.env.registry.get('stock.warehouse') else None

        # ►► Cliente SIEMPRE = Public user
        public_partner = self.env.ref('base.public_partner').sudo()
        if not public_partner.customer_rank:
            try:
                public_partner.customer_rank = 1
            except Exception:
                _logger.exception("No se pudo ajustar customer_rank de Public user")

        variant = self.product_variant_id
        if hasattr(variant, 'rent_ok') and not variant.rent_ok:
            try:
                variant.write({'rent_ok': True})
            except Exception:
                raise UserError(_("El producto debe estar marcado como 'Can be Rented'."))

        # Horas de producto (strings) convertidas a tiempo
        t_from = parse_hhmm(self.turn_hour_from or "09:00")
        t_to = parse_hhmm(self.turn_hour_to or "18:00")

        ui_ctx = dict(self.env.context or {})
        ui_ctx.setdefault('tz', normalize_tz_name(self.env.context.get('tz') or public_partner.tz or self.env.user.tz or 'UTC'))
        ui_ctx.setdefault('lang', public_partner.lang or self.env.user.lang)

        import pytz
        from datetime import datetime as dt
        tz = pytz.timezone(normalize_tz_name(ui_ctx['tz']))

        for iso in sorted(set(iso_dates)):
            y, m, d = [int(x) for x in iso.split('-')]
            local_start = dt(y, m, d, t_from.hour, t_from.minute, 0)
            local_end = dt(y, m, d, t_to.hour, t_to.minute, 0)
            try:
                aware_s = tz.localize(local_start, is_dst=None)
                aware_e = tz.localize(local_end, is_dst=None)
            except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                aware_s = tz.localize(local_start, is_dst=False)
                aware_e = tz.localize(local_end, is_dst=False)
            start_dt = aware_s.astimezone(pytz.UTC).replace(tzinfo=None)
            stop_dt = aware_e.astimezone(pytz.UTC).replace(tzinfo=None)

            # ¿Ya existe orden para ese rango y este producto? (sin importar el partner actual)
            domain = [('company_id', '=', company.id)]
            if rent_start_f and rent_return_f:
                domain += [(rent_start_f, '=', start_dt), (rent_return_f, '=', stop_dt)]
            elif pickup_f and return_f:
                domain += [(pickup_f, '=', start_dt), (return_f, '=', stop_dt)]
            domain += [('order_line.product_id', 'in', [variant.id])]
            existing = Order.search(domain, limit=1)

            if existing:
                # ► Actualizar a Public user + setear campos del turno
                write_vals = {
                    'partner_id': public_partner.id,
                }
                if 'x_turn_date' in Order._fields:
                    write_vals['x_turn_date'] = fields.Date.to_date(iso)
                if 'x_turn_hour_from' in Order._fields:
                    write_vals['x_turn_hour_from'] = _adapt_hour_for(Order, 'x_turn_hour_from', self.turn_hour_from or "09:00", fallback="09:00")
                if 'x_turn_hour_to' in Order._fields:
                    write_vals['x_turn_hour_to'] = _adapt_hour_for(Order, 'x_turn_hour_to', self.turn_hour_to or "18:00", fallback="18:00")
                if 'x_turn_slot' in Order._fields:
                    write_vals['x_turn_slot'] = False

                with self.env.cr.savepoint():
                    existing.write(write_vals)
                    try:
                        if hasattr(existing, 'action_update_rental_prices'):
                            existing.action_update_rental_prices()
                    except Exception:
                        _logger.exception("No se pudo actualizar precios (update).")
                continue

            # ► Crear nueva orden si no existe
            line_vals = {'product_id': variant.id, 'product_uom_qty': 1.0}
            order_vals = {
                'partner_id': public_partner.id,
                'company_id': company.id,
                'origin': f"Turno – {self.display_name} {iso}",
                'note': f"Auto – Turno {self.display_name} {iso}",
                'order_line': [(0, 0, line_vals)],
                'x_turn_yacht_id': (self.turn_yacht_id.id or False),
                'x_turn_season_id': (self.nav_season_id.id or False),
            }
            if pricelist_f and not order_vals.get(pricelist_f):
                order_vals[pricelist_f] = public_partner.property_product_pricelist.id or False
            if warehouse_f:
                wh = self.env['stock.warehouse'].sudo().search([('company_id', '=', company.id)], limit=1)
                if wh:
                    order_vals[warehouse_f] = wh.id

            with self.env.cr.savepoint():
                tmp = Order.with_context(ui_ctx).new(order_vals)
                try:
                    if hasattr(tmp, '_onchange_partner_id'): tmp._onchange_partner_id()
                    if hasattr(tmp, '_onchange_pricelist_id'): tmp._onchange_pricelist_id()
                    if hasattr(tmp, '_onchange_company_id'): tmp._onchange_company_id()
                except Exception:
                    _logger.exception("Onchange de cabecera no disponible.")

                if rent_start_f and rent_return_f:
                    setattr(tmp, rent_start_f, start_dt)
                    setattr(tmp, rent_return_f, stop_dt)
                    if hasattr(tmp, '_onchange_rental_dates'):
                        tmp._onchange_rental_dates()
                elif pickup_f and return_f:
                    setattr(tmp, pickup_f, start_dt)
                    setattr(tmp, return_f, stop_dt)

                for l in tmp.order_line.filtered(lambda ll: not ll.display_type):
                    if rent_start_f and rent_return_f and line_rent_start_f and line_rent_return_f:
                        setattr(l, line_rent_start_f, start_dt)
                        setattr(l, line_rent_return_f, stop_dt)
                    elif pickup_f and return_f and line_pickup_f and line_return_f:
                        setattr(l, line_pickup_f, start_dt)
                        setattr(l, line_return_f, stop_dt)
                    try:
                        if hasattr(l, '_onchange_product_id'): l._onchange_product_id()
                        if hasattr(l, '_onchange_product_uom_qty'): l._onchange_product_uom_qty()
                    except Exception:
                        _logger.exception("Onchange de línea no disponible.")

                # Guardar fecha/hora del turno en la cabecera
                if 'x_turn_date' in Order._fields:
                    setattr(tmp, 'x_turn_date', fields.Date.to_date(iso))
                if 'x_turn_hour_from' in Order._fields:
                    setattr(tmp, 'x_turn_hour_from', _adapt_hour_for(Order, 'x_turn_hour_from', self.turn_hour_from or "09:00", fallback="09:00"))
                if 'x_turn_hour_to' in Order._fields:
                    setattr(tmp, 'x_turn_hour_to', _adapt_hour_for(Order, 'x_turn_hour_to', self.turn_hour_to or "18:00", fallback="18:00"))
                if 'x_turn_slot' in Order._fields:
                    setattr(tmp, 'x_turn_slot', False)

                order = Order.create(tmp._convert_to_write(tmp._cache))
                try:
                    if hasattr(order, 'action_update_rental_prices'):
                        order.action_update_rental_prices()
                except Exception:
                    _logger.exception("No se pudo actualizar precios (create).")

                try:
                    order.invalidate_recordset()
                    if hasattr(order.order_line, '_compute_is_rental'): order.order_line._compute_is_rental()
                    if hasattr(order, '_compute_has_rented_products'): order._compute_has_rented_products()
                    if hasattr(order, '_compute_is_rental_order'): order._compute_is_rental_order()
                    if hasattr(order, '_compute_remaining_hours'): order._compute_remaining_hours()
                except Exception:
                    _logger.exception("No se pudo forzar recomputes de alquiler.")

    def action_fix_existing_turn_orders(self):
        Order = self.env['sale.order'].sudo()
        for prod in self:
            partner = self.env.ref('base.public_partner').sudo()
            orders = Order.search([
                ('company_id', '=', (prod.company_id or self.env.company).id),
                ('order_line.product_id', 'in', [prod.product_variant_id.id]),
            ])
            for order in orders:
                try:
                    order.write({'partner_id': partner.id})
                    if hasattr(order, 'action_update_rental_prices'):
                        order.action_update_rental_prices()
                except Exception:
                    _logger.exception("No se pudo reparar la orden %s", order.name or order.id)

    def action_open_turn_batch_wizard(self):
        self.ensure_one()

        # Defaults al wizard DEBEN ser floats
        def _flt(val, fallback):
            return _coerce_hhmm_to_float(val, fallback=fallback)

        return {
            "type": "ir.actions.act_window",
            "res_model": "rental.turn.batch.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "lang": self.env.user.lang or "es_ES",
                "default_product_id": self.id,
                "default_yacht_id": self.turn_yacht_id.id or False,
                "default_season_id": self.nav_season_id.id or False,
                "default_hour_from": _flt(self.turn_hour_from, 8.0),
                "default_hour_to":   _flt(self.turn_hour_to, 18.0),
                "default_quota": self.turn_quota or 0,
                "default_line_ids": [(0, 0, {"date": l.date}) for l in self.turn_param_line_ids if l.date],
                "default_wizard_available_dates": ", ".join(sorted({l.date.isoformat() for l in self.turn_param_line_ids if l.date})),
            },
        }
