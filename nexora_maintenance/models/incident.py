from odoo import fields, models


class NexoraVehicleIncident(models.Model):
    _inherit = 'nexora.vehicle.incident'

    maintenance_order_ids = fields.One2many('nexora.maintenance.order', 'incident_id')

    def action_create_maintenance_order(self):
        self.ensure_one()
        order = self.env['nexora.maintenance.order'].create({
            'vehicle_id': self.vehicle_id.id,
            'incident_id': self.id,
            'order_type': 'corrective',
            'description': self.description or self.name,
            'priority': '2' if self.severity in ('major', 'total_loss') else '1',
            'responsible_id': self.responsible_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nexora.maintenance.order',
            'res_id': order.id,
            'view_mode': 'form',
        }