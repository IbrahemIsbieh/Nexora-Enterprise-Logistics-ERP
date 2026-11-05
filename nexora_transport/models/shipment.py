from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .transport_order import TEMP_SELECTION, max_temp


class NexoraShipment(models.Model):
    _name = 'nexora.shipment'
    _description = 'Shipment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_pickup_date desc, id desc'

    name = fields.Char(string='Shipment No.', default='New', copy=False, readonly=True)
    order_id = fields.Many2one(
        'nexora.transport.order', required=True, ondelete='restrict', index=True, tracking=True)
    partner_id = fields.Many2one(related='order_id.partner_id', store=True, string='Customer')
    trip_id = fields.Many2one(
        'nexora.transport.trip', string='Trip', tracking=True, copy=False, index=True,
        domain="[('state', 'in', ('draft', 'planned'))]")
    vehicle_id = fields.Many2one(related='trip_id.vehicle_id', store=True, string='Vehicle')
    driver_id = fields.Many2one(related='trip_id.driver_id', store=True, string='Driver')

    pickup_partner_id = fields.Many2one(
        'res.partner', string='Pickup Address', compute='_compute_defaults',
        store=True, readonly=False)
    delivery_partner_id = fields.Many2one(
        'res.partner', string='Delivery Address', compute='_compute_defaults',
        store=True, readonly=False)
    planned_pickup_date = fields.Datetime(
        compute='_compute_defaults', store=True, readonly=False, tracking=True)
    planned_delivery_date = fields.Datetime(
        compute='_compute_defaults', store=True, readonly=False, tracking=True)
    actual_pickup_date = fields.Datetime(readonly=True, copy=False)
    actual_delivery_date = fields.Datetime(readonly=True, copy=False)

    state = fields.Selection(
        [('draft', 'Draft'), ('planned', 'Planned'), ('in_transit', 'In Transit'),
         ('delivered', 'Delivered'), ('failed', 'Failed'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)

    line_ids = fields.One2many('nexora.transport.order.line', 'shipment_id', string='Cargo')
    total_weight = fields.Float(string='Weight (kg)', compute='_compute_totals', store=True)
    total_volume = fields.Float(string='Volume (m³)', compute='_compute_totals', store=True)
    temperature_class = fields.Selection(
        TEMP_SELECTION, compute='_compute_totals', store=True)
    has_hazardous = fields.Boolean(string='Hazardous', compute='_compute_totals', store=True)

    event_ids = fields.One2many('nexora.shipment.event', 'shipment_id', string='Tracking')

    pod_receiver_name = fields.Char(string='Received By', copy=False)
    pod_signature = fields.Binary(string='Signature', attachment=True, copy=False)
    pod_photo = fields.Image(string='Delivery Photo', max_width=1280, max_height=1280, copy=False)
    pod_note = fields.Text(string='Delivery Note', copy=False)
    failure_reason = fields.Text(copy=False)

    delay_hours = fields.Float(compute='_compute_delay', store=True, string='Delay (h)')
    on_time = fields.Boolean(compute='_compute_delay', store=True, string='On Time')
    company_id = fields.Many2one(related='order_id.company_id', store=True)

    # ------------------------------------------------------------------
    @api.depends('order_id')
    def _compute_defaults(self):
        for rec in self:
            order = rec.order_id
            rec.pickup_partner_id = order.pickup_partner_id
            rec.delivery_partner_id = order.delivery_partner_id
            rec.planned_pickup_date = order.requested_pickup_date
            rec.planned_delivery_date = order.requested_delivery_date

    @api.depends('line_ids.weight', 'line_ids.volume',
                 'line_ids.temperature_class', 'line_ids.hazardous')
    def _compute_totals(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped('weight'))
            rec.total_volume = sum(rec.line_ids.mapped('volume'))
            rec.temperature_class = max_temp(rec.line_ids.mapped('temperature_class'))
            rec.has_hazardous = any(rec.line_ids.mapped('hazardous'))

    @api.depends('state', 'actual_delivery_date', 'planned_delivery_date')
    def _compute_delay(self):
        grace = float(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_transport.ontime_grace_hours', 2))
        for rec in self:
            if rec.state == 'delivered' and rec.actual_delivery_date and rec.planned_delivery_date:
                delta = (rec.actual_delivery_date - rec.planned_delivery_date).total_seconds() / 3600.0
                rec.delay_hours = max(delta, 0.0)
                rec.on_time = delta <= grace
            else:
                rec.delay_hours = 0.0
                rec.on_time = False

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.shipment') or 'New'
        records = super().create(vals_list)
        records._log_event('status', _("Shipment created"))
        return records

    def write(self, vals):
        if 'trip_id' in vals:
            locked = self.filtered(
                lambda s: s.state not in ('draft', 'planned') and s.trip_id.id != vals['trip_id'])
            if locked:
                raise UserError(_(
                    "The trip of shipment %s can no longer be changed.", locked[:1].name))
            if vals['trip_id']:
                trip = self.env['nexora.transport.trip'].browse(vals['trip_id'])
                if trip.state not in ('draft', 'planned'):
                    raise UserError(_("Shipments can only be added to draft or planned trips."))
        res = super().write(vals)
        if 'trip_id' in vals:
            for rec in self:
                if rec.trip_id and rec.trip_id.state == 'planned' and rec.state == 'draft':
                    rec.state = 'planned'
                    rec._log_event('status', _("Planned on trip %s", rec.trip_id.name))
                elif not rec.trip_id and rec.state == 'planned':
                    rec.state = 'draft'
            self.trip_id.filtered(lambda t: t.state == 'planned')._check_trip_load()
        return res

    def _log_event(self, event_type, note='', location=''):
        Event = self.env['nexora.shipment.event'].sudo()
        for rec in self:
            Event.create({
                'shipment_id': rec.id,
                'event_type': event_type,
                'note': note,
                'location': location,
                'user_id': self.env.user.id,
            })

    # ------------------------------------------------------------------
    def action_deliver(self):
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError(_("Only shipments in transit can be delivered (%s).", rec.name))
            if not rec.pod_receiver_name or not (rec.pod_signature or rec.pod_photo):
                raise UserError(_(
                    "Proof of delivery is required for %s: receiver name and a signature or a photo.",
                    rec.name))
        now = fields.Datetime.now()
        for rec in self:
            rec.write({'state': 'delivered', 'actual_delivery_date': now})
            rec._log_event('delivered', _("Delivered to %s", rec.pod_receiver_name))
        self.order_id._update_state()

    def action_fail(self):
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError(_("Only shipments in transit can be marked as failed (%s).", rec.name))
            if not rec.failure_reason:
                raise UserError(_("Enter the failure reason for %s first.", rec.name))
        for rec in self:
            rec.state = 'failed'
            rec._log_event('failed', rec.failure_reason)
        self.order_id._update_state()

    def action_retry(self):
        for rec in self.filtered(lambda s: s.state == 'failed'):
            rec.write({'state': 'draft', 'actual_pickup_date': False, 'failure_reason': False})
            rec.trip_id = False
            rec._log_event('status', _("Rescheduled after a failed delivery"))
        self.order_id._update_state()

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'planned'):
                raise UserError(_(
                    "Shipment %s cannot be cancelled in its current state.", rec.name))
        for rec in self:
            rec.trip_id = False
            rec.line_ids.write({'shipment_id': False})
            rec.state = 'cancelled'
            rec._log_event('status', _("Shipment cancelled"))
        self.order_id._update_state()

    # ------------------------------------------------------------------
    @api.model
    def _cron_late_shipments(self):
        now = fields.Datetime.now()
        late = self.search([
            ('state', 'in', ('draft', 'planned', 'in_transit')),
            ('planned_delivery_date', '!=', False),
            ('planned_delivery_date', '<', now),
        ])
        admin = self.env.ref('base.user_admin')
        summary = _("Shipment is late")
        for shipment in late:
            if shipment.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            shipment.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=_("Planned delivery was %s.", shipment.planned_delivery_date),
                user_id=(shipment.order_id.responsible_id or admin).id,
            )


class NexoraShipmentEvent(models.Model):
    _name = 'nexora.shipment.event'
    _description = 'Shipment Tracking Event'
    _order = 'date desc, id desc'

    shipment_id = fields.Many2one('nexora.shipment', required=True, ondelete='cascade', index=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    event_type = fields.Selection(
        [
            ('status', 'Status Change'),
            ('pickup', 'Picked Up'),
            ('checkpoint', 'Checkpoint'),
            ('delivered', 'Delivered'),
            ('failed', 'Delivery Failed'),
            ('note', 'Note'),
        ],
        default='checkpoint', required=True)
    location = fields.Char()
    note = fields.Char()
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user)