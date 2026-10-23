"""Vendor ledgers, guided offsets, and bank balances."""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import db
from dependencies import get_current_user, require_finance, write_audit, _uid, _now
from finance import POSTED, CASH_POSTED, approved, allocation, basis, currency, rate, number
from settlements import settlement_lock, prepare_payment, sync_payable

router = APIRouter(tags=['accounts'])


async def _vendor_ledgers(store=None):
    db = store if store is not None else globals()["db"]
    vendors = await db.vendors.find({}).to_list(None)
    by_id = {v['id']: v for v in vendors}
    by_name = {name: v for v in vendors for name in [v.get('name'), *v.get('aliases', [])] if name}
    def identity(doc):
        vendor = by_id.get(doc.get('vendor_id')) or by_name.get(doc.get('vendor'))
        return (vendor['id'], vendor['name']) if vendor else (doc.get('vendor'), doc.get('vendor'))
    payables = await db.payables.find({}).to_list(None)
    payments = await db.payments.find(POSTED).to_list(None)
    originals = {p['id']: p for p in payables}
    by_parent = {}
    for payment in payments:
        by_parent.setdefault(payment.get('payable_id'), []).append(payment)
    groups = {}
    def group(doc):
        key, name = identity(doc)
        if not name:
            return None
        return groups.setdefault(key, {'id': key, 'name': name, 'debt': 0., 'receivable': 0.,
            'paid': 0., 'received': 0., 'unallocated_paid': 0., 'unallocated_received': 0.,
            'cash_paid': 0., 'cash_received': 0., 'open_debt': 0., 'open_receivable': 0.,
            'balance': 0., 'document_balance': 0., 'count': 0, 'payables': [], 'payments': [],
            '_cash_carrying_paid': 0., '_cash_carrying_received': 0.})
    for p in payables:
        if not approved(p):
            continue
        g = group(p)
        if g is None:
            continue
        total, book = basis(p)
        expected_type = 'TAHSİL' if p.get('kind') == 'RECEIVABLE' else 'TEDİYE'
        settled = sum(
            allocation(payment, p) * book / total if total else 0
            for payment in by_parent.get(p['id'], [])
            if payment.get('type') == expected_type)
        open_usd = round(max(0, book - settled), 2)
        g['payables'].append({**p, 'ledger_remaining_usd': open_usd})
        g['count'] += 1
        side = 'receivable' if p.get('kind') == 'RECEIVABLE' else 'debt'
        g[side] += book
        g['open_receivable' if side == 'receivable' else 'open_debt'] += open_usd
    for p in payments:
        if p.get("is_transfer"):
            continue
        g = group(p)
        if g is None:
            continue
        g['payments'].append(p)
        actual = 0 if p.get('is_offset') else float(p.get('usd_amount') or 0)
        parent = originals.get(p.get('payable_id'))
        expected_kind = 'RECEIVABLE' if p.get('type') == 'TAHSİL' else 'PAYABLE'
        linked = parent and approved(parent) and parent.get('kind', 'PAYABLE') == expected_kind
        if linked:
            total, book = basis(parent)
            carrying = allocation(p, parent) * book / total if total else float(p.get('usd_amount') or 0)
        else:
            carrying = float(p.get('usd_amount') or 0)
        receipt = p.get('type') == 'TAHSİL'
        if linked:
            g['received' if receipt else 'paid'] += carrying
        else:
            g['unallocated_received' if receipt else 'unallocated_paid'] += carrying
        if not p.get('is_offset'):
            g['cash_received' if receipt else 'cash_paid'] += actual
            g['_cash_carrying_received' if receipt else '_cash_carrying_paid'] += carrying
    for g in groups.values():
        g['open_debt'] = round(g['open_debt'], 2)
        g['open_receivable'] = round(g['open_receivable'], 2)
        g['document_balance'] = round(g['open_debt'] - g['open_receivable'], 2)
        g['balance'] = round(g['document_balance'] - g['unallocated_paid'] + g['unallocated_received'], 2)
        g['fx_difference_usd'] = round(
            (g['cash_received'] - g['_cash_carrying_received'])
            - (g['cash_paid'] - g['_cash_carrying_paid']), 2)
        g['has_open_documents'] = g['open_debt'] > .005 or g['open_receivable'] > .005
        g['is_closed'] = not g['has_open_documents'] and g['unallocated_paid'] <= .005 and g['unallocated_received'] <= .005
    return list(groups.values())


