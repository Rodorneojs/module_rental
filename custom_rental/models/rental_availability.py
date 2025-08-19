from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date


class RentalAvailability(models.Model):
    _name = 'rental.availability'
    _description = 'Disponibilidad para Alquiler de Embarcación'

    boat_id = fields.Many2one('fleet.vehicle', string="Embarcación", required=True)
    date_from = fields.Date('Fecha Inicio', required=True)
    date_to = fields.Date('Fecha Fin', required=True)
    state = fields.Selection([
        ('active', 'Activo'),
        ('cancelled', 'Cancelado'),
        ('reserved', 'Reservado'),
    ], string='Estado', default='active')
    notes = fields.Text('Observaciones')
    display_name = fields.Char(compute='_compute_display_name', store=True)


    @api.constrains('boat_id', 'date_from', 'date_to')
    def _check_no_overlap(self):
        today = date.today()
        for rec in self:
            # FECHA EN EL PASADO
            if rec.date_from < today or rec.date_to < today:
                raise ValidationError('No puedes registrar periodos en fechas pasadas.')

            if rec.date_to < rec.date_from:
                raise ValidationError('La fecha final no puede ser anterior a la fecha de inicio.')

            # SOLAPES CON OTRA DISPONIBILIDAD
            overlaps = self.env['rental.availability'].search([
                ('boat_id', '=', rec.boat_id.id),
                ('id', '!=', rec.id),
                ('state', '=', 'active'),
                '|',
                    '&', ('date_from', '<=', rec.date_from), ('date_to', '>=', rec.date_from),
                    '&', ('date_from', '<=', rec.date_to), ('date_to', '>=', rec.date_to),
            ])
            if overlaps:
                raise ValidationError('¡Ya existe un periodo activo que se solapa con este rango!')

            # SOLAPE CON BLOQUEOS O USO PRIVADO
            blocked = self.env['rental.blocked.period'].search([
                ('boat_id', '=', rec.boat_id.id),
                ('date_blocked', '>=', rec.date_from),
                ('date_blocked', '<=', rec.date_to),
            ])
            if blocked:
                raise ValidationError('El periodo se solapa con días bloqueados o de uso privado.')
    def name_get(self):
        result = []
        for record in self:
            name = f"{record.boat_id.display_name or 'Embarcación'} ({record.date_from} a {record.date_to})"
            result.append((record.id, name))
        return result
    @api.depends('boat_id', 'date_from', 'date_to')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.boat_id.display_name if record.boat_id else 'Embarcación'}: {record.date_from or ''} a {record.date_to or ''}"
            
class SaleRentalSchedule(models.Model):
    _inherit = 'sale.rental.schedule'

    # (Puedes dejar este related o quitarlo; ya no lo usamos para el label)
    x_order_rental_status = fields.Selection(
        related='order_id.rental_status',
        string='Order Rental Status',
        store=False,
    )

    x_status_label = fields.Char(string='Status Label', compute='_compute_x_status_label')

    @api.depends('order_id.state', 'report_line_status')
    def _compute_x_status_label(self):
        for rec in self:
            label = ''
            # 1) Igual que Orders: si el pedido es draft/sent => Quotation
            if rec.order_id and rec.order_id.state in ('draft', 'sent'):
                label = 'Quotation'
            else:
                # 2) Si no, usa el estado logístico que pinta el schedule
                if rec.report_line_status == 'pickedup':
                    label = 'Picked-Up'
                elif rec.report_line_status == 'returned':
                    label = 'Returned'
                else:
                    label = 'Reserved'
            rec.x_status_label = label