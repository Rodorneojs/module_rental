# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Mapeo entre el state nativo de renting y tu estado de agenda
# draft->Available, sent->Request, pickup->Private Use, return->PreOnboard,
# returned->Invoiced, cancel->Cancelled
NATIVE_TO_X = {
    "draft":    "available",
    "sent":     "request",
    "pickup":   "private_use",
    "return":   "pre_onboard",
    "returned": "invoiced",
    "cancel":   "cancelled",
}

class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_schedule_state = fields.Selection(
        selection=[
            ("available",   "Available"),
            ("private_use", "Private Use"),
            ("request",     "Request"),
            ("pay_pending", "Pay Pending"),
            ("option",      "Option"),
            ("pre_onboard", "PreOnboard"),
            ("confirmed",   "Confirmed"),
            ("cancelled",   "Cancelled"),
            ("invoiced",    "Invoiced"),
        ],
        string="Schedule State",
        default="available",
        copy=False,
        index=True,
        store=True,
    )

    # --- Sincroniza automáticamente cuando cambia el state nativo ---
    @api.onchange('state')
    def _onchange_native_state_sync_x(self):
        for o in self:
            if o.state in NATIVE_TO_X and not o.env.context.get("skip_x_state_sync"):
                o.x_schedule_state = NATIVE_TO_X[o.state]

    def write(self, vals):
        res = super().write(vals)
        # Si cambió state por backend/botón, reflejamos en x_schedule_state
        if 'state' in vals:
            for o in self.with_context(skip_x_state_sync=False):
                if o.state in NATIVE_TO_X and (not o.x_schedule_state or o.x_schedule_state in NATIVE_TO_X.values()):
                    o.x_schedule_state = NATIVE_TO_X[o.state]
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        # Al crear, si es renting, asigna x_schedule_state según state nativo
        for r, vals in zip(recs, vals_list):
            if not vals.get('x_schedule_state') and r.state in NATIVE_TO_X:
                r.x_schedule_state = NATIVE_TO_X[r.state]
        return recs

    # --- Opcional: marcar algunos hooks comunes si existen (sin romper si no están) ---
    def action_confirm(self):
        res = super().action_confirm()
        # tras confirmar, tu estado deseado es "confirmed"
        self.filtered(lambda s: True).write({'x_schedule_state': 'confirmed'})
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self.write({'x_schedule_state': 'cancelled'})
        return res
