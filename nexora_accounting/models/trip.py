from odoo import _, fields, models
from odoo.exceptions import UserError

ACCOUNTING_GROUP = 'nexora_accounting.group_nexora_accounting_user'
OTHER_EXPENSE_TYPES = ('toll', 'parking', 'fine', 'cleaning', 'other')


class NexoraTransportTrip(models.Model):
    _inherit = 'nexora.transport.trip'

    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    fuel_cost = fields.Monetary(readonly=True, copy=False)
    maintenance_cost = fields.Monetary(readonly=True, copy=False)
    driver_cost = fields.Monetary(readonly=True, copy=False)
    other_cost = fields.Monetary(string='Tolls & Other', readonly=True, copy=False)
    overhead_cost = fields.Monetary(readonly=True, copy=False)
    total_cost = fields.Monetary(readonly=True, copy=False)

    def _icp_float(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(f'nexora_accounting.{key}')
        return float(value) if value not in (None, False, '') else default

    def _compute_costs(self):
        driver_rate = self._icp_float('driver_cost_per_hour', 5.0)
        maintenance_rate = self._icp_float('maintenance_per_km', 0.08)
        fuel_fallback = self._icp_float('fuel_fallback_per_km', 0.25)
        overhead_pct = self._icp_float('overhead_pct', 10.0)
        Log = self.env['nexora.fuel.log'].sudo()
        Expense = self.env['nexora.vehicle.expense'].sudo()
        for trip in self:
            distance = trip.distance
            logs = Log.search([
                ('vehicle_id', '=', trip.vehicle_id.id),
                ('state', '=', 'confirmed'),
                ('cost_per_km', '>', 0),
            ])
            fuel_per_km = sum(logs.mapped('cost_per_km')) / len(logs) if logs else fuel_fallback

            planned_hours = (trip.planned_end - trip.planned_start).total_seconds() / 3600.0
            actual_hours = 0.0
            if trip.actual_start:
                end = trip.actual_end or fields.Datetime.now()
                actual_hours = (end - trip.actual_start).total_seconds() / 3600.0
            # The driver is paid at least the planned shift.
            driver_cost = max(planned_hours, actual_hours) * driver_rate

            start_date = (trip.actual_start or trip.planned_start).date()
            end_date = (trip.actual_end or trip.planned_end).date()
            others = Expense.search([
                ('vehicle_id', '=', trip.vehicle_id.id),
                ('state', '=', 'confirmed'),
                ('expense_type', 'in', OTHER_EXPENSE_TYPES),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ])
            fuel = distance * fuel_per_km
            maintenance = distance * maintenance_rate
            other = sum(others.mapped('amount'))
            overhead = (fuel + maintenance + driver_cost + other) * overhead_pct / 100.0
            trip.write({
                'fuel_cost': fuel,
                'maintenance_cost': maintenance,
                'driver_cost': driver_cost,
                'other_cost': other,
                'overhead_cost': overhead,
                'total_cost': fuel + maintenance + driver_cost + other + overhead,
            })
            trip._allocate_costs()

    def _allocate_costs(self):
        basis = self.env['ir.config_parameter'].sudo().get_param(
            'nexora_accounting.allocation_basis') or 'weight'
        for trip in self:
            shipments = trip.shipment_ids.filtered(lambda s: s.state in ('delivered', 'failed'))
            if not shipments:
                continue
            if basis == 'weight':
                keys = {s.id: s.total_weight for s in shipments}
            elif basis == 'volume':
                keys = {s.id: s.total_volume for s in shipments}
            else:
                keys = {s.id: 1.0 for s in shipments}
            total = sum(keys.values())
            if not total:
                keys = {s.id: 1.0 for s in shipments}
                total = float(len(shipments))
            for shipment in shipments:
                shipment.allocated_cost = trip.total_cost * keys[shipment.id] / total

    def _finalize_costs(self):
        self.ensure_one()
        shipments = self.shipment_ids.filtered(lambda s: s.state in ('delivered', 'failed'))
        shipments.filtered(lambda s: not s.distance_km).write({'distance_km': self.distance})
        to_price = shipments.filtered(
            lambda s: s.state == 'delivered' and not s._is_invoiced()
            and (not s.freight_amount or s.freight_rate_id.basis == 'per_km'))
        to_price._auto_freight()
        self._compute_costs()

    def action_done(self):
        pending = self.filtered(lambda t: t.state == 'in_progress')
        res = super().action_done()
        for trip in pending.filtered(lambda t: t.state == 'done'):
            trip._finalize_costs()
        return res

    def action_compute_costs(self):
        if not self.env.user.has_group(ACCOUNTING_GROUP):
            raise UserError(_("You need Nexora Accounting access rights for this operation."))
        done = self.filtered(lambda t: t.state == 'done')
        if not done:
            raise UserError(_("Costs can only be computed for completed trips."))
        for trip in done:
            trip._finalize_costs()