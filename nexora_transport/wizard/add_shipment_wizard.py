from odoo import fields, models


class NexoraTripAddShipmentWizard(models.TransientModel):
    _name = 'nexora.trip.add.shipment.wizard'
    _description = 'Add Shipments to Trip'

    trip_id = fields.Many2one('nexora.transport.trip', required=True)
    shipment_ids = fields.Many2many(
        'nexora.shipment', string='Shipments', required=True,
        domain="[('state', '=', 'draft'), ('trip_id', '=', False)]")

    def action_add(self):
        self.ensure_one()
        self.shipment_ids.write({'trip_id': self.trip_id.id})
        return {'type': 'ir.actions.act_window_close'}