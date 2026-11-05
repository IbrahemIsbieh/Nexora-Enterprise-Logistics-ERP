from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class NexoraRfqTender(models.Model):
    _name = 'nexora.rfq.tender'
    _description = 'RFQ Tender (Quotation Comparison)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    request_id = fields.Many2one(
        'nexora.purchase.request', required=True, ondelete='restrict', tracking=True, index=True)
    deadline = fields.Date(string='Quotation Deadline', tracking=True)
    state = fields.Selection(
        [('open', 'Open'), ('awarded', 'Awarded'), ('cancelled', 'Cancelled')],
        default='open', tracking=True, copy=False, index=True)
    quote_ids = fields.One2many('purchase.order', 'tender_id', string='Quotations')
    quote_count = fields.Integer(compute='_compute_quote_count')
    best_quote_id = fields.Many2one('purchase.order', compute='_compute_best_quote')
    winner_id = fields.Many2one('purchase.order', string='Awarded Order', readonly=True, copy=False)
    notes = fields.Text()
    company_id = fields.Many2one(related='request_id.company_id', store=True)

    @api.depends('quote_ids')
    def _compute_quote_count(self):
        for rec in self:
            rec.quote_count = len(rec.quote_ids)

    @api.depends('quote_ids.amount_total', 'quote_ids.state')
    def _compute_best_quote(self):
        for rec in self:
            quotes = rec.quote_ids.filtered(lambda q: q.state != 'cancel' and q.amount_total > 0)
            rec.best_quote_id = min(quotes, key=lambda q: q.amount_total) if quotes else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.rfq.tender') or 'New'
        return super().create(vals_list)

    @api.model
    def _create_from_request(self, request, vendors, deadline=None):
        if request.state not in ('approved', 'rfq'):
            raise UserError(_("The purchase request must be approved first."))
        if not vendors:
            raise UserError(_("Select at least one vendor."))
        tender = self.create({'request_id': request.id, 'deadline': deadline})
        for vendor in vendors:
            line_cmds = []
            for line in request.line_ids:
                vals = {
                    'product_id': line.product_id.id,
                    'name': line.name or line.product_id.display_name,
                    'product_qty': line.quantity,
                }
                if request.date_required:
                    vals['date_planned'] = fields.Datetime.to_datetime(request.date_required)
                line_cmds.append(Command.create(vals))
            self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'origin': request.name,
                'request_id': request.id,
                'tender_id': tender.id,
                'order_line': line_cmds,
            })
        if request.state == 'approved':
            request.state = 'rfq'
        tender.message_post(body=_(
            "Quotations requested from: %s", ", ".join(vendors.mapped('name'))))
        return tender

    def _award(self, order):
        self.ensure_one()
        if self.state != 'open':
            return
        for other in (self.quote_ids - order).filtered(
                lambda o: o.state in ('draft', 'sent', 'to approve')):
            other.button_cancel()
        self.write({'state': 'awarded', 'winner_id': order.id})
        self.request_id.state = 'ordered'
        self.message_post(body=_("Awarded to %(vendor)s (%(order)s).",
                                 vendor=order.partner_id.display_name, order=order.name))

    def action_cancel(self):
        for rec in self.filtered(lambda t: t.state == 'open'):
            for quote in rec.quote_ids.filtered(lambda o: o.state in ('draft', 'sent', 'to approve')):
                quote.button_cancel()
            rec.state = 'cancelled'
            if not rec.request_id.tender_ids.filtered(lambda t: t.state == 'open'):
                rec.request_id.state = 'approved'

    def action_view_quotes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quotation Comparison'),
            'res_model': 'purchase.order',
            'views': [(self.env.ref('nexora_procurement.view_nexora_quote_compare_list').id, 'list'),
                      (False, 'form')],
            'domain': [('tender_id', '=', self.id)],
        }

    def action_view_matrix(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Price Matrix'),
            'res_model': 'purchase.order.line',
            'views': [(self.env.ref('nexora_procurement.view_nexora_quote_matrix_pivot').id, 'pivot')],
            'domain': [('nexora_tender_id', '=', self.id), ('display_type', '=', False)],
        }