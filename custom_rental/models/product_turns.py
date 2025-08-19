# custom_rental/models/product_turns.py

# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, date, time
import pytz
import logging
import re

_logger = logging.getLogger(__name__)

# ------------------------------------------------------
# Toggle opcional para reactivar plantilla (NO recomendado)
# ------------------------------------------------------
USE_TEMPLATE = False
TEMPLATE_NAME = "Rent Rooms"


# =====================================================
# Espejo opcional de fechas (solo para mostrar/contar)
# =====================================================
class RentalCalendarDate(models.Model):
    _name = "rental.calendar.date"
    _description = "Fecha disponible de producto"
    _order = "date"

    product_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    date = fields.Date(required=True, index=True)

    _sql_constraints = [
        ("product_date_uniq", "unique(product_id, date)", "La fecha ya existe para este producto."),
    ]


# =====================================================
# Bloqueos extendidos (marcamos los creados desde Turnos)
# =====================================================
class RentalBlockedPeriod(models.Model):
    _inherit = "rental.blocked.period"
    turn_block = fields.Boolean(default=False, index=True)


# =====================================================
# Marca en Sale Order: creado automáticamente por Turnos
# =====================================================
class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_turn_slot = fields.Boolean(
        string="Turn Slot",
        default=False,
        index=True,
        help="Orden creada automáticamente desde 'Turnos' del producto.",
    )
    x_turn_yacht_id = fields.Many2one(
        "fleet.vehicle",
        string="Embarcación Asociada",
        help="Embarcación/vehículo vinculado al turno que originó la orden.",
        index=True,
    )
    x_turn_season_id = fields.Many2one(
        "rental.season",
        string="Temporada (Zona)",
        help="Temporada/Zona del turno que originó la orden.",
        index=True,
    )
    rental_period_display = fields.Char(
        string='Rental Period',
        compute='_compute_rental_period_display',
        store=False
    )
    # Campos para las horas por separado (si no existen)
    rental_start_time = fields.Float(string='Start Time')
    rental_end_time = fields.Float(string='End Time')
    @api.depends('rental_start_date', 'rental_return_date')
    def _compute_rental_period_display(self):
        for record in self:
            if record.rental_start_date and record.rental_return_date:
                # Extraer la fecha (solo una vez)
                start_date = record.rental_start_date.date()
                
                # Extraer las horas
                start_time = record.rental_start_date.strftime('%H:%M')
                end_time = record.rental_return_date.strftime('%H:%M')
                
                # Formatear como: "08/12/2025    Hora inicio: 09:00    Hora Fin: 11:00"
                record.rental_period_display = f"{start_date.strftime('%d/%m/%Y')}    Hora inicio: {start_time}    Hora Fin: {end_time}"
            else:
                record.rental_period_display = ""
    
    def _get_rental_start_time(self):
        """Obtener solo la hora del campo rental_start_date"""
        if self.rental_start_date:
            return self.rental_start_date.hour + (self.rental_start_date.minute / 60.0)
        return 0.0
    
    def _get_rental_end_time(self):
        """Obtener solo la hora del campo rental_return_date"""
        if self.rental_return_date:
            return self.rental_return_date.hour + (self.rental_return_date.minute / 60.0)
        return 0.0
    def action_add_rental_product(self):
        """Abrir popup del formulario de línea con el contexto correcto para renting."""
        self.ensure_one()
        view = self.env.ref('sale.view_order_line_form')  # vista estándar de línea

        # Contexto similar al que usa Odoo para calcular precios/tributos
        ctx = {
            'default_order_id': self.id,
            'partner_id': self.partner_id.id,
            'pricelist': self.pricelist_id.id or (self.partner_id.property_product_pricelist.id if self.partner_id else False),
            'company_id': self.company_id.id,
            'rental_products': True,          # <- importante para filtrar/UX renting
            'default_is_rental': True,        # si el campo existe en líneas
            'search_default_rent_ok': 1,      # ayuda a filtrar productos rentables
        }

        return {
            'name': 'Add Rental Product',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': ctx,
        }
    def action_add_single_product_line(self):
        """Crea una línea vacía y enfoca el selector de producto.
           Se oculta el link después porque ya existe una línea."""
        self.ensure_one()
        # No permitir en órdenes de Turnos
        if self.x_turn_slot:
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # Si ya hay una línea “real”, no crear otra
        if self.order_line.filtered(lambda l: not l.display_type):
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        # Crear línea vacía con qty=1 (se editará inline)
        self.env['sale.order.line'].create({
            'order_id': self.id,
            'product_uom_qty': 1.0,
        })

        # Recargar para que la fila aparezca editable en el o2m
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    def action_add_rental_product(self):
        """Abrir el popup estándar de línea (sale.order.line) filtrado a productos vendibles/arrendables.
        Al elegir el producto, los onchanges rellenan 'name', impuestos, precio, etc.
        """
        self.ensure_one()

        # Vista de línea estándar (la de ventas funciona también con renting)
        line_form = self.env.ref('sale.view_order_line_form')

        # Dominio para el many2one de producto (vende o renta y de la compañía)
        # El propio formulario trae sus dominios, pero pasamos un contexto coherente.
        ctx = {
            'default_order_id': self.id,
            'default_product_uom_qty': 1.0,
            # Contextos que la vista/JS de ventas usa para pricing y onchanges
            'partner_id': self.partner_id.id,
            'pricelist': self.pricelist_id.id or (self.partner_id.property_product_pricelist.id if hasattr(self.partner_id, 'property_product_pricelist') else False),
            'company_id': self.company_id.id,
            # Sugerimos que muestre productos rentables
            'rental_products': True,
        }

        return {
            'name': _('Add product'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'form',
            'view_id': line_form.id,
            'target': 'new',
            'context': ctx,
        }
    @api.onchange('embarcacion_id')
    def _onchange_embarcacion_id(self):
        for rec in self:
            # Si el campo no existe en este DB (módulo opcional), salir sin hacer nada
            if 'boat_line_ids' not in rec._fields:
                return
            if not rec.embarcacion_id:
                return

            # --- tu lógica original, pero solo si el campo existe ---
            if rec.boat_line_ids:
                # ejemplo de actualización, adapta a tu modelo real
                rec.boat_line_ids.update({'boat_id': rec.embarcacion_id.id})
            else:
                rec.boat_line_ids = [(0, 0, {'boat_id': rec.embarcacion_id.id})]

    @api.constrains('order_line')
    def _limit_single_product_line(self):
        """Forzar que solo exista UNA línea de producto (sin contar secciones/notas)."""
        for order in self:
            real_lines = order.order_line.filtered(lambda l: not l.display_type)
            if len(real_lines) > 1:
                # (opcional) permitir 1 sola en cualquier caso;
                # si solo quieres limitar cuando NO sea de turnos, retira el comentario:
                # if not order.x_turn_slot and len(real_lines) > 1:
                raise ValidationError(_("Solo se permite un producto en la orden."))

# =====================================================
# Turno parametrizado (1 fila = 1 fecha)
# =====================================================
class RentalTurnParamLine(models.Model):
    _name = "rental.turn.param.line"
    _description = "Turno parametrizado por fecha"
    _order = "date"

    product_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    date = fields.Date(string="Fecha", required=True, index=True)

    yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    season_id = fields.Many2one("rental.season", string="Temporada (Zona)")

    def _time_selection(self):
        step, vals = 30, []
        for h in range(24):
            for m in range(0, 60, step):
                s = f"{h:02d}:{m:02d}"
                vals.append((s, s))
        return vals

    hour_from = fields.Selection(selection=_time_selection, string="Hora inicio", default="08:00")
    hour_to = fields.Selection(selection=_time_selection, string="Hora final", default="18:00")

    status = fields.Selection(
        [("active", "Activo"), ("inactive", "Inactivo")],
        string="Estado", default="inactive", required=True, index=True,
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


# =====================================================
# Product Template (parámetros + sincronías)
# =====================================================
class ProductTemplate(models.Model):
    _inherit = "product.template"

    turn_param_line_ids = fields.One2many("rental.turn.param.line", "product_id", string="Parámetros")
    turn_yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    nav_season_id = fields.Many2one("rental.season", string="Temporada (Zona)")
    turn_period_start = fields.Date(related="nav_season_id.date_from", store=True, readonly=True)
    turn_period_end = fields.Date(related="nav_season_id.date_to", store=True, readonly=True)

    def _get_time_selection(self):
        step, vals = 30, []
        for h in range(24):
            for m in range(0, 60, step):
                s = f"{h:02d}:{m:02d}"
                vals.append((s, s))
        return vals

    turn_hour_from = fields.Selection(selection=_get_time_selection, default="08:00", string="Hora inicio")
    turn_hour_to = fields.Selection(selection=_get_time_selection, default="18:00", string="Hora final")

    turn_status = fields.Selection(
        [("active", "Activo"), ("inactive", "Inactivo")],
        string="Estado", default="inactive", store=True, index=True,
        help="Estado por defecto para crear/actualizar turnos desde el wizard.",
    )

    calendar_date_ids = fields.One2many("rental.calendar.date", "product_id", string="Fechas")
    calendar_date_count = fields.Integer(compute="_compute_calendar_date_count", string="Fechas")
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

    @staticmethod
    def _hm_to_minutes(hhmm):
        if not hhmm:
            return None
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    @api.constrains("turn_hour_from", "turn_hour_to")
    def _check_times(self):
        for rec in self:
            f = rec._hm_to_minutes(rec.turn_hour_from)
            t = rec._hm_to_minutes(rec.turn_hour_to)
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

    def _parse_hhmm(self, hhmm):
        hh, mm = [int(x) for x in (hhmm or "00:00").split(":")]
        return time(hh, mm, 0)

    def _to_utc_dt(self, y, m, d, t):
        tz_name = self.env.context.get("tz") or self.env.user.tz or "UTC"
        tz_name = self._normalize_tz_name(tz_name)
        tz = pytz.timezone(tz_name)
        local_dt = datetime(y, m, d, t.hour, t.minute, 0)
        try:
            aware = tz.localize(local_dt, is_dst=None)
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
            aware = tz.localize(local_dt, is_dst=False)
        utc_dt = aware.astimezone(pytz.UTC)
        return utc_dt.replace(tzinfo=None)

    @staticmethod
    def _normalize_tz_name(tz_name):
        if not tz_name:
            return "UTC"
        name = str(tz_name).strip()
        if name.lower().startswith("etc/"):
            name = "Etc/" + name[4:]
        elif name.lower().startswith("etc-"):
            name = "Etc/" + name[4:]
        patterns = [
            r"(?i)^Etc/GMT\s*([+-])\s*(\d+)$",
            r"(?i)^GMT\s*([+-])\s*(\d+)$",
            r"(?i)^Etc[-/ ]GMT\s*([+-])\s*(\d+)$"
        ]
        for pattern in patterns:
            m = re.search(pattern, name)
            if m:
                sign, num = m.groups()
                inv = "+" if sign == "-" else "-"
                name = f"Etc/GMT{inv}{num}"
                break
        try:
            pytz.timezone(name)
            return name
        except Exception:
            return "UTC"

    def _get_turn_partner(self, company):
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
        self.ensure_one()
        new_dates = set(iso_dates or [])
        try:
            if not self.env.registry.get("rental.blocked.period"):
                return

            Period = self.env["rental.blocked.period"].sudo()

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

            t_from = self._parse_hhmm(self.turn_hour_from or "00:00")
            t_to = self._parse_hhmm(self.turn_hour_to or "23:59")

            for iso in new_dates:
                y, m, d = [int(x) for x in iso.split("-")]
                if is_dt:
                    start_val = self._to_utc_dt(y, m, d, t_from)
                    end_val = self._to_utc_dt(y, m, d, t_to)
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

        partner = self._get_turn_partner(company)
        variant = self.product_variant_id

        if hasattr(variant, 'rent_ok') and not variant.rent_ok:
            try:
                variant.write({'rent_ok': True})
            except Exception:
                raise UserError(_("El producto debe estar marcado como 'Can be Rented'."))

        existing = Order.search([
            ('x_turn_slot', '=', True),
            ('partner_id', '=', partner.id),
            ('company_id', '=', company.id),
        ])
        existing_keys = set()
        for o in existing:
            start_val = getattr(o, rent_start_f) if rent_start_f else (getattr(o, pickup_f) if pickup_f else False)
            end_val = getattr(o, rent_return_f) if rent_return_f else (getattr(o, return_f) if return_f else False)
            prod_ids = tuple(sorted(o.order_line.mapped('product_id').ids))
            existing_keys.add((start_val, end_val, prod_ids))

        t_from = self._parse_hhmm(self.turn_hour_from or "09:00")
        t_to = self._parse_hhmm(self.turn_hour_to or "18:00")

        ui_ctx = dict(self.env.context or {})
        ui_ctx.setdefault('tz', self._normalize_tz_name(self.env.context.get('tz') or partner.tz or self.env.user.tz or 'UTC'))
        ui_ctx.setdefault('lang', partner.lang or self.env.user.lang)

        for iso in sorted(set(iso_dates)):
            y, m, d = [int(x) for x in iso.split('-')]
            start_dt = self._to_utc_dt(y, m, d, t_from)
            stop_dt = self._to_utc_dt(y, m, d, t_to)

            key_products = (variant.id,)
            if (start_dt, stop_dt, key_products) in existing_keys:
                continue

            line_vals = {'product_id': variant.id, 'product_uom_qty': 1.0}
            order_vals = {
                'partner_id': partner.id,
                'company_id': company.id,
                'x_turn_slot': True,
                'origin': f"Turn Slots – {self.display_name} {iso}",
                'note': f"Auto – Turno {self.display_name} {iso}",
                'order_line': [(0, 0, line_vals)],
                'x_turn_yacht_id': (self.turn_yacht_id.id or False),
                'x_turn_season_id': (self.nav_season_id.id or False),
            }
            if pricelist_f and not order_vals.get(pricelist_f):
                order_vals[pricelist_f] = partner.property_product_pricelist.id or False
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

                if 'x_turn_date' in Order._fields:
                    setattr(tmp, 'x_turn_date', fields.Date.to_date(iso))
                    if 'x_turn_hour_from' in Order._fields:
                        setattr(tmp, 'x_turn_hour_from', self.turn_hour_from or "09:00")
                    if 'x_turn_hour_to' in Order._fields:
                        setattr(tmp, 'x_turn_hour_to', self.turn_hour_to or "18:00")

                order = Order.create(tmp._convert_to_write(tmp._cache))

                try:
                    if hasattr(order, 'action_update_rental_prices'):
                        order.action_update_rental_prices()
                except Exception:
                    _logger.exception("No se pudo actualizar precios de renting.")

                try:
                    order.invalidate_recordset()
                    if hasattr(order.order_line, '_compute_is_rental'): order.order_line._compute_is_rental()
                    if hasattr(order, '_compute_has_rented_products'): order._compute_has_rented_products()
                    if hasattr(order, '_compute_is_rental_order'): order._compute_is_rental_order()
                    if hasattr(order, '_compute_rental_status'): order._compute_rental_status()
                    if hasattr(order, '_compute_remaining_hours'): order._compute_remaining_hours()
                except Exception:
                    _logger.exception("No se pudo forzar recomputes de alquiler.")

    def action_fix_existing_turn_orders(self):
        Order = self.env['sale.order'].sudo()
        for prod in self:
            partner = prod._get_turn_partner(prod.company_id or self.env.company)
            orders = Order.search([
                ('x_turn_slot', '=', True),
                ('partner_id', '=', partner.id),
                ('company_id', '=', (prod.company_id or self.env.company).id),
            ])
            for order in orders:
                try:
                    if hasattr(order, '_onchange_rental_dates'):
                        order._onchange_rental_dates()
                    for line in order.order_line.filtered(lambda l: l.product_id == prod.product_variant_id and not l.display_type):
                        if hasattr(line, '_onchange_product_id'):
                            line._onchange_product_id()
                        if hasattr(line, '_onchange_product_uom_qty'):
                            line._onchange_product_uom_qty()
                    if hasattr(order, 'action_update_rental_prices'):
                        order.action_update_rental_prices()
                    order.invalidate_recordset()
                    if hasattr(order.order_line, '_compute_is_rental'):
                        order.order_line._compute_is_rental()
                    if hasattr(order, '_compute_has_rented_products'):
                        order._compute_has_rented_products()
                    if hasattr(order, '_compute_is_rental_order'):
                        order._compute_is_rental_order()
                    if hasattr(order, '_compute_rental_status'):
                        order._compute_rental_status()
                    if hasattr(order, '_compute_remaining_hours'):
                        order._compute_remaining_hours()
                except Exception:
                    _logger.exception("No se pudo reparar la orden %s", order.name or order.id)

    def action_open_turn_batch_wizard(self):
        self.ensure_one()
        csv_dates = ", ".join(sorted({l.date.isoformat() for l in self.turn_param_line_ids if l.date}))
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
                "default_hour_from": self.turn_hour_from or "08:00",
                "default_hour_to": self.turn_hour_to or "18:00",
                "default_status": self.turn_status or "inactive",
                "default_quota": self.turn_quota or 0,
                "default_line_ids": [(0, 0, {"date": l.date}) for l in self.turn_param_line_ids if l.date],
                "default_wizard_available_dates": csv_dates,
            },
        }

