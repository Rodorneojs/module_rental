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
    x_turn_slot      = fields.Boolean(default=False,  index=True)
    x_turn_yacht_id  = fields.Many2one("fleet.vehicle", string="Embarcación",index=True)
    x_turn_season_id = fields.Many2one("rental.season", string="Temporada",index=True)
    def action_add_rental_product(self):
        """Abre el wizard para elegir un producto de alquiler y agregarlo a la orden."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "custom_rental.action_rental_product_picker"
        )
        # Contexto por defecto para el wizard
        action["context"] = {
            **self.env.context,
            "default_order_id": self.id,
        }
        return action
