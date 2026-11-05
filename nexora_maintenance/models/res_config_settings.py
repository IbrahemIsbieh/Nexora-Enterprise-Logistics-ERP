from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nexora_maintenance_warn_km = fields.Float(
        string='Due Soon Warning (km)',
        config_parameter='nexora_maintenance.warn_km', default=500.0)
    nexora_maintenance_warn_days = fields.Integer(
        string='Due Soon Warning (days)',
        config_parameter='nexora_maintenance.warn_days', default=14)
    nexora_maintenance_auto_create = fields.Boolean(
        string='Auto-create Orders for Due Plans',
        config_parameter='nexora_maintenance.auto_create', default=True)