from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_transport_strict_capacity = fields.Boolean(
        string='Block Overloaded / Incompatible Trips',
        config_parameter='nexora_transport.strict_capacity', default=True)
    nexora_transport_ontime_grace_hours = fields.Float(
        string='On-time Grace (hours)',
        config_parameter='nexora_transport.ontime_grace_hours', default=2.0)