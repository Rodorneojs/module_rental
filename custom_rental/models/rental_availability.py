# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class RentalAvailability(models.Model):
    _name = 'rental.availability'
    _description = 'Disponibilidad para Alquiler de Embarcación'

    # ── Campos básicos
    boat_id = fields.Many2one('fleet.vehicle', string="Embarcación", required=True)

    # Fechas REALES en BD (no se muestran en el form)
    date_from = fields.Date('Fecha Inicio', required=True)
    date_to   = fields.Date('Fecha Fin',    required=True)

    # Proxies (solo FECHA) para el widget de rango en el formulario
    date_from_dt = fields.Date(
        string='Inicio (Date)',
        compute='_compute_dt_range',
        inverse='_inverse_dt_range',
        readonly=False,
        store=False,
        help='Proxy Date para el selector de rango; sincroniza con "Fecha Inicio".',
    )
    date_to_dt = fields.Date(
        string='Fin (Date)',
        compute='_compute_dt_range',
        inverse='_inverse_dt_range',
        readonly=False,
        store=False,
        help='Proxy Date para el selector de rango; sincroniza con "Fecha Fin".',
    )

    state = fields.Selection([
        ('active', 'Activo'),
        ('cancelled', 'Cancelado'),
        ('reserved', 'Reservado'),
    ], string='Estado', default='active')

    notes = fields.Text('Observaciones')

    display_name = fields.Char(compute='_compute_display_name', store=True)

    # ── Sincronización proxies <-> reales
    @api.depends('date_from', 'date_to')
    def _compute_dt_range(self):
        for r in self:
            r.date_from_dt = r.date_from or False
            r.date_to_dt   = r.date_to   or False

    def _inverse_dt_range(self):
        for r in self:
            r.date_from = r.date_from_dt or False
            r.date_to   = r.date_to_dt   or False

    def _merge_range_into_real(self, vals):
        if 'date_from_dt' in vals and vals.get('date_from_dt'):
            vals['date_from'] = vals['date_from_dt']
        if 'date_to_dt' in vals and vals.get('date_to_dt'):
            vals['date_to'] = vals['date_to_dt']
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._merge_range_into_real(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._merge_range_into_real(vals)
        return super().write(vals)

    # ── Validaciones
    @api.constrains('boat_id', 'date_from', 'date_to')
    def _check_no_overlap(self):
        today = date.today()
        for rec in self:
            if not (rec.date_from and rec.date_to):
                continue

            # Pasado
            if rec.date_from < today or rec.date_to < today:
                raise ValidationError('No puedes registrar periodos en fechas pasadas.')

            # Orden
            if rec.date_to < rec.date_from:
                raise ValidationError('La fecha final no puede ser anterior a la fecha de inicio.')

            # Solapes con otras disponibilidades "activas"
            overlaps = self.env['rental.availability'].search([
                ('boat_id', '=', rec.boat_id.id),
                ('id', '!=', rec.id),
                ('state', '=', 'active'),
                ('date_from', '<=', rec.date_to),
                ('date_to', '>=', rec.date_from),
            ])
            if overlaps:
                raise ValidationError('¡Ya existe un periodo activo que se solapa con este rango!')

            # 🔕 Se elimina la validación contra días bloqueados/uso privado
            # (permitir registrar aunque existan bloqueos en el rango)

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

    x_order_rental_status = fields.Selection(
        related='order_id.rental_status',
        string='Order Rental Status',
        store=False,
    )
    x_status_label = fields.Char(string='Status Label', compute='_compute_x_status_label')

    @api.depends('order_id.state', 'report_line_status')
    def _compute_x_status_label(self):
        for rec in self:
            if rec.order_id and rec.order_id.state in ('draft', 'sent'):
                rec.x_status_label = 'Quotation'
            else:
                if rec.report_line_status == 'pickedup':
                    rec.x_status_label = 'Picked-Up'
                elif rec.report_line_status == 'returned':
                    rec.x_status_label = 'Returned'
                else:
                    rec.x_status_label = 'Reserved'
