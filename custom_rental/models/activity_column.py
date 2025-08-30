# -*- coding: utf-8 -*-
from odoo import api, fields, models

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Columna solo de lectura para la lista
    x_activity_name = fields.Char(
        string='Activity',
        compute='_compute_x_activity_name',
        store=False,
        readonly=True,
    )

    @api.depends(
        'order_line.product_id',
        'order_line.display_type',
        'order_line.is_rental',
        'order_line.sequence',
    )
    def _compute_x_activity_name(self):
        for order in self:
            txt = ''
            # líneas reales con producto
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
            if lines:
                # prioriza renting; si no hay, primera por sequence
                rental = lines.filtered(lambda l: getattr(l, 'is_rental', False))
                line = (rental or lines.sorted(key=lambda l: (l.sequence, l.id)))[0]
                txt = line.product_id.display_name or line.product_id.name or ''
            order.x_activity_name = txt
