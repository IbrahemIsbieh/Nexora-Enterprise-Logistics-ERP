from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nexora_service_type = fields.Selection(
        [
            ('transport', 'Transportation'),
            ('warehousing', 'Warehousing'),
            ('handling', 'Handling'),
            ('customs', 'Customs Clearance'),
            ('packaging', 'Packaging'),
            ('other', 'Other'),
        ],
        string='Logistics Service Type',
    )
    nexora_temperature_class = fields.Selection(
        [('ambient', 'Ambient'), ('chilled', 'Chilled'), ('frozen', 'Frozen')],
        string='Temperature Class',
        default='ambient',
    )
    nexora_hazardous = fields.Boolean(string='Hazardous Goods')