from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    nexora_vendor_score = fields.Float(string='Vendor Score', readonly=True, copy=False, digits=(16, 1))
    nexora_vendor_rating = fields.Selection(
        [('a', 'A - Excellent'), ('b', 'B - Good'), ('c', 'C - Fair'), ('d', 'D - Poor')],
        string='Vendor Rating', readonly=True, copy=False)