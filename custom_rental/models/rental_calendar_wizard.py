from datetime import date, timedelta
from odoo import api, fields, models, _

class BoatAvailabilityWizard(models.TransientModel):
    _name = 'boat.availability.wizard'
    _description = 'Wizard para elegir embarcaciones y mostrar disponibilidad'

    boat_ids = fields.Many2many('fleet.vehicle', string="Embarcaciones", required=True)

    def action_show_calendar(self):
        # 1) Recojo disponibilidades y bloqueos
        availabilities = self.env['rental.availability'].search([
            ('boat_id', 'in', self.boat_ids.ids),
            ('state', '=', 'active'),
        ])
        blocks = self.env['rental.blocked.period'].search([
            ('boat_id', 'in', self.boat_ids.ids),
        ])
        blocked_dates = blocks.mapped('date_blocked')

        # 2) Calculo start/end (dinámico con fallback)
        all_starts = [av.date_from for av in availabilities] + blocked_dates
        all_ends   = [av.date_to   for av in availabilities] + blocked_dates
        if all_starts and all_ends:
            start = min(all_starts)
            end   = max(all_ends)
        else:
            today = date.today()
            start = today.replace(day=1)
            end   = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

        days = (end - start).days + 1

        # 3) Limpio solo el rango relevante
        self.env['boat.daily.availability'].search([
            ('boat_id', 'in', self.boat_ids.ids),
            ('date', '>=', start),
            ('date', '<=', end),
        ]).unlink()

        # 4) Mapeo de colores
        COLOR_MAP = {
            'available':   '#BAE1FF',
            'private':     '#D3D3D3',
            'maintenance': '#FF6961',
            'blocked':     '#FFB347',
        }

        # 5) Generación de registros con color en caliente
        records = []
        for boat in self.boat_ids:
            for i in range(days):
                day = start + timedelta(days=i)
                blocked = blocks.filtered(
                    lambda b: b.boat_id.id == boat.id and b.date_blocked == day
                )[:1]

                avail   = availabilities.filtered(
                    lambda a: a.boat_id.id == boat.id and a.date_from <= day <= a.date_to
                )[:1]

                if blocked:
                    # blocked es un record de rental.blocked.period
                    bt = blocked.block_type  # puede ser 'private', 'maintenance' o None
                    if bt == 'private':
                        state = 'private'
                    elif bt == 'maintenance':
                        state = 'maintenance'
                    else:
                        state = 'blocked'   # bloqueo operativo sin tipo
                    source = blocked
                elif avail:
                    # avail viene de rental.availability
                    state = 'blocked' if avail.state in ('reserved', 'pending') else 'available'
                    source = avail
                else:
                    continue  # no hay nada que pintar

                # Tipo de entrada
                entry_type = self._determine_entry_type(boat, day) if avail else 'none'

                records.append({
                    'boat_id':            boat.id,
                    'date':               day,
                    'availability_state': state,
                    'entry_type':         entry_type,
                    'source_record_id':   f"{source._name},{source.id}",
                    'name':               boat.name,
                    'color':              self._get_color_for(blocked, state),
                })

        # 6) Crear en batch
        if records:
            self.env['boat.daily.availability'].create(records)

        # 7) Devolver acción para el calendario
        return {
            'name':      _('Disponibilidad embarcaciones'),
            'type':      'ir.actions.act_window',
            'res_model': 'boat.daily.availability',
            'view_mode': 'calendar,search',
            'target':    'current',
            'domain':    [('boat_id', 'in', self.boat_ids.ids)],
            'views':     [(self.env.ref('custom_rental.view_boat_availability_calendar').id, 'calendar')],
        }

    def _determine_state(self, boat, day):
        blocked = self.env['rental.blocked.period'].search([
            ('boat_id', '=', boat.id),
            ('date_blocked', '=', day),
        ], limit=1)
        if blocked:
            return 'private' if blocked.use_type == 'private' else 'maintenance'

        avail = self.env['rental.availability'].search([
            ('boat_id', '=', boat.id),
            ('date_from', '<=', day),
            ('date_to',   '>=', day),
        ], limit=1)
        if avail:
            if avail.state in ('reserved', 'pending'):
                return 'blocked'
            if avail.state == 'cancelled':
                return 'available'
            return 'available'
        return False

    def _determine_entry_type(self, boat, day):
        # Buscamos reserva activa en ese día
        reserva = self.env['rental.availability'].search([
            ('boat_id', '=', boat.id),
            ('date_from', '<=', day),
            ('date_to', '>=', day)
        ], limit=1, order="state desc")

        if reserva:
            if reserva.state == 'request':
                return 'request'
            elif reserva.state == 'pending':
                return 'pending'
            elif reserva.state == 'active':
                return 'confirmed'
            elif reserva.state == 'cancel':
                return 'cancelled'
            elif reserva.state == 'done':
                return 'enrole'
        return 'none'

    def _get_color_for(self, blocked, state):
        if blocked:
            if blocked.block_type == 'private':
                return '#D3D3D3'   # Gris: uso privado
            if blocked.block_type == 'maintenance':
                return '#FF6961'   # Rojo: mantenimiento
            return '#FFB347'       # Naranja: bloqueo genérico
        # Si no hay bloqueo, se muestra disponible (azul)
        return '#BAE1FF'
