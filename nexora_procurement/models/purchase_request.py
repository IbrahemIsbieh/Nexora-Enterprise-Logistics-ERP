from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

APPROVAL_SUMMARY = "Approve purchase request"


class NexoraPurchaseRequest(models.Model):
    _name = 'nexora.purchase.request'
    _description = 'Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    requester_id = fields.Many2one(
        'res.users', string='Requester', default=lambda self: self.env.user,
        required=True, tracking=True, index=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Deliver To',
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1))
    cost_center_id = fields.Many2one('nexora.cost.center', string='Cost Center')
    date_required = fields.Date(string='Required By', tracking=True)
    priority = fields.Selection(
        [('normal', 'Normal'), ('urgent', 'Urgent')], default='normal', tracking=True)
    reason = fields.Text(string='Justification')
    state = fields.Selection(
        [('draft', 'Draft'), ('to_approve', 'To Approve'), ('approved', 'Approved'),
         ('rfq', 'Quotations'), ('ordered', 'Ordered'),
         ('rejected', 'Rejected'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)
    line_ids = fields.One2many('nexora.purchase.request.line', 'request_id', string='Items')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    total_estimated = fields.Monetary(
        compute='_compute_total', store=True, currency_field='currency_id')

    approval_rule_id = fields.Many2one(
        'nexora.purchase.approval.rule', readonly=True, copy=False)
    approver_id = fields.Many2one('res.users', string='Approver', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Datetime(readonly=True, copy=False)
    reject_reason = fields.Text(copy=False)
    can_approve = fields.Boolean(compute='_compute_can_approve')

    tender_ids = fields.One2many('nexora.rfq.tender', 'request_id')
    tender_count = fields.Integer(compute='_compute_counts')
    order_ids = fields.One2many('purchase.order', 'request_id')
    order_count = fields.Integer(compute='_compute_counts')

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for rec in self:
            rec.total_estimated = sum(rec.line_ids.mapped('subtotal'))

    @api.depends('tender_ids', 'order_ids')
    def _compute_counts(self):
        for rec in self:
            rec.tender_count = len(rec.tender_ids)
            rec.order_count = len(rec.order_ids)

    @api.depends_context('uid')
    @api.depends('approver_id', 'state')
    def _compute_can_approve(self):
        user = self.env.user
        is_manager = user.has_group('nexora_procurement.group_nexora_procurement_manager')
        for rec in self:
            rec.can_approve = rec.state == 'to_approve' and (is_manager or rec.approver_id == user)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.purchase.request') or 'New'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_active(self):
        if self.filtered(lambda r: r.state not in ('draft', 'cancelled')):
            raise UserError(_("Only draft or cancelled requests can be deleted."))

    def _close_approval_activities(self):
        for rec in self:
            rec.activity_ids.filtered(
                lambda a: a.summary == _(APPROVAL_SUMMARY)).sudo().action_feedback(
                feedback=_("Handled"))

    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self.filtered(lambda r: r.state == 'draft'):
            if not rec.line_ids:
                raise UserError(_("Add at least one item to the request."))
            rule = self.env['nexora.purchase.approval.rule']._match(
                rec.total_estimated, rec.company_id)
            if rule:
                rec.write({
                    'state': 'to_approve',
                    'approval_rule_id': rule.id,
                    'approver_id': rule.approver_id.id,
                })
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_(APPROVAL_SUMMARY),
                    date_deadline=rec.date_required or fields.Date.context_today(rec),
                    user_id=rule.approver_id.id,
                )
            else:
                rec.write({'state': 'approved', 'approved_date': fields.Datetime.now()})
                rec.message_post(body=_("Approved automatically (below the approval threshold)."))

    def action_approve(self):
        for rec in self:
            if rec.state != 'to_approve':
                raise UserError(_("Only requests waiting for approval can be approved."))
            if not (self.env.su or rec.can_approve):
                raise UserError(_(
                    "Only %s or a procurement manager can approve this request.",
                    rec.approver_id.name))
        self._close_approval_activities()
        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
            'reject_reason': False,
        })

    def action_reject(self):
        for rec in self:
            if rec.state != 'to_approve':
                raise UserError(_("Only requests waiting for approval can be rejected."))
            if not (self.env.su or rec.can_approve):
                raise UserError(_("You are not allowed to reject this request."))
            if not rec.reject_reason:
                raise UserError(_("Enter the rejection reason first."))
        self._close_approval_activities()
        self.write({'state': 'rejected'})

    def action_cancel(self):
        for rec in self:
            if rec.state in ('rfq', 'ordered'):
                raise UserError(_(
                    "Request %s already has quotations or orders. Cancel them first.", rec.name))
        self._close_approval_activities()
        self.filtered(lambda r: r.state in ('draft', 'to_approve', 'approved')).write(
            {'state': 'cancelled'})

    def action_draft(self):
        self.filtered(lambda r: r.state in ('rejected', 'cancelled')).write({
            'state': 'draft', 'approval_rule_id': False, 'approver_id': False,
            'approved_by': False, 'approved_date': False,
        })

    def action_view_tenders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tenders'),
            'res_model': 'nexora.rfq.tender',
            'view_mode': 'list,form',
            'domain': [('request_id', '=', self.id)],
        }

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('RFQs & Orders'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('request_id', '=', self.id)],
        }


class NexoraPurchaseRequestLine(models.Model):
    _name = 'nexora.purchase.request.line'
    _description = 'Purchase Request Line'

    request_id = fields.Many2one('nexora.purchase.request', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', required=True, domain=[('purchase_ok', '=', True)])
    name = fields.Char(string='Description')
    quantity = fields.Float(default=1.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit')
    currency_id = fields.Many2one(related='request_id.currency_id')
    estimated_price = fields.Monetary(string='Est. Unit Price', currency_field='currency_id')
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True, currency_field='currency_id')
    vendor_id = fields.Many2one(
        'res.partner', string='Preferred Vendor', domain=[('is_nexora_vendor', '=', True)])

    @api.depends('quantity', 'estimated_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.estimated_price

    @api.onchange('product_id')
    def _onchange_product_id(self):
        product = self.product_id
        if product:
            self.name = product.display_name
            self.uom_id = product.uom_id
            self.estimated_price = product.standard_price
            self.vendor_id = product.seller_ids[:1].partner_id

    @api.constrains('quantity', 'estimated_price')
    def _check_values(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))
            if line.estimated_price < 0:
                raise ValidationError(_("The price cannot be negative."))