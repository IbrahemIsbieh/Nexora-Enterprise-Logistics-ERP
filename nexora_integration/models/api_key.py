import hashlib
import ipaddress
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

KEY_PREFIX = 'nxk_'


class NexoraApiKey(models.Model):
    _name = 'nexora.api.key'
    _description = 'API Key'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True, help="Who uses this key, e.g. 'Customer ERP'.")
    active = fields.Boolean(default=True, tracking=True)
    user_id = fields.Many2one(
        'res.users', string='Acts As', required=True, tracking=True,
        help="Every request made with this key runs with this user's access rights. "
             "Use a dedicated technical user (a portal user for a customer integration).")
    responsible_id = fields.Many2one(
        'res.users', string='Order Responsible', default=lambda self: self.env.user,
        help="Becomes the responsible of the transport orders created through the API.")
    key_prefix = fields.Char(readonly=True, copy=False)
    key_hash = fields.Char(readonly=True, copy=False, index=True)
    scope_ids = fields.Many2many('nexora.api.scope', string='Scopes', tracking=True)
    allowed_ips = fields.Char(
        string='Allowed IPs', help="Comma-separated IPs or CIDR ranges. Empty = any address.")
    rate_limit = fields.Integer(
        string='Requests per Minute', default=60, help="0 = unlimited.")
    date_expiry = fields.Date(string='Expires On', tracking=True)
    last_used = fields.Datetime(readonly=True, copy=False)
    log_count = fields.Integer(compute='_compute_log_count')

    def _compute_log_count(self):
        data = {k.id: n for k, n in self.env['nexora.api.log']._read_group(
            [('key_id', 'in', self.ids)], ['key_id'], ['__count'])}
        for key in self:
            key.log_count = data.get(key.id, 0)

    @api.constrains('allowed_ips')
    def _check_allowed_ips(self):
        for key in self.filtered('allowed_ips'):
            for token in key.allowed_ips.replace(';', ',').split(','):
                token = token.strip()
                if not token:
                    continue
                try:
                    ipaddress.ip_network(token, strict=False)
                except ValueError:
                    raise ValidationError(_("'%s' is not a valid IP address or range.", token))

    @api.constrains('rate_limit')
    def _check_rate_limit(self):
        for key in self:
            if key.rate_limit < 0:
                raise ValidationError(_("The rate limit cannot be negative."))

    # ------------------------------------------------------------------
    def _generate_key(self):
        """Create a new secret. Only its hash is stored; the raw value is returned once."""
        self.ensure_one()
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        self.write({
            'key_prefix': raw[:12],
            'key_hash': hashlib.sha256(raw.encode()).hexdigest(),
        })
        self.message_post(body=_("A new key was generated (starts with %s…).", raw[:12]))
        return raw

    def action_generate_key(self):
        self.ensure_one()
        raw = self._generate_key()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'nexora_integration.action_nexora_api_key_reveal')
        action['context'] = {'default_raw_key': raw, 'default_key_id': self.id}
        return action

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('API Requests'),
            'res_model': 'nexora.api.log',
            'view_mode': 'list,form',
            'domain': [('key_id', '=', self.id)],
        }

    # ------------------------------------------------------------------
    # Runtime checks (used by the controllers)
    # ------------------------------------------------------------------
    @api.model
    def _authenticate(self, raw):
        if not raw or not raw.startswith(KEY_PREFIX):
            return self.browse()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        key = self.sudo().search([('key_hash', '=', digest)], limit=1)
        if not key:
            return key
        if key.date_expiry and key.date_expiry < fields.Date.context_today(key):
            return self.browse()
        if not key.user_id.active:
            return self.browse()
        return key

    def _ip_allowed(self, ip):
        self.ensure_one()
        if not self.allowed_ips:
            return True
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        for token in self.allowed_ips.replace(';', ',').split(','):
            token = token.strip()
            if token and address in ipaddress.ip_network(token, strict=False):
                return True
        return False

    def _is_rate_limited(self):
        self.ensure_one()
        if not self.rate_limit:
            return False
        since = fields.Datetime.now() - timedelta(seconds=60)
        used = self.env['nexora.api.log'].sudo().search_count(
            [('key_id', '=', self.id), ('create_date', '>=', since)])
        return used >= self.rate_limit

    def _touch(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if not self.last_used or self.last_used < now - timedelta(seconds=60):
            self.sudo().write({'last_used': now})


class NexoraApiKeyReveal(models.TransientModel):
    _name = 'nexora.api.key.reveal'
    _description = 'Reveal a freshly generated API key'

    key_id = fields.Many2one('nexora.api.key')
    raw_key = fields.Char(string='API Key', readonly=True)