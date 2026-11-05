from datetime import timedelta

from odoo import fields, models


class NexoraApiLog(models.Model):
    _name = 'nexora.api.log'
    _description = 'API Request Log'
    _order = 'id desc'

    key_id = fields.Many2one('nexora.api.key', ondelete='set null', index=True)
    key_name = fields.Char()
    method = fields.Char()
    path = fields.Char()
    status = fields.Integer(index=True)
    error = fields.Char()
    ip = fields.Char(string='IP Address')
    duration_ms = fields.Float(string='Duration (ms)')

    def _cron_purge(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_integration.log_retention_days') or 30)
        limit = fields.Datetime.now() - timedelta(days=days)
        self.sudo().search([('create_date', '<', limit)]).unlink()
        self.env['nexora.webhook.delivery']._purge(limit)