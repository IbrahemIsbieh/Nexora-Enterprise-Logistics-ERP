from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class NexoraMaintenanceOrder(models.Model):
    _name = 'nexora.maintenance.order'
    _description = 'Maintenance Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scheduled_date desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    order_type = fields.Selection(
        [
            ('preventive', 'Preventive'),
            ('corrective', 'Corrective'),
            ('inspection', 'Inspection'),
            ('tires', 'Tires'),
            ('other', 'Other'),
        ],
        required=True, default='corrective', tracking=True)
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'High'), ('2', 'Urgent')], default='0', tracking=True)
    plan_id = fields.Many2one('nexora.maintenance.plan', string='Plan',
                              domain="[('vehicle_id', '=', vehicle_id)]")
    incident_id = fields.Many2one('nexora.vehicle.incident', string='Incident',
                                  domain="[('vehicle_id', '=', vehicle_id)]")
    description = fields.Text(string='Work Requested')
    result_note = fields.Text(string='Work Performed')
    workshop_type = fields.Selection(
        [('internal', 'Internal Workshop'), ('external', 'External Vendor')],
        default='internal', required=True)
    vendor_id = fields.Many2one('res.partner', string='Workshop / Vendor')
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    scheduled_date = fields.Datetime(tracking=True)
    date_start = fields.Datetime(string='Started', readonly=True, copy=False)
    date_done = fields.Datetime(string='Completed', readonly=True, copy=False)
    downtime_hours = fields.Float(compute='_compute_downtime', string='Downtime (h)')
    odometer = fields.Float(string='Odometer (km)')
    state = fields.Selection(
        [('draft', 'Draft'), ('scheduled', 'Scheduled'), ('in_progress', 'In Progress'),
         ('done', 'Done'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)

    line_ids = fields.One2many('nexora.maintenance.order.line', 'order_id', string='Cost Lines')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    estimated_cost = fields.Monetary(currency_field='currency_id')
    total_cost = fields.Monetary(currency_field='currency_id', compute='_compute_total_cost',
                                 store=True)
    cost_center_id = fields.Many2one(
        'nexora.cost.center', string='Cost Center',
        compute='_compute_cost_center', store=True, readonly=False)
    expense_id = fields.Many2one('nexora.vehicle.expense', string='Expense',
                                 readonly=True, copy=False)
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)

    # ------------------------------------------------------------------
    @api.depends('line_ids.subtotal')
    def _compute_total_cost(self):
        for order in self:
            order.total_cost = sum(order.line_ids.mapped('subtotal'))

    @api.depends('vehicle_id')
    def _compute_cost_center(self):
        for order in self:
            order.cost_center_id = order.vehicle_id.nexora_cost_center_id

    @api.depends('date_start', 'date_done')
    def _compute_downtime(self):
        for order in self:
            if order.date_start and order.date_done:
                order.downtime_hours = (order.date_done - order.date_start).total_seconds() / 3600.0
            else:
                order.downtime_hours = 0.0

    @api.constrains('vehicle_id', 'plan_id', 'incident_id')
    def _check_links(self):
        for order in self:
            if order.plan_id and order.plan_id.vehicle_id != order.vehicle_id:
                raise ValidationError(_("The plan belongs to a different vehicle."))
            if order.incident_id and order.incident_id.vehicle_id != order.vehicle_id:
                raise ValidationError(_("The incident belongs to a different vehicle."))

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id:
            self.vehicle_id = self.plan_id.vehicle_id
            self.order_type = 'preventive'
            self.description = self.plan_id.description or self.plan_id.name
            self.estimated_cost = self.plan_id.estimated_cost

    @api.onchange('incident_id')
    def _onchange_incident_id(self):
        if self.incident_id:
            self.vehicle_id = self.incident_id.vehicle_id
            self.order_type = 'corrective'
            self.description = self.description or self.incident_id.description

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.maintenance.order') or 'New'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        if self.filtered(lambda o: o.state in ('in_progress', 'done')):
            raise UserError(_("Orders in progress or done cannot be deleted. Cancel them first."))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _release_vehicles(self):
        for vehicle in self.vehicle_id:
            still_busy = self.search_count([
                ('vehicle_id', '=', vehicle.id), ('state', '=', 'in_progress')])
            if not still_busy and vehicle.nexora_in_maintenance:
                vehicle.sudo().nexora_in_maintenance = False

    def _create_expense(self):
        for order in self.filtered(lambda o: o.total_cost > 0 and not o.expense_id):
            order.expense_id = self.env['nexora.vehicle.expense'].sudo().create({
                'vehicle_id': order.vehicle_id.id,
                'date': fields.Date.context_today(order),
                'expense_type': 'repair',
                'description': _("Maintenance %s", order.name),
                'partner_id': order.vendor_id.id,
                'amount': order.total_cost,
                'currency_id': order.currency_id.id,
                'cost_center_id': order.cost_center_id.id,
                'incident_id': order.incident_id.id,
                'state': 'confirmed',
            })

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_schedule(self):
        for order in self.filtered(lambda o: o.state == 'draft'):
            if not order.scheduled_date:
                raise UserError(_("Set a scheduled date first."))
            order.state = 'scheduled'

    def action_start(self):
        for order in self.filtered(lambda o: o.state in ('draft', 'scheduled')):
            vehicle = order.vehicle_id
            if vehicle.nexora_availability == 'assigned':
                raise UserError(_(
                    "Vehicle %s has an active assignment. Finish it before starting maintenance.",
                    vehicle.display_name))
            order.write({
                'state': 'in_progress',
                'date_start': fields.Datetime.now(),
                'odometer': order.odometer or vehicle.odometer,
            })
            vehicle.sudo().nexora_in_maintenance = True

    def action_done(self):
        now = fields.Datetime.now()
        for order in self.filtered(lambda o: o.state == 'in_progress'):
            if not order.line_ids and not order.result_note:
                raise UserError(_(
                    "Record the work performed (cost lines or a note) before completing."))
            vehicle = order.vehicle_id
            odometer = order.odometer or vehicle.odometer
            order.write({'state': 'done', 'date_done': now, 'odometer': odometer})
            if odometer > vehicle.odometer:
                self.env['fleet.vehicle.odometer'].sudo().create({
                    'vehicle_id': vehicle.id,
                    'value': odometer,
                    'date': fields.Date.context_today(order),
                })
            order._create_expense()
            if order.plan_id:
                order.plan_id.sudo().write({
                    'last_done_odometer': odometer,
                    'last_done_date': fields.Date.context_today(order),
                })
        self._release_vehicles()

    def action_cancel(self):
        orders = self.filtered(lambda o: o.state in ('draft', 'scheduled', 'in_progress'))
        orders.write({'state': 'cancelled'})
        self._release_vehicles()

    def action_draft(self):
        self.filtered(lambda o: o.state == 'cancelled').write({'state': 'draft'})


class NexoraMaintenanceOrderLine(models.Model):
    _name = 'nexora.maintenance.order.line'
    _description = 'Maintenance Order Cost Line'

    order_id = fields.Many2one('nexora.maintenance.order', required=True, ondelete='cascade')
    line_type = fields.Selection(
        [('labor', 'Labor'), ('part', 'Spare Part'), ('other', 'Other')],
        required=True, default='part')
    product_id = fields.Many2one('product.product', string='Product')
    name = fields.Char(string='Description', required=True)
    quantity = fields.Float(default=1.0)
    price_unit = fields.Monetary(string='Unit Price', currency_field='currency_id')
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='order_id.currency_id', store=True)

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.price_unit = self.product_id.standard_price

    @api.constrains('quantity', 'price_unit')
    def _check_values(self):
        for line in self:
            if line.quantity < 0 or line.price_unit < 0:
                raise ValidationError(_("Quantity and price cannot be negative."))