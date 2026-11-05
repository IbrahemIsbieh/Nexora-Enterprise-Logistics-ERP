from odoo import _, api, fields, models


class NexoraShipment(models.Model):
    _name = 'nexora.shipment'
    _inherit = ['nexora.shipment', 'portal.mixin']

    document_ids = fields.One2many('nexora.shipment.document', 'shipment_id', string='Documents')
    ticket_ids = fields.One2many('nexora.customer.ticket', 'shipment_id')
    ticket_count = fields.Integer(compute='_compute_ticket_count')

    def _compute_access_url(self):
        super()._compute_access_url()
        for shipment in self:
            shipment.access_url = '/my/shipments/%s' % shipment.id

    @api.depends('ticket_ids')
    def _compute_ticket_count(self):
        for shipment in self:
            shipment.ticket_count = len(shipment.ticket_ids)

    def action_view_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tickets'),
            'res_model': 'nexora.customer.ticket',
            'view_mode': 'list,form',
            'domain': [('shipment_id', '=', self.id)],
            'context': {'default_shipment_id': self.id, 'default_partner_id': self.partner_id.id},
        }


class NexoraShipmentDocument(models.Model):
    _name = 'nexora.shipment.document'
    _description = 'Shipment Document'
    _order = 'id desc'

    shipment_id = fields.Many2one('nexora.shipment', required=True, ondelete='cascade', index=True)
    name = fields.Char(required=True)
    doc_type = fields.Selection(
        [
            ('bol', 'Bill of Lading'),
            ('customs', 'Customs Document'),
            ('delivery_note', 'Delivery Note'),
            ('certificate', 'Certificate'),
            ('other', 'Other'),
        ],
        required=True, default='other')
    file = fields.Binary(string='File', attachment=True, required=True)
    filename = fields.Char()
    visible_to_customer = fields.Boolean(default=True)
    uploaded_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)