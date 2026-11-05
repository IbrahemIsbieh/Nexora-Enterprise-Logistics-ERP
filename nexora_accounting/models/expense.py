from odoo import Command, _, fields, models
from odoo.exceptions import UserError

ACCOUNTING_GROUP = 'nexora_accounting.group_nexora_accounting_user'


class NexoraVehicleExpense(models.Model):
    _inherit = 'nexora.vehicle.expense'

    bill_id = fields.Many2one(
        'account.move', string='Vendor Bill', readonly=True, copy=False, ondelete='set null')

    def action_cancel(self):
        if self.filtered('bill_id'):
            raise UserError(_("An expense linked to a vendor bill cannot be cancelled."))
        return super().action_cancel()

    def action_create_vendor_bill(self):
        if not self.env.user.has_group(ACCOUNTING_GROUP):
            raise UserError(_("You need Nexora Accounting access rights for this operation."))
        expenses = self.filtered(
            lambda e: e.state == 'confirmed' and not e.bill_id and e.partner_id and e.amount > 0)
        if not expenses:
            raise UserError(_(
                "Select confirmed expenses that have a vendor, an amount and no bill yet."))
        product = self.env.ref('nexora_accounting.product_vehicle_expense').product_variant_id
        groups = {}
        for expense in expenses:
            key = (expense.partner_id, expense.company_id, expense.cost_center_id,
                   expense.currency_id)
            groups.setdefault(key, self.browse())
            groups[key] |= expense

        moves = self.env['account.move']
        for (partner, company, cost_center, currency), group in groups.items():
            lines = [Command.create({
                'product_id': product.id,
                'name': " - ".join(filter(None, [
                    expense.name, expense.vehicle_id.display_name,
                    dict(expense._fields['expense_type'].selection)[expense.expense_type],
                    expense.description])),
                'quantity': 1.0,
                'price_unit': expense.amount,
            }) for expense in group]
            move = self.env['account.move'].with_company(company).create({
                'move_type': 'in_invoice',
                'partner_id': partner.id,
                'company_id': company.id,
                'currency_id': currency.id,
                'invoice_date': fields.Date.context_today(self),
                'invoice_origin': ", ".join(group.mapped('name')),
                'nexora_cost_center_id': cost_center.id,
                'invoice_line_ids': lines,
            })
            group.write({'bill_id': move.id})
            moves |= move

        action = {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bills'),
            'res_model': 'account.move',
            'context': {'default_move_type': 'in_invoice'},
        }
        if len(moves) == 1:
            action.update({'view_mode': 'form', 'res_id': moves.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)]})
        return action

    def action_view_bill(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.bill_id.id,
            'view_mode': 'form',
        }