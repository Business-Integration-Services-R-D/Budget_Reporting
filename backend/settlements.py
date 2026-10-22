"""Keep linked payments and outstanding payable amounts consistent."""
import asyncio
import math
from contextlib import asynccontextmanager
from fastapi import HTTPException
from dependencies import _now

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


async def prepare_payment(db, doc, payment_id=None):
    for field in ('amount', 'usd_amount'):
        value = float(doc.get(field) or 0)
        if not math.isfinite(value) or value < 0:
            raise HTTPException(400, 'Tutar geçerli ve negatif olmayan bir sayı olmalıdır.')
    if not doc.get('payable_id'):
        doc['payable_id'] = None
        return
    payable = await db.payables.find_one({'id': doc['payable_id']})
    if not payable:
        raise HTTPException(404, 'Bağlanacak borç/alacak bulunamadı.')
    if payable.get('status') == 'İPTAL':
        raise HTTPException(400, 'İptal edilmiş kayda ödeme bağlanamaz.')
    expected_type = 'TAHSİL' if payable.get('kind') == 'RECEIVABLE' else 'TEDİYE'
    if doc.get('type') != expected_type:
        raise HTTPException(400, 'Borç için TEDİYE, alacak için TAHSİL seçilmelidir.')
    for field in ('vendor', 'ship'):
        if doc.get(field) and payable.get(field) and doc[field] != payable[field]:
            raise HTTPException(400, 'Firma ve gemi seçilen borç/alacak ile aynı olmalıdır.')
        doc[field] = payable.get(field) or doc.get(field)
    if float(doc.get('usd_amount') or 0) <= 0:
        raise HTTPException(400, 'Bağlı ödeme tutarı sıfırdan büyük olmalıdır.')
    query = {'payable_id': payable['id']}
    if payment_id:
        query['id'] = {'$ne': payment_id}
    rows = await db.payments.aggregate([
        {'$match': query}, {'$group': {'_id': None, 'paid': {'$sum': '$usd_amount'}}}
    ]).to_list(1)
    paid = float(rows[0]['paid'] or 0) if rows else 0
    if paid + float(doc['usd_amount']) > float(payable.get('usd_amount') or 0) + 0.005:
        raise HTTPException(400, 'Ödeme, seçilen kaydın kalan tutarını aşamaz.')


async def sync_payable(db, pid):
    if not pid:
        return
    payable = await db.payables.find_one({'id': pid})
    if not payable:
        return
    rows = await db.payments.aggregate([
        {'$match': {'payable_id': pid}},
        {'$group': {'_id': None, 'paid': {'$sum': '$usd_amount'}, 'count': {'$sum': 1}}}
    ]).to_list(1)
    if not rows and '_status_before_payments' not in payable and 'remaining_usd' not in payable and payable.get('status') not in DERIVED_STATUSES:
        return
    paid = float(rows[0]['paid'] or 0) if rows else 0
    remaining = round(max(0, float(payable.get('usd_amount') or 0) - paid), 2)
    previous = payable.get('_status_before_payments') or payable.get('status') or 'ONAYLANDI'
    if previous in ('ÖDENDİ', 'KISMİ ÖDEME'):
        previous = 'ONAYLANDI'
    status = ('ÖDENDİ' if remaining <= 0.005 else 'KISMİ ÖDEME') if paid > 0 else previous
    if payable.get('status') == 'İPTAL':
        status = 'İPTAL'
    update = {'$set': {
        'paid_usd': round(paid, 2), 'remaining_usd': remaining,
        'status': status, 'updated_at': _now(),
    }}
    if rows:
        update['$set']['_status_before_payments'] = previous
    else:
        update['$unset'] = {'_status_before_payments': ''}
        if '_status_before_payments' not in payable and payable.get('status') not in DERIVED_STATUSES:
            update['$set']['status'] = payable.get('status', previous)
    await db.payables.update_one({'id': pid}, update)


async def normalize_payment_amount(db, doc):
    if doc.get('usd_amount') or not doc.get('amount'):
        return
    if (doc.get('currency') or '').upper() == 'USD':
        doc['usd_amount'] = float(doc['amount'])
        return
    usd = await db.currencies.find_one({'code': 'USD'})
    rate = float((usd or {}).get('rate_to_tl') or 0)
    if rate <= 0 or float(doc.get('fx_rate') or 0) <= 0:
        raise HTTPException(400, 'USD karşılığı için geçerli döviz kuru gereklidir.')
    doc['usd_amount'] = float(doc['amount']) * float(doc['fx_rate']) / rate
