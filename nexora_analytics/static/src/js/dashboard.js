/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class NexoraDashboard extends Component {
    static template = "nexora_analytics.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: null, data: null });
        onWillStart(async () => {
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("nexora.dashboard", "get_data", []);
        } catch (error) {
            this.state.error =
                (error && error.data && error.data.message) || "The dashboard could not be loaded.";
        }
        this.state.loading = false;
    }

    async refresh() {
        await this.load();
    }

    openTile(tile) {
        if (!tile.res_model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: tile.name || tile.label,
            res_model: tile.res_model,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: tile.domain || [],
        });
    }

    openAlert(alert) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: alert.name,
            res_model: "nexora.alert",
            res_id: alert.id,
            views: [[false, "form"]],
        });
    }

    openAllAlerts() {
        this.action.doAction("nexora_analytics.action_nexora_alert");
    }

    severityClass(severity) {
        return { high: "text-bg-danger", medium: "text-bg-warning", low: "text-bg-secondary" }[
            severity
        ];
    }
}

registry.category("actions").add("nexora_analytics.dashboard", NexoraDashboard);