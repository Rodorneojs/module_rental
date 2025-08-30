# models/sale_order_activity.py
# -*- coding: utf-8 -*-
from odoo import api, fields, models

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # 1) Columna visible en lista (NO almacenada)
    x_activity_name = fields.Char(
        string='Activity Name',
        compute='_compute_activity_name',
        store=False,
        readonly=True,
        help="Nombre de la actividad (producto principal) para mostrar en la lista."
    )

    # 2) Faceta para searchpanel (Many2one almacenado, indexado)
    x_activity_product_tmpl_id = fields.Many2one(
        'product.template',
        string='Activity Product',
        compute='_compute_activity_product',
        store=True,
        readonly=True,
        index=True,
        help="Plantilla de producto principal para facetar/filtrar en el searchpanel."
    )

    # ---------- Compute: x_activity_name (no stored) ----------
    @api.depends(
        'order_line.product_id',
        'order_line.display_type',
        'order_line.is_rental',
        'order_line.sequence',
    )
    def _compute_activity_name(self):
        for order in self:
            txt = ''
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
            if lines:
                rental = lines.filtered(lambda l: getattr(l, 'is_rental', False))
                line = (rental or lines.sorted(key=lambda l: (l.sequence, l.id)))[0]
                txt = line.product_id.display_name or line.product_id.name or ''
            order.x_activity_name = txt

    # ---------- Compute: x_activity_product_tmpl_id (stored) ----------
    @api.depends(
        'order_line.product_id',
        'order_line.display_type',
        'order_line.is_rental',
        'order_line.sequence',
    )
    def _compute_activity_product(self):
        for order in self:
            tmpl = False
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
            if lines:
                rental = lines.filtered(lambda l: getattr(l, 'is_rental', False))
                line = (rental or lines.sorted(key=lambda l: (l.sequence, l.id)))[0]
                tmpl = line.product_id.product_tmpl_id if line.product_id else False
            order.x_activity_product_tmpl_id = tmpl or False
