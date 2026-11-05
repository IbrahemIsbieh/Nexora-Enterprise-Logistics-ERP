import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
import uuid
from datetime import timedelta
from urllib.parse import urlparse

import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .. import serializers

_logger = logging.getLogger(__name__)
BACKOFF_MINUTES = [1, 5, 15, 60, 240]


class NexoraWebhook(models.Model):
    _name = 'nexora.webhook'
    _description = 'Webhook Endpoint'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    url = fields.Char(string='Endpoint URL', required=True, tracking=True)
    secret = fields.Char(
        default=lambda self: secrets.token_hex(24),
        help="Used to sign every request (HMAC-SHA256). Share it with the receiver.")
    event_ids = fields.Many2many('nexora.webhook.event', string='Events', tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Only for Customer',
        domain=[('is_nexora_customer', '=', True)],
        help="Restrict the events to this customer's shipments and orders. "
             "Leave empty for all records (trip events are only sent to unrestricted endpoints).")
    delivery_ids = fields.One2many('nexora.webhook.delivery', 'webhook_id')
    pending_count = fields.Integer(compute='_compute_counts')
    failed_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        data = {}
        for webhook, state, count in self.env['nexora.webhook.delivery']._read_group(
                [('webhook_id', 'in', self.ids), ('state', 'in', ('pending', 'retry', 'failed'))],
                ['webhook_id', 'state'], ['__count']):
            data[(webhook.id, state)] = count
        for hook in self:
            hook.pending_count = data.get((hook.id, 'pending'), 0) + data.get((hook.id, 'retry'), 0)
            hook.failed_count = data.get((hook.id, 'failed'), 0)

    # ------------------------------------------------------------------
    # URL safety
    # ------------------------------------------------------------------
    @api.model
    def _validate_url(self, url):
        parsed = urlparse(url or '')
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValidationError(_("The URL must start with http:// or https://."))
        allow_private = str(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_integration.allow_private_urls', 'False')) in ('True', 'true', '1')
        if allow_private:
            return
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        try:
            infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise ValidationError(_("The host '%s' cannot be resolved.", parsed.hostname))
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if (address.is_private or address.is_loopback or address.is_link_local
                    or address.is_reserved or address.is_multicast):
                raise ValidationError(_(
                    "The address %s is internal. Enable 'Allow private webhook URLs' in the "
                    "settings if this is intentional (development only).", address))

    @api.constrains('url')
    def _check_url(self):
        for hook in self:
            self._validate_url(hook.url)

    def _matches(self, record):
        self.ensure_one()
        if not self.partner_id:
            return True
        partner = getattr(record, 'partner_id', False)
        return bool(partner) and (
            partner.commercial_partner_id == self.partner_id.commercial_partner_id)

    # ------------------------------------------------------------------
    # Queueing (called from the business models, never raises)
    # ------------------------------------------------------------------
    @api.model
    def _enqueue(self, event_code, record, extra=None):
        try:
            with self.env.cr.savepoint():
                self._enqueue_unsafe(event_code, record, extra or {})
        except Exception:
            _logger.exception("Nexora webhooks: could not queue '%s'.", event_code)

    @api.model
    def _enqueue_unsafe(self, event_code, record, extra):
        hooks = self.sudo().search(
            [('active', '=', True), ('event_ids.code', '=', event_code)])
        hooks = hooks.filtered(lambda h: h._matches(record))
        if not hooks:
            return
        record = record.sudo()
        Delivery = self.env['nexora.webhook.delivery'].sudo()
        for hook in hooks:
            uid = str(uuid.uuid4())
            body = {
                'id': uid,
                'event': event_code,
                'created': serializers.iso(fields.Datetime.now()),
                'data': serializers.serialize(record, internal=not hook.partner_id),
            }
            body.update(extra)
            Delivery.create({
                'webhook_id': hook.id,
                'event_code': event_code,
                'event_uid': uid,
                'payload': json.dumps(body, ensure_ascii=False, separators=(',', ':')),
                'res_model': record._name,
                'res_id': record.id,
            })

    def action_test(self):
        self.ensure_one()
        uid = str(uuid.uuid4())
        delivery = self.env['nexora.webhook.delivery'].create({
            'webhook_id': self.id,
            'event_code': 'webhook.ping',
            'event_uid': uid,
            'payload': json.dumps({
                'id': uid, 'event': 'webhook.ping',
                'created': serializers.iso(fields.Datetime.now()),
                'data': {'message': 'Test delivery from Nexora.'},
            }),
        })
        ok = delivery._send()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Webhook test"),
                'message': _("Delivered (HTTP %s).", delivery.response_code) if ok
                else _("Failed: %s", delivery.error or delivery.response_code),
                'type': 'success' if ok else 'danger',
                'sticky': not ok,
            },
        }

    def action_view_deliveries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deliveries'),
            'res_model': 'nexora.webhook.delivery',
            'view_mode': 'list,form',
            'domain': [('webhook_id', '=', self.id)],
        }


