from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    weeks_occupied = fields.Integer(string='Weeks Occupied', default=0, config_parameter='custom_rental.weeks_occupied')
