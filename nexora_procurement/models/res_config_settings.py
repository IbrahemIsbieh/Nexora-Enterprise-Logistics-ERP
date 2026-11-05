from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_performance_days = fields.Integer(
        string='Performance Window (days)',
        config_parameter='nexora_procurement.performance_days', default=90)
    nexora_ontime_grace_days = fields.Float(
        string='On-time Grace (days)',
        config_parameter='nexora_procurement.ontime_grace_days', default=1.0)