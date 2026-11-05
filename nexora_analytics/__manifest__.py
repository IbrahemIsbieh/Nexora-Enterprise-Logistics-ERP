{
    'name': 'Nexora Analytics',
    'version': '19.0.1.0.0',
    'category': 'Nexora',
    'summary': 'Control tower dashboard, performance reports and automated operational alerts',
    'author': 'Ibrahem Issa',
    'license': 'LGPL-3',
    'depends': ['web', 'nexora_accounting', 'nexora_customer_portal'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/alert_views.xml',
        'views/report_views.xml',
        'views/dashboard_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nexora_analytics/static/src/css/dashboard.css',
            'nexora_analytics/static/src/js/dashboard.js',
            'nexora_analytics/static/src/xml/dashboard.xml',
        ],
    },
    'installable': True,
}