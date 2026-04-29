from uuid import uuid4

from odoo import api, models, fields
from odoo.exceptions import UserError

class Tagihan(models.Model):
    _name = 'manajemen_piutang.tagihan'
    _description = 'Data Tagihan & Piutang'
    _order = 'tgl_jatuh_tempo asc, id desc'


    konsumen_id = fields.Many2one('manajemen_piutang.konsumen', string='Pelanggan', required=True, ondelete='restrict')
    pembayaran_ids = fields.One2many('manajemen_piutang.pembayaran', 'tagihan_id', string='Riwayat Pembayaran')
    
    total_tagihan = fields.Integer(string='Total Tagihan (Rp)', required=True)
    rincian_item = fields.Text(string='Rincian Item Pesanan')
    tgl_terbit = fields.Date(string='Tanggal Terbit', default=fields.Date.context_today)
    tgl_jatuh_tempo = fields.Date(string='Tanggal Jatuh Tempo', required=True)
    
    status_lunas = fields.Selection([
        ('belum_lunas', 'Belum Lunas'),
        ('lunas', 'Lunas')
    ], string='Status Pembayaran', default='belum_lunas')

    jumlah_terbayar = fields.Float(
        string='Total Terbayar (Rp)',
        compute='_compute_tagihan_metrics',
        store=True,
    )
    sisa_tagihan = fields.Float(
        string='Sisa Tagihan (Rp)',
        compute='_compute_tagihan_metrics',
        store=True,
    )
    hari_menuju_jatuh_tempo = fields.Integer(
        string='Hari Menuju Jatuh Tempo',
        compute='_compute_tagihan_metrics',
        store=True,
    )
    kategori_aging = fields.Selection([
        ('paid', 'Lunas'),
        ('due_soon', 'Jatuh Tempo <= 3 Hari'),
        ('current', 'Belum Jatuh Tempo'),
        ('overdue_1_30', 'Terlambat 1-30 Hari'),
        ('overdue_31_60', 'Terlambat 31-60 Hari'),
        ('overdue_61_plus', 'Terlambat > 60 Hari'),
    ], string='Kategori Aging', compute='_compute_tagihan_metrics', store=True, index=True)
    
    link_payment = fields.Char(string='Link Pembayaran (Gateway)')
    xendit_invoice_id = fields.Char(string='Xendit Invoice ID', readonly=True, copy=False)
    xendit_external_id = fields.Char(string='Xendit External ID', readonly=True, copy=False)

    _sql_constraints = [
        ('total_tagihan_positive', 'CHECK(total_tagihan > 0)', 'Total tagihan harus lebih besar dari 0.'),
    ]

    @api.depends('total_tagihan', 'tgl_jatuh_tempo', 'status_lunas', 'pembayaran_ids.nominal_masuk')
    def _compute_tagihan_metrics(self):
        today = fields.Date.context_today(self)
        for record in self:
            total_terbayar = sum(record.pembayaran_ids.mapped('nominal_masuk'))
            record.jumlah_terbayar = total_terbayar
            record.sisa_tagihan = max(float(record.total_tagihan or 0) - total_terbayar, 0)

            if record.tgl_jatuh_tempo:
                delta_days = (record.tgl_jatuh_tempo - today).days
            else:
                delta_days = 0
            record.hari_menuju_jatuh_tempo = delta_days

            if record.status_lunas == 'lunas':
                record.kategori_aging = 'paid'
            elif delta_days >= 0 and delta_days <= 3:
                record.kategori_aging = 'due_soon'
            elif delta_days > 3:
                record.kategori_aging = 'current'
            else:
                keterlambatan = abs(delta_days)
                if keterlambatan <= 30:
                    record.kategori_aging = 'overdue_1_30'
                elif keterlambatan <= 60:
                    record.kategori_aging = 'overdue_31_60'
                else:
                    record.kategori_aging = 'overdue_61_plus'

    def generateInvoice(self):
        """Dipanggil saat tombol 'Kirim E-Invoice' di klik pada layar UI"""
        params = self.env['ir.config_parameter'].sudo()
        secret_key = params.get_param('manajemen_piutang.xendit_secret_api_key')

        if not secret_key:
            raise UserError('Xendit Secret API Key belum diisi. Buka Settings > Manajemen Piutang untuk mengisi kredensial Xendit.')

        callback_base_url = params.get_param('web.base.url')

        # Import requests lazily to avoid failing module import when the
        # `requests` package is not available in the container environment.
        try:
            import requests
        except Exception as exc:
            raise UserError('The `requests` library is required for Xendit integration.\n'
                            'Install it in the Odoo environment (e.g. pip install requests).') from exc

        for record in self:
            external_id = f"INV-{record.id}-{uuid4().hex[:8]}"
            payload = {
                'external_id': external_id,
                'amount': float(record.total_tagihan),
                'description': f'Tagihan #{record.id} - {record.konsumen_id.nama_pelanggan}',
                'currency': 'IDR',
                'invoice_duration': 86400,
                'success_redirect_url': f'{callback_base_url}/web',
            }

            try:
                response = requests.post(
                    'https://api.xendit.co/v2/invoices',
                    json=payload,
                    auth=(secret_key, ''),
                    timeout=15,
                )
                response.raise_for_status()
                result = response.json()
            except requests.RequestException as exc:
                raise UserError(f'Gagal membuat invoice Xendit: {exc}') from exc

            record.link_payment = result.get('invoice_url')
            record.xendit_invoice_id = result.get('id')
            record.xendit_external_id = external_id
            

            
    def reconcilePayment(self):
        """Dipanggil oleh WebhookPaymentAPI saat konsumen selesai membayar"""
        for record in self:
            record.status_lunas = 'lunas'