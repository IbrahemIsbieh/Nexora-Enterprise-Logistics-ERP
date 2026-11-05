from odoo import fields, models, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    request_id = fields.Many2one(
        'nexora.purchase.request', string='Purchase Request', copy=False, index=True)
    tender_id = fields.Many2one(
        'nexora.rfq.tender', string='Tender', copy=False, index=True)
    nexora_is_best_price = fields.Boolean(
        string='Best Price', compute='_compute_nexora_is_best_price')
    nexora_vendor_rating = fields.Selection(
        related='partner_id.nexora_vendor_rating', string='Vendor Rating')

    @api.depends('tender_id.best_quote_id')
    def _compute_nexora_is_best_price(self):
        for order in self:
            order.nexora_is_best_price = bool(
                order.tender_id and order.tender_id.best_quote_id == order)

    def _nexora_after_confirm(self):
        for order in self.filtered(lambda o: o.state in ('purchase', 'done')):
            if order.tender_id:
                order.tender_id._award(order)
            elif order.request_id and order.request_id.state in ('approved', 'rfq'):
                order.request_id.state = 'ordered'

    def button_confirm(self):
        res = super().button_confirm()
        self._nexora_after_confirm()
        return res

    def button_approve(self, force=False):
        res = super().button_approve(force=force)
        self._nexora_after_confirm()
        return res


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    nexora_tender_id = fields.Many2one(
        related='order_id.tender_id', store=True, string='Tender')