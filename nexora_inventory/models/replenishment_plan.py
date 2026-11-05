import math

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .analysis import RISK_SELECTION


class NexoraReplenishmentPlan(models.Model):
    _name = 'nexora.replenishment.plan'
    _description = 'Replenishment Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', required=True, tracking=True)
    company_id = fields.Many2one(related='warehouse_id.company_id', store=True)
    plan_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    responsible_id = fields.Many2one('res.users', string='Responsible', tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('approved', 'Approved'),
         ('applied', 'Applied'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False)
    line_ids = fields.One2many('nexora.replenishment.plan.line', 'plan_id', string='Lines')
    line_count = fields.Integer(compute='_compute_line_count')
    note = fields.Text()

    @api.depends('line_ids')
    def _compute_line_count(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.replenishment.plan') or 'New'
        return super().create(vals_list)

    @api.model
    def _create_from_analysis(self, warehouse):
        analyses = self.env['nexora.inventory.analysis'].search([
            ('warehouse_id', '=', warehouse.id),
            ('suggested_qty', '>', 0),
        ])
        if not analyses:
            return self.browse()
        return self.create({
            'warehouse_id': warehouse.id,
            'line_ids': [Command.create({
                'product_id': a.product_id.id,
                'on_hand': a.on_hand,
                'position': a.position,
                'forecast_daily': a.forecast_daily,
                'lead_time': a.lead_time,
                'reorder_point': a.reorder_point,
                'risk_level': a.risk_level,
                'suggested_qty': a.suggested_qty,
                'approved_qty': a.suggested_qty,
                'vendor_id': a.product_id.seller_ids[:1].partner_id.id,
            }) for a in analyses],
        })

    def _notify_responsible(self):
        for plan in self:
            user = plan.warehouse_id.nexora_manager_id.user_id or self.env.ref('base.user_admin')
            plan.responsible_id = user
            plan.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Review replenishment plan"),
                user_id=user.id,
            )

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_approve(self):
        for plan in self:
            if not plan.line_ids.filtered(lambda l: l.approved_qty > 0):
                raise UserError(_("Nothing to approve: all approved quantities are zero."))
        self.write({'state': 'approved'})

    def action_apply(self):
        manager_group = 'nexora_inventory.group_nexora_inventory_manager'
        if not self.env.user.has_group(manager_group):
            raise UserError(_("Only inventory managers can apply a plan."))
        Orderpoint = self.env['stock.warehouse.orderpoint'].with_context(active_test=False)
        for plan in self.filtered(lambda p: p.state == 'approved'):
            warehouse = plan.warehouse_id
            location = warehouse.lot_stock_id
            for line in plan.line_ids.filtered(lambda l: l.approved_qty > 0):
                minimum = math.ceil(line.reorder_point)
                vals = {
                    'product_min_qty': minimum,
                    'product_max_qty': minimum + line.approved_qty,
                }
                orderpoint = Orderpoint.search([
                    ('product_id', '=', line.product_id.id),
                    ('warehouse_id', '=', warehouse.id),
                    ('location_id', '=', location.id),
                ], limit=1)
                if orderpoint:
                    orderpoint.write(dict(vals, active=True))
                else:
                    Orderpoint.create(dict(vals, **{
                        'product_id': line.product_id.id,
                        'warehouse_id': warehouse.id,
                        'location_id': location.id,
                    }))
            plan.state = 'applied'
            plan.message_post(body=_("Reordering rules updated from this plan."))

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.filtered(lambda p: p.state in ('approved', 'cancelled')).write({'state': 'draft'})


class NexoraReplenishmentPlanLine(models.Model):
    _name = 'nexora.replenishment.plan.line'
    _description = 'Replenishment Plan Line'
    _order = 'risk_sequence, id'

    plan_id = fields.Many2one('nexora.replenishment.plan', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')
    on_hand = fields.Float()
    position = fields.Float(string='Forecasted Stock')
    forecast_daily = fields.Float(string='Forecast Daily', digits=(16, 3))
    lead_time = fields.Float(string='Lead Time (days)')
    reorder_point = fields.Float()
    risk_level = fields.Selection(RISK_SELECTION)
    risk_sequence = fields.Integer(compute='_compute_risk_sequence', store=True)
    suggested_qty = fields.Float(string='Suggested Qty')
    approved_qty = fields.Float(string='Approved Qty')
    vendor_id = fields.Many2one('res.partner', string='Preferred Vendor')

    @api.depends('risk_level')
    def _compute_risk_sequence(self):
        order = {'stockout': 1, 'critical': 2, 'low': 3, 'overstock': 4, 'dead': 5, 'ok': 6}
        for line in self:
            line.risk_sequence = order.get(line.risk_level, 9)