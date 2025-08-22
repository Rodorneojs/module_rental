
# -*- coding: utf-8 -*-
from odoo import api, fields, models
from .schedule_states import SCHEDULE_STATE_SELECTION
class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"
    # Nuevo campo de estado (combo)
    x_schedule_state = fields.Selection(
        selection=SCHEDULE_STATE_SELECTION,
        string="Schedule State",
        default='available',
        copy=False,
    )
    x_sched_start = fields.Datetime(string="Gantt Start", compute="_compute_turn_sched", store=True, index=True)
    x_sched_stop = fields.Datetime(string="Gantt Stop", compute="_compute_turn_sched", store=True, index=True)
    x_is_rental_any = fields.Boolean(string="Rental (any)", compute="_compute_turn_sched", store=True, index=True)

    x_turn_yacht_id = fields.Many2one(
        "fleet.vehicle", string="Embarcación (Orden)",
        related="order_id.x_turn_yacht_id", store=True, readonly=True, index=True,
    )
    x_turn_season_id = fields.Many2one(
        "rental.season", string="Temporada (Orden)",
        related="order_id.x_turn_season_id", store=True, readonly=True, index=True,
    )

    @api.depends(
        "display_type", "product_id", "product_id.rent_ok", "order_id",
        "order_id.rental_start_date", "order_id.rental_return_date", "order_id.state",
    )
    def _compute_turn_sched(self):
        for l in self:
            if l.display_type:
                l.x_is_rental_any = False
                l.x_sched_start = False
                l.x_sched_stop = False
                continue
            is_rental_flag = bool(getattr(l, "is_rental", False))
            is_rent_ok = bool(getattr(l.product_id, "rent_ok", False))
            l.x_is_rental_any = is_rental_flag or is_rent_ok

            start = (
                getattr(l, "rental_start_date", False)
                or getattr(l, "pickup_date", False)
                or getattr(l.order_id, "rental_start_date", False)
            )
            stop = (
                getattr(l, "rental_return_date", False)
                or getattr(l, "return_date", False)
                or getattr(l.order_id, "rental_return_date", False)
            )
            l.x_sched_start = start
            l.x_sched_stop = stop
