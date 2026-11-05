import math
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import NormalDist

from odoo import api, fields, models

RISK_SELECTION = [
    ('stockout', 'Stockout'),
    ('critical', 'Critical'),
    ('low', 'Below Reorder Point'),
    ('ok', 'Healthy'),
    ('overstock', 'Overstock'),
    ('dead', 'No Demand'),
]
RISK_ORDER = {'stockout': 1, 'critical': 2, 'low': 3, 'overstock': 4, 'dead': 5, 'ok': 6}


class NexoraInventoryAnalysis(models.Model):
    _name = 'nexora.inventory.analysis'
    _description = 'Inventory Analysis Snapshot'
    _order = 'risk_sequence, days_of_cover, id'

    product_id = fields.Many2one('product.product', required=True, ondelete='cascade', index=True)
    categ_id = fields.Many2one(related='product_id.categ_id', store=True, string='Product Category')
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')
    warehouse_id = fields.Many2one('stock.warehouse', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='warehouse_id.company_id', store=True)
    analysis_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    history_days = fields.Integer(string='History (days)')

    on_hand = fields.Float(string='On Hand')
    incoming = fields.Float(string='Incoming')
    position = fields.Float(string='Forecasted Stock', help="On hand + incoming - outgoing (reservations included).")
    avg_daily_demand = fields.Float(string='Avg. Daily Demand', digits=(16, 3))
    forecast_daily = fields.Float(string='Forecast Daily Demand', digits=(16, 3))
    trend_pct = fields.Float(string='Trend (%)', digits=(16, 1))
    demand_std = fields.Float(string='Demand Std. Dev.', digits=(16, 3))
    lead_time = fields.Float(string='Lead Time (days)')
    safety_stock = fields.Float(string='Safety Stock')
    reorder_point = fields.Float(string='Reorder Point')
    days_of_cover = fields.Float(string='Days of Cover', digits=(16, 1))
    suggested_qty = fields.Float(string='Suggested Order Qty')
    risk_level = fields.Selection(RISK_SELECTION, required=True, index=True)
    risk_sequence = fields.Integer(compute='_compute_risk_sequence', store=True)

    @api.depends('risk_level')
    def _compute_risk_sequence(self):
        for rec in self:
            rec.risk_sequence = RISK_ORDER.get(rec.risk_level, 9)

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------
    @api.model
    def _nexora_param(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(f'nexora_inventory.{key}')
        return value if value not in (None, False, '') else default

    @api.model
    def _nexora_default_params(self):
        return {
            'history_days': int(self._nexora_param('history_days', 90)),
            'horizon_days': int(self._nexora_param('horizon_days', 30)),
            'service_level': float(self._nexora_param('service_level', 95)),
            'default_lead_time': float(self._nexora_param('default_lead_time', 7)),
            'overstock_days': int(self._nexora_param('overstock_days', 180)),
        }

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------
    @api.model
    def _run_for_warehouse(self, warehouse, history_days, horizon_days, service_level,
                           default_lead_time, overstock_days):
        history_days = max(int(history_days), 14)
        now = fields.Datetime.now()
        start = now - timedelta(days=history_days)
        mid_date = (now - timedelta(days=history_days / 2.0)).date()
        view_loc = warehouse.view_location_id

        # 1) Daily outgoing demand per product
        groups = self.env['stock.move']._read_group(
            [
                ('state', '=', 'done'),
                ('date', '>=', start),
                ('location_id', 'child_of', view_loc.id),
                ('location_id.usage', '=', 'internal'),
                ('location_dest_id.usage', '=', 'customer'),
                ('product_id.is_storable', '=', True),
            ],
            ['product_id', 'date:day'],
            ['product_qty:sum'],
        )
        demand = defaultdict(lambda: {'total': 0.0, 'old': 0.0, 'recent': 0.0, 'days': []})
        for product, day, qty in groups:
            day = day.date() if isinstance(day, datetime) else day
            rec = demand[product.id]
            rec['total'] += qty
            rec['days'].append(qty)
            if day >= mid_date:
                rec['recent'] += qty
            else:
                rec['old'] += qty

        # 2) Products currently in stock in this warehouse
        quant_groups = self.env['stock.quant']._read_group(
            [
                ('location_id', 'child_of', view_loc.id),
                ('location_id.usage', '=', 'internal'),
                ('quantity', '>', 0),
                ('product_id.is_storable', '=', True),
            ],
            ['product_id'],
            ['quantity:sum'],
        )
        stocked = {product.id for product, _qty in quant_groups}
        product_ids = set(demand) | stocked

        # 3) Compute metrics
        z = NormalDist().inv_cdf(min(max(service_level, 50.0), 99.9) / 100.0)
        half = history_days / 2.0
        products = self.env['product.product'].browse(sorted(product_ids)).with_context(
            warehouse_id=warehouse.id)
        vals_list = []
        for product in products:
            d = demand.get(product.id, {'total': 0.0, 'old': 0.0, 'recent': 0.0, 'days': []})
            avg_total = d['total'] / history_days
            avg_old = d['old'] / half
            avg_recent = d['recent'] / half
            forecast = 0.7 * avg_recent + 0.3 * avg_total
            if avg_old:
                trend = (avg_recent - avg_old) / avg_old * 100.0
            else:
                trend = 100.0 if avg_recent else 0.0

            mean = avg_total
            non_zero = d['days']
            variance = (sum((v - mean) ** 2 for v in non_zero)
                        + (history_days - len(non_zero)) * mean ** 2) / history_days
            std = math.sqrt(variance)

            seller = product.seller_ids[:1]
            lead = float(seller.delay) if seller else float(default_lead_time)
            safety = z * std * math.sqrt(lead)
            rop = forecast * lead + safety

            on_hand = product.qty_available
            incoming = product.incoming_qty
            position = product.virtual_available

            if forecast > 0:
                cover = min(on_hand / forecast, 999.0) if on_hand > 0 else 0.0
            else:
                cover = 999.0 if on_hand > 0 else 0.0

            if forecast > 0:
                if on_hand <= 0:
                    risk = 'stockout'
                elif position / forecast < lead:
                    risk = 'critical'
                elif position <= rop:
                    risk = 'low'
                elif cover > overstock_days:
                    risk = 'overstock'
                else:
                    risk = 'ok'
            else:
                risk = 'dead' if on_hand > 0 else 'ok'

            suggested = 0.0
            if risk in ('stockout', 'critical', 'low'):
                target = rop + forecast * horizon_days
                suggested = max(0.0, math.ceil(target - position))

            vals_list.append({
                'product_id': product.id,
                'warehouse_id': warehouse.id,
                'history_days': history_days,
                'on_hand': on_hand,
                'incoming': incoming,
                'position': position,
                'avg_daily_demand': avg_total,
                'forecast_daily': forecast,
                'trend_pct': trend,
                'demand_std': std,
                'lead_time': lead,
                'safety_stock': safety,
                'reorder_point': rop,
                'days_of_cover': cover,
                'suggested_qty': suggested,
                'risk_level': risk,
            })

        self.search([('warehouse_id', '=', warehouse.id)]).unlink()
        return self.create(vals_list)

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_run_analysis(self):
        companies = self.env['res.company'].sudo().search([])
        self = self.with_context(allowed_company_ids=companies.ids)
        params = self._nexora_default_params()
        auto_plan = str(self._nexora_param('auto_plan', 'True')) in ('True', 'true', '1')
        Plan = self.env['nexora.replenishment.plan']
        for warehouse in self.env['stock.warehouse'].search([]):
            self._run_for_warehouse(warehouse, **params)
            if auto_plan and not Plan.search_count(
                    [('warehouse_id', '=', warehouse.id), ('state', '=', 'draft')]):
                plan = Plan._create_from_analysis(warehouse)
                if plan:
                    plan._notify_responsible()