# =====================================================
# Wizard (crear/actualizar lotes de fechas)
# =====================================================
class RentalTurnBatchWizard(models.TransientModel):
    _name = "rental.turn.batch.wizard"
    _description = "Wizard Registrar Fechas y Parámetros"

    product_id = fields.Many2one("product.template", required=True, string="Product", readonly=True)
    yacht_id = fields.Many2one("fleet.vehicle", string="Embarcación")
    season_id = fields.Many2one("rental.season", string="Temporada (Zona)")

    def _time_selection(self):
        step, vals = 30, []
        for h in range(24):
            for m in range(0, 60, step):
                s = f"{h:02d}:{m:02d}"
                vals.append((s, s))
        return vals

    hour_from = fields.Selection(_time_selection, string="Hora desde", default="08:00")
    hour_to = fields.Selection(_time_selection, string="Hora hasta", default="18:00")

    status = fields.Selection(
        [("active", "Activo"), ("inactive", "Inactivo")],
        string="Estado", default="inactive", required=True
    )
    quota = fields.Integer(string="Cuota", default=0)

    wizard_available_dates = fields.Text(string="Calendario (selección)")
    line_ids = fields.One2many("rental.turn.batch.wizard.line", "wizard_id", string="Fechas seleccionadas")

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        csv_ctx = self.env.context.get("default_wizard_available_dates")
        if csv_ctx:
            vals.setdefault("wizard_available_dates", csv_ctx)
        elif vals.get("product_id"):
            prod = self.env["product.template"].browse(vals["product_id"])
            csv_text = ", ".join([l.date.isoformat() for l in prod.turn_param_line_ids if l.date])
            vals.setdefault("wizard_available_dates", csv_text)
        return vals

    @api.onchange("wizard_available_dates")
    def _onchange_wizard_available_dates(self):
        for wiz in self:
            csv = wiz.wizard_available_dates or ""
            dates = sorted({s.strip() for s in csv.split(",") if s.strip()})
            wiz.line_ids = [(5, 0, 0)] + [(0, 0, {"date": d}) for d in dates]

    def action_confirm(self):
        self.ensure_one()
        prod = self.product_id.sudo()

        def _normalize_tz_name_any(tzname):
            if not tzname:
                return "UTC"
            name = str(tzname).strip()
            if name.lower().startswith("etc/"):
                name = "Etc/" + name[4:]
            elif name.lower().startswith("etc-"):
                name = "Etc/" + name[4:]
            m = (re.search(r"(?i)^Etc/GMT\s*([+-])\s*(\d+)$", name)
                 or re.search(r"(?i)^GMT\s*([+-])\s*(\d+)$", name)
                 or re.search(r"(?i)^Etc[-/ ]GMT\s*([+-])\s*(\d+)$", name))
            if m:
                sign, num = m.groups()
                inv = "+" if sign == "-" else "-"
                name = f"Etc/GMT{inv}{num}"
            try:
                pytz.timezone(name)
                return name
            except Exception:
                return "UTC"

        try:
            with self.env.cr.savepoint():
                prod.write({
                    "turn_yacht_id": self.yacht_id.id or False,
                    "nav_season_id": self.season_id.id or False,
                    "turn_hour_from": self.hour_from or "08:00",
                    "turn_hour_to": self.hour_to or "18:00",
                    "turn_quota": self.quota or 0,
                    "turn_status": self.status or "inactive",
                })

                Line = self.env["rental.turn.param.line"].sudo()
                selected_dates = sorted({fields.Date.to_date(l.date) for l in self.line_ids if l.date})

                existing = Line.search([("product_id", "=", prod.id)])
                existing_by_date = {r.date: r for r in existing}

                vals_common = {
                    "product_id": prod.id,
                    "yacht_id": self.yacht_id.id or False,
                    "season_id": self.season_id.id or False,
                    "hour_from": self.hour_from or "08:00",
                    "hour_to": self.hour_to or "18:00",
                    "status": self.status or "inactive",
                    "quota": self.quota or 0,
                }

                for d in selected_dates:
                    with self.env.cr.savepoint():
                        if d in existing_by_date:
                            existing_by_date[d].write(vals_common)
                        else:
                            Line.create(dict(vals_common, date=d))

                to_keep = set(selected_dates)
                to_drop = existing.filtered(lambda r: r.date not in to_keep)
                if to_drop:
                    with self.env.cr.savepoint():
                        to_drop.unlink()

                iso_dates = [d.isoformat() for d in selected_dates]

                with self.env.cr.savepoint():
                    prod._sync_blocked_periods_from_turn_dates(iso_dates)

                with self.env.cr.savepoint():
                    raw_tz = (self.env.user.tz or self.env.context.get('tz') or 'UTC')
                    if hasattr(prod, "_normalize_tz_name"):
                        try:
                            user_tz = prod._normalize_tz_name(raw_tz)
                        except Exception:
                            user_tz = _normalize_tz_name_any(raw_tz)
                    else:
                        user_tz = _normalize_tz_name_any(raw_tz)

                    prod.with_context(tz=user_tz)._ensure_turn_orders(iso_dates)

        except Exception as e:
            _logger.exception("Error general al confirmar el wizard de turnos")
            raise UserError(_("No se pudieron registrar los turnos.\nDetalle técnico: %s") % (str(e) or repr(e)))

        return {"type": "ir.actions.act_window_close"}

