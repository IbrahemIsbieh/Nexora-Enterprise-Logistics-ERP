from odoo import fields, models, tools


class NexoraSupplierReport(models.Model):
    _name = 'nexora.supplier.report'
    _description = 'Supplier Analysis'
    _auto = False
    _order = 'date desc'

    date = fields.Date(readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    qty_ordered = fields.Float(string='Qty Ordered', readonly=True)
    qty_received = fields.Float(string='Qty Received', readonly=True)
    price_unit = fields.Float(string='Avg. Unit Price', readonly=True, aggregator='avg')
    amount = fields.Float(string='Spend', readonly=True)
    fill_rate = fields.Float(string='Fill Rate (%)', readonly=True, aggregator='avg')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))

    def _query(self):
        return """
            SELECT pol.id AS id,
                   po.date_order::date AS date,
                   po.partner_id AS partner_id,
                   pol.product_id AS product_id,
                   pt.categ_id AS categ_id,
                   po.company_id AS company_id,
                   pol.product_qty AS qty_ordered,
                   pol.qty_received AS qty_received,
                   pol.price_unit AS price_unit,
                   pol.price_subtotal AS amount,
                   CASE WHEN pol.product_qty > 0
                        THEN LEAST(pol.qty_received / pol.product_qty, 1.0) * 100.0 END AS fill_rate
              FROM purchase_order_line pol
              JOIN purchase_order po ON po.id = pol.order_id
         LEFT JOIN product_product pp ON pp.id = pol.product_id
         LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE po.state IN ('purchase', 'done')
               AND pol.display_type IS NULL
        """