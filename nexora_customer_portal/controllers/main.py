from datetime import datetime

import pytz

from odoo import Command, _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

from ..models.ticket import get_portal_responsible

TEMPERATURES = [('ambient', 'Ambient'), ('chilled', 'Chilled'), ('frozen', 'Frozen')]
TICKET_TYPES = [('complaint', 'Complaint'), ('service', 'Service Request'), ('inquiry', 'Inquiry')]
SHIPMENT_STEPS = [('draft', 'Received'), ('planned', 'Planned'),
                  ('in_transit', 'In Transit'), ('delivered', 'Delivered')]


class NexoraCustomerPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _nx_partner(self):
        return request.env.user.partner_id.commercial_partner_id

    def _nx_domain(self):
        return [('partner_id', 'child_of', [self._nx_partner().id])]

    def _nx_can_request(self, partner):
        enabled = request.env['ir.config_parameter'].sudo().get_param(
            'nexora_portal.requests_enabled', 'True')
        return partner.is_nexora_customer and str(enabled) in ('True', 'true', '1')

    def _nx_addresses(self, partner):
        partner = partner.sudo()
        return partner | partner.child_ids.filtered(lambda p: p.type in ('delivery', 'other'))

    @staticmethod
    def _nx_float(value, default=0.0):
        try:
            return max(float(str(value).replace(',', '.')), 0.0)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _nx_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _nx_parse_dt(value):
        """Convert an HTML datetime-local value (user timezone) to a naive UTC datetime."""
        if not value:
            return False
        try:
            naive = datetime.strptime(value.replace('T', ' ')[:16], '%Y-%m-%d %H:%M')
        except ValueError:
            return False
        tz = pytz.timezone(request.env.user.tz or 'UTC')
        return tz.localize(naive).astimezone(pytz.utc).replace(tzinfo=None)

    def _nx_check(self, model, record_id, access_token=None):
        try:
            return self._document_check_access(model, record_id, access_token=access_token)
        except (AccessError, MissingError):
            return None

    # ------------------------------------------------------------------
    # Home counters
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        for key, model in (('nx_shipment_count', 'nexora.shipment'),
                           ('nx_order_count', 'nexora.transport.order'),
                           ('nx_ticket_count', 'nexora.customer.ticket')):
            if key in counters:
                Model = request.env[model]
                values[key] = Model.search_count(self._nx_domain()) \
                    if Model.has_access('read') else 0
        return values

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    @http.route(['/my/shipments', '/my/shipments/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_shipments(self, page=1, sortby=None, filterby=None, **kw):
        values = self._prepare_portal_layout_values()
        Shipment = request.env['nexora.shipment']
        sortings = {
            'date': {'label': _('Planned Delivery'), 'order': 'planned_delivery_date desc, id desc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'state': {'label': _('Status'), 'order': 'state, id desc'},
        }
        filters = {
            'all': {'label': _('All'), 'domain': []},
            'active': {'label': _('In Progress'),
                       'domain': [('state', 'in', ('draft', 'planned', 'in_transit'))]},
            'delivered': {'label': _('Delivered'), 'domain': [('state', '=', 'delivered')]},
            'failed': {'label': _('Failed'), 'domain': [('state', '=', 'failed')]},
        }
        sortby = sortby if sortby in sortings else 'date'
        filterby = filterby if filterby in filters else 'all'
        domain = self._nx_domain() + [('state', '!=', 'cancelled')] + filters[filterby]['domain']
        count = Shipment.search_count(domain)
        pager = portal_pager(
            url='/my/shipments', url_args={'sortby': sortby, 'filterby': filterby},
            total=count, page=page, step=self._items_per_page)
        shipments = Shipment.search(
            domain, order=sortings[sortby]['order'],
            limit=self._items_per_page, offset=pager['offset'])
        values.update({
            'shipments': shipments, 'page_name': 'nexora_shipment', 'pager': pager,
            'default_url': '/my/shipments', 'searchbar_sortings': sortings, 'sortby': sortby,
            'searchbar_filters': filters, 'filterby': filterby,
            'shipment_states': dict(Shipment._fields['state'].selection),
        })
        return request.render('nexora_customer_portal.portal_my_shipments', values)

    @http.route('/my/shipments/<int:shipment_id>', type='http', auth='public', website=True)
    def portal_shipment_page(self, shipment_id, access_token=None, **kw):
        shipment = self._nx_check('nexora.shipment', shipment_id, access_token)
        if not shipment:
            return request.redirect('/my')
        state_order = [step[0] for step in SHIPMENT_STEPS]
        current = state_order.index(shipment.state) if shipment.state in state_order \
            else (state_order.index('in_transit') if shipment.state == 'failed' else -1)
        steps = [{'label': label, 'done': idx <= current, 'current': idx == current}
                 for idx, (key, label) in enumerate(SHIPMENT_STEPS)]
        invoice = shipment.invoice_id if shipment.invoice_id.state == 'posted' \
            else request.env['account.move']
        values = {
            'shipment': shipment,
            'token': access_token or shipment.access_token,
            'steps': steps,
            'events': shipment.event_ids.filtered(lambda e: e.event_type != 'note').sorted(
                lambda e: (e.date, e.id), reverse=True),
            'documents': shipment.document_ids.filtered('visible_to_customer'),
            'invoice': invoice,
            'invoice_url': invoice.get_portal_url() if invoice else False,
            'shipment_states': dict(shipment._fields['state'].selection),
            'page_name': 'nexora_shipment',
        }
        return request.render('nexora_customer_portal.portal_shipment_page', values)

    @http.route('/my/shipments/<int:shipment_id>/waybill', type='http', auth='public', website=True)
    def portal_shipment_waybill(self, shipment_id, access_token=None, **kw):
        shipment = self._nx_check('nexora.shipment', shipment_id, access_token)
        if not shipment:
            return request.redirect('/my')
        return self._show_report(
            model=shipment, report_type='pdf',
            report_ref='nexora_transport.action_report_shipment_waybill', download=True)

    @http.route('/my/shipments/<int:shipment_id>/document/<int:document_id>',
                type='http', auth='public', website=True)
    def portal_shipment_document(self, shipment_id, document_id, access_token=None, **kw):
        shipment = self._nx_check('nexora.shipment', shipment_id, access_token)
        if not shipment:
            return request.redirect('/my')
        document = shipment.document_ids.filtered(
            lambda d: d.id == document_id and d.visible_to_customer)
        if not document:
            return request.not_found()
        stream = request.env['ir.binary']._get_stream_from(
            document, 'file', filename_field='filename')
        return stream.get_response(as_attachment=True)

    @http.route('/my/shipments/<int:shipment_id>/pod/<string:kind>',
                type='http', auth='public', website=True)
    def portal_shipment_pod(self, shipment_id, kind, access_token=None, **kw):
        if kind not in ('signature', 'photo'):
            return request.not_found()
        shipment = self._nx_check('nexora.shipment', shipment_id, access_token)
        if not shipment or shipment.state != 'delivered' or not shipment['pod_' + kind]:
            return request.not_found()
        stream = request.env['ir.binary']._get_image_stream_from(shipment, 'pod_' + kind)
        return stream.get_response()

    # ------------------------------------------------------------------
    # Transport orders
    # ------------------------------------------------------------------
    @http.route(['/my/transport-orders', '/my/transport-orders/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_orders(self, page=1, sortby=None, filterby=None, **kw):
        values = self._prepare_portal_layout_values()
        Order = request.env['nexora.transport.order']
        sortings = {
            'date': {'label': _('Newest'), 'order': 'order_date desc, id desc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'state': {'label': _('Status'), 'order': 'state, id desc'},
        }
        filters = {
            'all': {'label': _('All'), 'domain': []},
            'requests': {'label': _('Awaiting Confirmation'), 'domain': [('state', '=', 'draft')]},
            'open': {'label': _('Open'), 'domain': [('state', 'in', ('confirmed', 'in_progress'))]},
            'done': {'label': _('Completed'), 'domain': [('state', '=', 'done')]},
        }
        sortby = sortby if sortby in sortings else 'date'
        filterby = filterby if filterby in filters else 'all'
        domain = self._nx_domain() + filters[filterby]['domain']
        count = Order.search_count(domain)
        pager = portal_pager(
            url='/my/transport-orders', url_args={'sortby': sortby, 'filterby': filterby},
            total=count, page=page, step=self._items_per_page)
        orders = Order.search(domain, order=sortings[sortby]['order'],
                              limit=self._items_per_page, offset=pager['offset'])
        values.update({
            'orders': orders, 'page_name': 'nexora_order', 'pager': pager,
            'default_url': '/my/transport-orders', 'searchbar_sortings': sortings,
            'sortby': sortby, 'searchbar_filters': filters, 'filterby': filterby,
            'order_states': dict(Order._fields['state'].selection),
            'can_request': self._nx_can_request(self._nx_partner()),
        })
        return request.render('nexora_customer_portal.portal_my_orders', values)

    @http.route('/my/transport-orders/<int:order_id>', type='http', auth='public', website=True)
    def portal_order_page(self, order_id, access_token=None, **kw):
        order = self._nx_check('nexora.transport.order', order_id, access_token)
        if not order:
            return request.redirect('/my')
        values = {
            'order': order,
            'token': access_token or order.access_token,
            'shipments': order.shipment_ids.filtered(lambda s: s.state != 'cancelled'),
            'order_states': dict(order._fields['state'].selection),
            'shipment_states': dict(request.env['nexora.shipment']._fields['state'].selection),
            'success': kw.get('success'),
            'page_name': 'nexora_order',
        }
        return request.render('nexora_customer_portal.portal_order_page', values)

    @http.route('/my/transport-orders/<int:order_id>/cancel', type='http', auth='user',
                methods=['POST'], website=True)
    def portal_order_cancel(self, order_id, **kw):
        order = request.env['nexora.transport.order'].search(
            self._nx_domain() + [('id', '=', order_id), ('portal_request', '=', True),
                                 ('state', '=', 'draft')], limit=1)
        if order:
            order.sudo().action_cancel()
            order.sudo().message_post(body=_("Cancelled by the customer from the portal."))
        return request.redirect('/my/transport-orders')

    # ------------------------------------------------------------------
    # New transport request
    # ------------------------------------------------------------------
    def _request_form_values(self, partner, post=None, errors=None):
        values = self._prepare_portal_layout_values()
        values.update({
            'addresses': self._nx_addresses(partner), 'temperatures': TEMPERATURES,
            'post': post or {}, 'errors': errors or {}, 'page_name': 'nexora_request',
        })
        return values

    @http.route('/my/transport-requests/new', type='http', auth='user', website=True)
    def portal_transport_request_new(self, **kw):
        partner = self._nx_partner()
        if not self._nx_can_request(partner):
            return request.redirect('/my')
        return request.render('nexora_customer_portal.portal_transport_request_new',
                              self._request_form_values(partner))

    @http.route('/my/transport-requests/submit', type='http', auth='user',
                methods=['POST'], website=True)
    def portal_transport_request_submit(self, **post):
        partner = self._nx_partner()
        if not self._nx_can_request(partner):
            return request.redirect('/my')
        env = request.env
        errors = {}

        cargo = []
        for i in range(1, 6):
            description = (post.get('line_desc_%s' % i) or '').strip()
            if not description:
                continue
            temperature = post.get('line_temp_%s' % i)
            cargo.append(Command.create({
                'name': description,
                'quantity': self._nx_float(post.get('line_qty_%s' % i), 1.0) or 1.0,
                'weight': self._nx_float(post.get('line_weight_%s' % i)),
                'volume': self._nx_float(post.get('line_volume_%s' % i)),
                'temperature_class': temperature if temperature in dict(TEMPERATURES) else 'ambient',
                'hazardous': bool(post.get('line_haz_%s' % i)),
            }))
        if not cargo:
            errors['cargo'] = _("Add at least one cargo line.")

        pickup_dt = self._nx_parse_dt(post.get('requested_pickup'))
        delivery_dt = self._nx_parse_dt(post.get('requested_delivery'))
        if (post.get('requested_pickup') and not pickup_dt) \
                or (post.get('requested_delivery') and not delivery_dt):
            errors['dates'] = _("Enter valid dates.")
        elif pickup_dt and delivery_dt and delivery_dt < pickup_dt:
            errors['dates'] = _("The delivery cannot be requested before the pickup.")

        allowed = self._nx_addresses(partner)
        new_name = (post.get('new_name') or '').strip()
        new_street = (post.get('new_street') or '').strip()
        new_city = (post.get('new_city') or '').strip()
        delivery = env['res.partner']
        if new_street or new_city:
            if not (new_street and new_city):
                errors['address'] = _("Enter both the street and the city of the new address.")
        else:
            delivery_id = self._nx_int(post.get('delivery_partner_id'))
            delivery = allowed.filtered(lambda p: p.id == delivery_id)
            if not delivery:
                errors['delivery'] = _("Choose a delivery address or enter a new one.")
        pickup_id = self._nx_int(post.get('pickup_partner_id'))
        pickup = allowed.filtered(lambda p: p.id == pickup_id)

        if errors:
            return request.render('nexora_customer_portal.portal_transport_request_new',
                                  self._request_form_values(partner, post, errors))

        if not delivery:
            delivery = env['res.partner'].sudo().create({
                'parent_id': partner.id, 'type': 'delivery',
                'name': new_name or partner.name, 'street': new_street, 'city': new_city,
                'phone': post.get('new_phone') or False,
                'country_id': partner.country_id.id,
            })
        responsible = get_portal_responsible(env)
        order = env['nexora.transport.order'].sudo().create({
            'partner_id': partner.id,
            'delivery_partner_id': delivery.id,
            'pickup_partner_id': pickup.id or False,
            'requested_pickup_date': pickup_dt or False,
            'requested_delivery_date': delivery_dt or False,
            'priority': 'urgent' if post.get('urgent') else 'normal',
            'reference': (post.get('reference') or '').strip() or False,
            'notes': (post.get('notes') or '').strip() or False,
            'portal_request': True,
            'responsible_id': responsible.id,
            'line_ids': cargo,
        })
        order.message_subscribe(partner_ids=[env.user.partner_id.id])
        order.message_post(body=_("Submitted from the customer portal by %s.", env.user.name))
        order.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_("Review portal transport request"),
            user_id=responsible.id,
        )
        return request.redirect('/my/transport-orders/%s?success=1' % order.id)

    # ------------------------------------------------------------------
    # Tickets
    # ------------------------------------------------------------------
    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_tickets(self, page=1, sortby=None, filterby=None, **kw):
        values = self._prepare_portal_layout_values()
        Ticket = request.env['nexora.customer.ticket']
        sortings = {
            'date': {'label': _('Newest'), 'order': 'id desc'},
            'state': {'label': _('Status'), 'order': 'state, id desc'},
        }
        filters = {
            'all': {'label': _('All'), 'domain': []},
            'open': {'label': _('Open'), 'domain': [('state', 'in', ('new', 'in_progress'))]},
            'resolved': {'label': _('Resolved'), 'domain': [('state', 'in', ('resolved', 'closed'))]},
        }
        sortby = sortby if sortby in sortings else 'date'
        filterby = filterby if filterby in filters else 'all'
        domain = self._nx_domain() + filters[filterby]['domain']
        count = Ticket.search_count(domain)
        pager = portal_pager(
            url='/my/tickets', url_args={'sortby': sortby, 'filterby': filterby},
            total=count, page=page, step=self._items_per_page)
        tickets = Ticket.search(domain, order=sortings[sortby]['order'],
                                limit=self._items_per_page, offset=pager['offset'])
        values.update({
            'tickets': tickets, 'page_name': 'nexora_ticket', 'pager': pager,
            'default_url': '/my/tickets', 'searchbar_sortings': sortings, 'sortby': sortby,
            'searchbar_filters': filters, 'filterby': filterby,
            'ticket_states': dict(Ticket._fields['state'].selection),
            'ticket_types': dict(Ticket._fields['ticket_type'].selection),
        })
        return request.render('nexora_customer_portal.portal_my_tickets', values)

    @http.route('/my/tickets/<int:ticket_id>', type='http', auth='public', website=True)
    def portal_ticket_page(self, ticket_id, access_token=None, **kw):
        ticket = self._nx_check('nexora.customer.ticket', ticket_id, access_token)
        if not ticket:
            return request.redirect('/my')
        ticket._portal_ensure_token()
        values = {
            'ticket': ticket,
            'token': access_token or ticket.access_token,
            'ticket_states': dict(ticket._fields['state'].selection),
            'ticket_types': dict(ticket._fields['ticket_type'].selection),
            'success': kw.get('success'),
            'page_name': 'nexora_ticket',
        }
        return request.render('nexora_customer_portal.portal_ticket_page', values)

    def _ticket_form_values(self, partner, post=None, errors=None):
        values = self._prepare_portal_layout_values()
        shipments = request.env['nexora.shipment'].search(
            [('partner_id', 'child_of', [partner.id]), ('state', '!=', 'cancelled')],
            order='id desc', limit=100)
        values.update({
            'shipments': shipments, 'ticket_types': TICKET_TYPES, 'post': post or {},
            'errors': errors or {}, 'page_name': 'nexora_ticket',
        })
        return values

    @http.route('/my/tickets/new', type='http', auth='user', website=True)
    def portal_ticket_new(self, shipment_id=None, **kw):
        partner = self._nx_partner()
        if not partner.is_nexora_customer:
            return request.redirect('/my')
        return request.render('nexora_customer_portal.portal_ticket_new',
                              self._ticket_form_values(partner, {'shipment_id': shipment_id or ''}))

    @http.route('/my/tickets/submit', type='http', auth='user', methods=['POST'], website=True)
    def portal_ticket_submit(self, **post):
        partner = self._nx_partner()
        if not partner.is_nexora_customer:
            return request.redirect('/my')
        errors = {}
        subject = (post.get('subject') or '').strip()
        description = (post.get('description') or '').strip()
        if not subject:
            errors['subject'] = _("Enter a subject.")
        if not description:
            errors['description'] = _("Describe your request.")
        ticket_type = post.get('ticket_type')
        if ticket_type not in dict(TICKET_TYPES):
            ticket_type = 'complaint'
        shipment = request.env['nexora.shipment']
        shipment_id = self._nx_int(post.get('shipment_id'))
        if shipment_id:
            shipment = request.env['nexora.shipment'].search(
                [('id', '=', shipment_id), ('partner_id', 'child_of', [partner.id])], limit=1)
        if errors:
            return request.render('nexora_customer_portal.portal_ticket_new',
                                  self._ticket_form_values(partner, post, errors))
        ticket = request.env['nexora.customer.ticket'].sudo().create({
            'partner_id': partner.id,
            'subject': subject,
            'description': description,
            'ticket_type': ticket_type,
            'shipment_id': shipment.id or False,
            'source': 'portal',
            'responsible_id': get_portal_responsible(request.env).id,
        })
        ticket._portal_ensure_token()
        return request.redirect('/my/tickets/%s?success=1' % ticket.id)