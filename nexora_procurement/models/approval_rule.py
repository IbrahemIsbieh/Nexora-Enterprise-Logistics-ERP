from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NexoraPurchaseApprovalRule(models.Model):
    _name = 'nexora.purchase.approval.rule'
    _description = 'Purchase Approval Rule'
    _order = 'min_amount desc, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    min_amount = fields.Monetary(
        string='Applies From Amount', required=True, currency_field='currency_id',
        help="Requests whose estimated total reaches this amount need this approver. "
             "The rule with the highest matching amount wins.")
    approver_id = fields.Many2one('res.users', string='Approver', required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    @api.constrains('min_amount')
    def _check_amount(self):
        for rule in self:
            if rule.min_amount < 0:
                raise ValidationError(_("The amount cannot be negative."))

    @api.model
    def _match(self, amount, company):
        return self.sudo().search([
            ('active', '=', True),
            ('company_id', 'in', [company.id, False]),
            ('min_amount', '<=', amount),
        ], order='min_amount desc', limit=1)