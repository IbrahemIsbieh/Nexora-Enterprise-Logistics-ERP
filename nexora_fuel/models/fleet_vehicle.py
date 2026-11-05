from odoo import _, fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    nexora_target_consumption = fields.Float(
        string='Target Consumption (per 100 km)',
        help="Reference value used to detect abnormal consumption. "
             "If empty, the vehicle's own average is used (after 3 measurements).")
    nexora_avg_consumption = fields.Float(
        string='Avg. Consumption (per 100 km)', digits=(16, 2),
        compute='_compute_nexora_fuel_stats')
    nexora_fuel_log_count = fields.Integer(compute='_compute_nexora_fuel_stats')
    nexora_expense_count = fields.Integer(compute='_compute_nexora_fuel_stats')
    nexora_total_expense = fields.Float(
        string='Total Expenses', compute='_compute_nexora_fuel_stats',
        help="Sum of confirmed expenses (no currency conversion).")
    nexora_fuel_card_ids = fields.One2many('nexora.fuel.card', 'vehicle_id', string='Fuel Cards')

    def _compute_nexora_fuel_stats(self):
        Log = self.env['nexora.fuel.log']
        Expense = self.env['nexora.vehicle.expense']
        avg = {v.id: a for v, a in Log._read_group(
            [('vehicle_id', 'in', self.ids), ('state', '=', 'confirmed'), ('consumption', '>', 0)],
            ['vehicle_id'], ['consumption:avg'])}
        logs = {v.id: c for v, c in Log._read_group(
            [('vehicle_id', 'in', self.ids), ('state', '=', 'confirmed')],
            ['vehicle_id'], ['__count'])}
        exp = {v.id: (c, s) for v, c, s in Expense._read_group(
            [('vehicle_id', 'in', self.ids), ('state', '=', 'confirmed')],
            ['vehicle_id'], ['__count', 'amount:sum'])}
        for vehicle in self:
            vehicle.nexora_avg_consumption = avg.get(vehicle.id, 0.0)
            vehicle.nexora_fuel_log_count = logs.get(vehicle.id, 0)
            count, total = exp.get(vehicle.id, (0, 0.0))
            vehicle.nexora_expense_count = count
            vehicle.nexora_total_expense = total

    def action_view_nexora_fuel_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fuel Logs'),
            'res_model': 'nexora.fuel.log',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_nexora_expenses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Expenses'),
            'res_model': 'nexora.vehicle.expense',
            'view_mode': 'list,form,graph,pivot',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }