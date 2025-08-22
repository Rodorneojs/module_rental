# -*- coding: utf-8 -*-
from odoo import api, fields, models

class BoatDailyAvailability(models.Model):
    _name = 'boat.daily.availability'
    _description = 'Disponibilidad diaria embarcaciones (Calendario)'

    date = fields.Date('Fecha', required=True, index=True)
    boat_id = fields.Many2one('fleet.vehicle', string="Embarcación", required=True, index=True)

    # Estado operativo del día (operativo/logístico)
    availability_state = fields.Selection([
        ('available',   'Disponible para alquiler'),
        ('private',     'Uso Privado'),
        ('maintenance', 'Mantenimiento'),
        ('blocked',     'Bloqueo operativo'),
    ], string="Estado", required=True, default='available', index=True)

    # Estado de agenda (tus categorías de Schedule)
    booking_stage = fields.Selection([
        ('available',   'Available'),
        ('private_use', 'Private Use'),
        ('request',     'Request'),
        ('pay_pending', 'PayPending'),
        ('option',      'Option'),
        ('pre_onboard', 'PreOnboard'),
        ('confirmed',   'Confirmed'),
        ('cancelled',   'Cancelled'),
        ('invoiced',    'Invoiced'),
    ], string="Schedule", default='available', index=True)

    # Línea de venta (si aplica)
    sale_line_id = fields.Many2one('sale.order.line', string="Línea de venta", index=True)
    order_id = fields.Many2one('sale.order', string="Pedido",
                               related='sale_line_id.order_id', store=True, readonly=True, index=True)

    # 🔧 Campo que la search está usando en tus vistas
    entry_type = fields.Selection([
        ('request',   'Solicitud'),
        ('pending',   'Pendiente de pago'),
        ('confirmed', 'Reserva confirmada'),
        ('cancelled', 'Cancelada'),
        ('enrole',    'Enrole'),
        ('none',      'Sin etiqueta'),
    ], string="Tipo de Entrada", default='none', index=True)

    color = fields.Char(string='Color (HEX)')
