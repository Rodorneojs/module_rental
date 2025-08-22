
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from ..utils.datetime_tools import time_selection, hm_to_minutes, to_utc_naive, to_user_tz
from datetime import datetime, time, timedelta

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Fecha/Hora única para alquiler de 1 día
    x_turn_date = fields.Date()
    x_turn_hour_from = fields.Float()  # 8.0 = 08:00
    x_turn_hour_to   = fields.Float()
    @staticmethod
    def _float_to_time(f):
        h = int(f)
        m = int(round((f - h) * 60))
        return time(h, m)
    def _sync_rental_dates_from_turn(self, vals):
        """Mapea x_turn_* a pickup/return si existen esos campos en el modelo."""
        if 'pickup_date' not in self._fields or 'return_date' not in self._fields:
            return vals
        turn_date_str = vals.get('x_turn_date') or self.x_turn_date
        if not turn_date_str:
            return vals
        h_from = vals.get('x_turn_hour_from', self.x_turn_hour_from or "08:00")
        h_to = vals.get('x_turn_hour_to', self.x_turn_hour_to or "18:00")

        turn_date = fields.Date.to_date(turn_date_str)
        if hm_to_minutes(h_from) >= hm_to_minutes(h_to):
            raise ValidationError(_("La hora de inicio debe ser menor que la hora final."))

        user_tz = self.env.user.tz or "UTC"
        vals['pickup_date'] = to_utc_naive(turn_date, h_from, user_tz)
        vals['return_date'] = to_utc_naive(turn_date, h_to, user_tz)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        processed = [self._sync_rental_dates_from_turn(dict(v)) for v in vals_list]
        orders = super().create(processed)
        # Si ya existen pickup/return, rellenar x_turn_* para coherencia visual
        if 'pickup_date' in self._fields and 'return_date' in self._fields:
            user_tzname = self.env.user.tz or "UTC"
            for o in orders.filtered(lambda o: o.pickup_date and o.return_date and not o.x_turn_date):
                p = to_user_tz(o.pickup_date, user_tzname)
                r = to_user_tz(o.return_date, user_tzname)
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
    @staticmethod
    def _to_time(val):
        """Acepta '08:00', 8.5, 8, time(8,0) y devuelve time(h, m)."""
        if isinstance(val, time):
            return val
        if isinstance(val, (int, float)):          # ej. 8.5
            h = int(val)
            m = int(round((val - h) * 60))
            return time(h, m)
        if isinstance(val, str) and val:
            try:
                hh, mm = val.split(':')
                return time(int(hh), int(mm))
            except Exception:
                pass
        return time(0, 0)
    @api.onchange('x_turn_date', 'x_turn_hour_from', 'x_turn_hour_to')
    def _onchange_turn_dates(self):
        for o in self:
            if o.x_turn_date and o.x_turn_hour_from is not None and o.x_turn_hour_to is not None:
                h_from = int(o.x_turn_hour_from)
                m_from = int(round((o.x_turn_hour_from - h_from) * 60))
                h_to   = int(o.x_turn_hour_to)
                m_to   = int(round((o.x_turn_hour_to - h_to) * 60))
                start_dt = datetime.combine(o.x_turn_date, time(h_from, m_from))
                end_dt   = datetime.combine(o.x_turn_date, time(h_to,   m_to))
                # Si usas pricing nativo de renting, sigue rellenando los nativos
                o.with_context(tracking_disable=True).update({
                    'rental_start_date': start_dt,
                    'rental_return_date': end_dt,
                })
