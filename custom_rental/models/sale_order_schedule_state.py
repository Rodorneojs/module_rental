# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Mapeo del estado nativo de Odoo a tu estado de agenda personalizado.
# Se usa para sincronizar si el estado cambia por un proceso externo.
NATIVE_TO_X_STATE = {
    'draft':    'available',
    'sent':     'request',
    'sale':     'confirmed',
    'done':     'confirmed',
    'cancel':   'cancelled',
}

# Mapeo adicional para los estados del módulo sale_renting.
RENTING_NATIVE_TO_X_STATE = {
    'pickup':   'pre_onboard',
    'return':   'pre_onboard',
    'returned': 'invoiced',
}

class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_schedule_state = fields.Selection(
        selection=[
            ('available',   'Available'),      # Como Quotation (borrador)
            ('request',     'Request'),        # Como Quotation Sent (solicitud)
            ('pay_pending', 'Pay Pending'),    # Como Quotation Sent
            ('option',      'Option'),         # Como Quotation (borrador)
            ('private_use', 'Private Use'),    # Bloqueo interno, equivale a Cancelled
            ('pre_onboard', 'PreOnboard'),     # Reservado, listo para salida
            ('confirmed',   'Confirmed'),      # Reservado
            ('cancelled',   'Cancelled'),      # Cancelado
            ('invoiced',    'Invoiced'),       # Estado visual para facturado
        ],
        string="Schedule State",
        default="available",
        copy=False,
        index=True,
        store=True,
        tracking=True,
    )

    def _get_full_native_mapping(self):
        """Devuelve el mapeo de estados completo, incluyendo renting si aplica."""
        mapping = NATIVE_TO_X_STATE.copy()
        if 'is_rental_order' in self._fields:
            mapping.update(RENTING_NATIVE_TO_X_STATE)
        return mapping

    def write(self, vals):
        # Si se está sincronizando, no hacer nada para evitar bucles.
        if self.env.context.get('syncing_state'):
            return super().write(vals)

        # Contexto para marcar que estamos en un proceso de sincronización.
        ctx = self.env.context.copy()
        ctx['syncing_state'] = True

        # 1. Sincronizar x_schedule_state -> state nativo
        if 'x_schedule_state' in vals:
            new_x_state = vals['x_schedule_state']
            for o in self:
                if o.x_schedule_state != new_x_state:
                    if new_x_state in ('confirmed', 'pre_onboard'):
                        if o.state in ('draft', 'sent'):
                            o.with_context(ctx).action_confirm()
                    elif new_x_state in ('cancelled', 'private_use'):
                        if o.state != 'cancel':
                            o.with_context(ctx).action_cancel()
                    elif new_x_state in ('available', 'option'):
                        if o.state in ('cancel', 'sent'):
                            o.with_context(ctx).action_draft()
                    elif new_x_state in ('request', 'pay_pending'):
                        if o.state == 'draft':
                            o.with_context(ctx).write({'state': 'sent'})

        res = super().write(vals)

        # 2. Sincronizar state nativo -> x_schedule_state
        if 'state' in vals:
            mapping = self._get_full_native_mapping()
            for o in self:
                if o.state in mapping and o.x_schedule_state != mapping[o.state]:
                    o.with_context(ctx).write({'x_schedule_state': mapping[o.state]})

        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Al crear, asegura la consistencia inicial de los estados."""
        recs = super().create(vals_list)
        mapping = self._get_full_native_mapping()
        for r in recs:
            if r.state in mapping and r.x_schedule_state != mapping[r.state]:
                r.with_context(syncing_state=True).x_schedule_state = mapping[r.state]
        return recs

    # --- Overrides de acciones para mantener la consistencia ---
    def action_confirm(self):
        res = super().action_confirm()
        if not self.env.context.get('syncing_state'):
            self.with_context(syncing_state=True).write({'x_schedule_state': 'confirmed'})
        return res

    def action_cancel(self):
        res = super().action_cancel()
        if not self.env.context.get('syncing_state'):
            self.with_context(syncing_state=True).write({'x_schedule_state': 'cancelled'})
        return res

    def action_draft(self):
        res = super().action_draft()
        if not self.env.context.get('syncing_state'):
            self.with_context(syncing_state=True).write({'x_schedule_state': 'available'})
        return res