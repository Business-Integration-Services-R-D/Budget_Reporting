"""Integration checks against a disposable, isolated local MongoDB database.
Run from backend: .venv/bin/python -m unittest tests.test_payment_settlement -v
"""
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
import httpx
from routers import payments, payables, dashboard, reports, accounts
import dependencies
import settlements


class PaymentSettlementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncIOMotorClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=5000)
        self.db_name = 'budget_settlement_test_' + uuid.uuid4().hex
        self.db = self.client[self.db_name]
        self.patches = [patch.object(module, 'db', self.db) for module in
                        (payments, payables, dashboard, reports, accounts, dependencies)]
        for item in self.patches:
            item.start()
        settlements._locks.clear()
        app = FastAPI()
        for module in (payments, payables, dashboard, reports, accounts):
            app.include_router(module.router, prefix='/api')
        app.dependency_overrides[dependencies.get_current_user] = lambda: {'id': 'tester', 'email': 'test@local.dev', 'role': 'admin'}
        self.api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')
        await self.db.banks.insert_one({'id': 'test-bank', 'name': 'Test Bank', 'currency': 'USD'})
        self.debt = await self.create_debt()

    async def asyncTearDown(self):
        await self.api.aclose()
        assert self.db_name.startswith('budget_settlement_test_')
        await self.client.drop_database(self.db_name)
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    async def create_debt(self, kind='PAYABLE', amount=1000, **extra):
        r = await self.api.post('/api/payables', json={'kind': kind, 'vendor': 'Test Firma',
            'ship': 'Test Gemi', 'due_date': datetime.now(timezone.utc).date().isoformat(), 'usd_amount': amount,
            'original_amount': amount, 'status': 'ONAYLANDI', **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def pay(self, amount, **extra):
        r = await self.api.post('/api/payments', json={'payable_id': self.debt['id'],
            'type': 'TEDİYE', 'amount': amount, 'currency': 'USD', 'payment_method': 'Test Bank', **extra})
        return r

    async def state(self, status, remaining, debt=None):
        r = await self.api.get('/api/payables/' + (debt or self.debt)['id'])
        self.assertEqual(r.json()['status'], status)
        self.assertEqual(r.json()['remaining_usd'], remaining)

    async def test_partial_full_and_delete_reopens(self):
        first = await self.pay(400)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['vendor'], 'Test Firma')
        await self.state('KISMİ ÖDEME', 600)
        kpi = (await self.api.get('/api/dashboard/kpi')).json()
        self.assertEqual(kpi['open_payable']['total'], 600)
        self.assertEqual(kpi['week_due']['total'], 600)
        self.assertEqual(kpi['month_due']['total'], 600)
        ships = (await self.api.get('/api/dashboard/by-ship')).json()
        self.assertEqual(ships[0]['total'], 600)
        aging = (await self.api.get('/api/reports/aging')).json()
        self.assertEqual(next(row['total'] for row in aging if row['bucket'] == '0-30'), 600)
        monthly = (await self.api.get('/api/reports/monthly-projection')).json()
        self.assertEqual(monthly[0]['total'], 600)
        banks = (await self.api.get('/api/bank-accounts')).json()
        self.assertEqual(banks[0]['out'], 400)
        report = (await self.api.get('/api/reports/by-ship-detail')).json()[0]
        self.assertEqual((report['paid'], report['open']), (400, 600))
        second = await self.pay(600)
        self.assertEqual(second.status_code, 200, second.text)
        await self.state('ÖDENDİ', 0)
        await self.api.delete('/api/payments/' + second.json()['id'])
        await self.state('KISMİ ÖDEME', 600)
        await self.api.delete('/api/payments/' + first.json()['id'])
        await self.state('ONAYLANDI', 1000)
        banks = (await self.api.get('/api/bank-accounts')).json()
        self.assertEqual(banks[0]['out'], 0)
        await self.api.put('/api/payables/' + self.debt['id'], json={'usd_amount': 2000, 'original_amount': 2000})
        await self.state('ONAYLANDI', 2000)

    async def test_edit_reassign_and_detach(self):
        payment = (await self.pay(400)).json()
        r = await self.api.put('/api/payments/' + payment['id'], json={'amount': 250})
        self.assertEqual(r.status_code, 200, r.text)
        await self.state('KISMİ ÖDEME', 750)
        other = await self.create_debt(amount=500)
        r = await self.api.put('/api/payments/' + payment['id'], json={'payable_id': other['id']})
        self.assertEqual(r.status_code, 200, r.text)
        await self.state('ONAYLANDI', 1000)
        await self.state('KISMİ ÖDEME', 250, other)
        r = await self.api.put('/api/payments/' + payment['id'], json={'payable_id': None})
        self.assertEqual(r.status_code, 200)
        await self.state('ONAYLANDI', 500, other)

    async def test_invalid_links_do_not_write(self):
        for extra in [{'type': 'TAHSİL'}, {'payable_id': 'missing'}, {'vendor': 'Başka Firma'}, {'ship': 'Başka Gemi'}]:
            r = await self.pay(100, **extra)
            self.assertIn(r.status_code, [400, 404], r.text)
        self.assertEqual((await self.pay(1001)).status_code, 400)
        self.assertEqual((await self.pay(0)).status_code, 400)
        cancelled = await self.create_debt(status='İPTAL')
        self.assertEqual((await self.pay(100, payable_id=cancelled['id'])).status_code, 400)
        self.assertEqual(await self.db.payments.count_documents({}), 0)

    async def test_receivable_and_independent_payment(self):
        receivable = await self.create_debt(kind='RECEIVABLE')
        r = await self.pay(1000, payable_id=receivable['id'], type='TAHSİL')
        self.assertEqual(r.status_code, 200, r.text)
        await self.state('ÖDENDİ', 0, receivable)
        r = await self.pay(2000, payable_id=None)
        self.assertEqual(r.status_code, 200, r.text)
        original = (await self.api.get('/api/payables/' + self.debt['id'])).json()
        self.assertEqual(original['status'], 'ONAYLANDI')

    async def test_guards_and_payable_amount_edit(self):
        payment = (await self.pay(400)).json()
        self.assertEqual((await self.api.delete('/api/payables/' + self.debt['id'])).status_code, 409)
        self.assertEqual((await self.api.put('/api/payables/' + self.debt['id'], json={'usd_amount': 300, 'original_amount': 300})).status_code, 400)
        r = await self.api.put('/api/payables/' + self.debt['id'], json={'usd_amount': 1500, 'original_amount': 1500})
        self.assertEqual(r.status_code, 200, r.text)
        await self.state('KISMİ ÖDEME', 1100)
        r = await self.api.put('/api/payments/' + payment['id'], json={'amount': 1600})
        self.assertEqual(r.status_code, 400)
        await self.state('KISMİ ÖDEME', 1100)

    async def test_multiple_payments_and_concurrent_overpayment(self):
        import asyncio
        results = await asyncio.gather(self.pay(700), self.pay(700))
        self.assertEqual(sorted(r.status_code for r in results), [200, 400])
        await self.state('KISMİ ÖDEME', 300)

    async def test_manual_settlement_statuses_are_rejected(self):
        for status in ('ÖDENDİ', 'KISMİ ÖDEME'):
            r = await self.api.post('/api/payables', json={'usd_amount': 1000, 'status': status})
            self.assertEqual(r.status_code, 400, r.text)
            r = await self.api.put('/api/payables/' + self.debt['id'], json={'status': status})
            self.assertEqual(r.status_code, 400, r.text)
        payment = (await self.pay(400)).json()
        # Ordinary edits may send the unchanged, automatically calculated status.
        r = await self.api.put('/api/payables/' + self.debt['id'], json={'status': 'KISMİ ÖDEME', 'description': 'Updated'})
        self.assertEqual(r.status_code, 200, r.text)
        await self.state('KISMİ ÖDEME', 600)

    async def test_legacy_paid_without_link_is_reopened(self):
        for status in ('ÖDENDİ', 'KISMİ ÖDEME'):
            await self.db.payables.update_one({'id': self.debt['id']}, {'$set': {'status': status}})
            await settlements.sync_payable(self.db, self.debt['id'])
            await self.state('ONAYLANDI', 1000)
        # An unrelated payment to the same vendor must not close this debt.
        await self.pay(1000, payable_id=None)
        await settlements.sync_payable(self.db, self.debt['id'])
        await self.state('ONAYLANDI', 1000)

    async def test_net_position_tracks_actual_cash_movements(self):
        async def net(expected):
            r = await self.api.get('/api/dashboard/kpi')
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['net_position'], expected)
            return r.json()
        # An unpaid obligation alone is not a cash movement.
        await net(0)
        debt_payment = (await self.pay(1000)).json()
        await net(-1000)
        receivable = await self.create_debt(kind='RECEIVABLE', amount=5000)
        receipt = await self.pay(5000, payable_id=receivable['id'], type='TAHSİL')
        self.assertEqual(receipt.status_code, 200, receipt.text)
        data = await net(4000)
        self.assertEqual(data['open_payable']['total'], 0)
        self.assertEqual(data['open_receivable']['total'], 0)
        self.assertEqual(data['received_total']['total'], 5000)
        independent = (await self.pay(2000, payable_id=None)).json()
        await net(2000)
        r = await self.api.put('/api/payments/' + independent['id'], json={'amount': 500})
        self.assertEqual(r.status_code, 200, r.text)
        await net(3500)
        await self.api.delete('/api/payments/' + independent['id'])
        await net(4000)
        await self.api.delete('/api/payments/' + receipt.json()['id'])
        await net(-1000)
        await self.api.delete('/api/payments/' + debt_payment['id'])
        await net(0)
