from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta, date

class RentalBlockedPeriod(models.Model):
    _name = 'rental.blocked.period'
    _description = 'Periodo Bloqueado de Embarcación'

    block_type_select = fields.Selection([
        ('single', 'Bloqueo Individual'),
        ('range', 'Bloqueo por Rango'),
    ], string="Tipo de Bloqueo Seleccion", default='single', required=True)

    boat_id = fields.Many2one('fleet.vehicle', string="Embarcación", required=True)
    date_single = fields.Date("Fecha (bloqueo individual)")
    date_from = fields.Date("Fecha Inicio (bloqueo por rango)")
    date_to = fields.Date("Fecha Fin (bloqueo por rango)")
    use_type = fields.Selection([
        ('private', 'Uso Privado'),
        ('maintenance', 'Mantenimiento'),
    ], string="Tipo de Uso", required=False)

    date_blocked = fields.Date(string='Fecha bloqueada')
    block_type = fields.Selection([
        ('private',      'Uso Privado'),
        ('maintenance',  'Mantenimiento'),
    ], string="Tipo de Bloqueo", required=False)

    notes = fields.Text(string="Descripción")  # <-- Nuevo campo
    display_name = fields.Char(string='Nombre para mostrar', compute='_compute_display_name', store=True)

    @api.depends('boat_id', 'date_blocked', 'notes')
    def _compute_display_name(self):
        for rec in self:
            # Puedes personalizar el texto aquí
            rec.display_name = f"{rec.boat_id.display_name or ''} - {rec.date_blocked or ''} {rec.notes or ''}"
    @api.model_create_multi
    def create(self, vals_list):
        today = date.today()
        records = self.browse()
        for vals in vals_list:
            fechas = []
            if vals.get('block_type_select') == 'range':
                date_from = fields.Date.from_string(vals['date_from'])
                date_to = fields.Date.from_string(vals['date_to'])
                fechas = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
            else:
                fechas = [fields.Date.from_string(vals['date_single'])]
            for f in fechas:
                if f < today:
                    raise ValidationError("No puedes registrar bloqueos en fechas pasadas.")
                disponibilidad = self.env['rental.availability'].search([
                    ('boat_id', '=', vals['boat_id']),
                    ('state', '=', 'active'),
                    ('date_from', '<=', f),
                    ('date_to', '>=', f),
                ])
                if disponibilidad:
                    raise ValidationError("No puedes bloquear días que ya están disponibles para alquiler.")
                bloqueado = self.env['rental.blocked.period'].search([
                    ('boat_id', '=', vals['boat_id']),
                    ('date_blocked', '=', f),
                ])
                if bloqueado:
                    raise ValidationError(f"Ya existe un bloqueo o uso privado para la embarcación en la fecha {f}.")
                vals_copy = vals.copy()
                vals_copy['date_blocked'] = f
                vals_copy['block_type'] = vals['use_type']
                vals_copy.pop('date_single', None)
                vals_copy.pop('date_from', None)
                vals_copy.pop('date_to', None)
                vals_copy.pop('block_type_select', None)
                vals_copy.pop('use_type', None)
                record = super(RentalBlockedPeriod, self).create([vals_copy])
                records += record
        return records
