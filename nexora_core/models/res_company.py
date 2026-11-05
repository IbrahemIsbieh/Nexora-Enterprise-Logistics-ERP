from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    nexora_branch_code = fields.Char(string='Branch Code', copy=False)
    nexora_branch_type = fields.Selection(
        [
            ('hq', 'Headquarters'),
            ('branch', 'Branch'),
            ('hub', 'Logistics Hub'),
            ('depot', 'Depot'),
        ],
        string='Branch Type',
        default='branch',
    )
    nexora_manager_id = fields.Many2one('hr.employee', string='Branch Manager')

    _nexora_branch_code_uniq = models.Constraint(
        'unique(nexora_branch_code)',
        'Branch code must be unique.',
    )