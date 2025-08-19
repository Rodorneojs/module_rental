from odoo import models

class BlockPeriodActionSelector(models.TransientModel):
    _name = 'block.period.action.selector'
    _description = 'Selector de Acción para Bloqueo'

    def action_individual(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rental.blocked.period',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_range(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'block.period.range.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
