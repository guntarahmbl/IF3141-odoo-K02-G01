from odoo import models, fields


class ReminderLog(models.Model):
    _name = 'manajemen_piutang.reminder_log'
    _description = 'Log Pengiriman Reminder WhatsApp'
    _order = 'waktu_kirim desc'

    tagihan_id = fields.Many2one(
        'manajemen_piutang.tagihan',
        string='Tagihan',
        required=True,
        ondelete='cascade',
    )
    konsumen_id = fields.Many2one(
        related='tagihan_id.konsumen_id',
        string='Konsumen',
        store=False,
    )
    waktu_kirim = fields.Datetime(
        string='Waktu Kirim',
        required=True,
        default=fields.Datetime.now,
    )
    jenis_pengingat = fields.Selection([
        ('h_minus_3', 'H-3 (3 Hari Sebelum Jatuh Tempo)'),
        ('h_minus_1', 'H-1 (1 Hari Sebelum Jatuh Tempo)'),
        ('manual',    'Manual (On-Demand)'),
    ], string='Jenis Pengingat', required=True)
    status_kirim = fields.Selection([
        ('terkirim', 'Terkirim'),
        ('gagal',    'Gagal'),
    ], string='Status Kirim', required=True)
    pesan_terkirim = fields.Text(string='Pesan yang Dikirim')
    keterangan_error = fields.Char(string='Keterangan Error')
