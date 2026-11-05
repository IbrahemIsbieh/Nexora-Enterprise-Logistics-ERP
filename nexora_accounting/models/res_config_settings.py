from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_acc_driver_cost_per_hour = fields.Float(
        string='Driver Cost per Hour',
        config_parameter='nexora_accounting.driver_cost_per_hour', default=5.0)
    nexora_acc_maintenance_per_km = fields.Float(
        string='Maintenance Cost per km',
        config_parameter='nexora_accounting.maintenance_per_km', default=0.08)
    nexora_acc_fuel_fallback_per_km = fields.Float(
        string='Fallback Fuel Cost per km',
        config_parameter='nexora_accounting.fuel_fallback_per_km', default=0.25)
    nexora_acc_overhead_pct = fields.Float(
        string='Overhead (%)',
        config_parameter='nexora_accounting.overhead_pct', default=10.0)
    nexora_acc_allocation_basis = fields.Selection(
        [('weight', 'Weight'), ('volume', 'Volume'), ('equal', 'Equal Split')],
        string='Cost Allocation Basis',
        config_parameter='nexora_accounting.allocation_basis', default='weight')