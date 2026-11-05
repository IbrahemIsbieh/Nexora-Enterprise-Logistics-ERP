from odoo import api, models


class NexoraShipment(models.Model):
    _inherit = 'nexora.shipment'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            self.env['nexora.webhook']._enqueue('shipment.created', record)
        return records

    def write(self, vals):
        previous = {rec.id: rec.state for rec in self} if 'state' in vals else {}
        res = super().write(vals)
        for rec in self:
            old = previous.get(rec.id)
            if old is None or old == rec.state:
                continue
            Webhook = self.env['nexora.webhook']
            Webhook._enqueue('shipment.status_changed', rec, {'previous_state': old})
            if rec.state == 'delivered':
                Webhook._enqueue('shipment.delivered', rec, {'previous_state': old})
            elif rec.state == 'failed':
                Webhook._enqueue('shipment.failed', rec, {'previous_state': old})
        return res