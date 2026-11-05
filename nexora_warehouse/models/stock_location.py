from odoo import fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    nexora_location_type = fields.Selection(
        [
            ('receiving', 'Receiving'),
            ('storage', 'Storage'),
            ('picking', 'Picking'),
            ('packing', 'Packing'),
            ('shipping', 'Shipping'),
            ('quarantine', 'Quarantine'),
            ('returns', 'Returns'),
            ('other', 'Other'),
        ],
        string='Functional Type',
    )
    nexora_temperature_class = fields.Selection(
        [('ambient', 'Ambient'), ('chilled', 'Chilled'), ('frozen', 'Frozen')],
        string='Temperature Class',
        help="Leave empty to accept any product.",
    )
    nexora_allow_hazardous = fields.Boolean(string='Allow Hazardous Goods')
    nexora_enforce_rules = fields.Boolean(
        string='Enforce Capacity & Storage Rules',
        help="When enabled, stock moves that exceed the capacity or violate "
             "temperature / hazardous rules are blocked.",
    )
    nexora_max_weight = fields.Float(string='Max Weight (kg)', help="0 = unlimited")
    nexora_max_volume = fields.Float(string='Max Volume (m³)', help="0 = unlimited")
    nexora_used_weight = fields.Float(
        string='Used Weight (kg)', compute='_compute_nexora_usage')
    nexora_used_volume = fields.Float(
        string='Used Volume (m³)', compute='_compute_nexora_usage')
    nexora_occupancy = fields.Float(
        string='Occupancy (%)', compute='_compute_nexora_usage')

    def _nexora_load_by_location(self):
        """Return {location_id: (weight, volume)} computed from current quants."""
        if not self.ids:
            return {}
        result = {loc_id: [0.0, 0.0] for loc_id in self.ids}
        groups = self.env['stock.quant'].sudo()._read_group(
            [('location_id', 'in', self.ids), ('quantity', '>', 0)],
            ['location_id', 'product_id'],
            ['quantity:sum'],
        )
        for location, product, qty in groups:
            result[location.id][0] += qty * product.weight
            result[location.id][1] += qty * product.volume
        return {loc_id: tuple(vals) for loc_id, vals in result.items()}

    def _compute_nexora_usage(self):
        load = self._nexora_load_by_location()
        for loc in self:
            weight, volume = load.get(loc.id, (0.0, 0.0))
            loc.nexora_used_weight = weight
            loc.nexora_used_volume = volume
            ratios = []
            if loc.nexora_max_weight:
                ratios.append(weight / loc.nexora_max_weight)
            if loc.nexora_max_volume:
                ratios.append(volume / loc.nexora_max_volume)
            loc.nexora_occupancy = max(ratios) * 100 if ratios else 0.0