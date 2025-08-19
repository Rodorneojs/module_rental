# -*- coding: utf-8 -*-

# from odoo import models, fields, api


# class custom_rental(models.Model):
#     _name = 'custom_rental.custom_rental'
#     _description = 'custom_rental.custom_rental'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

