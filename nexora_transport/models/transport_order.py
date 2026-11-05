from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TEMP_SELECTION = [('ambient', 'Ambient'), ('chilled', 'Chilled'), ('frozen', 'Frozen')]
TEMP_RANK = {'ambient': 0, 'chilled': 1, 'frozen': 2}


def max_temp(classes):
    classes = [c for c in classes if c]
    return max(classes, key=TEMP_RANK.get) if classes else 'ambient'


class NexoraTransportOrder(models.Model):
    _name = 'nexora.transport.order'
    _description = 'Transport Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'order_date desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    reference = fields.Char(string='Customer Reference', tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True, index=True,
        domain="[('is_nexora_customer', '=', True)]")
    contract_id = fields.Many2one(
        'nexora.contract', string='Contract', tracking=True,
        domain="[('partner_id', '=', partner_id), ('contract_type', '=', 'customer'),"
               " ('state', '=', 'active')]")
    order_date = fields.Datetime(default=fields.Datetime.now, tracking=True)
    pickup_partner_id = fields.Many2one('res.partner', string='Pickup Address / Contact')
    delivery_partner_id = fields.Many2one(
        'res.partner', string='Delivery Address / Contact', required=True)
    origin_warehouse_id = fields.Many2one('stock.warehouse', string='Origin Warehouse')
    requested_pickup_date = fields.Datetime(tracking=True)
    requested_delivery_date = fields.Datetime(tracking=True)
    priority = fields.Selection(
        [('normal', 'Normal'), ('urgent', 'Urgent')], default='normal', tracking=True)
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    cost_center_id = fields.Many2one('nexora.cost.center', string='Cost Center')
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('in_progress', 'In Progress'),
         ('done', 'Done'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)
    line_ids = fields.One2many('nexora.transport.order.line', 'order_id', string='Cargo')
    shipment_ids = fields.One2many('nexora.shipment', 'order_id', string='Shipments')
    shipment_count = fields.Integer(compute='_compute_shipment_count')
    unshipped_count = fields.Integer(compute='_compute_unshipped_count')
    total_weight = fields.Float(string='Total Weight (kg)', compute='_compute_totals', store=True)
    total_volume = fields.Float(string='Total Volume (m³)', compute='_compute_totals', store=True)
    temperature_class = fields.Selection(
        TEMP_SELECTION, string='Temperature Requirement', compute='_compute_totals', store=True)
    has_hazardous = fields.Boolean(string='Hazardous Cargo', compute='_compute_totals', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    notes = fields.Text()

    # ------------------------------------------------------------------
    @api.depends('line_ids.weight', 'line_ids.volume',
                 'line_ids.temperature_class', 'line_ids.hazardous')
    def _compute_totals(self):
        for order in self:
            order.total_weight = sum(order.line_ids.mapped('weight'))
            order.total_volume = sum(order.line_ids.mapped('volume'))
            order.temperature_class = max_temp(order.line_ids.mapped('temperature_class'))
            order.has_hazardous = any(order.line_ids.mapped('hazardous'))

    @api.depends('shipment_ids')
    def _compute_shipment_count(self):
        for order in self:
            order.shipment_count = len(order.shipment_ids)

    @api.depends('line_ids.shipment_id')
    def _compute_unshipped_count(self):
        for order in self:
            order.unshipped_count = len(order.line_ids.filtered(lambda l: not l.shipment_id))

    @api.constrains('requested_pickup_date', 'requested_delivery_date')
    def _check_dates(self):
        for order in self:
            if (order.requested_pickup_date and order.requested_delivery_date
                    and order.requested_delivery_date < order.requested_pickup_date):
                raise ValidationError(_("Delivery cannot be requested before the pickup."))

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.delivery_partner_id = self.partner_id
            if self.contract_id.partner_id != self.partner_id:
                self.contract_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.transport.order') or 'New'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_active(self):
        if self.filtered(lambda o: o.state not in ('draft', 'cancelled')):
            raise UserError(_("Only draft or cancelled orders can be deleted."))

    # ------------------------------------------------------------------
    def _update_state(self):
        for order in self.filtered(lambda o: o.state in ('confirmed', 'in_progress')):
            shipments = order.shipment_ids.filtered(lambda s: s.state != 'cancelled')
            pending = order.line_ids.filtered(lambda l: not l.shipment_id)
            if shipments and not pending and all(s.state == 'delivered' for s in shipments):
                new_state = 'done'
            elif any(s.state in ('in_transit', 'delivered', 'failed') for s in shipments):
                new_state = 'in_progress'
            else:
                new_state = 'confirmed'
            if new_state != order.state:
                order.state = new_state

    # ------------------------------------------------------------------
    def action_confirm(self):
        for order in self.filtered(lambda o: o.state == 'draft'):
            if not order.line_ids:
                raise UserError(_("Add at least one cargo line."))
            if order.contract_id and order.contract_id.state != 'active':
                raise UserError(_("The contract %s is not active.", order.contract_id.name))
            order.state = 'confirmed'

    def action_create_shipment(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'in_progress'):
            raise UserError(_("Confirm the order before creating shipments."))
        pending = self.line_ids.filtered(lambda l: not l.shipment_id)
        if not pending:
            raise UserError(_("All cargo lines are already assigned to shipments."))
        shipment = self.env['nexora.shipment'].create({'order_id': self.id})
        pending.write({'shipment_id': shipment.id})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nexora.shipment',
            'res_id': shipment.id,
            'view_mode': 'form',
        }

    def action_cancel(self):
        for order in self.filtered(lambda o: o.state != 'cancelled'):
            if order.shipment_ids.filtered(lambda s: s.state in ('in_transit', 'delivered')):
                raise UserError(_(
                    "Order %s has shipments in transit or delivered and cannot be cancelled.",
                    order.name))
        for order in self.filtered(lambda o: o.state != 'cancelled'):
            order.shipment_ids.filtered(lambda s: s.state in ('draft', 'planned')).action_cancel()
            order.state = 'cancelled'

    def action_draft(self):
        self.filtered(lambda o: o.state == 'cancelled').write({'state': 'draft'})

    def action_view_shipments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipments'),
            'res_model': 'nexora.shipment',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }


