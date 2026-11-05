from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_api_enabled = fields.Boolean(
        string='Enable the REST API',
        config_parameter='nexora_integration.api_enabled', default=True)
    nexora_api_log_days = fields.Integer(
        string='Keep Logs (days)',
        config_parameter='nexora_integration.log_retention_days', default=30)
    nexora_api_allow_private_urls = fields.Boolean(
        string='Allow Private Webhook URLs',
        config_parameter='nexora_integration.allow_private_urls', default=False)
    nexora_webhook_max_attempts = fields.Integer(
        string='Webhook Max Attempts',
        config_parameter='nexora_integration.webhook_max_attempts', default=5)
    nexora_webhook_timeout = fields.Float(
        string='Webhook Timeout (seconds)',
        config_parameter='nexora_integration.webhook_timeout', default=10.0)