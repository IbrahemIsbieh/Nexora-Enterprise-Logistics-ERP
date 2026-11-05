from odoo import _, fields, models, api
from odoo.exceptions import ValidationError


class NexoraFreightRate(models.Model):
    _name = 'nexora.freight.rate'
    _description = 'Freight Rate'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    product_id = fields.Many2one(
        'product.product', string='Service Product', required=True,
        domain=[('type', '=', 'service')],
        help="Product invoiced for this rate. A contract line with the same product "
             "overrides the unit price.")
    partner_id = fields.Many2one(
        'res.partner', string='Customer', domain=[('is_nexora_customer', '=', True)],
        help="Leave empty for a generic rate. Customer rates win over generic ones.")
    basis = fields.Selection(
        [('fixed', 'Fixed per Shipment'), ('per_kg', 'Per kg'),
         ('per_m3', 'Per m³'), ('per_km', 'Per km')],
        required=True, default='fixed')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    price = fields.Monetary(string='Unit Price', required=True)
    minimum_charge = fields.Monetary()
    chilled_pct = fields.Float(string='Chilled Surcharge (%)')
    frozen_pct = fields.Float(string='Frozen Surcharge (%)')
    hazmat_pct = fields.Float(string='Hazmat Surcharge (%)')
    urgent_pct = fields.Float(string='Urgent Surcharge (%)')
    date_from = fields.Date()
    date_to = fields.Date()

    @api.constrains('price', 'minimum_charge', 'chilled_pct', 'frozen_pct',
                    'hazmat_pct', 'urgent_pct')
    def _check_values(self):
        for rate in self:
            if min(rate.price, rate.minimum_charge, rate.chilled_pct, rate.frozen_pct,
                   rate.hazmat_pct, rate.urgent_pct) < 0:
                raise ValidationError(_("Prices and surcharges cannot be negative."))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rate in self:
            if rate.date_from and rate.date_to and rate.date_to < rate.date_from:
                raise ValidationError(_("The end date cannot be before the start date."))