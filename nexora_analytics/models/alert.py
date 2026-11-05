import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

SEVERITY = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]
SEVERITY_RANK = {'low': 1, 'medium': 2, 'high': 3}
ALERT_TYPES = [
    ('late_shipment', 'Late Shipment'),
    ('failed_delivery', 'Failed Delivery'),
    ('stock', 'Stock Risk'),
    ('vehicle_docs', 'Vehicle Documents'),
    ('maintenance', 'Maintenance Overdue'),
    ('driver_license', 'Driver License'),
    ('contract', 'Contract Expiry'),
    ('negative_margin', 'Negative Margin'),
    ('fuel_anomaly', 'Abnormal Fuel Consumption'),
    ('fuel_card', 'Fuel Card Limit'),
    ('vendor', 'Poor Vendor'),
    ('approval', 'Pending Approval'),
    ('ticket', 'Unattended Ticket'),
]
DETECTORS = [
    ('late_shipment', '_detect_late_shipments'),
    ('failed_delivery', '_detect_failed_deliveries'),
    ('stock', '_detect_stock_risks'),
    ('vehicle_docs', '_detect_vehicle_documents'),
    ('maintenance', '_detect_maintenance'),
    ('driver_license', '_detect_driver_licenses'),
    ('contract', '_detect_contracts'),
    ('negative_margin', '_detect_negative_margin'),
    ('fuel_anomaly', '_detect_fuel_anomalies'),
    ('fuel_card', '_detect_fuel_cards'),
    ('vendor', '_detect_poor_vendors'),
    ('approval', '_detect_pending_approvals'),
    ('ticket', '_detect_tickets'),
]


