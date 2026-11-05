from odoo import _, fields, models


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    nexora_plan_ids = fields.One2many('nexora.maintenance.plan', 'vehicle_id')
    nexora_maintenance_order_ids = fields.One2many('nexora.maintenance.order', 'vehicle_id')
    nexora_plan_count = fields.Integer(compute='_compute_nexora_maintenance_stats')
    nexora_maintenance_order_count = fields.Integer(compute='_compute_nexora_maintenance_stats')
    nexora_open_order_count = fields.Integer(compute='_compute_nexora_maintenance_stats')
    nexora_maintenance_cost = fields.Float(
        string='Maintenance Cost', compute='_compute_nexora_maintenance_stats',
        help="Sum of completed orders (no currency conversion).")
    nexora_maintenance_status = fields.Selection(
        [('ok', 'Up to date'), ('due_soon', 'Due Soon'), ('overdue', 'Overdue')],
        string='Maintenance Status', compute='_compute_nexora_maintenance_status')

    def _compute_nexora_maintenance_stats(self):
        Plan = self.env['nexora.maintenance.plan']
        Order = self.env['nexora.maintenance.order']
        plans = {v.id: c for v, c in Plan._read_group(
            [('vehicle_id', 'in', self.ids)], ['vehicle_id'], ['__count'])}
        done = {v.id: (c, cost) for v, c, cost in Order._read_group(
            [('vehicle_id', 'in', self.ids), ('state', '=', 'done')],
            ['vehicle_id'], ['__count', 'total_cost:sum'])}
        open_ = {v.id: c for v, c in Order._read_group(
            [('vehicle_id', 'in', self.ids),
             ('state', 'in', ('draft', 'scheduled', 'in_progress'))],
            ['vehicle_id'], ['__count'])}
        for vehicle in self:
            count_done, cost = done.get(vehicle.id, (0, 0.0))
            vehicle.nexora_plan_count = plans.get(vehicle.id, 0)
            vehicle.nexora_maintenance_order_count = count_done + open_.get(vehicle.id, 0)
            vehicle.nexora_open_order_count = open_.get(vehicle.id, 0)
            vehicle.nexora_maintenance_cost = cost

    def _compute_nexora_maintenance_status(self):
        rank = {'ok': 0, 'due_soon': 1, 'overdue': 2}
        for vehicle in self:
            states = vehicle.nexora_plan_ids.filtered('active').mapped('due_state')
            vehicle.nexora_maintenance_status = max(states, key=rank.get) if states else False

    def action_view_nexora_maintenance_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Orders'),
            'res_model': 'nexora.maintenance.order',
            'view_mode': 'list,form,calendar,graph,pivot',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_nexora_maintenance_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Plans'),
            'res_model': 'nexora.maintenance.plan',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }