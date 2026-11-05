from datetime import timedelta

from odoo import api, fields, models


class NexoraRequestTenderWizard(models.TransientModel):
    _name = 'nexora.request.tender.wizard'
    _description = 'Request Quotations'

    request_id = fields.Many2one('nexora.purchase.request', required=True)
    vendor_ids = fields.Many2many(
        'res.partner', string='Vendors', required=True,
        domain=[('is_nexora_vendor', '=', True)])
    deadline = fields.Date(
        default=lambda self: fields.Date.context_today(self) + timedelta(days=7))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        request = self.env['nexora.purchase.request'].browse(res.get('request_id'))
        if request and 'vendor_ids' in fields_list:
            res['vendor_ids'] = [(6, 0, request.line_ids.vendor_id.ids)]
        return res

    def action_create(self):
        self.ensure_one()
        tender = self.env['nexora.rfq.tender']._create_from_request(
            self.request_id, self.vendor_ids, self.deadline)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nexora.rfq.tender',
            'res_id': tender.id,
            'view_mode': 'form',
        }