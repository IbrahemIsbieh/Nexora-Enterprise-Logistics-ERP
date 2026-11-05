from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NexoraCostCenter(models.Model):
    _name = 'nexora.cost.center'
    _description = 'Nexora Cost Center'
    _inherit = ['mail.thread']
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    complete_name = fields.Char(compute='_compute_complete_name', recursive=True, store=True)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one('nexora.cost.center', string='Parent', index=True, ondelete='restrict')
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many('nexora.cost.center', 'parent_id', string='Children')
    center_type = fields.Selection(
        [
            ('operations', 'Operations'),
            ('warehouse', 'Warehouse'),
            ('transport', 'Transportation'),
            ('fleet', 'Fleet'),
            ('sales', 'Sales'),
            ('admin', 'Administration'),
        ],
        string='Type',
        default='operations',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    manager_id = fields.Many2one('res.users', string='Responsible')
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account', copy=False)
    note = fields.Text()

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Cost center code must be unique per company.',
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = f"{rec.parent_id.complete_name} / {rec.name}"
            else:
                rec.complete_name = rec.name

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("You cannot create recursive cost centers."))

    def action_create_analytic_account(self):
        Plan = self.env['account.analytic.plan'].sudo()
        plan = Plan.search([('name', '=', 'Nexora Cost Centers')], limit=1) \
            or Plan.create({'name': 'Nexora Cost Centers'})
        for rec in self.filtered(lambda r: not r.analytic_account_id):
            rec.analytic_account_id = self.env['account.analytic.account'].sudo().create({
                'name': rec.complete_name,
                'code': rec.code,
                'plan_id': plan.id,
                'company_id': rec.company_id.id,
            })