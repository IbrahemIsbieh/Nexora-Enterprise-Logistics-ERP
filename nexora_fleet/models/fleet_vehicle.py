from datetime import timedelta

from odoo import _, api, fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    # --- Specifications -------------------------------------------------
    nexora_vehicle_class = fields.Selection(
        [
            ('van', 'Van'),
            ('pickup', 'Pickup'),
            ('truck_light', 'Light Truck'),
            ('truck_heavy', 'Heavy Truck'),
            ('trailer', 'Trailer / Semi-trailer'),
            ('tanker', 'Tanker'),
            ('refrigerated', 'Refrigerated Truck'),
            ('other', 'Other'),
        ],
        string='Vehicle Class',
    )
    nexora_max_payload = fields.Float(string='Max Payload (kg)')
    nexora_cargo_volume = fields.Float(string='Cargo Volume (m³)')
    nexora_axles = fields.Integer(string='Axles')
    nexora_temperature_class = fields.Selection(
        [('ambient', 'Ambient'), ('chilled', 'Chilled'), ('frozen', 'Frozen')],
        string='Temperature Capability', default='ambient')
    nexora_hazmat_certified = fields.Boolean(string='Hazmat Certified')
    nexora_home_warehouse_id = fields.Many2one('stock.warehouse', string='Home Warehouse')
    nexora_cost_center_id = fields.Many2one('nexora.cost.center', string='Cost Center')

    # --- Registration & documents ----------------------------------------
    nexora_registration_no = fields.Char(string='Registration No.')
    nexora_registration_expiry = fields.Date(string='Registration Expiry')
    nexora_insurance_policy = fields.Char(string='Insurance Policy No.')
    nexora_insurance_expiry = fields.Date(string='Insurance Expiry')
    nexora_inspection_expiry = fields.Date(string='Inspection Expiry')
    nexora_doc_status = fields.Selection(
        [('valid', 'Valid'), ('expiring', 'Expiring Soon'), ('expired', 'Expired')],
        string='Documents', compute='_compute_nexora_doc_status')

    # --- Availability ------------------------------------------------------
    nexora_out_of_service = fields.Boolean(string='Out of Service', tracking=True)
    nexora_in_maintenance = fields.Boolean(string='In Maintenance', tracking=True)
    nexora_availability = fields.Selection(
        [
            ('available', 'Available'),
            ('assigned', 'Assigned'),
            ('maintenance', 'In Maintenance'),
            ('out_of_service', 'Out of Service'),
        ],
        string='Availability', compute='_compute_nexora_availability',
        store=True, index=True)
    nexora_current_driver_id = fields.Many2one(
        'hr.employee', string='Current Driver', compute='_compute_nexora_current_driver')

    nexora_assignment_ids = fields.One2many('nexora.vehicle.assignment', 'vehicle_id')
    nexora_incident_ids = fields.One2many('nexora.vehicle.incident', 'vehicle_id')
    nexora_assignment_count = fields.Integer(compute='_compute_nexora_counts')
    nexora_incident_count = fields.Integer(compute='_compute_nexora_counts')

    _NEXORA_DOC_FIELDS = (
        'nexora_registration_expiry',
        'nexora_insurance_expiry',
        'nexora_inspection_expiry',
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends(
        'nexora_out_of_service', 'nexora_in_maintenance',
        'nexora_assignment_ids.state',
        'nexora_incident_ids.blocks_vehicle', 'nexora_incident_ids.state')
    def _compute_nexora_availability(self):
        for vehicle in self:
            blocking = vehicle.nexora_incident_ids.filtered(
                lambda i: i.blocks_vehicle and i.state in ('reported', 'investigating'))
            if vehicle.nexora_out_of_service or blocking:
                vehicle.nexora_availability = 'out_of_service'
            elif vehicle.nexora_in_maintenance:
                vehicle.nexora_availability = 'maintenance'
            elif any(a.state == 'active' for a in vehicle.nexora_assignment_ids):
                vehicle.nexora_availability = 'assigned'
            else:
                vehicle.nexora_availability = 'available'

    @api.depends('nexora_assignment_ids.state', 'nexora_assignment_ids.driver_id')
    def _compute_nexora_current_driver(self):
        for vehicle in self:
            active = vehicle.nexora_assignment_ids.filtered(lambda a: a.state == 'active')[:1]
            vehicle.nexora_current_driver_id = active.driver_id

    @api.depends(*_NEXORA_DOC_FIELDS)
    def _compute_nexora_doc_status(self):
        today = fields.Date.context_today(self)
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_fleet.doc_alert_days', 30))
        for vehicle in self:
            dates = [vehicle[f] for f in self._NEXORA_DOC_FIELDS if vehicle[f]]
            if not dates:
                vehicle.nexora_doc_status = False
                continue
            earliest = min(dates)
            if earliest < today:
                vehicle.nexora_doc_status = 'expired'
            elif (earliest - today).days <= days:
                vehicle.nexora_doc_status = 'expiring'
            else:
                vehicle.nexora_doc_status = 'valid'

    def _compute_nexora_counts(self):
        for vehicle in self:
            vehicle.nexora_assignment_count = len(vehicle.nexora_assignment_ids)
            vehicle.nexora_incident_count = len(vehicle.nexora_incident_ids)

    # ------------------------------------------------------------------
    # API for other modules (transport, maintenance ...)
    # ------------------------------------------------------------------
    @api.model
    def nexora_get_available_vehicles(self, date_start, date_end=None, vehicle_class=None):
        """Vehicles that are operational and free of assignments in the given window."""
        domain = [('nexora_availability', 'in', ('available', 'assigned'))]
        if vehicle_class:
            domain.append(('nexora_vehicle_class', '=', vehicle_class))
        vehicles = self.search(domain)
        busy_domain = [
            ('state', 'in', ('planned', 'active')),
            ('vehicle_id', 'in', vehicles.ids),
        ]
        if date_end:
            busy_domain.append(('date_start', '<', date_end))
        busy_domain += ['|', ('date_end', '=', False), ('date_end', '>', date_start)]
        busy = self.env['nexora.vehicle.assignment'].search(busy_domain).vehicle_id
        return vehicles - busy

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_nexora_assignments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assignments'),
            'res_model': 'nexora.vehicle.assignment',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_nexora_incidents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Incidents'),
            'res_model': 'nexora.vehicle.incident',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_document_expiry_alert(self):
        today = fields.Date.context_today(self)
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_fleet.doc_alert_days', 30))
        limit = today + timedelta(days=days)
        admin = self.env.ref('base.user_admin')
        for vehicle in self.search([]):
            for fname in self._NEXORA_DOC_FIELDS:
                expiry = vehicle[fname]
                if not expiry or expiry > limit:
                    continue
                label = self._fields[fname].string
                summary = _("Vehicle document expiring: %s", label)
                if vehicle.activity_ids.filtered(lambda a: a.summary == summary):
                    continue
                vehicle.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=expiry,
                    summary=summary,
                    user_id=(vehicle.manager_id or admin).id,
                )