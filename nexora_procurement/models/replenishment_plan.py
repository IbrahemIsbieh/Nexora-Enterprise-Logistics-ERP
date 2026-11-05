from odoo import Command, _, fields, models
from odoo.exceptions import UserError


class NexoraReplenishmentPlan(models.Model):
    _inherit = 'nexora.replenishment.plan'

    purchase_request_id = fields.Many2one(
        'nexora.purchase.request', string='Purchase Request', readonly=True, copy=False)

    def action_create_purchase_request(self):
        self.ensure_one()
        if self.state not in ('approved', 'applied'):
            raise UserError(_("Approve the plan first."))
        lines = self.line_ids.filtered(lambda l: l.approved_qty > 0)
        if not lines:
            raise UserError(_("The plan has no approved quantities."))
        urgent = any(l.risk_level in ('stockout', 'critical') for l in lines)
        request = self.env['nexora.purchase.request'].create({
            'warehouse_id': self.warehouse_id.id,
            'cost_center_id': self.warehouse_id.nexora_cost_center_id.id,
            'priority': 'urgent' if urgent else 'normal',
            'reason': _("Replenishment plan %s", self.name),
            'line_ids': [Command.create({
                'product_id': l.product_id.id,
                'name': l.product_id.display_name,
                'quantity': l.approved_qty,
                'uom_id': l.product_id.uom_id.id,
                'estimated_price': l.product_id.standard_price,
                'vendor_id': l.vendor_id.id,
            }) for l in lines],
        })
        self.purchase_request_id = request
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nexora.purchase.request',
            'res_id': request.id,
            'view_mode': 'form',
        }