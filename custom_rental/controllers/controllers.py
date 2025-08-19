# -*- coding: utf-8 -*-
# from odoo import http


# class CustomRental(http.Controller):
#     @http.route('/custom_rental/custom_rental', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/custom_rental/custom_rental/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('custom_rental.listing', {
#             'root': '/custom_rental/custom_rental',
#             'objects': http.request.env['custom_rental.custom_rental'].search([]),
#         })

#     @http.route('/custom_rental/custom_rental/objects/<model("custom_rental.custom_rental"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('custom_rental.object', {
#             'object': obj
#         })

