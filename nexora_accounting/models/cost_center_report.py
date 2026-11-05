from odoo import fields, models, tools


class NexoraCostCenterReport(models.Model):
    _name = 'nexora.cost.center.report'
    _description = 'Cost Center Analysis'
    _auto = False
    _order = 'date desc'

    date = fields.Date(readonly=True)
    cost_center_id = fields.Many2one('nexora.cost.center', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True)
    source = fields.Selection(
        [('expense', 'Vehicle Expense'), ('vendor_bill', 'Vendor Bill'),
         ('customer_invoice', 'Customer Invoice')], readonly=True)
    kind = fields.Selection([('cost', 'Cost'), ('revenue', 'Revenue')], readonly=True)
    amount = fields.Float(readonly=True)
    signed_amount = fields.Float(string='Net (Revenue - Cost)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))

    def _query(self):
        return """
            SELECT row_number() OVER () AS id, q.*
            FROM (
                -- Confirmed vehicle expenses (unless already carried by a posted vendor bill)
                SELECT e.date AS date, e.cost_center_id AS cost_center_id, e.company_id AS company_id,
                       e.partner_id AS partner_id, 'expense' AS source, 'cost' AS kind,
                       e.amount AS amount, -e.amount AS signed_amount
                  FROM nexora_vehicle_expense e
             LEFT JOIN account_move bm ON bm.id = e.bill_id
                 WHERE e.state = 'confirmed'
                   AND e.cost_center_id IS NOT NULL
                   AND (e.bill_id IS NULL OR bm.state != 'posted')
                UNION ALL
                -- Posted vendor bills
                SELECT m.date, m.nexora_cost_center_id, m.company_id, m.partner_id,
                       'vendor_bill', 'cost', l.balance, -l.balance
                  FROM account_move_line l
                  JOIN account_move m ON m.id = l.move_id
                 WHERE m.state = 'posted'
                   AND m.move_type IN ('in_invoice', 'in_refund')
                   AND l.display_type = 'product'
                   AND m.nexora_cost_center_id IS NOT NULL
                UNION ALL
                -- Posted customer invoices
                SELECT m.date, m.nexora_cost_center_id, m.company_id, m.partner_id,
                       'customer_invoice', 'revenue', -l.balance, -l.balance
                  FROM account_move_line l
                  JOIN account_move m ON m.id = l.move_id
                 WHERE m.state = 'posted'
                   AND m.move_type IN ('out_invoice', 'out_refund')
                   AND l.display_type = 'product'
                   AND m.nexora_cost_center_id IS NOT NULL
            ) q
        """