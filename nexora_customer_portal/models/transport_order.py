from odoo import fields, models


class NexoraTransportOrder(models.Model):
    _name = 'nexora.transport.order'
    _inherit = ['nexora.transport.order', 'portal.mixin']

    portal_request = fields.Boolean(
        string='Portal Request', readonly=True, copy=False,
        help="Submitted by the customer from the portal.")

    def _compute_access_url(self):
        super()._compute_access_url()
        for order in self:
            order.access_url = '/my/transport-orders/%s' % order.id