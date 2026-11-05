from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_dashboard_days = fields.Integer(
        string='Dashboard Period (days)',
        config_parameter='nexora_analytics.dashboard_days', default=30)
    nexora_working_hours = fields.Float(
        string='Working Hours per Vehicle per Day',
        config_parameter='nexora_analytics.working_hours', default=10.0)
    nexora_approval_stale_days = fields.Integer(
        string='Pending Approval Alert (days)',
        config_parameter='nexora_analytics.approval_stale_days', default=3)
    nexora_alert_responsible_id = fields.Many2one(
        'res.users', string='Default Alert Responsible',
        config_parameter='nexora_analytics.alert_responsible_id')