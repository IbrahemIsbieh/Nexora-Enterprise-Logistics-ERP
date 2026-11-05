from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


def get_portal_responsible(env):
    """Default responsible for portal requests and tickets (setting, else the admin)."""
    value = env['ir.config_parameter'].sudo().get_param('nexora_portal.responsible_id')
    user = env['res.users'].sudo().browse(int(value)).exists() if value else env['res.users']
    return user or env.ref('base.user_admin')


class NexoraCustomerTicket(models.Model):
    _name = 'nexora.customer.ticket'
    _description = 'Customer Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    subject = fields.Char(required=True, tracking=True)
    ticket_type = fields.Selection(
        [('complaint', 'Complaint'), ('service', 'Service Request'), ('inquiry', 'Inquiry')],
        required=True, default='complaint', tracking=True)
    description = fields.Text()
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True, index=True,
        domain="[('is_nexora_customer', '=', True)]")
    shipment_id = fields.Many2one(
        'nexora.shipment', string='Shipment', tracking=True,
        domain="[('partner_id', '=', partner_id)]")
    order_id = fields.Many2one(related='shipment_id.order_id', store=True, string='Transport Order')
    priority = fields.Selection(
        [('low', 'Low'), ('normal', 'Normal'), ('high', 'High')], default='normal', tracking=True)
    state = fields.Selection(
        [('new', 'New'), ('in_progress', 'In Progress'), ('resolved', 'Resolved'),
         ('closed', 'Closed')],
        default='new', tracking=True, copy=False, index=True)
    source = fields.Selection(
        [('internal', 'Internal'), ('portal', 'Customer Portal')],
        default='internal', readonly=True, copy=False)
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', tracking=True,
        default=lambda self: get_portal_responsible(self.env))
    resolution = fields.Text(copy=False)
    date_resolved = fields.Datetime(readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    def _compute_access_url(self):
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/tickets/%s' % ticket.id

    @api.constrains('partner_id', 'shipment_id')
    def _check_shipment_partner(self):
        for ticket in self.filtered('shipment_id'):
            if ticket.shipment_id.partner_id.commercial_partner_id != ticket.partner_id.commercial_partner_id:
                raise ValidationError(_("The shipment does not belong to this customer."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.customer.ticket') or 'New'
        tickets = super().create(vals_list)
        for ticket in tickets:
            ticket.message_subscribe(partner_ids=[ticket.partner_id.id])
            if ticket.source == 'portal' and ticket.responsible_id:
                ticket.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_("New customer ticket"),
                    user_id=ticket.responsible_id.id,
                )
        return tickets

    def action_start(self):
        self.filtered(lambda t: t.state == 'new').write({'state': 'in_progress'})

    def action_resolve(self):
        for ticket in self.filtered(lambda t: t.state in ('new', 'in_progress')):
            if not ticket.resolution:
                raise UserError(_("Write the resolution first: it is sent to the customer."))
            ticket.write({'state': 'resolved', 'date_resolved': fields.Datetime.now()})
            ticket.message_post(
                body=ticket.resolution, message_type='comment',
                subtype_xmlid='mail.mt_comment', partner_ids=[ticket.partner_id.id])

    def action_close(self):
        self.filtered(lambda t: t.state == 'resolved').write({'state': 'closed'})

    def action_reopen(self):
        self.filtered(lambda t: t.state in ('resolved', 'closed')).write(
            {'state': 'in_progress', 'date_resolved': False})