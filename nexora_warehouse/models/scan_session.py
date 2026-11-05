from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class NexoraScanSession(models.Model):
    _name = 'nexora.scan.session'
    _description = 'Barcode Scan Session'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    operation = fields.Selection(
        [('receive', 'Receive Goods'), ('internal', 'Internal Transfer')],
        required=True, default='receive', tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done'), ('cancelled', 'Cancelled')],
        default='draft', tracking=True, copy=False)
    warehouse_id = fields.Many2one(
        'stock.warehouse', required=True,
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1))
    company_id = fields.Many2one(
        related='warehouse_id.company_id', store=True, string='Company')
    partner_id = fields.Many2one('res.partner', string='Partner')
    location_src_id = fields.Many2one(
        'stock.location', string='From Location', domain=[('usage', '=', 'internal')])
    location_dest_id = fields.Many2one(
        'stock.location', string='To Location', domain=[('usage', '=', 'internal')])
    scan_input = fields.Char(string='Scan')
    scan_message = fields.Char(readonly=True, copy=False)
    line_ids = fields.One2many('nexora.scan.session.line', 'session_id', string='Scanned Items')
    picking_id = fields.Many2one('stock.picking', string='Transfer', readonly=True, copy=False)
    note = fields.Text()

    @api.onchange('warehouse_id', 'operation')
    def _onchange_warehouse_operation(self):
        if self.operation == 'receive':
            self.location_src_id = False
            self.location_dest_id = self.warehouse_id.lot_stock_id
        elif self.location_dest_id and self.location_dest_id.warehouse_id != self.warehouse_id:
            self.location_dest_id = False

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    @api.onchange('scan_input')
    def _onchange_scan_input(self):
        code = (self.scan_input or '').strip()
        self.scan_input = False
        if not code:
            return
        self._process_barcode(code)

    def _process_barcode(self, code):
        # 1) Product barcode
        product = self.env['product.product'].search([('barcode', '=', code)], limit=1)
        if product:
            if product.tracking == 'none':
                line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
                if line:
                    line.qty += 1
                else:
                    self.line_ids = [Command.create({'product_id': product.id, 'qty': 1.0})]
                self.scan_message = _("Added: %s", product.display_name)
            else:
                self.line_ids = [Command.create({'product_id': product.id, 'qty': 1.0})]
                self.scan_message = _(
                    "%s is tracked: scan its lot / serial number now.", product.display_name)
            return

        # 2) Location barcode
        location = self.env['stock.location'].search([('barcode', '=', code)], limit=1)
        if location:
            if self.operation == 'receive' or (self.location_src_id and not self.location_dest_id):
                self.location_dest_id = location
                self.scan_message = _("Destination: %s", location.display_name)
            elif not self.location_src_id:
                self.location_src_id = location
                self.scan_message = _("Source: %s", location.display_name)
            else:
                self.location_dest_id = location
                self.scan_message = _("Destination: %s", location.display_name)
            return

        # 3) Lot / serial for the last tracked line waiting for one
        pending = self.line_ids.filtered(lambda l: l.tracking != 'none' and not l.lot_name)[-1:]
        if pending:
            pending.lot_name = code
            self.scan_message = _("Lot/Serial %(lot)s set for %(product)s",
                                  lot=code, product=pending.product_id.display_name)
            return

        self.scan_message = _("Unknown barcode: %s", code)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('nexora.scan.session') or 'New'
        return super().create(vals_list)

    def _prepare_validation(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Scan at least one product first."))
        if self.operation == 'receive':
            if not self.location_dest_id:
                raise UserError(_("Select or scan the destination location."))
            src = self.env.ref('stock.stock_location_suppliers')
            dest = self.location_dest_id
            picking_type = self.warehouse_id.in_type_id
        else:
            if not self.location_src_id or not self.location_dest_id:
                raise UserError(_("Select or scan both source and destination locations."))
            src, dest = self.location_src_id, self.location_dest_id
            picking_type = self.warehouse_id.int_type_id
        for line in self.line_ids:
            if line.qty <= 0:
                raise UserError(_("Quantity must be positive for %s.", line.product_id.display_name))
            if line.tracking != 'none' and not line.lot_name:
                raise UserError(_("Lot/Serial number missing for %s.", line.product_id.display_name))
            if line.tracking == 'serial' and line.qty != 1:
                raise UserError(_("Serial-tracked product %s must have quantity 1 per line.",
                                  line.product_id.display_name))
        return src, dest, picking_type

    def action_validate(self):
        self.ensure_one()
        if self.state != 'draft':
            return
        src, dest, picking_type = self._prepare_validation()

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'partner_id': self.partner_id.id,
            'origin': self.name,
        })
        move_fields = self.env['stock.move']._fields
        moves = self.env['stock.move']
        move_by_product = {}
        for product in self.line_ids.product_id:
            lines = self.line_ids.filtered(lambda l: l.product_id == product)
            vals = {
                'product_id': product.id,
                'product_uom_qty': sum(lines.mapped('qty')),
                'product_uom': product.uom_id.id,
                'picking_id': picking.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
            }
            if 'name' in move_fields:
                vals['name'] = product.display_name
            move = self.env['stock.move'].create(vals)
            move_by_product[product.id] = move
            moves |= move

        picking.action_confirm()
        if self.operation == 'internal':
            picking.action_assign()

        # Replace automatic move lines with the exact scanned lines
        moves.move_line_ids.unlink()
        for line in self.line_ids:
            move = move_by_product[line.product_id.id]
            ml_vals = {
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': line.product_id.id,
                'product_uom_id': line.product_id.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'quantity': line.qty,
            }
            if line.tracking != 'none':
                if self.operation == 'receive':
                    ml_vals['lot_name'] = line.lot_name
                else:
                    lot = self.env['stock.lot'].search([
                        ('name', '=', line.lot_name),
                        ('product_id', '=', line.product_id.id),
                    ], limit=1)
                    if not lot:
                        raise UserError(_("Lot/Serial %(lot)s does not exist for %(product)s.",
                                          lot=line.lot_name, product=line.product_id.display_name))
                    ml_vals['lot_id'] = lot.id
            self.env['stock.move.line'].create(ml_vals)
        moves.write({'picked': True})

        result = picking.with_context(skip_backorder=True).button_validate()
        if picking.state != 'done':
            if isinstance(result, dict):
                self.picking_id = picking
                return result
            raise UserError(_("The transfer %s could not be validated.", picking.name))

        self.write({'state': 'done', 'picking_id': picking.id})
        self.message_post(body=_("Transfer %s validated.", picking.name))

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.filtered(lambda s: s.state == 'cancelled').write({'state': 'draft'})

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }


class NexoraScanSessionLine(models.Model):
    _name = 'nexora.scan.session.line'
    _description = 'Barcode Scan Session Line'

    session_id = fields.Many2one('nexora.scan.session', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    tracking = fields.Selection(related='product_id.tracking')
    lot_name = fields.Char(string='Lot / Serial')
    qty = fields.Float(string='Quantity', default=1.0)
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))