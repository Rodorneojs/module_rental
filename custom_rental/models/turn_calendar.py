
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class RentalCalendarDate(models.Model):
    _name = "rental.calendar.date"
    _description = "Fecha disponible de producto"
    _order = "date"

    product_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    date = fields.Date(required=True, index=True)

    _sql_constraints = [
        ("product_date_uniq", "unique(product_id, date)", "La fecha ya existe para este producto."),
    ]
