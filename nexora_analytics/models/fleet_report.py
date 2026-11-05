from odoo import fields, models, tools


class NexoraFleetReport(models.Model):
    _name = 'nexora.fleet.report'
    _description = 'Fleet Utilization'
    _auto = False
    _order = 'date desc'

    date = fields.Date(readonly=True)
    trip_id = fields.Many2one('nexora.transport.trip', readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', readonly=True)
    driver_id = fields.Many2one('hr.employee', string='Driver', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    trip_count = fields.Integer(string='Trips', readonly=True)
    hours = fields.Float(string='Trip Hours', readonly=True)
    distance = fields.Float(string='Distance (km)', readonly=True)
    weight = fields.Float(string='Load (kg)', readonly=True)
    payload_usage = fields.Float(string='Payload Usage (%)', readonly=True, aggregator='avg')
    volume_usage = fields.Float(string='Volume Usage (%)', readonly=True, aggregator='avg')
    shipments_delivered = fields.Integer(string='Shipments Delivered', readonly=True)
    total_cost = fields.Float(string='Trip Cost', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))

    def _query(self):
        return """
            SELECT t.id AS id,
                   t.id AS trip_id,
                   t.vehicle_id AS vehicle_id,
                   t.driver_id AS driver_id,
                   t.company_id AS company_id,
                   COALESCE(t.actual_start, t.planned_start)::date AS date,
                   1 AS trip_count,
                   GREATEST(
                       EXTRACT(EPOCH FROM (COALESCE(t.actual_end, t.planned_end)
                                           - COALESCE(t.actual_start, t.planned_start))),
                       EXTRACT(EPOCH FROM (t.planned_end - t.planned_start)),
                       0) / 3600.0 AS hours,
                   CASE WHEN t.odometer_end > t.odometer_start
                        THEN t.odometer_end - t.odometer_start ELSE 0 END AS distance,
                   t.total_weight AS weight,
                   t.payload_usage AS payload_usage,
                   t.volume_usage AS volume_usage,
                   (SELECT COUNT(*) FROM nexora_shipment sh
                     WHERE sh.trip_id = t.id AND sh.state = 'delivered') AS shipments_delivered,
                   t.total_cost AS total_cost
              FROM nexora_transport_trip t
             WHERE t.state = 'done'
        """