# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _search_title(self, operator, value):
        # permite buscar por Title como si fuera name
        return [('name', operator, value)]
    
    title = fields.Char(
        string="Title",
        compute="_compute_title",
        inverse="_inverse_title",
        search="_search_title",
    )
    zone_id = fields.Many2one(
        'navigation.zone.config',
        string="Zone",
        ondelete='restrict',
        index=True,
        required=False,
    )
    featured         = fields.Boolean(string="Featured products?")
    provider_sel = fields.Char(string="Provider", required=False)
    currency_id      = fields.Many2one(
                         "res.currency",
                         string="Currency",
                         required=True,
                     )
    active_status = fields.Selection(
        [("true", "True"), ("false", "False")],
        string="Active/Status",
        required=True,
        default="true",
        help="Si está activo o no",
    )
    publish_web  = fields.Selection(
        [("true", "True"), ("false", "False")],
        string="Publish in Web",
        required=True,
        default="true",
        help="Si se publicará en la web",
    )
    price            = fields.Float(string="Price")
    quota            = fields.Integer(string="Quota")
    price_adult      = fields.Float(string="Price Adult")
    price_child      = fields.Float(string="Price Child")
    min_pax          = fields.Integer(string="Min. Pax")
    max_pax          = fields.Integer(string="Max. Pax")
    time_start       = fields.Float(string="Time Start")
    time_end         = fields.Float(string="Time End")

    type_activity = fields.Selection(
        [
            ('fullboat', 'FULLBOAT'),
            ('ticket',   'TICKET'),
        ],
        string="Type activity",
        required=True,
        default='fullboat',
    )

    # Sólo para FULLBOAT: modo Per hour vs Vacation more than one day
    fullboat_mode = fields.Selection(
        [
            ('per_hour',  'Per hour'),
            ('multi_day', 'Vacation more than one day'),
        ],
        string="FULLBOAT",
        default='per_hour',
    )

    # Cuando fullboat_mode = per_hour → casillas de tiempo
    time_30m    = fields.Boolean(string="30 Min.")
    time_1h     = fields.Boolean(string="1 hour")
    time_2h     = fields.Boolean(string="2 hours")
    time_3h     = fields.Boolean(string="3 hours")
    time_4h     = fields.Boolean(string="4 hours")
    time_5h     = fields.Boolean(string="5 hours")
    time_6h     = fields.Boolean(string="6 hours")
    time_fullday= fields.Boolean(string="Full day")

    # Cuando fullboat_mode = multi_day → días mínimos y máximos
    min_days    = fields.Integer(string="Min. number of days per Rent", default=1)
    max_days    = fields.Integer(string="Max. number of days per Rent", default=1)
    
    first_shift   = fields.Float(string="First shift")
    second_shift  = fields.Float(string="Second shift")
    third_shift   = fields.Float(string="Third shift")
    fourth_shift  = fields.Float(string="Fourth shift")
    fifth_shift   = fields.Float(string="Fifth shift")
    sixth_shift   = fields.Float(string="Sixth shift")
    seventh_shift = fields.Float(string="Seventh shift")
    eighth_shift  = fields.Float(string="Eighth shift")
    
    image_gallery_ids = fields.One2many(
        'rental.product.image',
        'product_tmpl_id',
        string='Image Gallery',
    )

    @api.constrains('image_gallery_ids')
    def _check_image_limit(self):
        for tmpl in self:
            if len(tmpl.image_gallery_ids) > 5:
                raise ValidationError(_("You can only add up to 5 images in the gallery."))
            
    # SEO Metas
    url_seo          = fields.Char(string="URL SEO",
                                  help="Slug amigable para la URL (sin espacios ni caracteres especiales)")
    seo_title        = fields.Char(string="SEO Title",
                                  help="Meta title que se mostrará en buscadores")
    meta_description = fields.Text(string="Meta Description",
                                  help="Breve descripción para SEO")
    meta_keywords    = fields.Char(string="Meta Keywords",
                                  help="Palabras clave separadas por comas")

    # ——— Textos detallados ———
    resume_text           = fields.Html(string="Resum")
    description_text      = fields.Html(string="Detailed Description")
    cancel_condition_text = fields.Html(string="Cancel Condition")
    general_condition_text= fields.Html(string="General Condition")
    collection_point_text = fields.Html(string="Collection Point")
    important_info_text   = fields.Html(string="Important Information")

    @api.depends('name')
    def _compute_title(self):
        for rec in self:
            rec.title = rec.name

    def _inverse_title(self):
        # Se llama AL GUARDAR cuando el usuario edita 'title'
        for rec in self:
            rec.name = rec.title or False

    def _search_title(self, operator, value):
        # Permite buscar/filtrar por Title como si fuera 'name'
        return [('name', operator, value)]

    @api.onchange('title')
    def _onchange_title_sync_name(self):
        # Para ver el cambio reflejado en la cabecera ANTES de guardar
        for rec in self:
            rec.name = rec.title or False
    def action_open_turn_batch_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Registrar parámetros y fechas"),
            "res_model": "rental.turn.batch.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_product_id": self.id,
                "default_hour_from": self.env.context.get("default_hour_from", 8.0),
                "default_hour_to": self.env.context.get("default_hour_to", 18.0),
                "default_yacht_id": self.env.context.get("default_yacht_id"),
                "default_season_id": self.env.context.get("default_season_id"),
            },
        }