@router.get('/current-accounts')
async def list_current_accounts(user: dict = Depends(get_current_user)):
    groups = await _vendor_ledgers()
    return sorted([{k: v for k, v in g.items() if k not in {'payables', 'payments'} and not k.startswith('_')} for g in groups], key=lambda g: g['balance'], reverse=True)


@router.get('/current-accounts/{name}')
async def current_account_detail(name: str, user: dict = Depends(get_current_user)):
    vendor = await db.vendors.find_one({'$or': [{'id': name}, {'name': name}, {'aliases': name}]})
    for g in await _vendor_ledgers():
        if g['id'] == name or g['name'] == name or (vendor and g['id'] == vendor['id']):
            for collection in ('payables', 'payments'):
                for doc in g[collection]:
                    doc.pop('_id', None)
            return {'id': g['id'], 'name': g['name'],
                'summary': {k: v for k, v in g.items() if k not in {'payables', 'payments', 'name', 'id'} and not k.startswith('_')},
                'payables': sorted(g['payables'], key=lambda p: p.get('due_date') or '', reverse=True),
                'payments': sorted(g['payments'], key=lambda p: p.get('date') or '', reverse=True)}
    raise HTTPException(404, 'Cari hesap bulunamadı.')


class OffsetInput(BaseModel):
    amount_usd: Optional[float] = None
    date: Optional[str] = None
    description: Optional[str] = None


def _find_ledger(groups, name, vendor=None):
    return next((g for g in groups if g['id'] == name or g['name'] == name or (vendor and g['id'] == vendor['id'])), None)


@router.post('/current-accounts/{name}/offset')
async def offset_current_account(name: str, body: OffsetInput, user: dict = Depends(require_finance)):
    """Set off open payables and receivables without creating a bank/cash movement."""
    vendor = await db.vendors.find_one({'$or': [{'id': name}, {'name': name}, {'aliases': name}]})
    ledger = _find_ledger(await _vendor_ledgers(), name, vendor)
    if not ledger:
        raise HTTPException(404, 'Cari hesap bulunamadı.')
    maximum = min(ledger['open_debt'], ledger['open_receivable'])
    amount = number(body.amount_usd if body.amount_usd is not None else maximum, 'Mahsup tutarı', positive=True)
    if amount > maximum + .005:
        raise HTTPException(400, 'Mahsup tutarı açık borç veya açık alacak tutarını aşamaz.')

    open_docs = [p for p in ledger['payables'] if float(p.get('ledger_remaining_usd') or 0) > .005]
    group_id = _uid()
    movement_date = body.date or datetime.now(timezone.utc).date().isoformat()
    description = body.description or 'Cari borç/alacak mahsubu'
    async with settlement_lock(*(p['id'] for p in open_docs)):
        refreshed = _find_ledger(await _vendor_ledgers(), name, vendor)
        maximum = min(refreshed['open_debt'], refreshed['open_receivable']) if refreshed else 0
        if amount > maximum + .005:
            raise HTTPException(409, 'Açık tutarlar değişti. Güncel değerleri kontrol edip yeniden deneyin.')
        docs = [p for p in refreshed['payables'] if float(p.get('ledger_remaining_usd') or 0) > .005]
        movements = []
        for kind, movement_type in (('PAYABLE', 'TEDİYE'), ('RECEIVABLE', 'TAHSİL')):
            remaining = amount
            candidates = sorted(
                (p for p in docs if p.get('kind', 'PAYABLE') == kind),
                key=lambda p: (p.get('due_date') or '9999', p.get('created_at') or ''))
            for payable in candidates:
                if remaining <= .005:
                    break
                open_usd = float(payable.get('ledger_remaining_usd') or 0)
                take = min(remaining, open_usd)
                total, book = basis(payable)
                original_amount = take * total / book if book else take
                code = currency(payable.get('currency'))
                doc = {
                    'id': _uid(), 'type': movement_type, 'payable_id': payable['id'],
                    'vendor': payable.get('vendor'), 'vendor_id': payable.get('vendor_id'),
                    'ship': payable.get('ship'), 'description': description, 'date': movement_date,
                    'amount': round(original_amount, 4), 'currency': code, 'usd_amount': round(take, 2),
                    'fx_rate': await rate(db, code), 'usd_fx_rate': await rate(db, 'USD'),
                    'posting_status': 'posted', 'approved': True,
                    'is_offset': True, 'offset_group_id': group_id,
                    'created_at': _now(), 'created_by': user['email'],
                }
                await prepare_payment(db, doc)
                movements.append(doc)
                remaining = round(remaining - take, 2)
            if remaining > .005:
                raise HTTPException(409, 'Mahsup için yeterli açık belge bulunamadı.')
        await db.payments.insert_many(movements)
        parent_ids = sorted({movement['payable_id'] for movement in movements})
        for payable_id in parent_ids:
            await sync_payable(db, payable_id)
    await write_audit(user, 'offset', 'current_account', str(ledger['id']), {
        'offset_group_id': group_id, 'amount_usd': amount, 'movement_count': len(movements)})
    return {
        'ok': True, 'offset_group_id': group_id, 'amount_usd': round(amount, 2),
        'movement_count': len(movements),
        'remaining_debt': round(ledger['open_debt'] - amount, 2),
        'remaining_receivable': round(ledger['open_receivable'] - amount, 2),
    }


