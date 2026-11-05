from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NexoraMaintenancePlan(models.Model):
    _name = 'nexora.maintenance.plan'
    _description = 'Preventive Maintenance Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'vehicle_id, name'

    name = fields.Char(string='Service', required=True, tracking=True)
    active = fields.Boolean(default=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', required=True, tracking=True, index=True, ondelete='cascade')
    description = fields.Text(string='Tasks / Checklist')
    trigger_type = fields.Selection(
        [('km', 'By Distance'), ('days', 'By Time'), ('both', 'Distance or Time (first reached)')],
        required=True, default='both', tracking=True)
    interval_km = fields.Float(string='Every (km)', tracking=True)
    interval_days = fields.Integer(string='Every (days)', tracking=True)
    last_done_odometer = fields.Float(string='Last Done at (km)', tracking=True)
    last_done_date = fields.Date(string='Last Done on', tracking=True)

    next_due_odometer = fields.Float(string='Next Due (km)', compute='_compute_due')
    next_due_date = fields.Date(string='Next Due Date', compute='_compute_due')
    remaining_km = fields.Float(string='Remaining (km)', compute='_compute_due')
    remaining_days = fields.Integer(string='Remaining (days)', compute='_compute_due')
    due_state = fields.Selection(
        [('ok', 'Up to date'), ('due_soon', 'Due Soon'), ('overdue', 'Overdue')],
        string='Status', compute='_compute_due')

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    estimated_cost = fields.Monetary(currency_field='currency_id')
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)
    order_ids = fields.One2many('nexora.maintenance.order', 'plan_id')
    order_count = fields.Integer(compute='_compute_order_count')

    @api.depends('order_ids')
    def _compute_order_count(self):
        for plan in self:
            plan.order_count = len(plan.order_ids)

    @api.constrains('trigger_type', 'interval_km', 'interval_days')
    def _check_intervals(self):
        for plan in self:
            if plan.trigger_type in ('km', 'both') and plan.interval_km <= 0:
                raise ValidationError(_("Set a distance interval greater than zero."))
            if plan.trigger_type in ('days', 'both') and plan.interval_days <= 0:
                raise ValidationError(_("Set a time interval greater than zero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vehicle = self.env['fleet.vehicle'].browse(vals.get('vehicle_id'))
            if 'last_done_odometer' not in vals:
                vals['last_done_odometer'] = vehicle.odometer
            if not vals.get('last_done_date'):
                vals['last_done_date'] = fields.Date.context_today(self)
        return super().create(vals_list)

    def _compute_due(self):
        today = fields.Date.context_today(self)
        icp = self.env['ir.config_parameter'].sudo()
        warn_km = float(icp.get_param('nexora_maintenance.warn_km', 500))
        warn_days = int(icp.get_param('nexora_maintenance.warn_days', 14))
        for plan in self:
            next_km, next_date = 0.0, False
            rem_km, rem_days = 0.0, 0
            state = 'ok'
            if plan.trigger_type in ('km', 'both') and plan.interval_km:
                next_km = plan.last_done_odometer + plan.interval_km
                rem_km = next_km - plan.vehicle_id.odometer
                if rem_km <= 0:
                    state = 'overdue'
                elif rem_km <= warn_km:
                    state = 'due_soon'
            if plan.trigger_type in ('days', 'both') and plan.interval_days and plan.last_done_date:
                next_date = plan.last_done_date + timedelta(days=plan.interval_days)
                rem_days = (next_date - today).days
                if rem_days <= 0:
                    state = 'overdue'
                elif rem_days <= warn_days and state != 'overdue':
                    state = 'due_soon'
            plan.next_due_odometer = next_km
            plan.next_due_date = next_date
            plan.remaining_km = rem_km
            plan.remaining_days = rem_days
            plan.due_state = state

    def _create_order(self):
        self.ensure_one()
        return self.env['nexora.maintenance.order'].create({
            'vehicle_id': self.vehicle_id.id,
            'plan_id': self.id,
            'order_type': 'preventive',
            'description': self.description or self.name,
            'scheduled_date': fields.Datetime.now(),
            'estimated_cost': self.estimated_cost,
            'responsible_id': self.responsible_id.id,
        })

    def action_create_order(self):
        self.ensure_one()
        order = self._create_order()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nexora.maintenance.order',
            'res_id': order.id,
            'view_mode': 'form',
        }

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Orders'),
            'res_model': 'nexora.maintenance.order',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id, 'default_vehicle_id': self.vehicle_id.id},
        }

    @api.model
    def _cron_plan_check(self):
        icp = self.env['ir.config_parameter'].sudo()
        auto = str(icp.get_param('nexora_maintenance.auto_create', 'True')) in ('True', 'true', '1')
        admin = self.env.ref('base.user_admin')
        summary = _("Preventive maintenance due")
        due_plans = self.search([('active', '=', True)]).filtered(lambda p: p.due_state != 'ok')
        for plan in due_plans:
            has_open = plan.order_ids.filtered(
                lambda o: o.state in ('draft', 'scheduled', 'in_progress'))
            if has_open:
                continue
            if auto:
                plan._create_order()
            if not plan.activity_ids.filtered(lambda a: a.summary == summary):
                plan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=plan.next_due_date or fields.Date.context_today(plan),
                    summary=summary,
                    user_id=(plan.responsible_id or admin).id,
                )