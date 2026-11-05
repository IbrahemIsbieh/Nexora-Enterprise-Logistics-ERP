from odoo import _, api, models
from odoo.exceptions import ValidationError


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.constrains('quantity', 'location_id', 'product_id')
    def _check_nexora_location_rules(self):
        enforced = self.filtered(
            lambda q: q.location_id.usage == 'internal'
            and q.location_id.nexora_enforce_rules
            and q.quantity > 0
        )
        if not enforced:
            return

        # Storage rules: hazardous goods and temperature class
        for quant in enforced:
            loc, product = quant.location_id, quant.product_id
            if product.nexora_hazardous and not loc.nexora_allow_hazardous:
                raise ValidationError(_(
                    "Location %(loc)s does not accept hazardous goods (%(product)s).",
                    loc=loc.display_name, product=product.display_name))
            loc_class = loc.nexora_temperature_class
            prod_class = product.nexora_temperature_class
            if loc_class and prod_class and loc_class != prod_class:
                raise ValidationError(_(
                    "Temperature mismatch: %(product)s is %(pc)s but location %(loc)s is %(lc)s.",
                    product=product.display_name, pc=prod_class,
                    loc=loc.display_name, lc=loc_class))

        # Capacity rules: weight and volume
        locations = enforced.mapped('location_id')
        load = locations._nexora_load_by_location()
        for loc in locations:
            weight, volume = load.get(loc.id, (0.0, 0.0))
            if loc.nexora_max_weight and weight > loc.nexora_max_weight:
                raise ValidationError(_(
                    "Location %(loc)s exceeds its weight capacity: %(used).1f / %(max).1f kg.",
                    loc=loc.display_name, used=weight, max=loc.nexora_max_weight))
            if loc.nexora_max_volume and volume > loc.nexora_max_volume:
                raise ValidationError(_(
                    "Location %(loc)s exceeds its volume capacity: %(used).2f / %(max).2f m³.",
                    loc=loc.display_name, used=volume, max=loc.nexora_max_volume))