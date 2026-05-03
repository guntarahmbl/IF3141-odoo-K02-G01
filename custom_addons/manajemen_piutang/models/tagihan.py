import logging
from uuid import uuid4
import requests
from datetime import date, timedelta, datetime
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class Tagihan(models.Model):
    _name = 'manajemen_piutang.tagihan'
    _description = 'Data Tagihan & Piutang'

    _rec_name = 'xendit_external_id'

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
    
    link_payment = fields.Char(string='Link Pembayaran (Gateway)')
    xendit_invoice_id = fields.Char(string='Xendit Invoice ID', readonly=True, copy=False)
    xendit_external_id = fields.Char(string='Xendit External ID', readonly=True, copy=False)

    is_eskalasi = fields.Boolean(string='Perlu Eskalasi', compute='_compute_eskalasi', store=True)
    days_overdue = fields.Integer(string='Hari Terlambat', compute='_compute_dashboard_metrics', store=True)
    aging_bucket = fields.Selection([
        ('lunas', 'Lunas'),
        ('belum_jatuh_tempo', 'Belum Jatuh Tempo'),
        ('jatuh_tempo_hari_ini', 'Jatuh Tempo Hari Ini'),
        ('terlambat_1_7', 'Terlambat 1-7 Hari'),
        ('terlambat_8_30', 'Terlambat 8-30 Hari'),
        ('terlambat_30_plus', 'Terlambat >30 Hari'),
    ], string='Aging Piutang', compute='_compute_dashboard_metrics', store=True)

    @api.depends('tgl_jatuh_tempo', 'status_lunas')
    def _compute_dashboard_metrics(self):
        today = date.today()
        for rec in self:
            if rec.status_lunas == 'lunas':
                rec.days_overdue = 0
                rec.aging_bucket = 'lunas'
                continue

            if not rec.tgl_jatuh_tempo:
                rec.days_overdue = 0
                rec.aging_bucket = 'belum_jatuh_tempo'
                continue

            days_overdue = (today - rec.tgl_jatuh_tempo).days
            rec.days_overdue = max(days_overdue, 0)

            if days_overdue < 0:
                rec.aging_bucket = 'belum_jatuh_tempo'
            elif days_overdue == 0:
                rec.aging_bucket = 'jatuh_tempo_hari_ini'
            elif days_overdue <= 7:
                rec.aging_bucket = 'terlambat_1_7'
            elif days_overdue <= 30:
                rec.aging_bucket = 'terlambat_8_30'
            else:
                rec.aging_bucket = 'terlambat_30_plus'

    @api.depends('tgl_jatuh_tempo', 'status_lunas')
    def _compute_eskalasi(self):
        limit_hari = self.env['ir.config_parameter'].sudo().get_param('manajemen_piutang.hari_toleransi_eskalasi', 0)
        today = date.today()
        for rec in self:
            if rec.status_lunas == 'belum_lunas' and rec.tgl_jatuh_tempo:
                deadline = rec.tgl_jatuh_tempo + timedelta(days=int(limit_hari))
                rec.is_eskalasi = today > deadline
            else:
                rec.is_eskalasi = False

    def generateInvoice(self):
        params = self.env['ir.config_parameter'].sudo()
        secret_key = (params.get_param('manajemen_piutang.xendit_secret_api_key') or '').strip()

        if not secret_key:
            raise UserError('Xendit Secret API Key belum diisi. Buka Settings > Manajemen Piutang untuk mengisi kredensial Xendit.')

        callback_base_url = (params.get_param('web.base.url') or '').rstrip('/')
        processed_existing_invoice = False

        for record in self:
            if record.xendit_invoice_id and record.link_payment:
                processed_existing_invoice = True
                record._send_invoice_wa_after_xendit_create()
                continue

            external_id = f"INV-{record.id}-{uuid4().hex[:8]}"
            payload = {
                'external_id': external_id,
                'amount': float(record.total_tagihan),
                'description': f'Tagihan #{record.id} - {record.konsumen_id.nama_pelanggan}',
                'currency': 'IDR',
                'invoice_duration': 86400,
                'success_redirect_url': f'{callback_base_url}/web',
            }

            if record.konsumen_id:
                customer = {
                    'given_names': record.konsumen_id.nama_pelanggan,
                }
                if record.konsumen_id.no_wa and record._validate_no_wa(record.konsumen_id.no_wa):
                    customer['mobile_number'] = f'+{record.konsumen_id.no_wa.lstrip("+")}'
                payload['customer'] = customer

            try:
                response = requests.post(
                    'https://api.xendit.co/v2/invoices',
                    json=payload,
                    auth=(secret_key, ''),
                    timeout=15,
                )
                try:
                    result = response.json()
                except ValueError:
                    result = {}
            except requests.RequestException as exc:
                raise UserError(f'Gagal membuat invoice Xendit: {exc}') from exc

            if not response.ok:
                error_message = (
                    result.get('message')
                    or result.get('error_code')
                    or response.text[:300]
                    or response.reason
                )
                raise UserError(
                    f'Gagal membuat invoice Xendit ({response.status_code}): {error_message}'
                )

            invoice_id = result.get('id')
            invoice_url = result.get('invoice_url')

            if not invoice_id or not invoice_url:
                _logger.error(
                    'Response Xendit tidak lengkap untuk tagihan %s. Keys: %s',
                    record.id, ', '.join(sorted(result.keys())),
                )
                raise UserError(
                    'Xendit berhasil merespons, tetapi response tidak berisi ID invoice atau link pembayaran.'
                )

            record.write({
                'link_payment': invoice_url,
                'xendit_invoice_id': invoice_id,
                'xendit_external_id': result.get('external_id') or external_id,
                'status_lunas': 'belum_lunas',
            })
            record._send_invoice_wa_after_xendit_create()

        message = 'Link pembayaran Xendit berhasil dibuat dan data tagihan akan dimuat ulang.'
        if processed_existing_invoice:
            message = 'Tagihan sudah memiliki link Xendit. Data tagihan akan dimuat ulang.'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'E-Invoice Dibuat',
                'message': message,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                },
            },
        }
            
    def reconcilePayment(self):
        for record in self:
            record.status_lunas = 'lunas'

    def _send_invoice_wa_after_xendit_create(self) -> None:
        self.ensure_one()
        token = self.env['ir.config_parameter'].sudo().get_param(
            'manajemen_piutang.wa_fonnte_token', ''
        )

        if not token:
            self._buat_reminder_log(
                self, 'invoice', '',
                'gagal',
                'Fonnte Token belum dikonfigurasi.',
            )
            _logger.warning('Invoice WA tidak dikirim untuk tagihan %s karena token Fonnte kosong', self.id)
            return

        no_wa = self.konsumen_id.no_wa or ''
        if not self._validate_no_wa(no_wa):
            self._buat_reminder_log(
                self, 'invoice', '',
                'gagal',
                f'Format no_wa tidak valid: {no_wa}',
            )
            _logger.warning('Invoice WA tidak dikirim untuk tagihan %s karena no_wa tidak valid: %s', self.id, no_wa)
            return

        pesan = self._render_pesan(self, 0)
        sukses, keterangan_error = self._send_via_wa(no_wa, pesan, token)
        self._buat_reminder_log(
            self, 'invoice', pesan,
            'terkirim' if sukses else 'gagal',
            keterangan_error,
        )

        if not sukses:
            _logger.warning('Invoice WA gagal dikirim untuk tagihan %s: %s', self.id, keterangan_error)

    def _validate_no_wa(self, no_wa: str) -> bool:
        if not no_wa or not no_wa.isdigit():
            return False
        return no_wa.startswith('62') and 10 <= len(no_wa) <= 15

    def _render_pesan(self, tagihan, days_before: int) -> str:
        params = self.env['ir.config_parameter'].sudo()
        template = params.get_param('manajemen_piutang.template_pesan_wa', '')
        if not template:
            template = (
                'Halo {nama}, tagihan Anda sebesar Rp {nominal} akan jatuh tempo pada '
                '{jatuh_tempo}. Mohon segera melakukan pembayaran.'
            )

        nama = tagihan.konsumen_id.nama_pelanggan
        nominal = '{:,}'.format(tagihan.total_tagihan).replace(',', '.')
        jatuh_tempo = tagihan.tgl_jatuh_tempo.strftime('%d/%m/%Y')

        pesan = template.format(nama=nama, nominal=nominal, jatuh_tempo=jatuh_tempo)

        if tagihan.link_payment:
            pesan += '\n' + tagihan.link_payment

        return pesan

    def _send_via_wa(self, no_wa: str, pesan: str, token: str) -> tuple:
        url = 'https://api.fonnte.com/send'
        headers = {'Authorization': token}
        payload = {
            'target': no_wa,
            'message': pesan,
            'countryCode': '62',
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                return (True, '')
            return (False, f'HTTP {response.status_code}: {response.text[:200]}')
        except requests.Timeout as exc:
            return (False, f'timeout: {exc}')
        except requests.RequestException as exc:
            return (False, f'network error: {exc}')

    def _buat_reminder_log(self, tagihan, jenis_pengingat: str, pesan: str,
                           status_kirim: str, keterangan_error: str = '') -> None:
        self.env['manajemen_piutang.reminder_log'].sudo().create({
            'tagihan_id': tagihan.id,
            'jenis_pengingat': jenis_pengingat,
            'pesan_terkirim': pesan,
            'status_kirim': status_kirim,
            'keterangan_error': keterangan_error,
        })

    def _is_duplicate_log(self, tagihan, jenis_pengingat: str) -> bool:
        today = date.today()
        today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
        tomorrow_start = today_start + timedelta(days=1)
        domain = [
            ('tagihan_id', '=', tagihan.id),
            ('jenis_pengingat', '=', jenis_pengingat),
            ('status_kirim', '=', 'terkirim'),
            ('waktu_kirim', '>=', fields.Datetime.to_string(today_start)),
            ('waktu_kirim', '<', fields.Datetime.to_string(tomorrow_start)),
        ]
        return bool(self.env['manajemen_piutang.reminder_log'].sudo().search(domain, limit=1))

    def _get_tagihan_reminder(self, days_before: int):
        target_date = date.today() + timedelta(days=days_before)
        return self.env['manajemen_piutang.tagihan'].search([
            ('status_lunas', '=', 'belum_lunas'),
            ('tgl_jatuh_tempo', '=', target_date),
        ])

    def _get_reminder_schedule(self):
        raw_schedule = self.env['ir.config_parameter'].sudo().get_param(
            'manajemen_piutang.hari_reminder',
            '3,0',
        )
        days = []
        for raw_day in (raw_schedule or '').split(','):
            raw_day = raw_day.strip()
            if not raw_day:
                continue
            if not raw_day.isdigit():
                _logger.warning('Jadwal reminder tidak valid: %s', raw_schedule)
                continue
            days.append(int(raw_day))

        if not days:
            days = [3, 0]

        return [(day, self._get_reminder_type(day)) for day in sorted(set(days), reverse=True)]

    def _get_reminder_type(self, days_before: int) -> str:
        if days_before == 0:
            return 'h_0'
        if days_before == 1:
            return 'h_minus_1'
        if days_before == 3:
            return 'h_minus_3'
        return 'scheduled'

    def run_daily_reminder(self) -> None:
        token = self.env['ir.config_parameter'].sudo().get_param(
            'manajemen_piutang.wa_fonnte_token', ''
        )
        if not token:
            _logger.error('Fonnte Token belum dikonfigurasi')
            return

        schedule = self._get_reminder_schedule()

        for days_before, jenis_pengingat in schedule:
            tagihan_list = self._get_tagihan_reminder(days_before)
            for tagihan in tagihan_list:
                try:
                    if self._is_duplicate_log(tagihan, jenis_pengingat):
                        continue

                    no_wa = tagihan.konsumen_id.no_wa or ''
                    if not self._validate_no_wa(no_wa):
                        self._buat_reminder_log(
                            tagihan, jenis_pengingat, '',
                            'gagal',
                            f'Format no_wa tidak valid: {no_wa}',
                        )
                        continue

                    pesan = self._render_pesan(tagihan, days_before)
                    sukses, keterangan_error = self._send_via_wa(no_wa, pesan, token)
                    self._buat_reminder_log(
                        tagihan, jenis_pengingat, pesan,
                        'terkirim' if sukses else 'gagal',
                        keterangan_error,
                    )
                except Exception as exc:
                    _logger.error(
                        'Error saat memproses reminder untuk tagihan %s: %s',
                        tagihan.id, exc
                    )

    def kirim_reminder_wa(self) -> dict:
        if self.status_lunas == 'lunas':
            raise UserError('Tagihan sudah lunas, tidak perlu mengirim reminder.')

        token = self.env['ir.config_parameter'].sudo().get_param(
            'manajemen_piutang.wa_fonnte_token', ''
        )
        if not token:
            raise UserError(
                'Fonnte Token belum dikonfigurasi. Buka Pengaturan untuk mengisi token.'
            )

        no_wa = self.konsumen_id.no_wa or ''
        if not self._validate_no_wa(no_wa):
            self._buat_reminder_log(
                self, 'manual', '',
                'gagal',
                f'Format no_wa tidak valid: {no_wa}',
            )
            raise UserError(f'Format no_wa tidak valid: {no_wa}')

        pesan = self._render_pesan(self, 0)
        sukses, keterangan_error = self._send_via_wa(no_wa, pesan, token)
        self._buat_reminder_log(
            self, 'manual', pesan,
            'terkirim' if sukses else 'gagal',
            keterangan_error,
        )

        if not sukses:
            raise UserError(f'Gagal mengirim reminder WA: {keterangan_error}')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Reminder Terkirim',
                'message': 'Reminder WhatsApp berhasil dikirim.',
                'type': 'success',
            },
        }
