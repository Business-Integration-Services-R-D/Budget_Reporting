"""Linked settlements close obligations in their original currency."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import HTTPException
from dependencies import _now
from finance import POSTED, posted, approved, approval, number, currency, basis, allocation, rate, resolve_bank, resolve_vendor

_locks = {}
OPEN_AMOUNT = {'$ifNull': ['$remaining_usd', '$usd_amount']}
DERIVED_STATUSES = {'ÖDENDİ', 'KISMİ ÖDEME'}


@asynccontextmanager
async def settlement_lock(*ids):
    locks = [_locks.setdefault(pid, asyncio.Lock()) for pid in sorted(set(filter(None, ids)))]
    for lock in locks:
        await lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


async def prepare_payment(db, doc, payment_id=None, preserve_conversion=False):
    if doc.get('type') not in {'TEDİYE', 'TAHSİL'}:
        raise HTTPException(400, 'İşlem türü Ödeme veya Tahsilat olmalıdır.')
    number(doc.get('amount'), positive=True)
    number(doc.get('usd_amount'), positive=True)
    await resolve_vendor(db, doc)
    bank = await resolve_bank(db, doc)
    if bank and not (preserve_conversion and doc.get("bank_amount") is not None):
        bank_currency = currency(bank.get('currency'))
        if bank_currency == currency(doc.get('currency')):
            doc['bank_amount'] = float(doc['amount'])
        elif bank_currency == 'USD':
            doc['bank_amount'] = float(doc['usd_amount'])
        else:
            tl = float(doc['amount']) * float(doc.get('fx_rate') or 0)
            if currency(doc.get('currency')) == 'USD':
                tl = float(doc['amount']) * float(doc.get('usd_fx_rate') or await rate(db, 'USD'))
            doc['bank_amount'] = tl / await rate(db, bank_currency)
        doc['bank_currency'] = bank_currency
    if not doc.get('payable_id'):
        doc['payable_id'] = None
        for field in ('allocated_amount', 'allocated_usd', 'allocation_currency', 'fx_difference_usd'):
            doc.pop(field, None)
        return
    payable = await db.payables.find_one({'id': doc['payable_id']})
    if not payable:
        raise HTTPException(404, 'Bağlanacak borç/alacak bulunamadı.')
    if payable.get('status') == 'İPTAL':
        raise HTTPException(400, 'İptal edilmiş kayda ödeme bağlanamaz.')
    if posted(doc) and not approved(payable):
        raise HTTPException(400, 'Önce borç/alacak belgesini onaylayın. Taslak belgeye gerçekleşen ödeme kaydedilemez.')
    if doc.get('type') != ('TAHSİL' if payable.get('kind') == 'RECEIVABLE' else 'TEDİYE'):
        raise HTTPException(400, 'Borç için Ödeme, alacak için Tahsilat seçilmelidir.')
    if payable.get('vendor_id') and doc.get('vendor_id') and payable['vendor_id'] != doc['vendor_id']:
        raise HTTPException(400, 'Firma seçilen kayıttaki firma ile aynı olmalıdır.')
    if not payable.get('vendor_id') and doc.get('vendor') and payable.get('vendor') and doc['vendor'] != payable['vendor']:
        vendor = await db.vendors.find_one({'id': doc.get('vendor_id'), 'aliases': payable['vendor']})
        if not vendor:
            raise HTTPException(400, 'Firma seçilen kayıttaki firma ile aynı olmalıdır.')
    if doc.get('ship') and payable.get('ship') and doc['ship'] != payable['ship']:
        raise HTTPException(400, 'Gemi seçilen kayıttaki gemi ile aynı olmalıdır.')
    doc['vendor'] = payable.get('vendor') or doc.get('vendor')
    if payable.get('vendor_id'):
        doc['vendor_id'] = payable['vendor_id']
    doc['ship'] = payable.get('ship') or doc.get('ship')
    await resolve_vendor(db, doc)
    total, book = basis(payable)
    # Recalculate allocation on every edit; never trust a stale submitted derived value.
    if preserve_conversion and doc.get('allocated_amount') is not None:
        allocated = float(doc['allocated_amount'])
    elif currency(doc.get('currency')) == currency(payable.get('currency')):
        allocated = float(doc['amount'])
    elif currency(payable.get('currency')) == 'USD':
        allocated = float(doc['usd_amount'])
    else:
        tl = float(doc['amount']) * float(doc.get('fx_rate') or 0)
        if currency(doc.get('currency')) == 'USD':
            tl = float(doc['amount']) * float(doc.get('usd_fx_rate') or await rate(db, 'USD'))
        allocated = tl / await rate(db, payable.get('currency'))
    query = {**POSTED, 'payable_id': payable['id']}
    if payment_id:
        query['id'] = {'$ne': payment_id}
    others = await db.payments.find(query).to_list(None)
    if posted(doc) and sum(allocation(p, payable) for p in others) + allocated > total + 0.005:
        raise HTTPException(400, 'Ödeme seçilen kaydın kalan tutarını aşamaz.')
    doc['allocated_amount'] = allocated
    doc['allocation_currency'] = currency(payable.get('currency'))
    doc['allocated_usd'] = round(allocated * book / total, 2) if total else 0
    doc['fx_difference_usd'] = round(float(doc['usd_amount']) - doc['allocated_usd'], 2)


async def sync_payable(db, pid):
    if not pid:
        return
    payable = await db.payables.find_one({'id': pid})
    if not payable:
        return
    rows = await db.payments.find({**POSTED, 'payable_id': pid}).to_list(None)
    if not rows and '_status_before_payments' not in payable and 'remaining_usd' not in payable and payable.get('status') not in DERIVED_STATUSES:
        return
    total, book = basis(payable)
    paid_amount = sum(allocation(p, payable) for p in rows)
    remaining_amount = round(max(0, total - paid_amount), 2)
    remaining_usd = round(remaining_amount * book / total, 2) if total else 0
    previous = payable.get('_status_before_payments') or payable.get('status') or 'ONAYLANDI'
    if previous in DERIVED_STATUSES:
        previous = 'ONAYLANDI'
    status = ('ÖDENDİ' if remaining_amount <= 0.005 else 'KISMİ ÖDEME') if paid_amount > 0 else previous
    if payable.get('status') == 'İPTAL':
        status = 'İPTAL'
    cash_paid = sum(float(p.get('usd_amount') or 0) for p in rows)
    allocated_usd = round(book - remaining_usd, 2)
    update = {'$set': {'paid_usd': allocated_usd, 'remaining_usd': remaining_usd,
        'paid_original': round(paid_amount, 2), 'remaining_amount': remaining_amount,
        'cash_paid_usd': round(cash_paid, 2), 'fx_difference_usd': round(cash_paid - allocated_usd, 2),
        'approval_status': approval(payable), 'payment_status': 'paid' if paid_amount > 0 and not remaining_amount else 'partial' if paid_amount > 0 else 'unpaid',
        'status': status, 'updated_at': _now()}}
    if rows:
        update['$set']['_status_before_payments'] = previous
    else:
        update['$unset'] = {'_status_before_payments': ''}
    await db.payables.update_one({'id': pid}, update)


async def normalize_payment_amount(db, doc):
    amount = number(doc.get('amount'), positive=True)
    if currency(doc.get('currency')) == 'USD':
        doc['usd_amount'] = amount
        return
    if currency(doc.get('currency')) == 'TL':
        doc['fx_rate'] = 1
    else:
        number(doc.get('fx_rate'), 'Kur', positive=True)
    if doc.get('usd_fx_rate') is not None:
        number(doc['usd_fx_rate'], 'USD kuru', positive=True)
    if doc.get('usd_amount'):
        number(doc['usd_amount'], positive=True)
        return
    usd = number(doc.get('usd_fx_rate')) or await rate(db, 'USD')
    local_rate = 1 if currency(doc.get('currency')) == 'TL' else number(doc.get('fx_rate'), 'Kur', positive=True)
    doc['fx_rate'], doc['usd_fx_rate'] = local_rate, usd
    doc['usd_amount'] = round(amount * local_rate / usd, 2)
