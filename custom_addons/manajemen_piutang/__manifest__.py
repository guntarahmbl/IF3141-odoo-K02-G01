{
    'name': "Manajemen Piutang",
    'summary': 'Module Odoo untuk menyimpan Manajemen Piutang',
    'description': 'Module Odoo untuk menyimpan dan menampilkan data Manajemen Piutang',
    'sequence': -100,
    'author': "K02-G07",
    'category': 'Uncategorized',
    'version': '1.0',
    'depends': ['base'],
    'data': [
        'security/security_groups.xml', 
        'security/ir.model.access.csv',
        'data/wa_reminder_cron.xml',
        'views/konsumen_view.xml',
        'views/tagihan_view.xml',
        'views/kunjungan_view.xml',
        'views/laporan_view.xml',
        'views/pengaturan_view.xml',
        'views/reminder_log_view.xml',
        'views/menu.xml',
        'data/data_dummy.xml',
    ],
    'demo': [
        'demo/demo.xml',
    ],
    'qweb': [


    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
