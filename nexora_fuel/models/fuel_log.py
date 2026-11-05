from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

FUEL_TYPES = [
    ('diesel', 'Diesel'),
    ('gasoline', 'Gasoline'),
    ('lpg', 'LPG'),
    ('cng', 'CNG'),
    ('electric', 'Electric (kWh)'),
]


class NexoraFuelLog(models.Model):
    _name = 'nexora.fuel.log'
    _description = 'Fuel Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, odometer desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    driver_id = fields.Many2one(
        'hr.employee', string='Driver', domain=[('is_driver', '=', True)],
        compute='_compute_from_vehicle', store=True, readonly=False, tracking=True)
    cost_center_id = fields.Many2one(
        'nexora.cost.center', string='Cost Center',
        compute='_compute_from_vehicle', store=True, readonly=False)
    fuel_type = fields.Selection(
        FUEL_TYPES, required=True,
        compute='_compute_from_vehicle', store=True, readonly=False)
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True, index=True)
    odometer = fields.Float(required=True, tracking=True)
    quantity = fields.Float(string='Quantity (L / kWh)', digits=(16, 2), required=True)
    price_unit = fields.Float(string='Price per Unit', digits=(16, 3))
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(
        currency_field='currency_id', compute='_compute_amount',
        store=True, readonly=False, tracking=True,
        help="Computed from quantity x price, but can be overridden with the invoiced total.")
    full_tank = fields.Boolean(string='Full Tank', default=True,
                               help="Required for accurate consumption calculation.")
    station_id = fields.Many2one('res.partner', string='Station / Vendor')
    card_id = fields.Many2one('nexora.fuel.card', string='Fuel Card',
                              domain="[('state', '=', 'active')]")
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)

    distance = fields.Float(string='Distance (km)', readonly=True, copy=False)
    consumption = fields.Float(string='Consumption (per 100 km)', digits=(16, 2),
                               readonly=True, copy=False)
    cost_per_km = fields.Float(string='Cost per km', digits=(16, 3), readonly=True, copy=False)
    is_anomaly = fields.Boolean(string='Abnormal Consumption', readonly=True, copy=False)
    over_limit = fields.Boolean(string='Over Card Limit', readonly=True, copy=False)

    expense_ids = fields.One2many('nexora.vehicle.expense', 'fuel_log_id')
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)
    notes = fields.Text()

    # ------------------------------------------------------------------
    # Computes & constraints
    # ------------------------------------------------------------------
    @api.depends('vehicle_id')
    def _compute_from_vehicle(self):
        known = dict(FUEL_TYPES)
        for log in self:
            vehicle = log.vehicle_id
            log.driver_id = vehicle.nexora_current_driver_id
            log.cost_center_id = vehicle.nexora_cost_center_id
            if vehicle.fuel_type in known:
                log.fuel_type = vehicle.fuel_type
            else:
                log.fuel_type = log.fuel_type or 'diesel'

    @api.depends('quantity', 'price_unit')
    def _compute_amount(self):
        for log in self:
            log.amount = log.quantity * log.price_unit

    @api.constrains('quantity', 'price_unit', 'odometer')
    def _check_values(self):
        for log in self:
            if log.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))
            if log.price_unit < 0 or log.odometer < 0:
                raise ValidationError(_("Price and odometer cannot be negative."))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.fuel.log') or 'New'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        if self.filtered(lambda l: l.state == 'confirmed'):
            raise UserError(_("Confirmed fuel logs cannot be deleted. Cancel them first."))

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------
    def _check_before_confirm(self):
        self.ensure_one()
        card = self.card_id
        if card:
            if card.state != 'active':
                raise UserError(_("Fuel card %s is not active.", card.name))
            if card.expiry_date and card.expiry_date < self.date:
                raise UserError(_("Fuel card %s had expired on the fuel date.", card.name))
            if card.vehicle_id and card.vehicle_id != self.vehicle_id:
                raise UserError(_(
                    "Fuel card %(card)s is assigned to %(vehicle)s.",
                    card=card.name, vehicle=card.vehicle_id.display_name))
        # Odometer must be consistent with the chronological order of logs
        conflict = self.search_count([
            ('vehicle_id', '=', self.vehicle_id.id),
            ('state', '=', 'confirmed'),
            ('id', '!=', self.id),
            '|',
            '&', ('date', '<', self.date), ('odometer', '>', self.odometer),
            '&', ('date', '>', self.date), ('odometer', '<', self.odometer),
        ])
        if conflict:
            raise UserError(_(
                "The odometer reading %(odo).0f is inconsistent with other fuel logs of this vehicle.",
                odo=self.odometer))

    def _update_vehicle_odometer(self):
        for log in self:
            if log.odometer > log.vehicle_id.odometer:
                self.env['fleet.vehicle.odometer'].sudo().create({
                    'vehicle_id': log.vehicle_id.id,
                    'value': log.odometer,
                    'date': log.date,
                })

    def _sync_expense(self):
        Expense = self.env['nexora.vehicle.expense']
        for log in self:
            vals = {
                'vehicle_id': log.vehicle_id.id,
                'driver_id': log.driver_id.id,
                'date': log.date,
                'expense_type': 'fuel',
                'description': _("Fuel %(log)s", log=log.name),
                'partner_id': log.station_id.id,
                'amount': log.amount,
                'currency_id': log.currency_id.id,
                'cost_center_id': log.cost_center_id.id,
                'state': 'confirmed',
            }
            expense = log.expense_ids[:1]
            if expense:
                expense.write(vals)
            else:
                Expense.create(dict(vals, fuel_log_id=log.id))

    def _check_card_limit(self):
        for log in self.filtered('card_id'):
            card = log.card_id
            if card.monthly_limit and card._spend_in_month(log.date) > card.monthly_limit:
                log.over_limit = True
                body = _("Monthly limit of card %(card)s exceeded after %(log)s.",
                         card=card.name, log=log.name)
                log.message_post(body=body)
                card.message_post(body=body)

    def _notify_anomaly(self):
        admin = self.env.ref('base.user_admin')
        summary = _("Abnormal fuel consumption")
        for log in self:
            if log.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            log.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=_("%(value).1f per 100 km on %(vehicle)s",
                       value=log.consumption, vehicle=log.vehicle_id.display_name),
                user_id=(log.vehicle_id.manager_id or admin).id,
            )

    @api.model
    def _recompute_metrics(self, vehicles):
        """Full-tank method: consumption between two full fills =
        liters of all fills in between (including the last) / distance * 100."""
        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_fuel.anomaly_pct', 20))
        for vehicle in vehicles:
            logs = self.search(
                [('vehicle_id', '=', vehicle.id), ('state', '=', 'confirmed')],
                order='odometer, id')
            results = {}
            last_full = False
            qty_acc = amount_acc = 0.0
            for log in logs:
                res = {'distance': 0.0, 'consumption': 0.0, 'cost_per_km': 0.0}
                if last_full:
                    qty_acc += log.quantity
                    amount_acc += log.amount
                    if log.full_tank:
                        dist = log.odometer - last_full.odometer
                        if dist > 0:
                            res['distance'] = dist
                            res['consumption'] = qty_acc / dist * 100.0
                            res['cost_per_km'] = amount_acc / dist
                        last_full = log
                        qty_acc = amount_acc = 0.0
                elif log.full_tank:
                    last_full = log
                results[log.id] = res

            values = [r['consumption'] for r in results.values() if r['consumption'] > 0]
            baseline = vehicle.nexora_target_consumption or (
                sum(values) / len(values) if len(values) >= 3 else 0.0)
            for log in logs:
                res = results[log.id]
                res['is_anomaly'] = bool(
                    baseline and res['consumption'] > baseline * (1 + threshold / 100.0))
                log.write(res)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm(self):
        vehicles = self.env['fleet.vehicle']
        confirmed = self.browse()
        for log in self.filtered(lambda l: l.state == 'draft'):
            log._check_before_confirm()
            log.state = 'confirmed'
            log._update_vehicle_odometer()
            log._sync_expense()
            log._check_card_limit()
            vehicles |= log.vehicle_id
            confirmed |= log
        self._recompute_metrics(vehicles)
        confirmed.filtered('is_anomaly')._notify_anomaly()

    def action_cancel(self):
        logs = self.filtered(lambda l: l.state in ('draft', 'confirmed'))
        vehicles = logs.vehicle_id
        logs.write({
            'state': 'cancelled', 'distance': 0.0, 'consumption': 0.0,
            'cost_per_km': 0.0, 'is_anomaly': False, 'over_limit': False,
        })
        logs.expense_ids.write({'state': 'cancelled'})
        self._recompute_metrics(vehicles)

    def action_draft(self):
        self.filtered(lambda l: l.state == 'cancelled').write({'state': 'draft'})