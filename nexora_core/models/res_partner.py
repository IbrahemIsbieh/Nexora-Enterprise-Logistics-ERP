from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_nexora_customer = fields.Boolean(string='Logistics Customer')
    is_nexora_vendor = fields.Boolean(string='Logistics Vendor')
    nexora_code = fields.Char(string='Nexora Code', copy=False, readonly=True)
    nexora_contract_ids = fields.One2many('nexora.contract', 'partner_id', string='Nexora Contracts')
    nexora_contract_count = fields.Integer(compute='_compute_nexora_contract_count')

    _nexora_code_uniq = models.Constraint(
        'unique(nexora_code)',
        'Nexora code must be unique.',
    )

    def _compute_nexora_contract_count(self):
        data = self.env['nexora.contract']._read_group(
            [('partner_id', 'in', self.ids)], ['partner_id'], ['__count'])
        counts = {partner.id: count for partner, count in data}
        for partner in self:
            partner.nexora_contract_count = counts.get(partner.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (vals.get('is_nexora_customer') or vals.get('is_nexora_vendor')) \
                    and not vals.get('nexora_code'):
                vals['nexora_code'] = self.env['ir.sequence'].next_by_code('nexora.partner')
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_nexora_customer') or vals.get('is_nexora_vendor'):
            for partner in self.filtered(lambda p: not p.nexora_code):
                partner.nexora_code = self.env['ir.sequence'].next_by_code('nexora.partner')
        return res

    def action_view_nexora_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Contracts',
            'res_model': 'nexora.contract',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }