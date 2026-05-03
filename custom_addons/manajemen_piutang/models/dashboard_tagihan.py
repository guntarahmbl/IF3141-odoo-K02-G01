from odoo import fields, models, tools


class DashboardTagihan(models.Model):
    _name = 'manajemen_piutang.dashboard_tagihan'
    _description = 'Dashboard KPI Tagihan'
    _auto = False
    _order = 'sequence'

    name = fields.Char(string='KPI', readonly=True)
    display_value = fields.Char(string='Nilai', readonly=True)
    subtitle = fields.Char(string='Keterangan', readonly=True)
    sequence = fields.Integer(string='Urutan', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    1 AS id,
                    'Total Outstanding' AS name,
                    concat('Rp ', trim(to_char(coalesce(sum(total_tagihan), 0), 'FM999G999G999G999'))) AS display_value,
                    'Nilai tagihan belum lunas' AS subtitle,
                    10 AS sequence
                FROM manajemen_piutang_tagihan
                WHERE status_lunas = 'belum_lunas'

                UNION ALL

                SELECT
                    2 AS id,
                    'Total Lunas' AS name,
                    concat('Rp ', trim(to_char(coalesce(sum(total_tagihan), 0), 'FM999G999G999G999'))) AS display_value,
                    'Nilai tagihan yang sudah lunas' AS subtitle,
                    20 AS sequence
                FROM manajemen_piutang_tagihan
                WHERE status_lunas = 'lunas'

                UNION ALL

                SELECT
                    3 AS id,
                    'Tagihan Overdue' AS name,
                    count(*)::text AS display_value,
                    'Tagihan belum lunas lewat jatuh tempo' AS subtitle,
                    30 AS sequence
                FROM manajemen_piutang_tagihan
                WHERE status_lunas = 'belum_lunas'
                  AND tgl_jatuh_tempo < current_date

                UNION ALL

                SELECT
                    4 AS id,
                    'Perlu Eskalasi' AS name,
                    count(*)::text AS display_value,
                    'Tagihan yang melewati batas toleransi' AS subtitle,
                    40 AS sequence
                FROM manajemen_piutang_tagihan
                WHERE is_eskalasi IS TRUE
            )
        """ % self._table)
