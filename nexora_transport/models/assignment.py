from odoo import fields, models


class NexoraVehicleAssignment(models.Model):
    _inherit = 'nexora.vehicle.assignment'

    trip_id = fields.Many2one(
        'nexora.transport.trip', string='Trip', readonly=True, copy=False, ondelete='set null')