class NexoraTransportOrderLine(models.Model):
    _name = 'nexora.transport.order.line'
    _description = 'Transport Order Cargo Line'

    order_id = fields.Many2one('nexora.transport.order', required=True, ondelete='cascade')
    shipment_id = fields.Many2one('nexora.shipment', string='Shipment',
                                  copy=False, ondelete='set null', index=True)
    product_id = fields.Many2one('product.product', string='Product')
    name = fields.Char(string='Description', required=True)
    quantity = fields.Float(default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit')
    weight = fields.Float(string='Weight (kg)')
    volume = fields.Float(string='Volume (m³)')
    temperature_class = fields.Selection(TEMP_SELECTION, default='ambient', required=True)
    hazardous = fields.Boolean(string='Hazardous')
    notes = fields.Char()

    @api.onchange('product_id', 'quantity')
    def _onchange_product_id(self):
        product = self.product_id
        if product:
            self.name = self.name or product.display_name
            self.uom_id = product.uom_id
            self.weight = product.weight * self.quantity
            self.volume = product.volume * self.quantity
            self.temperature_class = product.nexora_temperature_class or 'ambient'
            self.hazardous = product.nexora_hazardous

    @api.constrains('quantity', 'weight', 'volume')
    def _check_values(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))
            if line.weight < 0 or line.volume < 0:
                raise ValidationError(_("Weight and volume cannot be negative."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_shipped(self):
        if self.filtered('shipment_id'):
            raise UserError(_("A cargo line assigned to a shipment cannot be deleted."))