# custom_rental/models/sale_order_single_date.py

# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import datetime
import pytz
import re

# =====================================================
# Helpers de Fecha y Zona Horaria
# =====================================================

def _normalize_tz_name(tz_name):
    """Normaliza nombres de zona horaria para pytz, corrigiendo el signo de Etc/GMT."""
    if not tz_name:
        return "UTC"
    name = str(tz_name).strip()
    if name.lower().startswith("etc/"):
        name = "Etc/" + name[4:]
    elif name.lower().startswith("etc-"):
        name = "Etc/" + name[4:]
    
    m = (re.search(r"(?i)^Etc/GMT\s*([+-])\s*(\d+)$", name) or
         re.search(r"(?i)^GMT\s*([+-])\s*(\d+)$", name) or
         re.search(r"(?i)^Etc[-/ ]GMT\s*([+-])\s*(\d+)$", name))
    if m:
        sign, num = m.groups()
        inv = "+" if sign == "-" else "-"
        name = f"Etc/GMT{inv}{num}"
    try:
        pytz.timezone(name)
        return name
    except Exception:
        return "UTC"

def _time_selection():
    """Genera una lista de horas en intervalos de 30 minutos para campos Selection."""
    return [(f"{h:02d}:{m:02d}", f"{h:02d}:{m:02d}") for h in range(24) for m in range(0, 60, 30)]

def _hm_to_minutes(hhmm):
    """Convierte una cadena 'HH:MM' a minutos totales."""
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def _to_utc_naive(date_obj, hhmm, user_tzname):
    """Convierte una fecha y hora locales a un objeto datetime UTC naive."""
    hh, mm = [int(x) for x in (hhmm or "00:00").split(":")]
    local_dt = datetime(date_obj.year, date_obj.month, date_obj.day, hh, mm, 0)
    tz = pytz.timezone(_normalize_tz_name(user_tzname))
    try:
        aware = tz.localize(local_dt, is_dst=None)
    except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
        aware = tz.localize(local_dt, is_dst=False)
    return aware.astimezone(pytz.UTC).replace(tzinfo=None)

def _to_user_tz(dt, user_tzname):
    """Convierte un datetime (potencialmente naive UTC) a la zona horaria del usuario."""
    tz = pytz.timezone(_normalize_tz_name(user_tzname))
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(tz)

# =====================================================
# Extensión del Modelo SaleOrder
# =====================================================

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # --- Campos para gestionar fecha/hora única de alquiler ---
    x_turn_date = fields.Date(string="Rental Date")

    # ¡CORRECCIÓN APLICADA AQUÍ!
    # Usamos una función lambda para que Odoo pueda llamar a la función de selección
    # sin causar un error de argumentos.
    x_turn_hour_from = fields.Selection(
        selection=lambda self: _time_selection(),
        string="Start Time",
        default="08:00",
    )
    x_turn_hour_to = fields.Selection(
        selection=lambda self: _time_selection(),
        string="End Time",
        default="18:00",
    )

    # --- Lógica de Sincronización ---
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
    def _sync_rental_dates_from_turn(self, vals):
        if 'pickup_date' not in self._fields or 'return_date' not in self._fields:
            return vals

        turn_date_str = vals.get('x_turn_date') or self.x_turn_date
        if not turn_date_str:
            return vals
            
        h_from = vals.get('x_turn_hour_from', self.x_turn_hour_from or "08:00")
        h_to = vals.get('x_turn_hour_to', self.x_turn_hour_to or "18:00")
        turn_date = fields.Date.to_date(turn_date_str)

        if _hm_to_minutes(h_from) >= _hm_to_minutes(h_to):
            raise ValidationError(_("La hora de inicio debe ser menor que la hora final."))

        user_tz = self.env.user.tz or "UTC"
        vals['pickup_date'] = _to_utc_naive(turn_date, h_from, user_tz)
        vals['return_date'] = _to_utc_naive(turn_date, h_to, user_tz)
        return vals

    # --- Métodos ORM Sobrescritos ---

    @api.model_create_multi
    def create(self, vals_list):
        processed_vals = [self._sync_rental_dates_from_turn(dict(vals)) for vals in vals_list]
        orders = super().create(processed_vals)

        if 'pickup_date' in self._fields and 'return_date' in self._fields:
            user_tzname = self.env.user.tz or "UTC"
            for o in orders.filtered(lambda o: o.pickup_date and o.return_date and not o.x_turn_date):
                p = _to_user_tz(o.pickup_date, user_tzname)
                r = _to_user_tz(o.return_date, user_tzname)
                if p.date() == r.date():
                    o.write({
                        'x_turn_date': p.date(),
                        'x_turn_hour_from': f"{p.hour:02d}:{p.minute:02d}",
                        'x_turn_hour_to': f"{r.hour:02d}:{r.minute:02d}",
                    })
        return orders

    def write(self, vals):
        if any(k in vals for k in ('x_turn_date', 'x_turn_hour_from', 'x_turn_hour_to')):
            record_vals = dict(vals)
            self._sync_rental_dates_from_turn(record_vals)
            return super().write(record_vals)
        
        return super().write(vals)

    # --- Métodos Onchange ---

    @api.onchange('x_turn_date', 'x_turn_hour_from', 'x_turn_hour_to')
    def _onchange_turn_to_rental_dates(self):
        if not (self.x_turn_date and self.x_turn_hour_from and self.x_turn_hour_to):
            return

        if _hm_to_minutes(self.x_turn_hour_from) >= _hm_to_minutes(self.x_turn_hour_to):
            # No se necesita ValidationError aquí, ya que el onchange es para la UI
            # y el constrains del write ya lo valida al guardar.
            return

        if 'pickup_date' in self._fields:
            self.pickup_date = _to_utc_naive(self.x_turn_date, self.x_turn_hour_from, self.env.user.tz or "UTC")
        if 'return_date' in self._fields:
            self.return_date = _to_utc_naive(self.x_turn_date, self.x_turn_hour_to, self.env.user.tz or "UTC")