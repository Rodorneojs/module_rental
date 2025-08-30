# -*- coding: utf-8 -*-
from odoo import models, api

class CustomRentalActionDefaults(models.AbstractModel):
    _name = 'custom_rental.action.defaults'
    _description = 'Ensure Rental Orders opens in List by default (no XML data)'

    @api.model
    def init(self):
        """Se ejecuta en install/upgrade del módulo."""
        env = self.env
        # Referencias seguras (no explotan si no existen)
        action = env.ref('sale_renting.rental_order_action', raise_if_not_found=False)
        list_view = env.ref('sale_renting.rental_order_view_tree', raise_if_not_found=False)
        kanban_view = env.ref('sale_renting.rental_order_view_kanban', raise_if_not_found=False)

        if not action or not list_view:
            return  # rental no instalado aún en esta DB

        # 1) Forzar que abra en LISTA y móvil en list,kanban
        action.sudo().write({
            'view_id': list_view.id,
            'mobile_view_mode': 'list,kanban',
        })

        # 2) (Opcional) Reordenar bindings existentes sin crear nuevos (evita UniqueViolation)
        Av = env['ir.actions.act_window.view'].sudo()

        bind_list = Av.search([
            ('act_window_id', '=', action.id),
            ('view_mode', '=', 'list'),
        ], limit=1)
        if bind_list:
            bind_list.sequence = 1

        bind_kanban = Av.search([
            ('act_window_id', '=', action.id),
            ('view_mode', '=', 'kanban'),
        ], limit=1)
        if bind_kanban:
            # Solo empuja Kanban debajo de List si hace falta
            if not bind_list or bind_kanban.sequence <= bind_list.sequence:
                bind_kanban.sequence = 2
