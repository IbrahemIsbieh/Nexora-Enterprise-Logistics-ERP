{
    'name': 'Nexora Core',
    'version': '19.0.1.0.0',
    'category': 'Nexora',
    'author': 'Ibrahem Issa',
    'summary': 'Foundation of the Nexora Logistics & Supply Chain Suite',
    'description': """
Nexora Core
===========
Branches, customers/vendors, drivers, logistics products,
cost centers, contracts, security groups and global settings.
    """,
    'author': 'Nexora',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'contacts', 'hr', 'product', 'analytic'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/cron_data.xml',
        'views/res_company_views.xml',
        'views/res_partner_views.xml',
        'views/hr_employee_views.xml',
        'views/product_views.xml',
        'views/cost_center_views.xml',
        'views/contract_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'application': True,
    'installable': True,
}