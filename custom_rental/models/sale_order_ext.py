# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from .schedule_states import SCHEDULE_STATE_SELECTION

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Flags del flujo "Turnos"
    x_turn_slot = fields.Boolean(
        string="Turn Slot",
        default=False,
        index=True,
        help="Orden creada automáticamente desde 'Turnos' del producto.",
    )
    x_turn_yacht_id = fields.Many2one(
        "fleet.vehicle",
        string="Embarcación",
        help="Embarcación/vehículo vinculado al turno que originó la orden.",
        index=True,
    )
    x_turn_season_id = fields.Many2one(
        "rental.season",
        string="Temporada",
        help="Temporada/Zona del turno que originó la orden.",
        index=True,
    )
    x_schedule_state = fields.Selection(
        selection=SCHEDULE_STATE_SELECTION,
        string="Estado",
        default='available',
    )

    def action_add_rental_product(self):
        """Mantengo tu entrypoint pero delega al picker nuevo."""
        return self.action_open_product_picker()

    def action_open_product_picker(self):
        """Abre el modal 'selector de producto' y al confirmar crea la línea."""
        self.ensure_one()
        view = self.env.ref("custom_rental.view_rental_product_picker_wizard_form")
        return {
            "type": "ir.actions.act_window",
            "name": _("Buscar producto (renting)"),
            "res_model": "rental.product.picker.wizard",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "search_default_rent_ok": 1,  # filtra rentables en el m2o
            },
        }

    @api.constrains('order_line')
    def _limit_single_product_line(self):
        """Permite solo una línea real en órdenes manuales (no-turnos)."""
        for order in self:
            if not order.x_turn_slot:
                real_lines = order.order_line.filtered(lambda l: not l.display_type)
                if len(real_lines) > 1:
                    raise ValidationError(_("Solo se permite un producto por orden de alquiler manual."))
