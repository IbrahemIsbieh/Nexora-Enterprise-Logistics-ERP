from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_fuel_anomaly_pct = fields.Float(
        string='Abnormal Consumption Threshold (%)',
        config_parameter='nexora_fuel.anomaly_pct', default=20.0)
    nexora_fuel_card_alert_days = fields.Integer(
        string='Fuel Card Expiry Alert (days)',
        config_parameter='nexora_fuel.card_alert_days', default=30)