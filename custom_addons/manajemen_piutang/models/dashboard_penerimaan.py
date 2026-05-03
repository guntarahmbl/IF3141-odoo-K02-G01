from odoo import fields, models, tools


class DashboardPenerimaan(models.Model):
    _name = 'manajemen_piutang.dashboard_penerimaan'
    _description = 'Dashboard Tren Penerimaan Kas'
    _auto = False
    _order = 'periode_bulan desc'

    periode_bulan = fields.Date(string='Bulan', readonly=True)
    nominal_masuk = fields.Float(string='Penerimaan Kas', readonly=True)
    jumlah_transaksi = fields.Integer(string='Jumlah Transaksi', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    row_number() OVER (ORDER BY date_trunc('month', waktu_bayar)) AS id,
                    date_trunc('month', waktu_bayar)::date AS periode_bulan,
                    coalesce(sum(nominal_masuk), 0) AS nominal_masuk,
                    count(*)::integer AS jumlah_transaksi
                FROM manajemen_piutang_pembayaran
                WHERE status_settlement = 'settlement'
                GROUP BY date_trunc('month', waktu_bayar)
            )
        """ % self._table)
