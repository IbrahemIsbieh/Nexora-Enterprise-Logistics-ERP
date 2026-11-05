from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NexoraFuelCard(models.Model):
    _name = 'nexora.fuel.card'
    _description = 'Fuel Card'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Card Number', required=True, copy=False, tracking=True)
    provider_id = fields.Many2one('res.partner', string='Provider', tracking=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Assigned Vehicle', tracking=True)
    driver_id = fields.Many2one(
        'hr.employee', string='Holder', domain=[('is_driver', '=', True)], tracking=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    monthly_limit = fields.Monetary(currency_field='currency_id', tracking=True,
                                    help="0 = no limit")
    expiry_date = fields.Date(tracking=True)
    state = fields.Selection(
        [('active', 'Active'), ('blocked', 'Blocked'), ('expired', 'Expired')],
        default='active', tracking=True, index=True)
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    log_ids = fields.One2many('nexora.fuel.log', 'card_id')
    log_count = fields.Integer(compute='_compute_log_count')
    month_spend = fields.Monetary(
        string='This Month Spend', currency_field='currency_id',
        compute='_compute_month_spend')
    usage_pct = fields.Float(
        string='Limit Usage (%)', compute='_compute_usage_pct')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)', 'This card number already exists.')

    def _compute_log_count(self):
        data = {c.id: n for c, n in self.env['nexora.fuel.log']._read_group(
            [('card_id', 'in', self.ids), ('state', '=', 'confirmed')],
            ['card_id'], ['__count'])}
        for card in self:
            card.log_count = data.get(card.id, 0)

    @api.depends('log_ids.amount', 'log_ids.state', 'log_ids.date')
    def _compute_month_spend(self):
        today = fields.Date.context_today(self)
        for card in self:
            card.month_spend = card._spend_in_month(today) if card.id else 0.0

    @api.depends('month_spend', 'monthly_limit')
    def _compute_usage_pct(self):
        for card in self:
            card.usage_pct = (
                card.month_spend / card.monthly_limit * 100.0
                if card.monthly_limit else 0.0)

    def _spend_in_month(self, date):
        self.ensure_one()
        start = date.replace(day=1)
        end = start + relativedelta(months=1) - timedelta(days=1)
        rows = self.env['nexora.fuel.log']._read_group(
            [('card_id', '=', self.id), ('state', '=', 'confirmed'),
             ('date', '>=', start), ('date', '<=', end)],
            [], ['amount:sum'])
        return rows[0][0] or 0.0

    def action_block(self):
        self.filtered(lambda c: c.state == 'active').write({'state': 'blocked'})

    def action_activate(self):
        today = fields.Date.context_today(self)
        for card in self.filtered(lambda c: c.state != 'active'):
            if card.expiry_date and card.expiry_date < today:
                raise UserError(
                    _("Card %s is past its expiry date. Update the date first.", card.name))
            card.state = 'active'

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fuel Logs'),
            'res_model': 'nexora.fuel.log',
            'view_mode': 'list,form',
            'domain': [('card_id', '=', self.id)],
        }

    @api.model
    def _cron_card_maintenance(self):
        today = fields.Date.context_today(self)
        self.search([('state', '=', 'active'), ('expiry_date', '<', today)]).write(
            {'state': 'expired'})
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_fuel.card_alert_days', 30))
        expiring = self.search([
            ('state', '=', 'active'),
            ('expiry_date', '>=', today),
            ('expiry_date', '<=', today + timedelta(days=days)),
        ])
        summary = _("Fuel card expiring")
        admin = self.env.ref('base.user_admin')
        for card in expiring:
            if card.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            card.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=card.expiry_date,
                summary=summary,
                user_id=(card.responsible_id or admin).id,
            )