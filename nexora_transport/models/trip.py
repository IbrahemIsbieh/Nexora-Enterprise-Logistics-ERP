from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .transport_order import TEMP_RANK, TEMP_SELECTION, max_temp


class NexoraTransportTrip(models.Model):
    _name = 'nexora.transport.trip'
    _description = 'Transport Trip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planned_start desc, id desc'

    name = fields.Char(string='Trip No.', default='New', copy=False, readonly=True)
    vehicle_id = fields.Many2one(
        'fleet.vehicle', required=True, tracking=True, index=True,
        domain="[('id', 'in', available_vehicle_ids)]")
    driver_id = fields.Many2one(
        'hr.employee', string='Driver', required=True, tracking=True, index=True,
        domain="[('id', 'in', available_driver_ids)]")
    available_vehicle_ids = fields.Many2many(
        'fleet.vehicle', compute='_compute_available_vehicles')
    available_driver_ids = fields.Many2many(
        'hr.employee', compute='_compute_available_drivers')
    origin_warehouse_id = fields.Many2one('stock.warehouse', string='Origin Warehouse')
    route = fields.Char(string='Route', help="e.g. Amman - Zarqa - Irbid")
    planned_start = fields.Datetime(
        required=True, default=fields.Datetime.now, tracking=True)
    planned_end = fields.Datetime(
        required=True, tracking=True,
        default=lambda self: fields.Datetime.now() + timedelta(hours=8))
    actual_start = fields.Datetime(readonly=True, copy=False)
    actual_end = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection(
        [('draft', 'Draft'), ('planned', 'Planned'), ('in_progress', 'In Progress'),
         ('done', 'Done'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)
    responsible_id = fields.Many2one(
        'res.users', string='Dispatcher', default=lambda self: self.env.user, tracking=True)

    shipment_ids = fields.One2many('nexora.shipment', 'trip_id', string='Shipments')
    shipment_count = fields.Integer(compute='_compute_shipment_count')
    total_weight = fields.Float(string='Load (kg)', compute='_compute_load', store=True)
    total_volume = fields.Float(string='Load (m³)', compute='_compute_load', store=True)
    temperature_class = fields.Selection(TEMP_SELECTION, compute='_compute_load', store=True)
    has_hazardous = fields.Boolean(string='Hazardous', compute='_compute_load', store=True)
    payload_usage = fields.Float(string='Payload Usage (%)', compute='_compute_load', store=True)
    volume_usage = fields.Float(string='Volume Usage (%)', compute='_compute_load', store=True)

    assignment_id = fields.Many2one('nexora.vehicle.assignment', string='Assignment',
                                    readonly=True, copy=False)
    odometer_start = fields.Float(readonly=True, copy=False)
    odometer_end = fields.Float(string='Odometer End (km)', copy=False)
    distance = fields.Float(compute='_compute_distance', string='Distance (km)')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    note = fields.Text()

    # ------------------------------------------------------------------
    @api.depends('planned_start', 'planned_end')
    def _compute_available_vehicles(self):
        Vehicle = self.env['fleet.vehicle']
        for trip in self:
            if trip.planned_start:
                trip.available_vehicle_ids = Vehicle.nexora_get_available_vehicles(
                    trip.planned_start, trip.planned_end)
            else:
                trip.available_vehicle_ids = Vehicle.search(
                    [('nexora_availability', 'in', ('available', 'assigned'))])

    @api.depends('planned_start', 'planned_end')
    def _compute_available_drivers(self):
        Employee = self.env['hr.employee']
        Assignment = self.env['nexora.vehicle.assignment']
        for trip in self:
            drivers = Employee.search([('is_driver', '=', True)])
            if trip.planned_start:
                domain = [('state', 'in', ('planned', 'active')), ('driver_id', 'in', drivers.ids)]
                if trip.planned_end:
                    domain.append(('date_start', '<', trip.planned_end))
                domain += ['|', ('date_end', '=', False), ('date_end', '>', trip.planned_start)]
                drivers -= Assignment.search(domain).driver_id
                start_date = trip.planned_start.date()
                drivers = drivers.filtered(
                    lambda d: not d.license_expiry or d.license_expiry >= start_date)
            trip.available_driver_ids = drivers

    @api.depends('shipment_ids')
    def _compute_shipment_count(self):
        for trip in self:
            trip.shipment_count = len(trip.shipment_ids)

    @api.depends('shipment_ids.state', 'shipment_ids.total_weight', 'shipment_ids.total_volume',
                 'shipment_ids.temperature_class', 'shipment_ids.has_hazardous',
                 'vehicle_id.nexora_max_payload', 'vehicle_id.nexora_cargo_volume')
    def _compute_load(self):
        for trip in self:
            active = trip.shipment_ids.filtered(lambda s: s.state != 'cancelled')
            weight = sum(active.mapped('total_weight'))
            volume = sum(active.mapped('total_volume'))
            payload = trip.vehicle_id.nexora_max_payload
            capacity = trip.vehicle_id.nexora_cargo_volume
            trip.total_weight = weight
            trip.total_volume = volume
            trip.temperature_class = max_temp(active.mapped('temperature_class'))
            trip.has_hazardous = any(active.mapped('has_hazardous'))
            trip.payload_usage = weight / payload * 100.0 if payload else 0.0
            trip.volume_usage = volume / capacity * 100.0 if capacity else 0.0

    @api.depends('odometer_start', 'odometer_end')
    def _compute_distance(self):
        for trip in self:
            trip.distance = trip.odometer_end - trip.odometer_start if trip.odometer_end else 0.0

    @api.constrains('planned_start', 'planned_end')
    def _check_dates(self):
        for trip in self:
            if trip.planned_end <= trip.planned_start:
                raise ValidationError(_("The planned end must be after the planned start."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.transport.trip') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if ('vehicle_id' in vals or 'driver_id' in vals) \
                and self.filtered(lambda t: t.state != 'draft'):
            raise UserError(_(
                "Vehicle and driver can only be changed on draft trips. Cancel the trip first."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_active(self):
        if self.filtered(lambda t: t.state not in ('draft', 'cancelled')):
            raise UserError(_("Only draft or cancelled trips can be deleted."))

    # ------------------------------------------------------------------
    # Load validation
    # ------------------------------------------------------------------
    def _check_trip_load(self):
        strict = str(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_transport.strict_capacity', 'True')) in ('True', 'true', '1')
        for trip in self:
            vehicle = trip.vehicle_id
            shipments = trip.shipment_ids.filtered(lambda s: s.state != 'cancelled')
            problems = []
            weight = sum(shipments.mapped('total_weight'))
            volume = sum(shipments.mapped('total_volume'))
            if vehicle.nexora_max_payload and weight > vehicle.nexora_max_payload:
                problems.append(_(
                    "Load %(w).1f kg exceeds the payload of %(v)s (%(m).1f kg).",
                    w=weight, v=vehicle.display_name, m=vehicle.nexora_max_payload))
            if vehicle.nexora_cargo_volume and volume > vehicle.nexora_cargo_volume:
                problems.append(_(
                    "Volume %(w).2f m³ exceeds the cargo volume of %(v)s (%(m).2f m³).",
                    w=volume, v=vehicle.display_name, m=vehicle.nexora_cargo_volume))
            cargo_rank = TEMP_RANK[max_temp(shipments.mapped('temperature_class'))]
            vehicle_rank = TEMP_RANK.get(vehicle.nexora_temperature_class or 'ambient', 0)
            if cargo_rank > vehicle_rank:
                problems.append(_(
                    "The cargo needs %(c)s transport but %(v)s only supports %(vc)s.",
                    c=max_temp(shipments.mapped('temperature_class')),
                    v=vehicle.display_name,
                    vc=vehicle.nexora_temperature_class or 'ambient'))
            if any(shipments.mapped('has_hazardous')) and not vehicle.nexora_hazmat_certified:
                problems.append(_(
                    "The cargo is hazardous but %s is not hazmat certified.",
                    vehicle.display_name))
            if problems:
                message = "\n".join(problems)
                if strict:
                    raise UserError(message)
                trip.message_post(body=message.replace("\n", "<br/>"))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_plan(self):
        for trip in self.filtered(lambda t: t.state == 'draft'):
            shipments = trip.shipment_ids.filtered(lambda s: s.state != 'cancelled')
            if not shipments:
                raise UserError(_("Add at least one shipment to the trip."))
            trip._check_trip_load()
            assignment = self.env['nexora.vehicle.assignment'].create({
                'vehicle_id': trip.vehicle_id.id,
                'driver_id': trip.driver_id.id,
                'purpose': 'trip',
                'date_start': trip.planned_start,
                'date_end': trip.planned_end,
                'trip_id': trip.id,
            })
            assignment.action_confirm()
            trip.write({'assignment_id': assignment.id, 'state': 'planned'})
            for shipment in shipments.filtered(lambda s: s.state == 'draft'):
                shipment.state = 'planned'
                shipment._log_event('status', _("Planned on trip %s", trip.name))

    def action_start(self):
        now = fields.Datetime.now()
        for trip in self.filtered(lambda t: t.state == 'planned'):
            trip.assignment_id.action_start()
            trip.write({
                'state': 'in_progress',
                'actual_start': now,
                'odometer_start': trip.assignment_id.odometer_start,
            })
            for shipment in trip.shipment_ids.filtered(lambda s: s.state == 'planned'):
                shipment.write({'state': 'in_transit', 'actual_pickup_date': now})
                shipment._log_event('pickup', _("Departed with trip %s", trip.name))
            trip.shipment_ids.order_id._update_state()

    def action_done(self):
        now = fields.Datetime.now()
        for trip in self.filtered(lambda t: t.state == 'in_progress'):
            open_shipments = trip.shipment_ids.filtered(
                lambda s: s.state in ('draft', 'planned', 'in_transit'))
            if open_shipments:
                raise UserError(_(
                    "Deliver or mark as failed all shipments first: %s",
                    ", ".join(open_shipments.mapped('name'))))
            if trip.odometer_end and trip.odometer_end < trip.odometer_start:
                raise UserError(_("The ending odometer cannot be lower than the starting one."))
            trip.assignment_id.odometer_end = trip.odometer_end
            trip.assignment_id.action_finish()
            trip.write({'state': 'done', 'actual_end': now})

    def action_cancel(self):
        for trip in self:
            if trip.state == 'in_progress':
                raise UserError(_(
                    "A trip in progress cannot be cancelled. Mark undelivered shipments as failed "
                    "and complete the trip."))
        for trip in self.filtered(lambda t: t.state in ('draft', 'planned')):
            if trip.assignment_id:
                trip.assignment_id.action_cancel()
            trip.shipment_ids.write({'trip_id': False})
            trip.state = 'cancelled'

    def action_draft(self):
        self.filtered(lambda t: t.state == 'cancelled').write(
            {'state': 'draft', 'assignment_id': False})

    def action_view_shipments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipments'),
            'res_model': 'nexora.shipment',
            'view_mode': 'list,form',
            'domain': [('trip_id', '=', self.id)],
        }