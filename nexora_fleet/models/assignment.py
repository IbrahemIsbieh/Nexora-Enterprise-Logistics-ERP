from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class NexoraVehicleAssignment(models.Model):
    _name = 'nexora.vehicle.assignment'
    _description = 'Vehicle Assignment'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    driver_id = fields.Many2one(
        'hr.employee', string='Driver', required=True, tracking=True, index=True,
        domain=[('is_driver', '=', True)])
    purpose = fields.Selection(
        [('trip', 'Trip / Shipment'), ('temporary', 'Temporary'), ('long_term', 'Long Term')],
        default='trip', required=True)
    date_start = fields.Datetime(string='Start', required=True,
                                 default=fields.Datetime.now, tracking=True)
    date_end = fields.Datetime(string='End', tracking=True,
                               help="Leave empty for an open-ended assignment.")
    state = fields.Selection(
        [('draft', 'Draft'), ('planned', 'Planned'), ('active', 'Active'),
         ('done', 'Done'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)
    odometer_start = fields.Float(string='Odometer Start', copy=False)
    odometer_end = fields.Float(string='Odometer End', copy=False)
    distance = fields.Float(compute='_compute_distance', string='Distance')
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)
    notes = fields.Text()

    @api.depends('odometer_start', 'odometer_end')
    def _compute_distance(self):
        for rec in self:
            rec.distance = rec.odometer_end - rec.odometer_start if rec.odometer_end else 0.0

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_end <= rec.date_start:
                raise ValidationError(_("The end must be after the start."))

    @api.constrains('vehicle_id', 'driver_id', 'date_start', 'date_end', 'state')
    def _check_overlap(self):
        for rec in self.filtered(lambda r: r.state in ('planned', 'active')):
            for fname, label in (('vehicle_id', _("vehicle")), ('driver_id', _("driver"))):
                domain = [
                    ('id', '!=', rec.id),
                    ('state', 'in', ('planned', 'active')),
                    (fname, '=', rec[fname].id),
                ]
                if rec.date_end:
                    domain.append(('date_start', '<', rec.date_end))
                domain += ['|', ('date_end', '=', False), ('date_end', '>', rec.date_start)]
                other = self.search(domain, limit=1)
                if other:
                    raise ValidationError(_(
                        "This %(label)s is already assigned in the same period (%(ref)s).",
                        label=label, ref=other.name))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.vehicle.assignment') or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Business rules
    # ------------------------------------------------------------------
    def _check_assignable(self):
        self.ensure_one()
        vehicle, driver = self.vehicle_id, self.driver_id
        if vehicle.nexora_availability in ('out_of_service', 'maintenance'):
            raise UserError(_(
                "Vehicle %(vehicle)s is not operational (%(state)s).",
                vehicle=vehicle.display_name,
                state=dict(vehicle._fields['nexora_availability'].selection)[vehicle.nexora_availability]))
        start = self.date_start.date()
        expired = [
            vehicle._fields[f].string for f in vehicle._NEXORA_DOC_FIELDS
            if vehicle[f] and vehicle[f] < start
        ]
        if expired:
            raise UserError(_(
                "Vehicle %(vehicle)s has expired documents: %(docs)s.",
                vehicle=vehicle.display_name, docs=", ".join(expired)))
        if not driver.is_driver:
            raise UserError(_("%s is not registered as a driver.", driver.name))
        if driver.license_expiry and driver.license_expiry < start:
            raise UserError(_(
                "The license of %(driver)s expires before the assignment start.",
                driver=driver.name))

    def _sync_vehicle_driver(self):
        for rec in self:
            partner = rec.driver_id.work_contact_id
            if partner and rec.vehicle_id.driver_id != partner:
                rec.vehicle_id.sudo().driver_id = partner

    def _release_vehicle_driver(self):
        for rec in self:
            partner = rec.driver_id.work_contact_id
            if partner and rec.vehicle_id.driver_id == partner:
                rec.vehicle_id.sudo().driver_id = False

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self.filtered(lambda r: r.state == 'draft'):
            rec._check_assignable()
            rec.state = 'planned'

    def action_start(self):
        for rec in self.filtered(lambda r: r.state == 'planned'):
            rec._check_assignable()
            rec.write({
                'state': 'active',
                'odometer_start': rec.vehicle_id.odometer,
            })
            rec._sync_vehicle_driver()

    def action_finish(self):
        now = fields.Datetime.now()
        for rec in self.filtered(lambda r: r.state == 'active'):
            if rec.odometer_end and rec.odometer_end < rec.odometer_start:
                raise UserError(_("The ending odometer cannot be lower than the starting one."))
            vals = {'state': 'done'}
            if not rec.date_end or rec.date_end > now:
                vals['date_end'] = now
            rec.write(vals)
            if rec.odometer_end:
                self.env['fleet.vehicle.odometer'].sudo().create({
                    'vehicle_id': rec.vehicle_id.id,
                    'value': rec.odometer_end,
                    'date': fields.Date.context_today(rec),
                })
            rec._release_vehicle_driver()

    def action_cancel(self):
        for rec in self.filtered(lambda r: r.state in ('draft', 'planned', 'active')):
            was_active = rec.state == 'active'
            rec.state = 'cancelled'
            if was_active:
                rec._release_vehicle_driver()

    def action_draft(self):
        self.filtered(lambda r: r.state == 'cancelled').write({'state': 'draft'})