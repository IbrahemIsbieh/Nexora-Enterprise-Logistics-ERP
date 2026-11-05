from odoo import api, models


class NexoraTransportOrder(models.Model):
    _inherit = 'nexora.transport.order'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            self.env['nexora.webhook']._enqueue('order.created', record)
        return records

    def write(self, vals):
        previous = {rec.id: rec.state for rec in self} if 'state' in vals else {}
        res = super().write(vals)
        for rec in self:
            old = previous.get(rec.id)
            if old is not None and old != rec.state:
                self.env['nexora.webhook']._enqueue(
                    'order.status_changed', rec, {'previous_state': old})
        return res