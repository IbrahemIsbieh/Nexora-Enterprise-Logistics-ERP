from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    nexora_cost_center_id = fields.Many2one(
        'nexora.cost.center', string='Cost Center', copy=False, index=True)
    nexora_shipment_ids = fields.One2many('nexora.shipment', 'invoice_id', string='Shipments')
    nexora_expense_ids = fields.One2many('nexora.vehicle.expense', 'bill_id', string='Expenses')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    nexora_shipment_id = fields.Many2one(
        'nexora.shipment', string='Shipment', copy=False, ondelete='set null')