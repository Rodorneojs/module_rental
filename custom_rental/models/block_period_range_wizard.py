from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta, date

class BlockPeriodWizard(models.TransientModel):
    _name = 'block.period.wizard'
    _description = 'Wizard Bloqueo (Individual o Rango)'

    block_type_select = fields.Selection([
        ('single', 'Bloqueo Individual'),
        ('range', 'Bloqueo por Rango'),
    ], string="Tipo de Bloqueo", default='single', required=True)

    boat_id = fields.Many2one('fleet.vehicle', string="Embarcación", required=True)
    date_single = fields.Date("Fecha (bloqueo individual)")
    date_from = fields.Date("Fecha Inicio (bloqueo por rango)")
    date_to = fields.Date("Fecha Fin (bloqueo por rango)")
    use_type = fields.Selection([
        ('private', 'Uso Privado'),
        ('maintenance', 'Mantenimiento'),
    ], string="Tipo de Uso", required=False)
    notes = fields.Text(string="Descripción")  # <-- Nuevo campo

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        calendar_date = self.env.context.get('default_date_blocked') or self.env.context.get('date')
        if calendar_date:
            defaults['date_single'] = calendar_date
        return defaults

    def action_apply(self):
        today = date.today()
        blocked = self.env['rental.blocked.period']
        # Individual
        if self.block_type_select == 'single':
            f = self.date_single
            if f < today:
                raise ValidationError('No puedes registrar bloqueos en fechas pasadas.')
            disponibilidad = self.env['rental.availability'].search([
                ('boat_id', '=', self.boat_id.id),
                ('state', '=', 'active'),
                ('date_from', '<=', f),
                ('date_to', '>=', f),
            ])
            if disponibilidad:
                raise ValidationError("No puedes bloquear días ya disponibles para alquiler.")
            bloqueado = self.env['rental.blocked.period'].search([
                ('boat_id', '=', self.boat_id.id),
                ('date_blocked', '=', f),
            ])
            if bloqueado:
                raise ValidationError(f"Ya existe un bloqueo o uso privado en {f}.")
            blocked.create({
                'boat_id': self.boat_id.id,
                'date_blocked': f,
                'block_type': self.use_type,
                'notes': self.notes,
            })
        # Rango
        elif self.block_type_select == 'range':
            d = self.date_from
            while d <= self.date_to:
                if d < today:
                    raise ValidationError('No puedes registrar bloqueos en fechas pasadas.')
                disponibilidad = self.env['rental.availability'].search([
                    ('boat_id', '=', self.boat_id.id),
                    ('state', '=', 'active'),
                    ('date_from', '<=', d),
                    ('date_to', '>=', d),
                ])
                if disponibilidad:
                    raise ValidationError(f"No puedes bloquear el día {d}, ya está disponible para alquiler.")
                bloqueado = self.env['rental.blocked.period'].search([
                    ('boat_id', '=', self.boat_id.id),
                    ('date_blocked', '=', d),
                ])
                if bloqueado:
                    raise ValidationError(f"Ya existe un bloqueo o uso privado en {d}.")
                blocked.create({
                    'boat_id': self.boat_id.id,
                    'date_blocked': d,
                    'block_type': self.use_type,
                    'notes': self.notes,
                })
                d += timedelta(days=1)
        return {'type': 'ir.actions.act_window_close'}
