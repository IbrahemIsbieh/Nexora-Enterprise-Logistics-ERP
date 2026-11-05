import json
import logging
import time
from datetime import datetime, timezone

from odoo import Command, _, fields, http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from .. import serializers

_logger = logging.getLogger(__name__)

SHIPMENT_STATES = {'draft', 'planned', 'in_transit', 'delivered', 'failed', 'cancelled'}
ORDER_STATES = {'draft', 'confirmed', 'in_progress', 'done', 'cancelled'}
AVAILABILITY = {'available', 'assigned', 'maintenance', 'out_of_service'}
TEMPERATURES = {'ambient', 'chilled', 'frozen'}
BASE = '/api/nexora/v1'


class ApiError(Exception):
    def __init__(self, status, code, message, extra=None, headers=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.extra, self.headers = extra or {}, headers or []


class NexoraApi(http.Controller):

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    def _authenticate(self, scope):
        icp = request.env['ir.config_parameter'].sudo()
        if str(icp.get_param('nexora_integration.api_enabled', 'True')) not in ('True', 'true', '1'):
            raise ApiError(503, 'api_disabled', "The API is disabled.")
        headers = request.httprequest.headers
        auth = headers.get('Authorization', '')
        raw = auth[7:].strip() if auth.lower().startswith('bearer ') else headers.get('X-API-Key', '')
        if not raw:
            raise ApiError(401, 'missing_key', "Send the key as 'Authorization: Bearer <key>'.")
        key = request.env['nexora.api.key']._authenticate(raw)
        if not key:
            raise ApiError(401, 'invalid_key', "The API key is invalid, expired or revoked.")
        ip = request.httprequest.remote_addr
        if not key._ip_allowed(ip):
            raise ApiError(403, 'ip_not_allowed', "This address is not allowed for the key.")
        if scope and scope not in key.scope_ids.mapped('code'):
            raise ApiError(403, 'insufficient_scope', "The key lacks the '%s' scope." % scope)
        if key._is_rate_limited():
            raise ApiError(429, 'rate_limited', "Too many requests. Slow down.",
                           headers=[('Retry-After', '60')])
        request.update_env(user=key.user_id.id)
        key._touch()
        return key

    def _respond(self, scope, handler):
        started = time.time()
        key = request.env['nexora.api.key']
        status, payload, error, headers = 200, None, None, []
        try:
            key = self._authenticate(scope)
            with request.env.cr.savepoint():
                payload, status = handler(key)
        except ApiError as exc:
            status, error, headers = exc.status, exc.code, exc.headers
            payload = {'error': dict({'code': exc.code, 'message': exc.message}, **exc.extra)}
        except AccessError:
            status, error = 403, 'forbidden'
            payload = {'error': {'code': 'forbidden',
                                 'message': "The key's user is not allowed to do this."}}
        except MissingError:
            status, error = 404, 'not_found'
            payload = {'error': {'code': 'not_found', 'message': "Record not found."}}
        except UserError as exc:
            status, error = 422, 'validation_error'
            payload = {'error': {'code': 'validation_error', 'message': str(exc.args[0])}}
        except Exception:
            _logger.exception("Nexora API: unexpected error on %s", request.httprequest.path)
            status, error = 500, 'internal_error'
            payload = {'error': {'code': 'internal_error', 'message': "Unexpected server error."}}
        try:
            request.env['nexora.api.log'].sudo().create({
                'key_id': key.id or False,
                'key_name': key.name or False,
                'method': request.httprequest.method,
                'path': request.httprequest.path[:250],
                'status': status,
                'error': error,
                'ip': request.httprequest.remote_addr,
                'duration_ms': (time.time() - started) * 1000.0,
            })
        except Exception:
            _logger.warning("Nexora API: could not write the request log.", exc_info=True)
        return request.make_json_response(payload, status=status, headers=headers)

    @staticmethod
    def _json_body():
        raw = request.httprequest.get_data(as_text=True) or '{}'
        try:
            data = json.loads(raw)
        except ValueError:
            raise ApiError(400, 'invalid_json', "The request body is not valid JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, 'invalid_json', "The request body must be a JSON object.")
        return data

    @staticmethod
    def _page():
        args = request.httprequest.args
        try:
            limit = min(max(int(args.get('limit', 50)), 1), 100)
            offset = max(int(args.get('offset', 0)), 0)
        except ValueError:
            raise ApiError(400, 'invalid_parameter', "limit and offset must be integers.")
        return limit, offset

    @staticmethod
    def _dt(value, name):
        """Parse an ISO 8601 value into a naive UTC datetime (None when empty)."""
        if value in (None, ''):
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            raise ApiError(400, 'invalid_parameter', "'%s' must be an ISO 8601 date-time." % name)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    @staticmethod
    def _int(value, name):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError(422, 'validation_error', "'%s' must be an integer." % name)

    @staticmethod
    def _number(value, name, minimum=0.0):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ApiError(422, 'validation_error', "'%s' must be a number." % name)
        if number < minimum:
            raise ApiError(422, 'validation_error', "'%s' cannot be below %s." % (name, minimum))
        return number

    @staticmethod
    def _internal():
        return request.env.user.has_group('base.group_user')

    def _find(self, model, record_id):
        record = request.env[model].search([('id', '=', record_id)], limit=1)
        if not record:
            raise ApiError(404, 'not_found', "Record %s not found." % record_id)
        return record

    @staticmethod
    def _listing(records, total, limit, offset, convert):
        return {
            'data': [convert(r) for r in records],
            'meta': {'total': total, 'limit': limit, 'offset': offset,
                     'count': len(records)},
        }

    # ------------------------------------------------------------------
    # Ping
    # ------------------------------------------------------------------
    @http.route(BASE + '/ping', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def ping(self, **kw):
        def handler(key):
            return {'data': {
                'status': 'ok',
                'key': key.name,
                'acts_as': key.user_id.name,
                'scopes': key.scope_ids.mapped('code'),
                'server_time': serializers.iso(fields.Datetime.now()),
            }}, 200
        return self._respond(None, handler)

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    @http.route(BASE + '/shipments', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def shipments(self, **kw):
        def handler(key):
            args = request.httprequest.args
            domain = []
            if args.get('state'):
                states = [s.strip() for s in args['state'].split(',') if s.strip()]
                if not set(states) <= SHIPMENT_STATES:
                    raise ApiError(400, 'invalid_parameter', "Unknown shipment state.")
                domain.append(('state', 'in', states))
            if args.get('number'):
                domain.append(('name', '=', args['number']))
            if args.get('order'):
                domain += ['|', ('order_id.name', '=', args['order']),
                           ('order_id.reference', '=', args['order'])]
            if args.get('customer_code'):
                domain.append(('partner_id.nexora_code', '=', args['customer_code']))
            for param, field, op in (('planned_from', 'planned_delivery_date', '>='),
                                     ('planned_to', 'planned_delivery_date', '<='),
                                     ('updated_since', 'write_date', '>=')):
                value = self._dt(args.get(param), param)
                if value:
                    domain.append((field, op, value))
            limit, offset = self._page()
            Shipment = request.env['nexora.shipment']
            records = Shipment.search(domain, limit=limit, offset=offset, order='id desc')
            internal = self._internal()
            return self._listing(
                records, Shipment.search_count(domain), limit, offset,
                lambda r: serializers.shipment(r, internal)), 200
        return self._respond('shipments:read', handler)

    @http.route(BASE + '/shipments/<int:shipment_id>', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def shipment_detail(self, shipment_id, **kw):
        def handler(key):
            shipment = self._find('nexora.shipment', shipment_id)
            return {'data': serializers.shipment(shipment, self._internal())}, 200
        return self._respond('shipments:read', handler)

    @http.route(BASE + '/shipments/<int:shipment_id>/tracking', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def shipment_tracking(self, shipment_id, **kw):
        def handler(key):
            shipment = self._find('nexora.shipment', shipment_id)
            events = shipment.event_ids.sorted(lambda e: (e.date, e.id))
            return {'data': {
                'shipment': shipment.name,
                'state': shipment.state,
                'events': [serializers.event(e) for e in events],
            }}, 200
        return self._respond('shipments:read', handler)

    @http.route(BASE + '/shipments/<int:shipment_id>/events', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def shipment_add_event(self, shipment_id, **kw):
        def handler(key):
            body = self._json_body()
            shipment = self._find('nexora.shipment', shipment_id)
            event_type = body.get('type', 'checkpoint')
            if event_type not in ('checkpoint', 'note'):
                raise ApiError(422, 'validation_error', "type must be 'checkpoint' or 'note'.")
            if shipment.state not in ('planned', 'in_transit'):
                raise ApiError(409, 'invalid_state',
                               "Events can only be added to planned or in-transit shipments.")
            if not (body.get('note') or body.get('location')):
                raise ApiError(422, 'validation_error', "Provide a note or a location.")
            event = request.env['nexora.shipment.event'].create({
                'shipment_id': shipment.id,
                'event_type': event_type,
                'location': str(body.get('location') or '')[:200] or False,
                'note': str(body.get('note') or '')[:500] or False,
                'date': self._dt(body.get('date'), 'date') or fields.Datetime.now(),
            })
            return {'data': serializers.event(event)}, 201
        return self._respond('shipments:write', handler)

    # ------------------------------------------------------------------
    # Transport orders
    # ------------------------------------------------------------------
    @http.route(BASE + '/orders', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def orders(self, **kw):
        def handler(key):
            args = request.httprequest.args
            domain = []
            if args.get('state'):
                states = [s.strip() for s in args['state'].split(',') if s.strip()]
                if not set(states) <= ORDER_STATES:
                    raise ApiError(400, 'invalid_parameter', "Unknown order state.")
                domain.append(('state', 'in', states))
            if args.get('reference'):
                domain.append(('reference', '=', args['reference']))
            if args.get('number'):
                domain.append(('name', '=', args['number']))
            if args.get('customer_code'):
                domain.append(('partner_id.nexora_code', '=', args['customer_code']))
            value = self._dt(args.get('updated_since'), 'updated_since')
            if value:
                domain.append(('write_date', '>=', value))
            limit, offset = self._page()
            Order = request.env['nexora.transport.order']
            records = Order.search(domain, limit=limit, offset=offset, order='id desc')
            internal = self._internal()
            return self._listing(
                records, Order.search_count(domain), limit, offset,
                lambda r: serializers.order(r, internal)), 200
        return self._respond('orders:read', handler)

    @http.route(BASE + '/orders/<int:order_id>', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def order_detail(self, order_id, **kw):
        def handler(key):
            order = self._find('nexora.transport.order', order_id)
            return {'data': serializers.order(order, self._internal())}, 200
        return self._respond('orders:read', handler)

    def _resolve_address(self, customer, value, name, required):
        Partner = request.env['res.partner'].sudo()
        if value in (None, '', {}):
            if required:
                raise ApiError(422, 'validation_error', "'%s' is required." % name)
            return Partner
        if isinstance(value, dict):
            street = str(value.get('street') or '').strip()
            city = str(value.get('city') or '').strip()
            if not (street and city):
                raise ApiError(422, 'validation_error', "'%s' needs a street and a city." % name)
            return Partner.create({
                'parent_id': customer.id, 'type': 'delivery',
                'name': str(value.get('name') or customer.name)[:120],
                'street': street[:200], 'city': city[:100],
                'phone': str(value.get('phone') or '')[:50] or False,
                'country_id': customer.country_id.id,
            })
        partner_id = self._int(value, name)
        partner = Partner.search(
            [('id', '=', partner_id), ('id', 'child_of', customer.id)], limit=1)
        if not partner:
            raise ApiError(422, 'validation_error',
                           "'%s' must be the customer or one of its addresses." % name)
        return partner

    def _cargo_commands(self, lines):
        if not isinstance(lines, list) or not 1 <= len(lines) <= 50:
            raise ApiError(422, 'validation_error', "'lines' must contain 1 to 50 cargo lines.")
        commands = []
        for index, line in enumerate(lines, start=1):
            if not isinstance(line, dict):
                raise ApiError(422, 'validation_error', "Line %s must be an object." % index)
            description = str(line.get('description') or '').strip()
            if not description:
                raise ApiError(422, 'validation_error', "Line %s needs a description." % index)
            temperature = line.get('temperature_class', 'ambient')
            if temperature not in TEMPERATURES:
                raise ApiError(422, 'validation_error',
                               "Line %s: temperature_class must be ambient, chilled or frozen." % index)
            commands.append(Command.create({
                'name': description[:200],
                'quantity': self._number(line.get('quantity', 1), 'quantity', 0.0001),
                'weight': self._number(line.get('weight_kg', 0), 'weight_kg'),
                'volume': self._number(line.get('volume_m3', 0), 'volume_m3'),
                'temperature_class': temperature,
                'hazardous': bool(line.get('hazardous', False)),
            }))
        return commands

    @http.route(BASE + '/orders', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def order_create(self, **kw):
        def handler(key):
            env = request.env
            body = self._json_body()
            user = env.user
            is_dispatcher = user.has_group('nexora_transport.group_nexora_transport_dispatcher')
            is_portal = user.has_group('base.group_portal')
            if not (is_dispatcher or is_portal):
                raise ApiError(403, 'forbidden', "The key's user cannot create transport orders.")

            Partner = env['res.partner'].sudo()
            if is_portal and not is_dispatcher:
                customer = user.commercial_partner_id
                if not customer.is_nexora_customer:
                    raise ApiError(403, 'forbidden', "Your company is not a logistics customer.")
            else:
                domain = [('is_nexora_customer', '=', True)]
                if body.get('customer_id'):
                    domain.append(('id', '=', self._int(body['customer_id'], 'customer_id')))
                elif body.get('customer_code'):
                    domain.append(('nexora_code', '=', str(body['customer_code'])))
                else:
                    raise ApiError(422, 'validation_error',
                                   "customer_id or customer_code is required.")
                customer = Partner.search(domain, limit=1)
                if not customer:
                    raise ApiError(404, 'customer_not_found', "Logistics customer not found.")

            reference = str(body.get('reference') or '').strip()[:100]
            Order = env['nexora.transport.order']
            if is_portal and not is_dispatcher:
                Order = Order.sudo()
            if reference:
                existing = Order.sudo().search(
                    [('partner_id', '=', customer.id), ('reference', '=', reference)], limit=1)
                if existing:
                    raise ApiError(409, 'duplicate_reference',
                                   "An order with this reference already exists.",
                                   extra={'order_id': existing.id, 'number': existing.name})

            priority = body.get('priority', 'normal')
            if priority not in ('normal', 'urgent'):
                raise ApiError(422, 'validation_error', "priority must be 'normal' or 'urgent'.")
            lines = self._cargo_commands(body.get('lines'))
            delivery = self._resolve_address(customer, body.get('delivery_address'),
                                             'delivery_address', True)
            pickup = self._resolve_address(customer, body.get('pickup_address'),
                                           'pickup_address', False)
            order = Order.create({
                'partner_id': customer.id,
                'delivery_partner_id': delivery.id,
                'pickup_partner_id': pickup.id or False,
                'reference': reference or False,
                'priority': priority,
                'requested_pickup_date': self._dt(body.get('requested_pickup_date'),
                                                  'requested_pickup_date') or False,
                'requested_delivery_date': self._dt(body.get('requested_delivery_date'),
                                                    'requested_delivery_date') or False,
                'notes': str(body.get('notes') or '')[:2000] or False,
                'responsible_id': key.responsible_id.id or False,
                'line_ids': lines,
            })
            order.message_post(body=_("Created through the API (key: %s).", key.name))
            if body.get('confirm') and is_dispatcher:
                order.action_confirm()
            return {'data': serializers.order(order.sudo(), self._internal())}, 201
        return self._respond('orders:write', handler)

    # ------------------------------------------------------------------
    # Fleet
    # ------------------------------------------------------------------
    @http.route(BASE + '/vehicles', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def vehicles(self, **kw):
        def handler(key):
            args = request.httprequest.args
            domain = []
            if args.get('availability'):
                if args['availability'] not in AVAILABILITY:
                    raise ApiError(400, 'invalid_parameter', "Unknown availability.")
                domain.append(('nexora_availability', '=', args['availability']))
            if args.get('class'):
                domain.append(('nexora_vehicle_class', '=', args['class']))
            if args.get('plate'):
                domain.append(('license_plate', 'ilike', args['plate']))
            limit, offset = self._page()
            Vehicle = request.env['fleet.vehicle']
            records = Vehicle.search(domain, limit=limit, offset=offset, order='license_plate')
            internal = self._internal()
            return self._listing(
                records, Vehicle.search_count(domain), limit, offset,
                lambda r: serializers.vehicle(r, internal)), 200
        return self._respond('fleet:read', handler)

    @http.route(BASE + '/vehicles/<int:vehicle_id>', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def vehicle_detail(self, vehicle_id, **kw):
        def handler(key):
            vehicle = self._find('fleet.vehicle', vehicle_id)
            return {'data': serializers.vehicle(vehicle, self._internal())}, 200
        return self._respond('fleet:read', handler)

    @http.route(BASE + '/vehicles/<int:vehicle_id>/odometer', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def vehicle_odometer(self, vehicle_id, **kw):
        def handler(key):
            body = self._json_body()
            vehicle = self._find('fleet.vehicle', vehicle_id)
            value = self._number(body.get('value'), 'value')
            if value < vehicle.odometer:
                raise ApiError(409, 'odometer_decreasing',
                               "The reading cannot be lower than the current odometer (%.0f)."
                               % vehicle.odometer)
            when = self._dt(body.get('date'), 'date')
            request.env['fleet.vehicle.odometer'].create({
                'vehicle_id': vehicle.id,
                'value': value,
                'date': when.date() if when else fields.Date.context_today(vehicle),
            })
            return {'data': serializers.vehicle(vehicle, self._internal())}, 201
        return self._respond('fleet:write', handler)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    @http.route(BASE + '/customers', type='http', auth='public', methods=['GET'],
                csrf=False, save_session=False)
    def customers(self, **kw):
        def handler(key):
            args = request.httprequest.args
            domain = [('is_nexora_customer', '=', True)]
            if args.get('code'):
                domain.append(('nexora_code', '=', args['code']))
            if args.get('name'):
                domain.append(('name', 'ilike', args['name']))
            limit, offset = self._page()
            Partner = request.env['res.partner']
            records = Partner.search(domain, limit=limit, offset=offset, order='name')
            return self._listing(
                records, Partner.search_count(domain), limit, offset, serializers.customer), 200
        return self._respond('customers:read', handler)