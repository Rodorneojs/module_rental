# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging
_logger = logging.getLogger(__name__)

class BoatDailyAvailability(models.TransientModel):
    _name = 'boat.daily.availability'
    _description = 'Disponibilidad diaria embarcaciones (Calendario)'

    boat_id = fields.Many2one('fleet.vehicle', string="Embarcación", required=True)
    date = fields.Date('Fecha', required=True)
    availability_state = fields.Selection([
        ('available', 'Disponible para alquiler'),
        ('private', 'Uso Privado'),
        ('maintenance', 'Mantenimiento'),
        ('blocked', 'Bloqueo operativo'),
    ], string="Estado", required=True)
    color = fields.Char(string='Color (HEX)', readonly=True)
    
    entry_type = fields.Selection([
        ('request', 'Solicitud'),
        ('pending', 'Pendiente de pago'),
        ('confirmed', 'Reserva confirmada'),
        ('cancelled', 'Cancelada'),
        ('enrole', 'Enrole'),
        ('none', 'Sin etiqueta'),
    ], string="Tipo de Entrada", default='none')

    source_record_id = fields.Reference(
        selection=[('rental.availability', 'Reserva'), ('rental.blocked.period', 'Bloqueo')],
        string="Registro de Origen"
    )

    name = fields.Char(string="Nombre", compute='_compute_name', store=True)

    @api.depends('boat_id')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.boat_id.name or ''

    @api.model
    def name_get(self):
        result = []
        for rec in self:
            name = rec.boat_id.name if rec.boat_id else super().name_get()[0][1]
            result.append((rec.id, name))
        return result