# =====================================================
# PINTAR SIEMPRE EN GANTT / SCHEDULE (líneas de venta)
# =====================================================
class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    x_sched_start = fields.Datetime(string="Gantt Start", compute="_compute_turn_sched", store=True, index=True)
    x_sched_stop = fields.Datetime(string="Gantt Stop", compute="_compute_turn_sched", store=True, index=True)
    x_is_rental_any = fields.Boolean(string="Rental (any)", compute="_compute_turn_sched", store=True, index=True)
    x_turn_yacht_id = fields.Many2one(
        "fleet.vehicle",
        string="Embarcación (Orden)",
        related="order_id.x_turn_yacht_id",
        store=True, readonly=True, index=True,
    )
    x_turn_season_id = fields.Many2one(
        "rental.season",
        string="Temporada (Orden)",
        related="order_id.x_turn_season_id",
        store=True, readonly=True, index=True,
    )

    @api.depends(
        "display_type",
        "product_id", "product_id.rent_ok",
        "order_id", "order_id.rental_start_date", "order_id.rental_return_date",
        "order_id.state",
    )
    def _compute_turn_sched(self):
        for l in self:
            if l.display_type:
                l.x_is_rental_any = False
                l.x_sched_start = False
                l.x_sched_stop = False
                continue

            is_rental_flag = bool(getattr(l, "is_rental", False))
            is_rent_ok = bool(getattr(l.product_id, "rent_ok", False))
            l.x_is_rental_any = is_rental_flag or is_rent_ok

            start = (
                getattr(l, "rental_start_date", False) or
                getattr(l, "pickup_date", False) or
                getattr(l.order_id, "rental_start_date", False)
            )
            stop = (
                getattr(l, "rental_return_date", False) or
                getattr(l, "return_date", False) or
                getattr(l.order_id, "rental_return_date", False)
            )

            l.x_sched_start = start
            l.x_sched_stop = stop

class RentalTurnBatchWizardLine(models.TransientModel):
    _name = "rental.turn.batch.wizard.line"
    _description = "Wizard - Fecha seleccionada"

    wizard_id = fields.Many2one("rental.turn.batch.wizard", required=True, ondelete="cascade")
    date = fields.Date(required=True)