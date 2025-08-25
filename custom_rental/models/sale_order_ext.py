# -*- coding: utf-8 -*-
from odoo import fields, models

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # enlace directo a tu turno
    turn_line_id = fields.Many2one(
        "rental.turn.param.line",
        string="Turno",
        ondelete="set null",
        index=True,
    )

    # (opcional) metadatos útiles
    x_turn_slot      = fields.Boolean(default=False, index=True)
    x_turn_yacht_id  = fields.Many2one("fleet.vehicle", index=True)
    x_turn_season_id = fields.Many2one("rental.season", index=True)
