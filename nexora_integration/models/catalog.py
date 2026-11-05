from odoo import fields, models


class NexoraApiScope(models.Model):
    _name = 'nexora.api.scope'
    _description = 'API Scope'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)

    _code_uniq = models.Constraint('unique(code)', 'The scope code must be unique.')


class NexoraWebhookEvent(models.Model):
    _name = 'nexora.webhook.event'
    _description = 'Webhook Event'
    _order = 'code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)

    _code_uniq = models.Constraint('unique(code)', 'The event code must be unique.')