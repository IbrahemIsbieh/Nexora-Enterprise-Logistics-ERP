from odoo import fields, models, tools


class NexoraDemandReport(models.Model):
    _name = 'nexora.demand.report'
    _description = 'Demand History'
    _auto = False
    _order = 'date desc'

    date = fields.Date(readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    quantity = fields.Float(string='Quantity Shipped', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))

    def _query(self):
        return """
            SELECT sm.id AS id,
                   sm.date::date AS date,
                   sm.product_id AS product_id,
                   pt.categ_id AS categ_id,
                   w.id AS warehouse_id,
                   sm.company_id AS company_id,
                   sm.product_qty AS quantity
              FROM stock_move sm
              JOIN stock_location src ON src.id = sm.location_id
              JOIN stock_location dst ON dst.id = sm.location_dest_id
              JOIN product_product pp ON pp.id = sm.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
         LEFT JOIN stock_warehouse w
                ON POSITION('/' || w.view_location_id::text || '/' IN '/' || src.parent_path) > 0
             WHERE sm.state = 'done'
               AND src.usage = 'internal'
               AND dst.usage = 'customer'
        """