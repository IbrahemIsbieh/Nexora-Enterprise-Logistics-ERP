from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class NexoraVehicleExpense(models.Model):
    _name = 'nexora.vehicle.expense'
    _description = 'Vehicle Expense'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, tracking=True, index=True)
    driver_id = fields.Many2one('hr.employee', string='Driver', domain=[('is_driver', '=', True)])
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True, index=True)
    expense_type = fields.Selection(
        [
            ('fuel', 'Fuel'),
            ('toll', 'Tolls'),
            ('parking', 'Parking'),
            ('fine', 'Traffic Fine'),
            ('tires', 'Tires'),
            ('cleaning', 'Cleaning'),
            ('insurance', 'Insurance'),
            ('registration', 'Registration / Licensing'),
            ('repair', 'Repair / Maintenance'),
            ('other', 'Other'),
        ],
        required=True, default='other', tracking=True, index=True)
    description = fields.Char()
    partner_id = fields.Many2one('res.partner', string='Vendor')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(currency_field='currency_id', required=True, tracking=True)
    cost_center_id = fields.Many2one(
        'nexora.cost.center', string='Cost Center',
        compute='_compute_cost_center', store=True, readonly=False)
    fuel_log_id = fields.Many2one('nexora.fuel.log', string='Fuel Log', readonly=True,
                                  copy=False, ondelete='cascade')
    incident_id = fields.Many2one('nexora.vehicle.incident', string='Related Incident')
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False, index=True)
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True)
    notes = fields.Text()

    @api.depends('vehicle_id')
    def _compute_cost_center(self):
        for rec in self:
            rec.cost_center_id = rec.vehicle_id.nexora_cost_center_id

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_("The amount cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.vehicle.expense') or 'New'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        if self.filtered(lambda e: e.state == 'confirmed'):
            raise UserError(_("Confirmed expenses cannot be deleted. Cancel them first."))

    def _check_manual(self):
        if self.filtered('fuel_log_id'):
            raise UserError(_("Expenses generated from a fuel log are managed from the fuel log."))

    def action_confirm(self):
        self.filtered(lambda e: e.state == 'draft').write({'state': 'confirmed'})

    def action_cancel(self):
        self._check_manual()
        self.filtered(lambda e: e.state in ('draft', 'confirmed')).write({'state': 'cancelled'})

    def action_draft(self):
        self._check_manual()
        self.filtered(lambda e: e.state == 'cancelled').write({'state': 'draft'})