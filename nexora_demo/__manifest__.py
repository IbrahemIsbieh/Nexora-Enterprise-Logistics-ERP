{
    'name': 'Nexora Demo Data',
    'version': '19.0.1.0.0',
    'category': 'Nexora',
    'summary': 'Loads a complete demo dataset for all Nexora modules',
    'author': 'Ibrahem Issa',
    'license': 'LGPL-3',
    'depends': ['nexora_procurement', 'nexora_transport', 'nexora_maintenance'],
    'data': [],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}