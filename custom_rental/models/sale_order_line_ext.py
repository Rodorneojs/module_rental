# -*- coding: utf-8 -*-
from odoo import api, fields, models

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    # Si ya los tenías definidos, conserva índices/strings, etc.
    x_sched_start = fields.Datetime(string="Gantt Start",
                                    compute="_compute_turn_sched",
                                    store=True, index=True)
    x_sched_stop  = fields.Datetime(string="Gantt Stop",
                                    compute="_compute_turn_sched",
                                    store=True, index=True)
    turn_line_id = fields.Many2one(
        "rental.turn.param.line",
        ondelete="set null",
        index=True,
    )
    # ¡OJO! Nada de campos que no existan en sale.order.line aquí.
    # Nos enganchamos a cambios en la orden: cualquier write en SO actualiza write_date.
    @api.depends('order_id', 'order_id.write_date')
    def _compute_turn_sched(self):
        for l in self:
            o = l.order_id

            # Tomamos lo que exista; getattr evita petar si el campo no está en ese DB.
            # 1) primero busca en la línea (por si algún módulo los puso ahí)
            start = (getattr(l, 'rental_start_date', False)
                     or getattr(l, 'pickup_date', False))
            stop  = (getattr(l, 'rental_return_date', False)
                     or getattr(l, 'return_date', False))

            # 2) luego en la cabecera de la orden
            if not start:
                start = (getattr(o, 'rental_start_date', False)
                         or getattr(o, 'pickup_date', False)
                         or getattr(o, 'date_order', False))
            if not stop:
                stop = (getattr(o, 'rental_return_date', False)
                        or getattr(o, 'return_date', False)
                        or getattr(o, 'validity_date', False)
                        or start)

            l.x_sched_start = start
            l.x_sched_stop  = stop
