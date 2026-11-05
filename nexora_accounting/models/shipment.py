from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

ACCOUNTING_GROUP = 'nexora_accounting.group_nexora_accounting_user'


class NexoraShipment(models.Model):
    _inherit = 'nexora.shipment'

    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    distance_km = fields.Float(
        string='Distance (km)', tracking=True,
        help="Used by per-km rates. Filled from the trip distance when the trip is completed.")
    freight_rate_id = fields.Many2one(
        'nexora.freight.rate', string='Freight Rate', readonly=True, copy=False)
    freight_base = fields.Monetary(readonly=True, copy=False)
    freight_surcharge = fields.Monetary(readonly=True, copy=False)
    freight_amount = fields.Monetary(string='Freight Amount', tracking=True, copy=False)
    allocated_cost = fields.Monetary(string='Allocated Cost', readonly=True, copy=False)
    profit = fields.Monetary(compute='_compute_profit', store=True)
    margin_pct = fields.Float(string='Margin (%)', compute='_compute_profit', store=True,
                              digits=(16, 1))
    invoice_id = fields.Many2one(
        'account.move', string='Customer Invoice', readonly=True, copy=False,
        ondelete='set null', index=True)
    invoice_status = fields.Selection(
        [('no', 'Nothing to Invoice'), ('to_invoice', 'To Invoice'), ('invoiced', 'Invoiced')],
        compute='_compute_invoice_status', store=True, index=True)
    payment_state = fields.Selection(related='invoice_id.payment_state', string='Payment')

    # ------------------------------------------------------------------
    @api.depends('freight_amount', 'allocated_cost')
    def _compute_profit(self):
        for rec in self:
            rec.profit = rec.freight_amount - rec.allocated_cost
            rec.margin_pct = (rec.profit / rec.freight_amount * 100.0) if rec.freight_amount else 0.0

    @api.depends('state', 'freight_amount', 'invoice_id', 'invoice_id.state')
    def _compute_invoice_status(self):
        for rec in self:
            if rec._is_invoiced():
                rec.invoice_status = 'invoiced'
            elif rec.state == 'delivered' and rec.freight_amount > 0:
                rec.invoice_status = 'to_invoice'
            else:
                rec.invoice_status = 'no'

    def _is_invoiced(self):
        self.ensure_one()
        return bool(self.invoice_id and self.invoice_id.state != 'cancel')

    def _check_accounting_rights(self):
        if not self.env.user.has_group(ACCOUNTING_GROUP):
            raise UserError(_("You need Nexora Accounting access rights for this operation."))

    # ------------------------------------------------------------------
    # Freight calculation
    # ------------------------------------------------------------------
    def _find_rate(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        rates = self.env['nexora.freight.rate'].search([
            ('active', '=', True),
            ('company_id', 'in', [self.company_id.id, False]),
            '|', ('partner_id', '=', self.partner_id.id), ('partner_id', '=', False),
            '|', ('date_from', '=', False), ('date_from', '<=', today),
            '|', ('date_to', '=', False), ('date_to', '>=', today),
        ])
        rates = rates.sorted(lambda r: (0 if r.partner_id else 1, r.sequence, r.id))
        return rates[:1]

    def _apply_freight(self):
        """Compute and store the freight. Returns True when a rate was found."""
        self.ensure_one()
        rate = self._find_rate()
        if not rate:
            return False
        unit_price = rate.price
        contract_line = self.order_id.contract_id.line_ids.filtered(
            lambda l: l.product_id == rate.product_id)[:1]
        if contract_line:
            unit_price = contract_line.price_unit
        quantity = {
            'fixed': 1.0,
            'per_kg': self.total_weight,
            'per_m3': self.total_volume,
            'per_km': self.distance_km,
        }[rate.basis]
        base = max(unit_price * quantity, rate.minimum_charge)
        pct = 0.0
        if self.temperature_class == 'chilled':
            pct += rate.chilled_pct
        elif self.temperature_class == 'frozen':
            pct += rate.frozen_pct
        if self.has_hazardous:
            pct += rate.hazmat_pct
        if self.order_id.priority == 'urgent':
            pct += rate.urgent_pct
        surcharge = base * pct / 100.0
        self.write({
            'freight_rate_id': rate.id,
            'freight_base': base,
            'freight_surcharge': surcharge,
            'freight_amount': base + surcharge,
        })
        return True

    def _auto_freight(self):
        for rec in self:
            rec._apply_freight()

    def action_compute_freight(self):
        self._check_accounting_rights()
        for rec in self:
            if rec._is_invoiced():
                raise UserError(_("Shipment %s is already invoiced.", rec.name))
            if not rec._apply_freight():
                raise UserError(_(
                    "No freight rate matches shipment %s. Define one in Accounting > Freight Rates.",
                    rec.name))

    def action_deliver(self):
        res = super().action_deliver()
        self.filtered(lambda s: not s.freight_amount)._auto_freight()
        return res

    # ------------------------------------------------------------------
    # Invoicing
    # ------------------------------------------------------------------
    def action_create_invoice(self):
        self._check_accounting_rights()
        shipments = self.filtered(lambda s: s.state == 'delivered' and not s._is_invoiced())
        if not shipments:
            raise UserError(_("Select delivered shipments that are not invoiced yet."))
        shipments.filtered(lambda s: not s.freight_amount)._auto_freight()
        missing = shipments.filtered(lambda s: s.freight_amount <= 0)
        if missing:
            raise UserError(_(
                "No freight amount for: %s. Define a freight rate or enter the amount.",
                ", ".join(missing.mapped('name'))))

        default_product = self.env.ref(
            'nexora_accounting.product_freight_service').product_variant_id
        groups = {}
        for shipment in shipments:
            key = (shipment.partner_id, shipment.company_id, shipment.order_id.cost_center_id)
            groups.setdefault(key, self.browse())
            groups[key] |= shipment

        moves = self.env['account.move']
        for (partner, company, cost_center), group in groups.items():
            lines = []
            for shipment in group:
                product = shipment.freight_rate_id.product_id or default_product
                destination = shipment.delivery_partner_id.city or shipment.delivery_partner_id.name
                lines.append(Command.create({
                    'product_id': product.id,
                    'name': _("%(product)s - %(shipment)s (%(order)s) to %(dest)s",
                              product=product.display_name, shipment=shipment.name,
                              order=shipment.order_id.name, dest=destination or ''),
                    'quantity': 1.0,
                    'price_unit': shipment.freight_amount,
                    'nexora_shipment_id': shipment.id,
                }))
            move = self.env['account.move'].with_company(company).create({
                'move_type': 'out_invoice',
                'partner_id': partner.id,
                'company_id': company.id,
                'invoice_origin': ", ".join(group.mapped('name')),
                'nexora_cost_center_id': cost_center.id,
                'invoice_line_ids': lines,
            })
            group.write({'invoice_id': move.id})
            moves |= move

        action = {
            'type': 'ir.actions.act_window',
            'name': _('Freight Invoices'),
            'res_model': 'account.move',
            'context': {'default_move_type': 'out_invoice'},
        }
        if len(moves) == 1:
            action.update({'view_mode': 'form', 'res_id': moves.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)]})
        return action

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
        }