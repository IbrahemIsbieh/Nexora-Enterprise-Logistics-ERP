from odoo import models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.request_id.cost_center_id:
            vals['nexora_cost_center_id'] = self.request_id.cost_center_id.id
        return vals