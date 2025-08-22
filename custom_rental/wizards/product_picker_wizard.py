# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from ..models.schedule_states import SCHEDULE_STATE_SELECTION

class RentalProductPickerWizard(models.TransientModel):
    _name = "rental.product.picker.wizard"
    _description = "Picker de productos para líneas de venta (renting)"

    order_id = fields.Many2one("sale.order", required=True, readonly=True, ondelete="cascade")
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain="[('sale_ok','=',False), ('rent_ok','=',True)]",
    )
    product_uom_qty = fields.Float(string="Cantidad", default=1.0)
    # NUEVO: el mismo combo de estados que en la orden
    schedule_state = fields.Selection(
        SCHEDULE_STATE_SELECTION,
        string="Estado",
        default='available',
        required=True,
    )
    # --- helpers de nombres de campos de fecha (compat entre builds) ---
    def _line_date_field_names(self):
        Line = self.env["sale.order.line"]
        start = "rental_start_date" if "rental_start_date" in Line._fields else ("pickup_date" if "pickup_date" in Line._fields else None)
        stop  = "rental_return_date" if "rental_return_date" in Line._fields else ("return_date" if "return_date" in Line._fields else None)
        return start, stop

    def _order_date_field_names(self):
        Order = self.env["sale.order"]
        start = "rental_start_date" if "rental_start_date" in Order._fields else ("pickup_date" if "pickup_date" in Order._fields else None)
        stop  = "rental_return_date" if "rental_return_date" in Order._fields else ("return_date" if "return_date" in Order._fields else None)
        return start, stop

    def action_confirm(self):
        self.ensure_one()
        if not self.order_id:
            raise UserError(_("No hay pedido."))

        order = self.order_id.sudo()

        # ---- (tu código actual para crear la línea) ----
        ctx = {
            "lang": order.partner_id.lang or self.env.user.lang,
            "partner_id": order.partner_id.id,
            "company_id": order.company_id.id,
            "pricelist": order.pricelist_id.id or (order.partner_id.property_product_pricelist.id if order.partner_id else False),
        }
        Line = self.env["sale.order.line"].with_context(**ctx).sudo()

        vals = {
            "order_id": order.id,
            "product_id": self.product_id.id,
            "product_uom_qty": self.product_uom_qty or 1.0,
        }
        if "is_rental" in Line._fields:
            vals["is_rental"] = True

        # Copiar fechas de la orden a la línea, como ya hacías
        def _order_field(name):
            return name if name in self.env["sale.order"]._fields else False
        def _line_field(name):
            return name if name in Line._fields else False

        start_o = _order_field("rental_start_date") or _order_field("pickup_date")
        stop_o  = _order_field("rental_return_date") or _order_field("return_date")
        start_l = _line_field("rental_start_date") or _line_field("pickup_date")
        stop_l  = _line_field("rental_return_date") or _line_field("return_date")

        if start_o and start_l:
            vals[start_l] = getattr(order, start_o)
        if stop_o and stop_l:
            vals[stop_l] = getattr(order, stop_o)

        tmp = Line.new(vals)
        if hasattr(tmp, "_onchange_product_id"):
            tmp._onchange_product_id()
        if hasattr(tmp, "_onchange_product_uom_qty"):
            tmp._onchange_product_uom_qty()
        Line.create(tmp._convert_to_write(tmp._cache))

        # NUEVO: escribir el estado elegido en la orden
        if self.schedule_state:
            order.write({'x_schedule_state': self.schedule_state})

        # Recalcular precios si procede (tu lógica existente)
        if hasattr(order, "action_update_rental_prices"):
            try:
                order.action_update_rental_prices()
            except Exception:
                pass

        return {"type": "ir.actions.act_window_close"}
