from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_fleet_doc_alert_days = fields.Integer(
        string='Vehicle Document Alert (days)',
        config_parameter='nexora_fleet.doc_alert_days',
        default=30,
    )