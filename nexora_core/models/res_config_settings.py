from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_license_alert_days = fields.Integer(
        string='Driver License Alert (days)',
        config_parameter='nexora_core.license_alert_days',
        default=30,
    )
    nexora_contract_alert_days = fields.Integer(
        string='Contract Expiry Alert (days)',
        config_parameter='nexora_core.contract_alert_days',
        default=30,
    )