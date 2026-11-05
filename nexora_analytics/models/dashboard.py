from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class NexoraDashboard(models.AbstractModel):
    _name = 'nexora.dashboard'
    _description = 'Nexora Control Tower'

    @api.model
    def _tile(self, label, value, display=None, color='secondary', sub='',
              res_model=None, domain=None, name=None):
        return {
            'label': label, 'value': value,
            'display': display if display is not None else str(value),
            'color': color, 'sub': sub, 'res_model': res_model,
            'domain': domain or [], 'name': name or label,
        }

    @api.model
    def get_data(self):
        if not self.env.user.has_group('nexora_analytics.group_nexora_analytics_user'):
            raise AccessError(_("You do not have access to the Control Tower."))
        env = self.sudo().env
        cids = self.env.companies.ids
        icp = env['ir.config_parameter'].sudo()
        days = int(icp.get_param('nexora_analytics.dashboard_days') or 30)
        work_hours = float(icp.get_param('nexora_analytics.working_hours') or 10.0)
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        now_s = fields.Datetime.to_string(now)
        since_s = fields.Datetime.to_string(now - timedelta(days=days))
        since_d = fields.Date.to_string(today - timedelta(days=days))
        symbol = self.env.company.currency_id.symbol or ''

        def money(value):
            return f"{value:,.0f} {symbol}".strip()

        co = [('company_id', 'in', cids)]
        Shipment = env['nexora.shipment']
        sections = []

        # ------------------------------------------------------------ deliveries
        open_states = ('draft', 'planned', 'in_transit')
        delivered_d = co + [('state', '=', 'delivered'), ('actual_delivery_date', '>=', since_s)]
        delivered = Shipment.search_count(delivered_d)
        on_time = Shipment.search_count(delivered_d + [('on_time', '=', True)])
        on_time_pct = (on_time / delivered * 100.0) if delivered else None
        late_d = co + [('state', 'in', open_states), ('planned_delivery_date', '<', now_s)]
        late = Shipment.search_count(late_d)
        failed_d = co + [('state', '=', 'failed')]
        failed = Shipment.search_count(failed_d)
        to_plan_d = co + [('state', '=', 'draft'), ('trip_id', '=', False)]
        sections.append({'title': _("Deliveries"), 'icon': 'fa-truck', 'tiles': [
            self._tile(_("In transit"), Shipment.search_count(co + [('state', '=', 'in_transit')]),
                       color='info', res_model='nexora.shipment',
                       domain=co + [('state', '=', 'in_transit')], name=_("Shipments in transit")),
            self._tile(_("Late now"), late, color='danger' if late else 'success',
                       res_model='nexora.shipment', domain=late_d, name=_("Late shipments")),
            self._tile(_("To plan"), Shipment.search_count(to_plan_d),
                       color='warning' if Shipment.search_count(to_plan_d) else 'success',
                       res_model='nexora.shipment', domain=to_plan_d,
                       name=_("Shipments waiting for a trip")),
            self._tile(_("Delivered"), delivered, sub=_("last %s days", days), color='success',
                       res_model='nexora.shipment', domain=delivered_d, name=_("Delivered shipments")),
            self._tile(_("On-time rate"), on_time_pct or 0,
                       display=f"{on_time_pct:.0f}%" if on_time_pct is not None else '-',
                       sub=_("last %s days", days),
                       color='secondary' if on_time_pct is None else (
                           'success' if on_time_pct >= 90 else
                           'warning' if on_time_pct >= 75 else 'danger'),
                       res_model='nexora.shipment', domain=delivered_d, name=_("Delivered shipments")),
            self._tile(_("Failed"), failed, sub=_("need rescheduling"),
                       color='danger' if failed else 'success',
                       res_model='nexora.shipment', domain=failed_d, name=_("Failed shipments")),
        ]})

        # ----------------------------------------------------------------- fleet
        Vehicle = env['fleet.vehicle']
        vdomain = co
        availability = dict(Vehicle._read_group(vdomain, ['nexora_availability'], ['__count']))
        total_vehicles = sum(availability.values())
        row = env['nexora.fleet.report']._read_group(
            co + [('date', '>=', since_d)], [], ['hours:sum'])
        hours = (row[0][0] or 0.0) if row else 0.0
        capacity = total_vehicles * days * work_hours
        utilization = min(hours / capacity * 100.0, 100.0) if capacity else 0.0
        doc_ids = Vehicle.search(vdomain).filtered(
            lambda v: v.nexora_doc_status in ('expired', 'expiring')).ids
        plan_ids = env['nexora.maintenance.plan'].search([('active', '=', True)]).filtered(
            lambda p: p.due_state == 'overdue').ids
        unavailable = availability.get('maintenance', 0) + availability.get('out_of_service', 0)
        bars = [
            {'label': label, 'value': availability.get(key, 0), 'color': color,
             'pct': (availability.get(key, 0) / total_vehicles * 100.0) if total_vehicles else 0}
            for key, label, color in [
                ('available', _("Available"), 'success'), ('assigned', _("Assigned"), 'info'),
                ('maintenance', _("In maintenance"), 'warning'),
                ('out_of_service', _("Out of service"), 'danger')]]
        sections.append({'title': _("Fleet"), 'icon': 'fa-bus', 'bars': bars, 'tiles': [
            self._tile(_("Vehicles"), total_vehicles, color='primary', res_model='fleet.vehicle',
                       domain=vdomain, name=_("Vehicles")),
            self._tile(_("Available now"), availability.get('available', 0), color='success',
                       res_model='fleet.vehicle',
                       domain=vdomain + [('nexora_availability', '=', 'available')],
                       name=_("Available vehicles")),
            self._tile(_("Unavailable"), unavailable, color='danger' if unavailable else 'success',
                       res_model='fleet.vehicle',
                       domain=vdomain + [('nexora_availability', 'in', ('maintenance', 'out_of_service'))],
                       name=_("Unavailable vehicles")),
            self._tile(_("Utilization"), utilization, display=f"{utilization:.0f}%",
                       sub=_("trip hours, last %s days", days),
                       color='success' if utilization >= 60 else 'warning' if utilization >= 30 else 'secondary',
                       res_model='nexora.transport.trip',
                       domain=co + [('state', '=', 'done')], name=_("Completed trips")),
            self._tile(_("Documents at risk"), len(doc_ids), sub=_("expired or expiring"),
                       color='danger' if doc_ids else 'success', res_model='fleet.vehicle',
                       domain=[('id', 'in', doc_ids)], name=_("Vehicles with document issues")),
            self._tile(_("Maintenance overdue"), len(plan_ids),
                       color='warning' if plan_ids else 'success',
                       res_model='nexora.maintenance.plan', domain=[('id', 'in', plan_ids)],
                       name=_("Overdue maintenance plans")),
        ]})

        # ------------------------------------------------------------- inventory
        Analysis = env['nexora.inventory.analysis']
        risk = dict(Analysis._read_group(co, ['risk_level'], ['__count']))

        def risk_tile(label, key, color):
            return self._tile(label, risk.get(key, 0), color=color if risk.get(key, 0) else 'success',
                              res_model='nexora.inventory.analysis',
                              domain=co + [('risk_level', '=', key)], name=label)

        needs_order = co + [('suggested_qty', '>', 0)]
        sections.append({'title': _("Inventory Risk"), 'icon': 'fa-cubes', 'tiles': [
            risk_tile(_("Stockout"), 'stockout', 'danger'),
            risk_tile(_("Critical"), 'critical', 'danger'),
            risk_tile(_("Below reorder point"), 'low', 'warning'),
            risk_tile(_("Overstock"), 'overstock', 'info'),
            risk_tile(_("No demand"), 'dead', 'secondary'),
            self._tile(_("Need ordering"), Analysis.search_count(needs_order), color='primary',
                       res_model='nexora.inventory.analysis', domain=needs_order,
                       name=_("Products to reorder")),
        ]})

        # --------------------------------------------------------------- finance
        rows = Shipment._read_group(
            delivered_d, [], ['freight_amount:sum', 'allocated_cost:sum', 'profit:sum'])
        revenue, cost, profit = (rows[0] if rows else (0.0, 0.0, 0.0))
        revenue, cost, profit = revenue or 0.0, cost or 0.0, profit or 0.0
        margin = profit / revenue * 100.0 if revenue else 0.0
        invoice_rows = Shipment._read_group(
            co + [('invoice_status', '=', 'to_invoice')], [], ['__count', 'freight_amount:sum'])
        to_invoice_count, to_invoice_amount = invoice_rows[0] if invoice_rows else (0, 0.0)
        loss_d = delivered_d + [('freight_amount', '>', 0), ('profit', '<', 0)]
        losses = Shipment.search_count(loss_d)
        sections.append({'title': _("Profitability"), 'icon': 'fa-line-chart', 'tiles': [
            self._tile(_("Freight revenue"), revenue, display=money(revenue),
                       sub=_("last %s days", days), color='primary', res_model='nexora.shipment',
                       domain=delivered_d, name=_("Delivered shipments")),
            self._tile(_("Allocated cost"), cost, display=money(cost), color='secondary',
                       res_model='nexora.shipment', domain=delivered_d, name=_("Delivered shipments")),
            self._tile(_("Profit"), profit, display=money(profit),
                       color='success' if profit >= 0 else 'danger', res_model='nexora.shipment',
                       domain=delivered_d, name=_("Delivered shipments")),
            self._tile(_("Margin"), margin, display=f"{margin:.1f}%" if revenue else '-',
                       color='secondary' if not revenue else (
                           'success' if margin >= 15 else 'warning' if margin >= 0 else 'danger')),
            self._tile(_("To invoice"), to_invoice_count or 0, display=str(to_invoice_count or 0),
                       sub=money(to_invoice_amount or 0.0),
                       color='warning' if to_invoice_count else 'success',
                       res_model='nexora.shipment',
                       domain=co + [('invoice_status', '=', 'to_invoice')],
                       name=_("Shipments to invoice")),
            self._tile(_("Loss-making"), losses, color='danger' if losses else 'success',
                       res_model='nexora.shipment', domain=loss_d,
                       name=_("Loss-making shipments")),
        ]})

        # ----------------------------------------------------------- procurement
        PR, Tender = env['nexora.purchase.request'], env['nexora.rfq.tender']
        spend_rows = env['nexora.supplier.report']._read_group(
            co + [('date', '>=', since_d)], [], ['amount:sum'])
        spend = (spend_rows[0][0] or 0.0) if spend_rows else 0.0
        poor_d = [('is_nexora_vendor', '=', True), ('nexora_vendor_rating', '=', 'd')]
        poor = env['res.partner'].search_count(poor_d)
        to_approve = PR.search_count(co + [('state', '=', 'to_approve')])
        sections.append({'title': _("Procurement"), 'icon': 'fa-shopping-cart', 'tiles': [
            self._tile(_("To approve"), to_approve, color='warning' if to_approve else 'success',
                       res_model='nexora.purchase.request',
                       domain=co + [('state', '=', 'to_approve')], name=_("Requests to approve")),
            self._tile(_("Awaiting RFQ"), PR.search_count(co + [('state', '=', 'approved')]),
                       color='info', res_model='nexora.purchase.request',
                       domain=co + [('state', '=', 'approved')], name=_("Approved requests")),
            self._tile(_("Open tenders"), Tender.search_count(co + [('state', '=', 'open')]),
                       color='info', res_model='nexora.rfq.tender',
                       domain=co + [('state', '=', 'open')], name=_("Open tenders")),
            self._tile(_("Purchase spend"), spend, display=money(spend),
                       sub=_("last %s days", days), color='primary'),
            self._tile(_("Poor vendors"), poor, sub=_("rated D"),
                       color='danger' if poor else 'success', res_model='res.partner',
                       domain=poor_d, name=_("Vendors rated D")),
        ]})

        # --------------------------------------------------------------- alerts
        Alert = env['nexora.alert']
        open_d = co + [('state', '=', 'open')]
        by_severity = dict(Alert._read_group(open_d, ['severity'], ['__count']))
        tickets_d = co + [('state', 'in', ('new', 'in_progress'))]
        tickets = env['nexora.customer.ticket'].search_count(tickets_d)
        sections.append({'title': _("Alerts & Support"), 'icon': 'fa-bell', 'tiles': [
            self._tile(_("High alerts"), by_severity.get('high', 0),
                       color='danger' if by_severity.get('high') else 'success',
                       res_model='nexora.alert', domain=open_d + [('severity', '=', 'high')],
                       name=_("High alerts")),
            self._tile(_("Medium alerts"), by_severity.get('medium', 0),
                       color='warning' if by_severity.get('medium') else 'success',
                       res_model='nexora.alert', domain=open_d + [('severity', '=', 'medium')],
                       name=_("Medium alerts")),
            self._tile(_("Low alerts"), by_severity.get('low', 0), color='secondary',
                       res_model='nexora.alert', domain=open_d + [('severity', '=', 'low')],
                       name=_("Low alerts")),
            self._tile(_("Open tickets"), tickets, color='warning' if tickets else 'success',
                       res_model='nexora.customer.ticket', domain=tickets_d,
                       name=_("Open customer tickets")),
        ]})

        types = dict(Alert._fields['alert_type'].selection)
        latest = [{
            'id': a.id, 'name': a.name, 'severity': a.severity,
            'type': types.get(a.alert_type), 'date': fields.Datetime.to_string(a.date),
            'message': a.message or '',
        } for a in Alert.search(open_d, order='severity_rank desc, date desc, id desc', limit=10)]

        return {
            'days': days, 'generated': now_s, 'sections': sections, 'alerts': latest,
            'alert_total': sum(by_severity.values()),
        }