from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NexoraVehicleIncident(models.Model):
    _name = 'nexora.vehicle.incident'
    _description = 'Vehicle Accident / Incident'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'incident_date desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    driver_id = fields.Many2one(
        'hr.employee', string='Driver', tracking=True, domain=[('is_driver', '=', True)])
    incident_date = fields.Datetime(string='Date & Time', required=True,
                                    default=fields.Datetime.now, tracking=True)
    incident_type = fields.Selection(
        [
            ('accident', 'Accident'),
            ('breakdown', 'Breakdown'),
            ('damage', 'Cargo / Vehicle Damage'),
            ('theft', 'Theft'),
            ('violation', 'Traffic Violation'),
            ('other', 'Other'),
        ],
        required=True, default='accident', tracking=True)
    severity = fields.Selection(
        [('minor', 'Minor'), ('moderate', 'Moderate'),
         ('major', 'Major'), ('total_loss', 'Total Loss')],
        required=True, default='minor', tracking=True)
    blocks_vehicle = fields.Boolean(
        string='Blocks Vehicle', compute='_compute_blocks_vehicle',
        store=True, readonly=False, tracking=True,
        help="While the incident is open, the vehicle is considered out of service.")
    location = fields.Char()
    description = fields.Text()
    injuries = fields.Boolean(string='Injuries Reported')
    police_report_no = fields.Char(string='Police Report No.')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    estimated_cost = fields.Monetary(currency_field='currency_id')
    actual_cost = fields.Monetary(currency_field='currency_id')
    insurance_claim = fields.Boolean(string='Insurance Claim')
    claim_reference = fields.Char()
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [('reported', 'Reported'), ('investigating', 'Investigating'),
         ('resolved', 'Resolved'), ('cancelled', 'Cancelled')],
        default='reported', tracking=True, copy=False, index=True)
    resolution_note = fields.Text()
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)

    @api.depends('severity')
    def _compute_blocks_vehicle(self):
        for rec in self:
            rec.blocks_vehicle = rec.severity in ('major', 'total_loss')

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id and not self.driver_id:
            self.driver_id = self.vehicle_id.nexora_current_driver_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.vehicle.incident') or 'New'
        records = super().create(vals_list)
        for rec in records.filtered('blocks_vehicle'):
            rec.vehicle_id.message_post(body=_(
                "Vehicle blocked by incident %(ref)s (%(severity)s).",
                ref=rec.name,
                severity=dict(rec._fields['severity'].selection)[rec.severity]))
        return records

    def action_investigate(self):
        self.filtered(lambda r: r.state == 'reported').write({'state': 'investigating'})

    def action_resolve(self):
        for rec in self.filtered(lambda r: r.state in ('reported', 'investigating')):
            if not rec.resolution_note:
                raise UserError(_("Add a resolution note before resolving the incident."))
            rec.state = 'resolved'
            if rec.blocks_vehicle:
                rec.vehicle_id.message_post(body=_("Incident %s resolved: vehicle released.", rec.name))

    def action_cancel(self):
        self.filtered(lambda r: r.state in ('reported', 'investigating')).write({'state': 'cancelled'})

    def action_reopen(self):
        self.filtered(lambda r: r.state in ('resolved', 'cancelled')).write({'state': 'investigating'})