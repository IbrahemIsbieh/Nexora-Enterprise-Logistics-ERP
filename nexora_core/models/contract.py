from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NexoraContract(models.Model):
    _name = 'nexora.contract'
    _description = 'Nexora Contract / Agreement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    title = fields.Char(required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Partner', required=True, tracking=True)
    contract_type = fields.Selection(
        [('customer', 'Customer'), ('vendor', 'Vendor')],
        required=True, default='customer', tracking=True)
    service_type = fields.Selection(
        [
            ('transport', 'Transportation'),
            ('warehousing', 'Warehousing'),
            ('supply', 'Supply / Procurement'),
            ('maintenance', 'Maintenance'),
            ('other', 'Other'),
        ],
        default='transport', tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('active', 'Active'),
         ('expired', 'Expired'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False)
    date_start = fields.Date(string='Start Date', required=True,
                             default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='End Date', tracking=True)
    days_to_expiry = fields.Integer(compute='_compute_days_to_expiry')
    auto_renew = fields.Boolean(string='Auto Renew')
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    contract_value = fields.Monetary(string='Committed Value', currency_field='currency_id')
    payment_term_id = fields.Many2one('account.payment.term', string='Payment Terms') \
        if False else fields.Many2one('account.payment.term', string='Payment Terms')
    cost_center_id = fields.Many2one('nexora.cost.center', string='Cost Center')
    terms = fields.Html(string='Terms & Conditions')
    line_ids = fields.One2many('nexora.contract.line', 'contract_id', string='Agreed Rates')

    @api.depends('date_end', 'state')
    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.days_to_expiry = (rec.date_end - today).days \
                if rec.date_end and rec.state == 'active' else 0

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("End date cannot be before start date."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.contract') or 'New'
        return super().create(vals_list)

    def action_activate(self):
        self.write({'state': 'active'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})

    @api.model
    def _cron_contract_maintenance(self):
        today = fields.Date.context_today(self)
        expired = self.search([('state', '=', 'active'), ('date_end', '<', today)])
        expired.write({'state': 'expired'})
        for contract in expired:
            contract.message_post(body=_("Contract expired automatically."))

        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_core.contract_alert_days', 30))
        expiring = self.search([
            ('state', '=', 'active'),
            ('date_end', '>=', today),
            ('date_end', '<=', today + timedelta(days=days)),
            ('responsible_id', '!=', False),
        ])
        summary = _("Contract about to expire")
        for contract in expiring:
            if contract.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            contract.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=contract.date_end,
                summary=summary,
                user_id=contract.responsible_id.id,
            )


class NexoraContractLine(models.Model):
    _name = 'nexora.contract.line'
    _description = 'Nexora Contract Line'

    contract_id = fields.Many2one('nexora.contract', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product / Service', required=True)
    name = fields.Char(string='Description')
    min_quantity = fields.Float(string='Min. Quantity', default=0.0)
    price_unit = fields.Monetary(string='Agreed Price', currency_field='currency_id')
    uom_id = fields.Many2one('uom.uom', related='product_id.uom_id', string='Unit')
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    notes = fields.Char()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.price_unit = self.product_id.list_price