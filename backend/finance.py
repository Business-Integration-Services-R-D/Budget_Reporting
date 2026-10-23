"""Shared business rules; legacy records remain readable without rewriting them."""
import math
from fastapi import HTTPException

# Old records without posting_status were already treated as posted.
POSTED = {'voided': {'$ne': True}, 'posting_status': {'$ne': 'draft'}}
APPROVED = {'status': {'$nin': ['TASLAK', 'ONAY BEKLİYOR', 'İPTAL']},
            'approval_status': {'$nin': ['draft', 'pending']}}
OPEN = {**APPROVED, 'status': {'$nin': ['TASLAK', 'ONAY BEKLİYOR', 'İPTAL', 'ÖDENDİ']}}
APPROVAL_LABELS = {'draft': 'TASLAK', 'pending': 'ONAY BEKLİYOR', 'approved': 'ONAYLANDI'}


def currency(code):
    return {'TRY': 'TL', 'POUND': 'GBP'}.get(str(code or 'USD').upper(), str(code or 'USD').upper())


def approval(doc):
    if doc.get('approval_status') in APPROVAL_LABELS:
        return doc['approval_status']
    status = doc.get('_status_before_payments') or doc.get('status')
    return {'TASLAK': 'draft', 'ONAY BEKLİYOR': 'pending'}.get(status, 'approved')


def approved(doc):
    return approval(doc) == 'approved' and doc.get('status') != 'İPTAL'


def posted(doc):
    return not doc.get('voided') and doc.get('posting_status', 'posted') != 'draft'


def number(value, label='Tutar', positive=False, allow_negative=False):
    try:
        result = float(value or 0)
    except (ValueError, TypeError):
        raise HTTPException(400, f'{label} geçerli bir sayı olmalıdır.')
    if not math.isfinite(result) or (result < 0 and not allow_negative) or (positive and result <= 0):
        raise HTTPException(400, f'{label} geçerli, pozitif bir sayı olmalıdır.')
    return result


async def rate(db, code):
    code = currency(code)
    if code == 'TL':
        return 1.0
    row = await db.currencies.find_one({'code': code})
    if not row and code == 'GBP':
        row = await db.currencies.find_one({'code': 'POUND'})
    value = number((row or {}).get('rate_to_tl'), 'Döviz kuru')
    if not value:
        raise HTTPException(400, f'{code} için geçerli kur bulunamadı.')
    return value


async def reference(db, collection, name=None, identifier=None, required=False):
    if identifier:
        item = await db[collection].find_one({'id': identifier})
        if not item:
            raise HTTPException(400, 'Seçilen tanım bulunamadı.')
    else:
        item = await db[collection].find_one({'$or': [{'name': name}, {'aliases': name}]}) if name else None
    if item and item.get('active') is False:
        raise HTTPException(400, 'Pasif tanım kullanılamaz.')
    if required and not item:
        raise HTTPException(400, 'Gerçekleşen hareket için geçerli bir banka/kasa hesabı seçin.')
    return item


async def resolve_vendor(db, doc):
    item = await reference(db, 'vendors', doc.get('vendor'), doc.get('vendor_id'))
    if item:
        doc['vendor_id'], doc['vendor'] = item['id'], item['name']


async def resolve_bank(db, doc):
    item = await reference(db, 'banks', doc.get('payment_method'), doc.get('bank_account_id'), required=posted(doc))
    if item:
        doc['bank_account_id'], doc['payment_method'] = item['id'], item['name']
    return item


def basis(payable):
    original = float(payable.get('original_amount') or 0)
    book_usd = float(payable.get('usd_amount') or 0)
    return original if original > 0 else book_usd, book_usd


def allocation(payment, payable):
    """Booked-value allocation, including pre-upgrade linked payment records."""
    total, book = basis(payable)
    if payment.get('allocation_currency') == currency(payable.get('currency')) and payment.get('allocated_amount') is not None:
        return float(payment['allocated_amount'])
    if currency(payment.get('currency')) == currency(payable.get('currency')):
        return float(payment.get('amount') or 0)
    return float(payment.get('usd_amount') or 0) * total / book if book else 0
