import json
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class XenditWebhookController(http.Controller):

    @http.route('/xendit/webhook/status', type='http', auth='public', methods=['GET'], csrf=False)
    def xendit_webhook_status(self, **kwargs):
        expected_token = request.env['ir.config_parameter'].sudo().get_param(
            'manajemen_piutang.xendit_webhook_token'
        )
        return request.make_json_response({
            'success': True,
            'service': 'xendit_webhook',
            'configured': bool(expected_token),
        }, status=200)

    @http.route('/xendit/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def xendit_webhook(self, **kwargs):
        payload_raw = request.httprequest.data.decode('utf-8') if request.httprequest.data else '{}'

        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            _logger.warning('Xendit webhook payload is not valid JSON: %s', payload_raw)
            return request.make_json_response({'success': False, 'message': 'invalid json'}, status=400)

        if not isinstance(payload, dict):
            _logger.warning('Xendit webhook payload root must be a JSON object: %s', payload_raw)
            return request.make_json_response({'success': False, 'message': 'invalid payload'}, status=400)

        params = request.env['ir.config_parameter'].sudo()
        expected_token = params.get_param('manajemen_piutang.xendit_webhook_token')
        callback_token = request.httprequest.headers.get('x-callback-token')

        if not expected_token:
            _logger.error('Xendit webhook rejected because callback token is not configured')
            return request.make_json_response({'success': False, 'message': 'callback token not configured'}, status=503)

        if callback_token != expected_token:
            _logger.warning('Xendit webhook rejected because callback token is invalid')
            return request.make_json_response({'success': False, 'message': 'unauthorized'}, status=401)

        data = payload.get('data')
        if not isinstance(data, dict):
            data = {}

        invoice_id = data.get('id') or payload.get('id')
        external_id = data.get('external_id') or payload.get('external_id')
        status = (data.get('status') or payload.get('status') or '').upper()
        paid_amount = data.get('paid_amount') or data.get('amount') or payload.get('paid_amount') or payload.get('amount') or 0
        payment_id = data.get('payment_id') or payload.get('payment_id')
        expired_at = data.get('expired_at') or payload.get('expired_at')
        event = (payload.get('event') or payload.get('event_type') or '').lower()

        is_paid_event = status in ('PAID', 'SETTLED', 'SUCCEEDED', 'COMPLETED') or bool(payment_id) or event.endswith('.paid')
        is_expired_event = status in ('EXPIRED', 'VOIDED') or bool(expired_at) or event.endswith('.expired')

        if not invoice_id and not external_id:
            _logger.warning('Xendit webhook missing invoice identifier: %s', payload)
            return request.make_json_response({'success': False, 'message': 'missing invoice identifier'}, status=400)

        domain = []
        if invoice_id and external_id:
            domain = ['|', ('xendit_invoice_id', '=', invoice_id), ('xendit_external_id', '=', external_id)]
        elif invoice_id:
            domain = [('xendit_invoice_id', '=', invoice_id)]
        else:
            domain = [('xendit_external_id', '=', external_id)]

        tagihan = request.env['manajemen_piutang.tagihan'].sudo().search(domain, limit=1)

        if not tagihan:
            _logger.info('Xendit webhook received but no matching tagihan: invoice_id=%s external_id=%s', invoice_id, external_id)
            return request.make_json_response({'success': True, 'message': 'no matching invoice'}, status=200)

        if is_paid_event:
            if not paid_amount:
                _logger.warning('Xendit webhook paid event missing amount for tagihan %s', tagihan.id)
                return request.make_json_response({'success': False, 'message': 'missing payment amount'}, status=400)

            try:
                paid_amount = float(paid_amount)
            except (TypeError, ValueError):
                _logger.warning('Xendit webhook paid amount is invalid for tagihan %s: %s', tagihan.id, paid_amount)
                return request.make_json_response({'success': False, 'message': 'invalid payment amount'}, status=400)

            if paid_amount != float(tagihan.total_tagihan):
                _logger.warning(
                    'Xendit webhook amount mismatch for tagihan %s: paid=%s expected=%s',
                    tagihan.id, paid_amount, tagihan.total_tagihan,
                )
                return request.make_json_response({'success': False, 'message': 'payment amount mismatch'}, status=400)

            pembayaran_model = request.env['manajemen_piutang.pembayaran'].sudo()
            existing_payment = pembayaran_model.search([
                '|',
                ('id_transaksi', '=', invoice_id),
                ('id_transaksi', '=', payment_id or external_id),
            ], limit=1)

            if not existing_payment:
                pembayaran_model.create({
                    'id_transaksi': payment_id or invoice_id or external_id or f'TRX-XENDIT-{tagihan.id}',
                    'nominal_masuk': paid_amount,
                    'waktu_bayar': fields.Datetime.now(),
                    'status_settlement': status.lower() or 'paid',
                    'tagihan_id': tagihan.id,
                })

            tagihan.write({'status_lunas': 'lunas'})
            _logger.info('Xendit webhook marked tagihan %s as paid', tagihan.id)

        if is_expired_event and not is_paid_event:
            tagihan.write({'status_lunas': 'belum_lunas'})
            _logger.info('Xendit webhook marked tagihan %s as expired', tagihan.id)

        return request.make_json_response({'success': True}, status=200)
