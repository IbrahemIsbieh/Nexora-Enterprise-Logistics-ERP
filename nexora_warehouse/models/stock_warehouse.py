from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    nexora_warehouse_type = fields.Selection(
        [
            ('central', 'Central Warehouse'),
            ('regional', 'Regional Warehouse'),
            ('crossdock', 'Cross-Dock'),
            ('cold', 'Cold Storage'),
            ('bonded', 'Bonded Warehouse'),
        ],
        string='Warehouse Type',
        default='regional',
    )
    nexora_manager_id = fields.Many2one('hr.employee', string='Warehouse Manager')
    nexora_cost_center_id = fields.Many2one('nexora.cost.center', string='Cost Center')
    nexora_location_count = fields.Integer(compute='_compute_nexora_capacity')
    nexora_total_max_volume = fields.Float(
        string='Total Capacity (m³)', compute='_compute_nexora_capacity')
    nexora_total_used_volume = fields.Float(
        string='Used Volume (m³)', compute='_compute_nexora_capacity')
    nexora_occupancy = fields.Float(
        string='Occupancy (%)', compute='_compute_nexora_capacity')

    def _compute_nexora_capacity(self):
        Location = self.env['stock.location'].sudo()
        for wh in self:
            locations = Location.search([
                ('warehouse_id', '=', wh.id),
                ('usage', '=', 'internal'),
            ]) if wh.id else Location
            load = locations._nexora_load_by_location()
            max_volume = sum(locations.mapped('nexora_max_volume'))
            used_volume = sum(volume for _weight, volume in load.values())
            wh.nexora_location_count = len(locations)
            wh.nexora_total_max_volume = max_volume
            wh.nexora_total_used_volume = used_volume
            wh.nexora_occupancy = (used_volume / max_volume * 100) if max_volume else 0.0

    def action_view_nexora_locations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Locations & Capacity',
            'res_model': 'stock.location',
            'view_mode': 'list,form',
            'views': [(self.env.ref('nexora_warehouse.view_nexora_location_capacity_list').id, 'list'),
                      (False, 'form')],
            'domain': [('warehouse_id', '=', self.id), ('usage', '=', 'internal')],
        }