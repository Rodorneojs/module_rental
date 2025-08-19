# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class RentalProductImage(models.Model):
    _name = 'rental.product.image'
    _description = 'Image Gallery for Rental Products'
    _order = 'sequence, id'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        ondelete='cascade',
        required=True,
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Title')
    image = fields.Binary(string='Image', attachment=True)
    is_default = fields.Boolean(string='Default')

    @api.model_create_multi
    def create(self, vals_list):
        # Creamos todos los registros de una vez
        records = super().create(vals_list)
        # Para cada nuevo registro, si is_default viene marcado, desmarcamos los demás
        for rec, vals in zip(records, vals_list):
            if vals.get('is_default'):
                rec._unset_others_default()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Tras actualizar, aplicamos la misma lógica si se cambió is_default
        if 'is_default' in vals and vals.get('is_default'):
            for rec in self:
                rec._unset_others_default()
        return res

    def _unset_others_default(self):
        # Desmarca como default todas las demás imágenes del mismo producto
        for rec in self:
            others = rec.search([
                ('product_tmpl_id', '=', rec.product_tmpl_id.id),
                ('id',               '!=', rec.id),
                ('is_default',       '=', True),
            ])
            if others:
                others.write({'is_default': False})
