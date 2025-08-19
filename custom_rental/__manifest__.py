{
    'name': 'KUMBRA Disponibilidad de Alquiler',
    'version': '18.0.1.3',
    'category': 'Rental',
    'summary': 'Disponibilidad para Alquiler de Embarcaciones',
    'author': 'Renkar',
    'depends': ['base', 'fleet','sale_renting', 'product', 'web','custom_zonas_nav','sale_management'],
    'assets': {
        'web.assets_backend': [
            'custom_rental/static/src/js/range_planner_field.js',
            'custom_rental/static/src/css/range_planner.css',
            'custom_rental/static/src/xml/range_planner_field.xml',
            'custom_rental/static/src/css/turns_view.css',
        ],
        'web.assets_qweb': [
            'custom_rental/static/src/xml/range_planner_field.xml',
        ],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/rental_availability_views.xml',
        'views/rental_blocked_period_views.xml',
        'views/block_period_range_wizard_views.xml',
        'views/rental_calendar_event_views.xml',
        #Producto
        'views/product_turns_view.xml',
        'views/product_general_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_rental_dates.xml',
        'views/sale_order_turn_fields_view.xml',

    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}