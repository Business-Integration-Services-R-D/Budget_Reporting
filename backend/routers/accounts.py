"""Vendor ledgers and bank balances, with legacy-name compatibility."""
from fastapi import APIRouter, Depends, HTTPException
from database import db
from dependencies import get_current_user
from finance import POSTED, approved, allocation, basis, currency, rate

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
    groups = {}
    def group(doc):
        key, name = identity(doc)
        if not name:
            return None
        return groups.setdefault(key, {'id': key, 'name': name, 'debt': 0., 'receivable': 0.,
            'paid': 0., 'received': 0., 'cash_paid': 0., 'cash_received': 0.,
            'balance': 0., 'count': 0, 'payables': [], 'payments': []})
    for p in payables:
        if not approved(p):
            continue
        g = group(p)
        if g is None:
            continue
        g['payables'].append(p)
        g['count'] += 1
        g['receivable' if p.get('kind') == 'RECEIVABLE' else 'debt'] += float(p.get('usd_amount') or 0)
    for p in payments:
        if p.get("is_transfer"):
            continue
        g = group(p)
        if g is None:
            continue
        g['payments'].append(p)
        actual = float(p.get('usd_amount') or 0)
        parent = originals.get(p.get('payable_id'))
        # A legacy cancellation keeps paid money as advance/refund, not phantom debt.
        if parent and parent.get('status') != 'İPTAL':
            total, book = basis(parent)
            carrying = allocation(p, parent) * book / total if total else actual
        else:
            carrying = actual
        receipt = p.get('type') == 'TAHSİL'
        g['received' if receipt else 'paid'] += carrying
        g['cash_received' if receipt else 'cash_paid'] += actual
    for g in groups.values():
        g['balance'] = round(g['debt'] - g['paid'] - g['receivable'] + g['received'], 2)
        g['open_debt'] = round(max(0, g['debt'] - g['paid']), 2)
        g['open_receivable'] = round(max(0, g['receivable'] - g['received']), 2)
        g['fx_difference_usd'] = round((g['cash_received'] - g['received']) - (g['cash_paid'] - g['paid']), 2)
    return list(groups.values())


@router.get('/current-accounts')
async def list_current_accounts(user: dict = Depends(get_current_user)):
    groups = await _vendor_ledgers()
    return sorted([{k: v for k, v in g.items() if k not in {'payables', 'payments'}} for g in groups], key=lambda g: g['balance'], reverse=True)


@router.get('/current-accounts/{name}')
async def current_account_detail(name: str, user: dict = Depends(get_current_user)):
    vendor = await db.vendors.find_one({'$or': [{'id': name}, {'name': name}, {'aliases': name}]})
    for g in await _vendor_ledgers():
        if g['id'] == name or g['name'] == name or (vendor and g['id'] == vendor['id']):
            for collection in ('payables', 'payments'):
                for doc in g[collection]:
                    doc.pop('_id', None)
            return {'id': g['id'], 'name': g['name'],
                'summary': {k: v for k, v in g.items() if k not in {'payables', 'payments', 'name', 'id'}},
                'payables': sorted(g['payables'], key=lambda p: p.get('due_date') or '', reverse=True),
                'payments': sorted(g['payments'], key=lambda p: p.get('date') or '', reverse=True)}
    raise HTTPException(404, 'Cari hesap bulunamadı.')


async def _bank_rows():
    banks = await db.banks.find({}, {'_id': 0}).to_list(None)
    movements = await db.payments.find(POSTED).to_list(None)
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
    return await db.payments.find({**POSTED, '$or': [{'bank_account_id': bank['id']},
        {'bank_account_id': {'$in': [None, '']}, 'payment_method': {'$in': [bank['name'], *bank.get('aliases', [])]}}]}, {'_id': 0}).sort('date', -1).to_list(None)
