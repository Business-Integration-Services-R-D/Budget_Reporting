"""Business invariants against isolated databases, never application data."""
from datetime import datetime, timedelta, timezone
import io
from unittest.mock import patch
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
import httpx
import uuid
import unittest
from openpyxl import load_workbook
from routers import accounts, dashboard, payments, payables, reports, master, export
import dependencies


class BusinessRuleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncIOMotorClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=5000)
        self.db = self.client['budget_business_test_' + uuid.uuid4().hex]
        self.patches = [patch.object(m, 'db', self.db) for m in (accounts, dashboard, payments, payables, reports, master, export, dependencies)]
        for p in self.patches: p.start()
        self.user = {'id': 'tester', 'email': 'tester@local.dev', 'role': 'admin'}
        self.app = FastAPI()
        for m in (accounts, dashboard, payments, payables, reports, master, export): self.app.include_router(m.router, prefix='/api')
        self.app.dependency_overrides[dependencies.get_current_user] = lambda: self.user
        self.api = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')
        await self.db.banks.insert_one({'id': 'bank', 'name': 'Banka', 'currency': 'USD', 'balance': 10000})
        await self.db.vendors.insert_one({'id': 'vendor', 'name': 'Firma'})
        await self.db.currencies.insert_many([{'code': 'USD', 'rate_to_tl': 50}, {'code': 'TL', 'rate_to_tl': 1}])

    async def asyncTearDown(self):
        await self.api.aclose()
        assert self.db.name.startswith('budget_business_test_')
        await self.client.drop_database(self.db.name)
        self.client.close()
        for p in reversed(self.patches): p.stop()

    async def debt(self, **extra):
        r = await self.api.post('/api/payables', json={'kind': 'PAYABLE', 'vendor': 'Firma', 'ship': 'Gemi', 'status': 'ONAYLANDI', 'currency': 'USD', 'original_amount': 1000, 'usd_amount': 1000, 'due_date': datetime.now(timezone.utc).date().isoformat(), **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def pay(self, parent=None, **extra):
        return await self.api.post('/api/payments', json={'type': 'TEDİYE', 'payable_id': (parent or {}).get('id'), 'vendor': 'Firma', 'payment_method': 'Banka', 'amount': 400, 'currency': 'USD', **extra})

    async def kpi(self): return (await self.api.get('/api/dashboard/kpi')).json()

    async def test_receivables_and_receipts_in_current_account(self):
        p = await self.debt(kind='RECEIVABLE', original_amount=5000, usd_amount=5000)
        rows = (await self.api.get('/api/current-accounts')).json()
        self.assertEqual(rows[0]['receivable'], 5000)
        self.assertEqual(rows[0]['balance'], -5000)
        self.assertEqual((await self.pay(p, type='TAHSİL', amount=2000)).status_code, 200)
        detail = (await self.api.get('/api/current-accounts/vendor')).json()
        self.assertEqual(detail['summary']['received'], 2000)
        self.assertEqual(detail['summary']['balance'], -3000)

    async def test_cancelled_obligation_not_in_current_account_or_currency_report(self):
        p = await self.debt()
        self.assertEqual((await self.api.put('/api/payables/' + p['id'], json={'status': 'İPTAL'})).status_code, 200)
        self.assertEqual((await self.kpi())['open_payable']['total'], 0)
        self.assertEqual((await self.api.get('/api/current-accounts')).json(), [])
        self.assertEqual((await self.api.get('/api/reports/by-currency')).json(), [])

    async def test_same_currency_payment_closes_original_amount_after_fx_change(self):
        p = await self.debt(currency='TL', original_amount=50000, usd_amount=1000)
        await self.db.currencies.update_one({'code': 'USD'}, {'$set': {'rate_to_tl': 55}})
        r = await self.pay(p, amount=50000, currency='TL', fx_rate=1)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(r.json()['usd_amount'], 909.09, places=2)
        row = (await self.api.get('/api/payables/' + p['id'])).json()
        self.assertEqual(row['remaining_amount'], 0)
        self.assertEqual(row['remaining_usd'], 0)
        self.assertEqual(row['status'], 'ÖDENDİ')
        self.assertEqual(row['paid_usd'], 1000)
        self.assertAlmostEqual(row['fx_difference_usd'], -90.91, places=2)
        self.assertEqual((await self.api.get('/api/current-accounts')).json()[0]['balance'], 0)

    async def test_original_currency_overpayment_rejected_after_fx_change(self):
        p = await self.debt(currency='TL', original_amount=50000, usd_amount=1000)
        await self.db.currencies.update_one({'code': 'USD'}, {'$set': {'rate_to_tl': 55}})
        self.assertEqual((await self.pay(p, amount=51000, currency='TL', fx_rate=1)).status_code, 400)

    async def test_posted_payment_requires_existing_bank(self):
        p = await self.debt()
        for fields in [{'payment_method': None}, {'payment_method': 'Yok'}, {'bank_account_id': 'unknown'}]:
            self.assertEqual((await self.pay(p, **fields)).status_code, 400)
        self.assertEqual((await self.kpi())['net_position'], 0)

    async def test_opening_balance_and_native_currency_balance(self):
        p = await self.debt()
        self.assertEqual((await self.pay(p, amount=1000)).status_code, 200)
        b = (await self.api.get('/api/bank-accounts')).json()[0]
        self.assertEqual(b['net'], -1000)
        self.assertEqual(b['current_balance'], 9000)
        self.assertEqual(b['balance_currency'], 'USD')
        await self.db.banks.update_one({'id': 'bank'}, {'$set': {'currency': 'TL', 'balance': 100000}})
        p2 = await self.debt()
        r = await self.pay(p2, amount=1000)
        self.assertEqual(r.status_code, 200, r.text)
        b = (await self.api.get('/api/bank-accounts')).json()[0]
        # First historical USD-bank movement is estimated; second has a saved 50,000 TL debit.
        self.assertEqual(b['current_balance'], 0)
        self.assertTrue(b['balance_estimated'])

    async def test_draft_obligation_excluded_and_cannot_be_paid(self):
        p = await self.debt(status='TASLAK')
        self.assertEqual((await self.kpi())['open_payable']['total'], 0)
        self.assertEqual((await self.pay(p)).status_code, 400)
        self.assertEqual((await self.api.get('/api/current-accounts')).json(), [])
        self.assertEqual((await self.api.put('/api/payables/' + p['id'], json={'approval_status': 'approved'})).status_code, 200)
        self.assertEqual((await self.pay(p)).status_code, 200)

    async def test_draft_payment_does_not_affect_cash_or_remaining_then_posts(self):
        p = await self.debt()
        r = await self.pay(p, posting_status='draft', payment_method=None)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.kpi())['net_position'], 0)
        self.assertEqual((await self.kpi())['open_payable']['total'], 1000)
        r = await self.api.put('/api/payments/' + r.json()['id'], json={'posting_status': 'posted', 'payment_method': 'Banka'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.kpi())['net_position'], -400)
        self.assertEqual((await self.kpi())['open_payable']['total'], 600)

    async def test_unapproved_new_payment_is_draft(self):
        p = await self.debt()
        r = await self.pay(p, approved=False, payment_method=None)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['posting_status'], 'draft')
        self.assertEqual((await self.kpi())['net_position'], 0)

    async def test_partial_payment_blocks_invoice_cancel_and_approval_removal(self):
        p = await self.debt()
        await self.pay(p)
        for payload in [{'status': 'İPTAL'}, {'approval_status': 'draft'}]:
            self.assertEqual((await self.api.put('/api/payables/' + p['id'], json=payload)).status_code, 409)

    async def test_void_keeps_history_and_reverses_all_totals(self):
        p = await self.debt()
        movement = (await self.pay(p)).json()
        r = await self.api.delete('/api/payments/' + movement['id'])
        self.assertEqual(r.status_code, 200)
        self.assertTrue((await self.db.payments.find_one({'id': movement['id']}))['voided'])
        self.assertEqual((await self.api.get('/api/payments')).json(), [])
        self.assertEqual(len((await self.api.get('/api/payments?include_voided=true')).json()), 1)
        self.assertEqual((await self.kpi())['net_position'], 0)
        self.assertEqual((await self.kpi())['open_payable']['total'], 1000)
        self.assertEqual((await self.api.put('/api/payments/' + movement['id'], json={'amount': 50})).status_code, 409)

    async def test_viewer_cannot_write_and_operations_cannot_post_or_approve(self):
        p = await self.debt()
        for role in ['viewer', 'operations']:
            self.user['role'] = role
            self.assertEqual((await self.pay(p)).status_code, 403)
            self.assertEqual((await self.api.post('/api/payables', json={'status': 'ONAYLANDI'})).status_code, 403)
        self.user['role'] = 'viewer'
        self.assertEqual((await self.api.post('/api/master/vendors', json={'name': 'X'})).status_code, 403)
        self.assertEqual((await self.api.put('/api/payables/' + p['id'], json={'description': 'X'})).status_code, 403)

    async def test_future_due_not_in_overdue_ageing(self):
        await self.debt(due_date=(datetime.now(timezone.utc).date() + timedelta(days=90)).isoformat())
        buckets = {p['bucket']: p['total'] for p in (await self.api.get('/api/reports/aging')).json()}
        self.assertEqual(buckets['Vadesi gelmemiş'], 1000)
        self.assertEqual(buckets['0-30'], 0)

    async def test_upcoming_windows_net_receivables_against_payables(self):
        due = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
        await self.debt(due_date=due, original_amount=1000, usd_amount=1000)
        await self.debt(kind='RECEIVABLE', due_date=due, original_amount=1500, usd_amount=1500)
        kpi = await self.kpi()
        for window in ('week_due', 'month_due'):
            self.assertEqual(kpi[window]['payable'], 1000)
            self.assertEqual(kpi[window]['receivable'], 1500)
            self.assertEqual(kpi[window]['total'], 500)
            self.assertEqual(kpi[window]['count'], 2)
        upcoming = (await self.api.get('/api/dashboard/upcoming?days=30')).json()
        self.assertEqual({row['kind'] for row in upcoming}, {'PAYABLE', 'RECEIVABLE'})

    async def test_operational_reports_and_download_formats(self):
        due = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
        debt = await self.debt(due_date=due, description='Liman ödemesi', budget_category='OPERASYON')
        office = (await self.api.get('/api/reports/office-payments')).json()
        self.assertEqual(office['weeks'][0]['rows'][0]['budget_category'], 'OPERASYON')
        matrix = (await self.api.get('/api/reports/all-debts?months=3')).json()
        self.assertEqual(matrix['rows'][0]['total'], 1000)
        self.assertEqual(sum(matrix['rows'][0]['monthly'].values()), 1000)
        await self.pay(debt, amount=400)
        cash = (await self.api.get('/api/reports/cash-report')).json()
        self.assertEqual(cash['movements'][0]['type'], 'TEDİYE')
        self.assertEqual(cash['balances'][0]['current_balance'], 9600)
        cash_export = await self.api.get('/api/export/reports/cash-report?format=xlsx')
        workbook = load_workbook(io.BytesIO(cash_export.content), data_only=True)
        self.assertEqual(workbook['Hareketler']['A2'].value, 1)
        for fmt, content_type, signature in [('xlsx', 'spreadsheetml', b'PK'), ('pdf', 'application/pdf', b'%PDF')]:
            response = await self.api.get(f'/api/export/reports/office-payments?format={fmt}')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(content_type, response.headers['content-type'])
            self.assertTrue(response.content.startswith(signature))

    async def test_vendor_rename_keeps_old_and_new_transactions_together(self):
        p = await self.debt()
        await self.api.put('/api/master/vendors/vendor', json={'name': 'Yeni Firma'})
        r = await self.pay(p, vendor='Yeni Firma')
        self.assertEqual(r.status_code, 200, r.text)
        rows = (await self.api.get('/api/current-accounts')).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Yeni Firma')
        self.assertEqual(rows[0]['balance'], 600)
        self.assertEqual((await self.api.get('/api/current-accounts/Firma')).status_code, 200)

    async def test_bank_rename_keeps_legacy_name_movements(self):
        p = await self.debt()
        await self.db.payments.insert_one({'id': 'legacy', 'type': 'TEDİYE', 'vendor': 'Firma', 'payment_method': 'Banka', 'currency': 'USD', 'amount': 100, 'usd_amount': 100})
        await self.api.put('/api/master/banks/bank', json={'name': 'Yeni Banka'})
        self.assertEqual((await self.pay(p, payment_method='Yeni Banka')).status_code, 200)
        bank = (await self.api.get('/api/bank-accounts')).json()[0]
        self.assertEqual(bank['out'], 500)
        self.assertEqual(len((await self.api.get('/api/bank-accounts/bank/transactions')).json()), 2)

    async def test_legacy_posted_false_approved_records_stay_in_cash(self):
        await self.db.payments.insert_one({'id': 'legacy', 'type': 'TAHSİL', 'amount': 200, 'usd_amount': 200, 'approved': False, 'vendor': 'Firma'})
        self.assertEqual((await self.kpi())['net_position'], 200)

    async def test_ai_uses_same_posting_and_cancel_guards(self):
        from ai_actions import handle_create_payment, handle_update_payable, handle_delete_payable
        from fastapi import HTTPException
        p = await self.debt()
        params = {'payable_id': p['id'], 'amount': 400, 'vendor': 'Firma', 'currency': 'USD'}
        draft = await handle_create_payment(params, self.user, None, self.db)
        self.assertEqual((await self.kpi())['net_position'], 0)
        self.assertEqual((await self.db.payments.find_one({'id': draft['created_id']}))['posting_status'], 'draft')
        with self.assertRaises(HTTPException):
            await handle_create_payment({**params, 'posting_status': 'posted'}, self.user, None, self.db)
        await self.pay(p)
        with self.assertRaises(HTTPException):
            await handle_update_payable({'payable_id': p['id'], 'status': 'İPTAL'}, self.user, None, self.db)
        with self.assertRaises(HTTPException):
            await handle_delete_payable({'payable_id': p['id']}, self.user, None, self.db)
        self.user['role'] = 'viewer'
        with self.assertRaises(HTTPException):
            await handle_create_payment(params, self.user, None, self.db)

    async def test_transfer_voids_both_sides_and_never_creates_vendor_balance(self):
        from ai_actions import handle_transfer_between_banks
        await self.db.banks.insert_one({'id': 'other', 'name': 'Diğer Banka', 'currency': 'TL', 'balance': 0})
        result = await handle_transfer_between_banks({'from_bank': 'Banka', 'to_bank': 'Diğer Banka', 'amount': 100, 'currency': 'USD'}, self.user, None, self.db)
        self.assertEqual((await self.kpi())['net_position'], 0)
        self.assertEqual((await self.api.get('/api/current-accounts')).json(), [])
        balances = {b['id']: b['current_balance'] for b in (await self.api.get('/api/bank-accounts')).json()}
        self.assertEqual(balances, {'bank': 9900, 'other': 5000})
        self.assertEqual((await self.api.put('/api/payments/' + result['created_id'], json={'amount': 200})).status_code, 409)
        self.assertEqual((await self.api.delete('/api/payments/' + result['created_id'])).status_code, 200)
        self.assertEqual(await self.db.payments.count_documents({'voided': True}), 2)
        balances = {b['id']: b['current_balance'] for b in (await self.api.get('/api/bank-accounts')).json()}
        self.assertEqual(balances, {'bank': 10000, 'other': 0})

    async def test_bank_currency_locked_after_movements_and_negative_opening_allowed(self):
        await self.pay(amount=100)
        self.assertEqual((await self.api.put('/api/master/banks/bank', json={'currency': 'TL'})).status_code, 409)
        r = await self.api.post('/api/master/banks', json={'name': 'Kredili Hesap', 'currency': 'USD', 'balance': -200})
        self.assertEqual(r.status_code, 200, r.text)
        bank = next(b for b in (await self.api.get('/api/bank-accounts')).json() if b['name'] == 'Kredili Hesap')
        self.assertEqual(bank['current_balance'], -200)

    async def test_ai_read_context_matches_dashboard(self):
        from routers import ai
        p = await self.debt(original_amount=1000, usd_amount=1000)
        await self.debt(status='TASLAK', original_amount=2000, usd_amount=2000)
        await self.pay(p, amount=400)
        await self.pay(p, amount=100, posting_status='draft')
        with patch.object(ai, 'db', self.db):
            context = await ai._build_assistant_context()
        self.assertEqual(context['kpi']['open_payable']['total'], 600)
        self.assertEqual(context['kpi']['paid_total']['total'], 400)
        self.assertEqual(len(context['recent_payments']), 1)
        self.assertEqual(context['by_currency'][0]['borç'], 600)

    async def test_unrelated_edit_preserves_saved_cross_currency_allocation(self):
        p = await self.debt(currency='TL', original_amount=50000, usd_amount=1000)
        movement = (await self.pay(p, amount=1000, usd_fx_rate=50)).json()
        await self.db.currencies.update_one({'code': 'USD'}, {'$set': {'rate_to_tl': 60}})
        r = await self.api.put('/api/payments/' + movement['id'], json={'description': 'Not güncellendi'})
        self.assertEqual(r.status_code, 200, r.text)
        row = (await self.api.get('/api/payables/' + p['id'])).json()
        self.assertEqual(row['remaining_amount'], 0)
        self.assertEqual(row['status'], 'ÖDENDİ')

    async def test_client_cannot_forge_transfer_pair_to_void_other_payment(self):
        first = (await self.pay(amount=100)).json()
        second = (await self.pay(amount=100, is_transfer=True, transfer_pair_id=first['id'])).json()
        self.assertFalse(second.get('is_transfer', False))
        await self.api.delete('/api/payments/' + second['id'])
        self.assertFalse((await self.db.payments.find_one({'id': first['id']})).get('voided', False))

    async def test_current_account_keeps_open_documents_visible_at_zero_net(self):
        debt = await self.debt(original_amount=1000, usd_amount=1000)
        await self.debt(kind='RECEIVABLE', original_amount=800, usd_amount=800)
        self.assertEqual((await self.pay(debt, amount=200)).status_code, 200)
        account = (await self.api.get('/api/current-accounts/vendor')).json()['summary']
        self.assertEqual(account['balance'], 0)
        self.assertEqual(account['open_debt'], 800)
        self.assertEqual(account['open_receivable'], 800)
        self.assertTrue(account['has_open_documents'])
        self.assertFalse(account['is_closed'])

    async def test_independent_payment_is_unallocated_and_does_not_close_document(self):
        await self.debt(original_amount=1000, usd_amount=1000)
        response = await self.pay(amount=400)
        self.assertEqual(response.status_code, 200, response.text)
        account = (await self.api.get('/api/current-accounts/vendor')).json()['summary']
        self.assertEqual(account['paid'], 0)
        self.assertEqual(account['unallocated_paid'], 400)
        self.assertEqual(account['open_debt'], 1000)
        self.assertEqual(account['balance'], 600)
        self.assertEqual(account['fx_difference_usd'], 0)

    async def test_guided_offset_settles_both_sides_without_cash_and_cancels_as_group(self):
        debt = await self.debt(original_amount=1000, usd_amount=1000)
        receivable = await self.debt(kind='RECEIVABLE', original_amount=800, usd_amount=800)
        before_bank = (await self.api.get('/api/bank-accounts')).json()[0]['current_balance']
        response = await self.api.post('/api/current-accounts/vendor/offset', json={'amount_usd': 600})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['remaining_debt'], 400)
        self.assertEqual(response.json()['remaining_receivable'], 200)
        rows = await self.db.payments.find({'offset_group_id': response.json()['offset_group_id']}).to_list(None)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['is_offset'] and not row.get('payment_method') for row in rows))
        self.assertEqual((await self.kpi())['net_position'], 0)
        self.assertEqual((await self.api.get('/api/bank-accounts')).json()[0]['current_balance'], before_bank)
        account = (await self.api.get('/api/current-accounts/vendor')).json()['summary']
        self.assertEqual((account['open_debt'], account['open_receivable'], account['balance']), (400, 200, 200))
        self.assertEqual((account['paid'], account['received']), (600, 600))
        self.assertEqual((await self.api.put('/api/payments/' + rows[0]['id'], json={'amount': 10})).status_code, 409)

        cancelled = await self.api.delete('/api/payments/' + rows[0]['id'])
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()['voided_count'], 2)
        self.assertEqual(await self.db.payments.count_documents({'offset_group_id': response.json()['offset_group_id'], 'voided': True}), 2)
        account = (await self.api.get('/api/current-accounts/vendor')).json()['summary']
        self.assertEqual((account['open_debt'], account['open_receivable'], account['balance']), (1000, 800, 200))
        self.assertEqual((await self.db.payables.find_one({'id': debt['id']}))['status'], 'ONAYLANDI')
        self.assertEqual((await self.db.payables.find_one({'id': receivable['id']}))['status'], 'ONAYLANDI')

    async def test_offset_validates_limit_permission_and_forged_flags(self):
        await self.debt(original_amount=1000, usd_amount=1000)
        await self.debt(kind='RECEIVABLE', original_amount=800, usd_amount=800)
        self.assertEqual((await self.api.post('/api/current-accounts/vendor/offset', json={'amount_usd': 801})).status_code, 400)
        forged = await self.pay(amount=100, is_offset=True, offset_group_id='forged')
        self.assertEqual(forged.status_code, 200, forged.text)
        self.assertFalse(forged.json().get('is_offset', False))
        self.user['role'] = 'viewer'
        self.assertEqual((await self.api.post('/api/current-accounts/vendor/offset', json={'amount_usd': 100})).status_code, 403)