class NexoraWebhookDelivery(models.Model):
    _name = 'nexora.webhook.delivery'
    _description = 'Webhook Delivery'
    _order = 'id desc'

    webhook_id = fields.Many2one('nexora.webhook', required=True, ondelete='cascade', index=True)
    event_code = fields.Char(required=True)
    event_uid = fields.Char(string='Event ID', index=True)
    payload = fields.Text()
    res_model = fields.Char()
    res_id = fields.Integer()
    state = fields.Selection(
        [('pending', 'Pending'), ('retry', 'Retrying'), ('done', 'Delivered'), ('failed', 'Failed')],
        default='pending', index=True)
    attempts = fields.Integer(readonly=True)
    next_attempt = fields.Datetime(default=fields.Datetime.now, index=True)
    sent_date = fields.Datetime(readonly=True)
    response_code = fields.Integer(readonly=True)
    response_body = fields.Text(readonly=True)
    error = fields.Char(readonly=True)

    # ------------------------------------------------------------------
    def _send(self):
        self.ensure_one()
        hook = self.webhook_id
        icp = self.env['ir.config_parameter'].sudo()
        timeout = float(icp.get_param('nexora_integration.webhook_timeout') or 10)
        max_attempts = int(icp.get_param('nexora_integration.webhook_max_attempts') or 5)

        body = (self.payload or '').encode('utf-8')
        timestamp = str(int(time.time()))
        signature = hmac.new(
            (hook.secret or '').encode(), timestamp.encode() + b'.' + body, hashlib.sha256
        ).hexdigest()
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Nexora-Webhook/1.0',
            'X-Nexora-Event': self.event_code,
            'X-Nexora-Delivery': self.event_uid or '',
            'X-Nexora-Timestamp': timestamp,
            'X-Nexora-Signature': 'sha256=' + signature,
        }
        ok = False
        vals = {}
        try:
            hook._validate_url(hook.url)
            response = requests.post(
                hook.url, data=body, headers=headers, timeout=timeout, allow_redirects=False)
            ok = 200 <= response.status_code < 300
            vals = {
                'response_code': response.status_code,
                'response_body': (response.text or '')[:500],
                'error': False if ok else 'HTTP %s' % response.status_code,
            }
        except (requests.RequestException, ValidationError) as exc:
            vals = {'response_code': 0, 'response_body': False, 'error': str(exc)[:500]}

        attempts = self.attempts + 1
        now = fields.Datetime.now()
        vals.update({'attempts': attempts, 'sent_date': now})
        if ok:
            vals['state'] = 'done'
        elif attempts >= max_attempts:
            vals['state'] = 'failed'
        else:
            vals['state'] = 'retry'
            vals['next_attempt'] = now + timedelta(
                minutes=BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)])
        self.write(vals)
        return ok

    def action_send_now(self):
        for delivery in self.filtered(lambda d: d.state in ('pending', 'retry', 'failed')):
            delivery._send()

    def action_retry(self):
        self.filtered(lambda d: d.state == 'failed').write(
            {'state': 'pending', 'attempts': 0, 'next_attempt': fields.Datetime.now(), 'error': False})

    @api.model
    def _cron_process_queue(self):
        batch = self.search([
            ('state', 'in', ('pending', 'retry')),
            ('next_attempt', '<=', fields.Datetime.now()),
            ('webhook_id.active', '=', True),
        ], order='id', limit=100)
        for delivery in batch:
            delivery._send()
            self.env.cr.commit()

    @api.model
    def _purge(self, limit):
        self.sudo().search([('state', '=', 'done'), ('create_date', '<', limit)]).unlink()