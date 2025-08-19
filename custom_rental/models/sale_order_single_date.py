# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import datetime
import pytz

# ---------- helpers ----------

def _time_selection():
    step, vals = 30, []
    for h in range(24):
        for m in range(0, 60, step):
            s = f"{h:02d}:{m:02d}"
            vals.append((s, s))
    return vals

def _hm_to_minutes(hhmm):
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def _to_utc_naive(date_obj, hhmm, user_tzname):
    """Devuelve datetime naive en UTC a partir de fecha + 'HH:MM' en tz del usuario."""
    hh, mm = [int(x) for x in (hhmm or "00:00").split(":")]
    local_dt = datetime(date_obj.year, date_obj.month, date_obj.day, hh, mm, 0)
    tz = pytz.timezone(user_tzname or "UTC")
    if local_dt.tzinfo is None:
        local_dt = tz.localize(local_dt)
    return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

def _to_user_tz(dt, user_tzname):
    user_tz = pytz.timezone(user_tzname or "UTC")
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(user_tz)

# ---------- modelo ----------

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Campos visibles (fecha única)
    x_turn_date = fields.Date(string="Rental date")

    # ¡IMPORTANTE!: usar un callable que acepte self; evita el TypeError al abrir la vista
    x_turn_hour_from = fields.Selection(
        selection=lambda self: _time_selection(),
        string="Start time",
        default="08:00",
    )
    x_turn_hour_to = fields.Selection(
        selection=lambda self: _time_selection(),
        string="End time",
        default="18:00",
    )
    x_turn_yacht_id = fields.Many2one(
        "fleet.vehicle",
        string="Embarcación Asociada",
        index=True,
    )
    x_turn_season_id = fields.Many2one(
        "rental.season",
        string="Temporada (Zona)",
        index=True,
    )

    # ---------- sync helpers ----------
    def _sync_pick_return_from_single_vals(self, vals):
        Order = self.env['sale.order']
        has_pickup = 'pickup_date' in Order._fields
        has_return = 'return_date' in Order._fields
        if not (has_pickup or has_return):
            return vals

        if not vals.get('x_turn_date'):
            return vals
        if not (vals.get('x_turn_hour_from') or vals.get('x_turn_hour_to')):
            return vals

        h_from = vals.get('x_turn_hour_from', self.x_turn_hour_from or "08:00")
        h_to   = vals.get('x_turn_hour_to',   self.x_turn_hour_to   or "18:00")
        d = fields.Date.to_date(vals['x_turn_date'])

        if (_hm_to_minutes(h_from) is not None and
            _hm_to_minutes(h_to)   is not None and
            _hm_to_minutes(h_from) >= _hm_to_minutes(h_to)):
            raise ValidationError(_("La hora de inicio debe ser menor que la hora final."))

        user_tz = self.env.user.tz or "UTC"
        if has_pickup:
            vals['pickup_date'] = _to_utc_naive(d, h_from, user_tz)
        if has_return:
            vals['return_date'] = _to_utc_naive(d, h_to, user_tz)
        return vals

    # ---------- ORM overrides ----------
    @api.model_create_multi
    def create(self, vals_list):
        fixed = []
        for vals in vals_list:
            fixed.append(self._sync_pick_return_from_single_vals(dict(vals)))
        orders = super().create(fixed)

        # si vienen con pickup/return pero sin x_*, derivarlos para que la UI muestre tu bloque
        Order = self.env['sale.order']
        has_pickup = 'pickup_date' in Order._fields
        has_return = 'return_date' in Order._fields
        if has_pickup and has_return:
            user_tzname = self.env.user.tz or "UTC"
            for o in orders:
                if o.pickup_date and o.return_date and not o.x_turn_date:
                    p = _to_user_tz(o.pickup_date, user_tzname)
                    r = _to_user_tz(o.return_date, user_tzname)
                    if p.date() == r.date():
                        o.write({
                            'x_turn_date': p.date(),
                            'x_turn_hour_from': f"{p.hour:02d}:{p.minute:02d}",
                            'x_turn_hour_to':   f"{r.hour:02d}:{r.minute:02d}",
                        })
        return orders

    def write(self, vals):
        if any(k in vals for k in ('x_turn_date', 'x_turn_hour_from', 'x_turn_hour_to')):
            for rec in self:
                vals = rec._sync_pick_return_from_single_vals(dict(vals))
        return super().write(vals)

    # ---------- onchange para que al editar se actualice el motor de rental ----------
    @api.onchange('x_turn_date', 'x_turn_hour_from', 'x_turn_hour_to')
    def _onchange_single_to_pick_return(self):
        Order = self.env['sale.order']
        has_pickup = 'pickup_date' in Order._fields
        has_return = 'return_date' in Order._fields
        for o in self:
            if not (o.x_turn_date and o.x_turn_hour_from and o.x_turn_hour_to):
                continue
            if _hm_to_minutes(o.x_turn_hour_from) >= _hm_to_minutes(o.x_turn_hour_to):
                raise ValidationError(_("La hora de inicio debe ser menor que la hora final."))
            if has_pickup:
                o.pickup_date = _to_utc_naive(o.x_turn_date, o.x_turn_hour_from, self.env.user.tz or "UTC")
            if has_return:
                o.return_date = _to_utc_naive(o.x_turn_date, o.x_turn_hour_to,   self.env.user.tz or "UTC")
