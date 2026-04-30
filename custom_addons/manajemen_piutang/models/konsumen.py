from odoo import models, fields, api

class Konsumen(models.Model):
    _name = 'manajemen_piutang.konsumen'
    _description = 'Data Master Konsumen'
    _rec_name = 'nama_pelanggan'
    _order = 'nama_pelanggan asc, id desc'

    nama_pelanggan = fields.Char(string='Nama Pelanggan', required=True)
    no_wa = fields.Char(string='Nomor WhatsApp', required=True, help="Gunakan format 628...")
    tipe_pelanggan = fields.Selection([
        ('b2b', 'B2B (Perusahaan)'),
        ('b2c', 'B2C (Individu)')
    ], string='Tipe Pelanggan', default='b2c')
    alamat = fields.Text(string='Alamat')
    
    tagihan_ids = fields.One2many('manajemen_piutang.tagihan', 'konsumen_id', string='Riwayat Tagihan')

    @api.model
    def create(self, vals):
        """Override method bawaan Odoo, merepresentasikan processSaveConsument()"""
        if 'no_wa' in vals:
            vals['no_wa'] = self.validateWA(vals['no_wa'])
        return super(Konsumen, self).create(vals)

    def validateWA(self, no_wa):
        """Method untuk memformat nomor telepon otomatis"""
        if no_wa and no_wa.startswith('0'):
            return '62' + no_wa[1:]
        return no_wa