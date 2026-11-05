from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models


class NexoraVendorPerformance(models.Model):
    _name = 'nexora.vendor.performance'
    _description = 'Vendor Performance'
    _order = 'score desc, id'

    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date()
    date_to = fields.Date()
    order_count = fields.Integer(string='Orders')
    total_spend = fields.Monetary(currency_field='currency_id',
                                  help="Sum of order totals, no currency conversion.")
    evaluated_orders = fields.Integer(string='Orders Received')
    on_time_orders = fields.Integer()
    on_time_rate = fields.Float(string='On-time Delivery (%)', digits=(16, 1))
    fill_rate = fields.Float(string='Fill Rate (%)', digits=(16, 1))
    score = fields.Float(digits=(16, 1))
    rating = fields.Selection(
        [('a', 'A - Excellent'), ('b', 'B - Good'), ('c', 'C - Fair'), ('d', 'D - Poor')])

    @api.model
    def _compute_all(self, days=None):
        icp = self.env['ir.config_parameter'].sudo()
        days = days or int(icp.get_param('nexora_procurement.performance_days', 90))
        grace = float(icp.get_param('nexora_procurement.ontime_grace_days', 1))
        date_to = fields.Date.context_today(self)
        date_from = date_to - timedelta(days=days)
        orders = self.env['purchase.order'].sudo().search([
            ('state', 'in', ('purchase', 'done')),
            ('date_approve', '>=', fields.Datetime.to_datetime(date_from)),
        ])
        self.sudo().search([]).unlink()
        groups = defaultdict(lambda: self.env['purchase.order'])
        for order in orders:
            groups[order.partner_id] |= order

        for partner, pos in groups.items():
            lines = pos.order_line.filtered(lambda l: not l.display_type)
            ordered = sum(lines.mapped('product_qty'))
            received = sum(min(l.qty_received, l.product_qty) for l in lines)
            fill = received / ordered * 100.0 if ordered else 0.0
            evaluated = on_time = 0
            for order in pos:
                done = [p.date_done for p in order.picking_ids if p.state == 'done' and p.date_done]
                if not done or not order.date_planned:
                    continue
                evaluated += 1
                if max(done) <= order.date_planned + timedelta(days=grace):
                    on_time += 1
            on_time_rate = on_time / evaluated * 100.0 if evaluated else 0.0
            if evaluated:
                score = 0.6 * on_time_rate + 0.4 * fill
                rating = 'a' if score >= 90 else 'b' if score >= 75 else 'c' if score >= 60 else 'd'
            else:
                score, rating = 0.0, False
            self.sudo().create({
                'partner_id': partner.id,
                'date_from': date_from, 'date_to': date_to,
                'order_count': len(pos),
                'total_spend': sum(pos.mapped('amount_total')),
                'evaluated_orders': evaluated, 'on_time_orders': on_time,
                'on_time_rate': on_time_rate, 'fill_rate': fill,
                'score': score, 'rating': rating,
            })
            partner.sudo().write({'nexora_vendor_score': score, 'nexora_vendor_rating': rating})

    @api.model
    def _cron_compute(self):
        self._compute_all()