class NexoraAlert(models.Model):
    _name = 'nexora.alert'
    _description = 'Operational Alert'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'severity_rank desc, date desc, id desc'

    name = fields.Char(string='Alert', required=True)
    key = fields.Char(required=True, index=True, copy=False,
                      help="Technical key that identifies the condition behind the alert.")
    alert_type = fields.Selection(ALERT_TYPES, required=True, index=True)
    severity = fields.Selection(SEVERITY, required=True, default='medium', tracking=True)
    severity_rank = fields.Integer(compute='_compute_severity_rank', store=True)
    message = fields.Text()
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    state = fields.Selection(
        [('open', 'Open'), ('acknowledged', 'Acknowledged'),
         ('dismissed', 'Ignored'), ('resolved', 'Resolved')],
        default='open', required=True, tracking=True, index=True)
    res_model = fields.Char(string='Related Model')
    res_id = fields.Integer(string='Related Record')
    responsible_id = fields.Many2one('res.users', string='Responsible', tracking=True)
    date_resolved = fields.Datetime(readonly=True, copy=False)
    auto_resolved = fields.Boolean(readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    @api.depends('severity')
    def _compute_severity_rank(self):
        for alert in self:
            alert.severity_rank = SEVERITY_RANK.get(alert.severity, 0)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_acknowledge(self):
        self.filtered(lambda a: a.state == 'open').write({'state': 'acknowledged'})

    def action_ignore(self):
        self.filtered(lambda a: a.state in ('open', 'acknowledged')).write({'state': 'dismissed'})

    def action_resolve(self):
        alerts = self.filtered(lambda a: a.state != 'resolved')
        alerts.write({'state': 'resolved', 'date_resolved': fields.Datetime.now(),
                      'auto_resolved': False})
        alerts.activity_unlink(['mail.mail_activity_data_todo'])

    def action_reopen(self):
        self.filtered(lambda a: a.state in ('resolved', 'dismissed')).write(
            {'state': 'open', 'date_resolved': False})

    def action_open_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------
    @api.model
    def _icp(self, key, default):
        value = self.env['ir.config_parameter'].sudo().get_param(key)
        return value if value not in (None, False, '') else default

    @api.model
    def _default_responsible(self):
        value = self._icp('nexora_analytics.alert_responsible_id', False)
        user = self.env['res.users'].browse(int(value)).exists() if value else self.env['res.users']
        return user or self.env.ref('base.user_admin')

    def _co(self, record):
        if 'company_id' in record._fields and record.company_id:
            return record.company_id.id
        return self.env.company.id

    def _item(self, key, severity, name, message, record, responsible=None,
              model=None, res_id=None):
        return {
            'key': key, 'severity': severity, 'name': name, 'message': message,
            'res_model': model or record._name, 'res_id': res_id or record.id,
            'company_id': self._co(record),
            'responsible_id': responsible.id if responsible else False,
        }

    @api.model
    def _cron_generate_alerts(self):
        self = self.sudo()
        found, failed = {}, set()
        for alert_type, method in DETECTORS:
            try:
                with self.env.cr.savepoint():
                    for item in getattr(self, method)():
                        found[item['key']] = dict(item, alert_type=alert_type)
            except Exception:
                _logger.exception("Nexora alerts: detector '%s' failed.", alert_type)
                failed.add(alert_type)

        existing = self.search([('state', '!=', 'resolved')])
        known = set(existing.mapped('key'))

        cleared = existing.filtered(lambda a: a.key not in found and a.alert_type not in failed)
        if cleared:
            cleared.write({'state': 'resolved', 'date_resolved': fields.Datetime.now(),
                           'auto_resolved': True})
            cleared.activity_unlink(['mail.mail_activity_data_todo'])

        default_user = self._default_responsible()
        vals_list = []
        for key, item in found.items():
            if key in known:
                continue
            item = dict(item)
            item['responsible_id'] = item.get('responsible_id') or default_user.id
            vals_list.append(item)
        created = self.create(vals_list)
        for alert in created.filtered(lambda a: a.severity == 'high' and a.responsible_id):
            alert.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=alert.name,
                note=alert.message or '',
                user_id=alert.responsible_id.id,
            )
        return len(created)

    # ------------------------------------------------------------------
    # Detectors (each returns a list of alert dicts)
    # ------------------------------------------------------------------
    def _detect_late_shipments(self):
        now = fields.Datetime.now()
        items = []
        for s in self.env['nexora.shipment'].search([
                ('state', 'in', ('draft', 'planned', 'in_transit')),
                ('planned_delivery_date', '!=', False),
                ('planned_delivery_date', '<', now)]):
            hours = (now - s.planned_delivery_date).total_seconds() / 3600.0
            items.append(self._item(
                f'late_shipment:{s.id}', 'high' if hours > 24 else 'medium',
                _("Late shipment %s", s.name),
                _("%(customer)s: planned delivery %(date)s, %(hours).0f h overdue.",
                  customer=s.partner_id.display_name, date=s.planned_delivery_date, hours=hours),
                s, s.order_id.responsible_id))
        return items

    def _detect_failed_deliveries(self):
        return [self._item(
            f'failed_delivery:{s.id}', 'high',
            _("Failed delivery %s", s.name),
            _("%(customer)s: %(reason)s", customer=s.partner_id.display_name,
              reason=s.failure_reason or _("no reason recorded")),
            s, s.order_id.responsible_id)
            for s in self.env['nexora.shipment'].search([('state', '=', 'failed')])]

    def _detect_stock_risks(self):
        items = []
        for a in self.env['nexora.inventory.analysis'].search(
                [('risk_level', 'in', ('stockout', 'critical'))]):
            stockout = a.risk_level == 'stockout'
            items.append(self._item(
                f'stock:{a.product_id.id}:{a.warehouse_id.id}',
                'high' if stockout else 'medium',
                (_("Stockout: %(p)s @ %(w)s") if stockout else _("Critical stock: %(p)s @ %(w)s"))
                % {'p': a.product_id.display_name, 'w': a.warehouse_id.name},
                _("On hand %(oh).0f, forecast demand %(fc).2f/day, suggested order %(q).0f.",
                  oh=a.on_hand, fc=a.forecast_daily, q=a.suggested_qty),
                a, model='product.product', res_id=a.product_id.id))
        return items

    def _detect_vehicle_documents(self):
        today = fields.Date.context_today(self)
        days = int(self._icp('nexora_fleet.doc_alert_days', 30))
        limit = today + timedelta(days=days)
        items = []
        for v in self.env['fleet.vehicle'].search([]):
            status = v.nexora_doc_status
            if status not in ('expired', 'expiring'):
                continue
            docs = ", ".join(
                f"{v._fields[f].string}: {v[f]}" for f in v._NEXORA_DOC_FIELDS
                if v[f] and v[f] <= limit)
            items.append(self._item(
                f'vehicle_docs:{v.id}:{status}', 'high' if status == 'expired' else 'medium',
                (_("Vehicle documents expired: %s") if status == 'expired'
                 else _("Vehicle documents expiring: %s")) % v.display_name,
                docs, v, v.manager_id))
        return items

    def _detect_maintenance(self):
        items = []
        for plan in self.env['nexora.maintenance.plan'].search([('active', '=', True)]):
            if plan.due_state != 'overdue':
                continue
            items.append(self._item(
                f'maintenance:{plan.id}', 'medium',
                _("Maintenance overdue: %(plan)s - %(vehicle)s",
                  plan=plan.name, vehicle=plan.vehicle_id.display_name),
                _("Due at %(km).0f km / %(date)s. Remaining: %(rkm).0f km, %(rd)s days.",
                  km=plan.next_due_odometer, date=plan.next_due_date or '-',
                  rkm=plan.remaining_km, rd=plan.remaining_days),
                plan, plan.responsible_id))
        return items

    def _detect_driver_licenses(self):
        items = []
        for emp in self.env['hr.employee'].search([('is_driver', '=', True)]):
            state = emp.license_state
            if state not in ('expired', 'expiring'):
                continue
            items.append(self._item(
                f'driver_license:{emp.id}:{state}', 'high' if state == 'expired' else 'medium',
                (_("Driver license expired: %s") if state == 'expired'
                 else _("Driver license expiring: %s")) % emp.name,
                _("License %(no)s expires on %(date)s.", no=emp.driver_license_no,
                  date=emp.license_expiry),
                emp, emp.parent_id.user_id))
        return items

    def _detect_contracts(self):
        today = fields.Date.context_today(self)
        days = int(self._icp('nexora_core.contract_alert_days', 30))
        items = []
        for c in self.env['nexora.contract'].search([
                ('state', '=', 'active'), ('date_end', '!=', False),
                ('date_end', '<=', today + timedelta(days=days))]):
            expired = c.date_end < today
            items.append(self._item(
                f'contract:{c.id}', 'high' if expired else 'medium',
                _("Contract %(state)s: %(name)s", state=_("expired") if expired else _("expiring"),
                  name=c.name),
                _("%(partner)s - ends on %(date)s.", partner=c.partner_id.display_name,
                  date=c.date_end),
                c, c.responsible_id))
        return items

    def _detect_negative_margin(self):
        since = fields.Datetime.now() - timedelta(days=14)
        return [self._item(
            f'negative_margin:{s.id}', 'medium',
            _("Loss-making shipment %s", s.name),
            _("Revenue %(r).2f, allocated cost %(c).2f, profit %(p).2f.",
              r=s.freight_amount, c=s.allocated_cost, p=s.profit),
            s, s.order_id.responsible_id)
            for s in self.env['nexora.shipment'].search([
                ('state', '=', 'delivered'), ('freight_amount', '>', 0),
                ('profit', '<', 0), ('actual_delivery_date', '>=', since)])]

    def _detect_fuel_anomalies(self):
        since = fields.Date.context_today(self) - timedelta(days=14)
        return [self._item(
            f'fuel_anomaly:{log.id}', 'medium',
            _("Abnormal fuel consumption: %s", log.vehicle_id.display_name),
            _("%(c).1f per 100 km on %(date)s (%(name)s).", c=log.consumption,
              date=log.date, name=log.name),
            log, log.vehicle_id.manager_id)
            for log in self.env['nexora.fuel.log'].search([
                ('state', '=', 'confirmed'), ('is_anomaly', '=', True), ('date', '>=', since)])]

    def _detect_fuel_cards(self):
        since = fields.Date.context_today(self) - timedelta(days=30)
        return [self._item(
            f'fuel_card:{log.id}', 'low',
            _("Fuel card limit exceeded: %s", log.card_id.name),
            _("Exceeded after %(name)s on %(date)s.", name=log.name, date=log.date),
            log, log.card_id.responsible_id)
            for log in self.env['nexora.fuel.log'].search([
                ('state', '=', 'confirmed'), ('over_limit', '=', True), ('date', '>=', since)])]

    def _detect_poor_vendors(self):
        return [self._item(
            f'vendor:{p.id}', 'low',
            _("Poor vendor rating: %s", p.display_name),
            _("Rated D with a score of %.1f.", p.nexora_vendor_score), p)
            for p in self.env['res.partner'].search([('nexora_vendor_rating', '=', 'd')])]

    def _detect_pending_approvals(self):
        days = int(self._icp('nexora_analytics.approval_stale_days', 3))
        limit = fields.Datetime.now() - timedelta(days=days)
        return [self._item(
            f'approval:{pr.id}', 'medium',
            _("Purchase request waiting for approval: %s", pr.name),
            _("Estimated %(amount).2f, requested by %(user)s.", amount=pr.total_estimated,
              user=pr.requester_id.name),
            pr, pr.approver_id)
            for pr in self.env['nexora.purchase.request'].search([
                ('state', '=', 'to_approve'), ('create_date', '<', limit)])]

    def _detect_tickets(self):
        limit = fields.Datetime.now() - timedelta(hours=24)
        return [self._item(
            f'ticket:{t.id}', 'high' if t.priority == 'high' else 'medium',
            _("Unattended ticket %s", t.name),
            _("%(partner)s: %(subject)s", partner=t.partner_id.display_name, subject=t.subject),
            t, t.responsible_id)
            for t in self.env['nexora.customer.ticket'].search([
                ('state', '=', 'new'), ('create_date', '<', limit)])]