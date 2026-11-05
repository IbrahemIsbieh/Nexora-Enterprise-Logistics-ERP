from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NexoraAnalysisWizard(models.TransientModel):
    _name = 'nexora.analysis.wizard'
    _description = 'Run Inventory Analysis'

    warehouse_ids = fields.Many2many('stock.warehouse', string='Warehouses', required=True)
    history_days = fields.Integer(string='History Window (days)')
    horizon_days = fields.Integer(string='Planning Horizon (days)')
    service_level = fields.Float(string='Service Level (%)')
    default_lead_time = fields.Float(string='Default Lead Time (days)')
    overstock_days = fields.Integer(string='Overstock Threshold (days)')
    create_plan = fields.Boolean(string='Generate Replenishment Plan', default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        params = self.env['nexora.inventory.analysis']._nexora_default_params()
        for key, value in params.items():
            res.setdefault(key, value)
        if 'warehouse_ids' in fields_list and not res.get('warehouse_ids'):
            warehouses = self.env['stock.warehouse'].search(
                [('company_id', 'in', self.env.companies.ids)])
            res['warehouse_ids'] = [(6, 0, warehouses.ids)]
        return res

    def action_run(self):
        self.ensure_one()
        if self.history_days < 14:
            raise UserError(_("The history window must be at least 14 days."))
        if not 50 <= self.service_level <= 99.9:
            raise UserError(_("Service level must be between 50 and 99.9 %."))

        Analysis = self.env['nexora.inventory.analysis'].sudo()
        Plan = self.env['nexora.replenishment.plan']
        for warehouse in self.warehouse_ids:
            Analysis._run_for_warehouse(
                warehouse,
                history_days=self.history_days,
                horizon_days=self.horizon_days,
                service_level=self.service_level,
                default_lead_time=self.default_lead_time,
                overstock_days=self.overstock_days,
            )
            if self.create_plan:
                plan = Plan._create_from_analysis(warehouse)
                if plan:
                    plan._notify_responsible()

        action = self.env['ir.actions.act_window']._for_xml_id(
            'nexora_inventory.action_nexora_inventory_analysis')
        action['domain'] = [('warehouse_id', 'in', self.warehouse_ids.ids)]
        return action