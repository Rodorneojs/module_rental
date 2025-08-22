
# -*- coding: utf-8 -*-
from odoo import fields, models

class RentalBlockedPeriod(models.Model):
    _inherit = "rental.blocked.period"

    turn_block = fields.Boolean(default=False, index=True)
