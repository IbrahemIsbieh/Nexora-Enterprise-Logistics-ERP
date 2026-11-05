from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_history_days = fields.Integer(
        string='History Window (days)',
        config_parameter='nexora_inventory.history_days', default=90)
    nexora_horizon_days = fields.Integer(
        string='Planning Horizon (days)',
        config_parameter='nexora_inventory.horizon_days', default=30)
    nexora_service_level = fields.Float(
        string='Service Level (%)',
        config_parameter='nexora_inventory.service_level', default=95.0)
    nexora_default_lead_time = fields.Float(
        string='Default Lead Time (days)',
        config_parameter='nexora_inventory.default_lead_time', default=7.0)
    nexora_overstock_days = fields.Integer(
        string='Overstock Threshold (days of cover)',
        config_parameter='nexora_inventory.overstock_days', default=180)
    nexora_auto_plan = fields.Boolean(
        string='Auto-create Draft Plans',
        config_parameter='nexora_inventory.auto_plan', default=True)