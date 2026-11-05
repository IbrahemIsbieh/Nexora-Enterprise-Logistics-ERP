from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_portal_requests_enabled = fields.Boolean(
        string='Allow Transport Requests from the Portal',
        config_parameter='nexora_portal.requests_enabled', default=True)
    nexora_portal_responsible_id = fields.Many2one(
        'res.users', string='Default Responsible',
        config_parameter='nexora_portal.responsible_id')