async def _bank_rows():
    banks = await db.banks.find({}, {'_id': 0}).to_list(None)
    movements = await db.payments.find(CASH_POSTED).to_list(None)
    out = []
    for bank in banks:
        names = [bank['name'], *bank.get('aliases', [])]
        rows = [p for p in movements if p.get('bank_account_id') == bank['id'] or (not p.get('bank_account_id') and p.get('payment_method') in names)]
        incoming = sum(float(p.get('usd_amount') or 0) for p in rows if p.get('type') == 'TAHSİL')
        outgoing = sum(float(p.get('usd_amount') or 0) for p in rows if p.get('type') == 'TEDİYE')
        code = currency(bank.get('currency'))
        native_net = 0.
        estimated = False
        for p in rows:
            if p.get('bank_amount') is not None and p.get('bank_currency') == code:
                value = float(p['bank_amount'])
            elif currency(p.get('currency')) == code:
                value = float(p.get('amount') or 0)
            elif code == 'USD':
                value = float(p.get('usd_amount') or 0)
            else:
                # Old cross-currency records have no saved bank amount: expose an estimate.
                try:
                    value = float(p.get('usd_amount') or 0) * await rate(db, 'USD') / await rate(db, code)
                except HTTPException:
                    value = 0
                estimated = True
            native_net += value if p.get('type') == 'TAHSİL' else -value
        opening = float(bank.get('balance') or 0)
        out.append({**bank, 'in': incoming, 'out': outgoing, 'net': round(incoming - outgoing, 2),
            'opening_balance': opening, 'balance_currency': code,
            'native_net': round(native_net, 2), 'current_balance': round(opening + native_net, 2),
            'balance_estimated': estimated})
    return out


@router.get('/bank-accounts')
async def list_bank_accounts(user: dict = Depends(get_current_user)):
    return await _bank_rows()


@router.get('/bank-accounts/{bank_name}/transactions')
async def bank_transactions(bank_name: str, user: dict = Depends(get_current_user)):
    bank = await db.banks.find_one({'$or': [{'id': bank_name}, {'name': bank_name}, {'aliases': bank_name}]})
    if not bank:
        raise HTTPException(404, 'Hesap bulunamadı.')
    return await db.payments.find({**CASH_POSTED, '$or': [{'bank_account_id': bank['id']},
        {'bank_account_id': {'$in': [None, '']}, 'payment_method': {'$in': [bank['name'], *bank.get('aliases', [])]}}]}, {'_id': 0}).sort('date', -1).to_list(None)
