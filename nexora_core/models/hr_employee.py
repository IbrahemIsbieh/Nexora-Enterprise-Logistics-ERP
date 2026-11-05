from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_driver = fields.Boolean(string='Is Driver')
    driver_license_no = fields.Char(string='License Number')
    license_class = fields.Selection(
        [('b', 'Class B (Light)'), ('c', 'Class C (Truck)'),
         ('d', 'Class D (Heavy)'), ('e', 'Class E (Trailer)')],
        string='License Class',
    )
    license_expiry = fields.Date(string='License Expiry')
    license_state = fields.Selection(
        [('valid', 'Valid'), ('expiring', 'Expiring Soon'), ('expired', 'Expired')],
        compute='_compute_license_state',
    )

    def _get_license_alert_days(self):
        return int(self.env['ir.config_parameter'].sudo().get_param(
            'nexora_core.license_alert_days', 30))

    @api.depends('is_driver', 'license_expiry')
    def _compute_license_state(self):
        today = fields.Date.context_today(self)
        alert_days = self._get_license_alert_days()
        for emp in self:
            if not emp.is_driver or not emp.license_expiry:
                emp.license_state = False
            elif emp.license_expiry < today:
                emp.license_state = 'expired'
            elif (emp.license_expiry - today).days <= alert_days:
                emp.license_state = 'expiring'
            else:
                emp.license_state = 'valid'

    @api.constrains('is_driver', 'driver_license_no', 'license_expiry')
    def _check_driver_license(self):
        for emp in self.filtered('is_driver'):
            if not emp.driver_license_no or not emp.license_expiry:
                raise ValidationError(
                    _("Driver %s needs a license number and an expiry date.", emp.name))

    @api.model
    def _cron_license_expiry_alert(self):
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=self._get_license_alert_days())
        drivers = self.search([
            ('is_driver', '=', True),
            ('license_expiry', '!=', False),
            ('license_expiry', '<=', limit),
        ])
        summary = _("Driver license expiring")
        for emp in drivers:
            if emp.activity_ids.filtered(lambda a: a.summary == summary):
                continue
            user = emp.parent_id.user_id or self.env.ref('base.user_admin')
            emp.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=emp.license_expiry,
                summary=summary,
                user_id=user.id,
            )