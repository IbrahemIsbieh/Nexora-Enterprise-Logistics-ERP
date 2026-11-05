from odoo import models


class NexoraTransportTrip(models.Model):
    _inherit = 'nexora.transport.trip'

    def write(self, vals):
        previous = {rec.id: rec.state for rec in self} if 'state' in vals else {}
        res = super().write(vals)
        for rec in self:
            old = previous.get(rec.id)
            if old is None or old == rec.state:
                continue
            if rec.state == 'in_progress':
                self.env['nexora.webhook']._enqueue('trip.started', rec, {'previous_state': old})
            elif rec.state == 'done':
                self.env['nexora.webhook']._enqueue('trip.completed', rec, {'previous_state': old})
        return res