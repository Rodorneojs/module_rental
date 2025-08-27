/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

patch(ListController.prototype, {
    /**
     * Override onRecordSaved to refresh searchpanel after saving
     */
    async onRecordSaved(record) {
        const result = await super.onRecordSaved(...arguments);
        
        // Si es el modelo sale.order, refrescar el searchpanel
        if (this.props.resModel === 'sale.order') {
            // Refrescar los contadores del searchpanel
            if (this.searchPanel) {
                await this.searchPanel.reload();
            }
            // Refrescar la lista completa
            await this.model.load();
        }
        
        return result;
    }
});