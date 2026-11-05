from odoo import fields, models, tools


class NexoraDeliveryReport(models.Model):
    _name = 'nexora.delivery.report'
    _description = 'Delivery Performance'
    _auto = False
    _order = 'date desc'

    date = fields.Date(readonly=True)
    shipment_id = fields.Many2one('nexora.shipment', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', readonly=True)
    driver_id = fields.Many2one('hr.employee', string='Driver', readonly=True)
    trip_id = fields.Many2one('nexora.transport.trip', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    state = fields.Selection(
        [('delivered', 'Delivered'), ('failed', 'Failed')], readonly=True)
    weight = fields.Float(string='Weight (kg)', readonly=True)
    delay_hours = fields.Float(string='Avg. Delay (h)', readonly=True, aggregator='avg')
    delivered_count = fields.Integer(string='Delivered', readonly=True)
    on_time_count = fields.Integer(string='On Time', readonly=True)
    late_count = fields.Integer(string='Late', readonly=True)
    failed_count = fields.Integer(string='Failed', readonly=True)
    on_time_pct = fields.Float(string='On-time Rate (%)', readonly=True, aggregator='avg')
    freight_amount = fields.Float(string='Revenue', readonly=True)
    allocated_cost = fields.Float(string='Cost', readonly=True)
    profit = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))

    def _query(self):
        return """
            SELECT s.id AS id,
                   s.id AS shipment_id,
                   COALESCE(s.actual_delivery_date, s.planned_delivery_date)::date AS date,
                   s.partner_id AS partner_id,
                   s.vehicle_id AS vehicle_id,
                   s.driver_id AS driver_id,
                   s.trip_id AS trip_id,
                   s.company_id AS company_id,
                   s.state AS state,
                   s.total_weight AS weight,
                   CASE WHEN s.state = 'delivered' THEN s.delay_hours END AS delay_hours,
                   CASE WHEN s.state = 'delivered' THEN 1 ELSE 0 END AS delivered_count,
                   CASE WHEN s.state = 'delivered' AND s.on_time THEN 1 ELSE 0 END AS on_time_count,
                   CASE WHEN s.state = 'delivered' AND NOT s.on_time THEN 1 ELSE 0 END AS late_count,
                   CASE WHEN s.state = 'failed' THEN 1 ELSE 0 END AS failed_count,
                   CASE WHEN s.state = 'delivered'
                        THEN (CASE WHEN s.on_time THEN 100.0 ELSE 0.0 END) END AS on_time_pct,
                   s.freight_amount AS freight_amount,
                   s.allocated_cost AS allocated_cost,
                   s.profit AS profit
              FROM nexora_shipment s
             WHERE s.state IN ('delivered', 'failed')
        """