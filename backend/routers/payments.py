"""Payments router."""
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from database import db
from dependencies import require_finance, get_current_user, write_audit, _uid, _now

from finance import POSTED
from settlements import settlement_lock, prepare_payment, sync_payable, normalize_payment_amount

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Optional[str] = "TEDİYE"
    date: Optional[str] = None
    payable_id: Optional[str] = None
    ship: Optional[str] = None
    vendor: Optional[str] = None
    manager: Optional[str] = None
    description: Optional[str] = None
    paying_company: Optional[str] = None
    payment_method: Optional[str] = None
    amount: Optional[float] = 0
    currency: Optional[str] = "USD"
    fx_rate: Optional[float] = 1
    usd_amount: Optional[float] = 0
    approved: Optional[bool] = True
    posting_status: Literal["draft", "posted"] = "posted"
    bank_account_id: Optional[str] = None
    vendor_id: Optional[str] = None


@router.get("")
async def list_payments(
    type: Optional[str] = None,
    bank: Optional[str] = None,
    ship: Optional[str] = None,
    company: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 1000,
    include_voided: bool = False,
    user: dict = Depends(get_current_user),
):
    q: dict = {} if include_voided else {"voided": {"$ne": True}}
    if type: q["type"] = type
    if bank: q["payment_method"] = bank
    if ship: q["ship"] = ship
    if company: q["paying_company"] = company
    if search:
        q["$or"] = [
            {"description": {"$regex": search, "$options": "i"}},
            {"vendor": {"$regex": search, "$options": "i"}},
        ]
    return await db.payments.find(q, {"_id": 0}).sort("date", -1).to_list(limit)


@router.post("")
async def create_payment(body: PaymentInput, user: dict = Depends(require_finance)):
    return await create_payment_record(db, body, user)


async def create_payment_record(store, body: PaymentInput, user: dict):
    db = store
    await require_finance(user)
    doc = body.model_dump()
    doc["id"] = _uid()
    doc["created_at"] = _now()
    doc["created_by"] = user["email"]
    if "posting_status" not in body.model_fields_set and body.approved is False:
        doc["posting_status"] = "draft"
    doc["approved"] = doc["posting_status"] == "posted"
    for field in ("voided", "voided_at", "voided_by", "is_transfer", "transfer_pair_id", "transfer_from", "transfer_to"):
        doc.pop(field, None)
    await normalize_payment_amount(db, doc)
    async with settlement_lock(doc.get("payable_id")):
        await prepare_payment(db, doc)
        await db.payments.insert_one(doc)
        await sync_payable(db, doc.get("payable_id"))
    await write_audit(user, "create", "payment", doc["id"])
    doc.pop("_id", None)
    return doc


@router.put("/{pid}")
async def update_payment(pid: str, body: PaymentInput, user: dict = Depends(require_finance)):
    return await update_payment_record(db, pid, body, user)


async def update_payment_record(store, pid: str, body: PaymentInput, user: dict):
    db = store
    await require_finance(user)
    old = await db.payments.find_one({"id": pid})
    if not old:
        raise HTTPException(404, "Ödeme bulunamadı.")
    if old.get("voided"):
        raise HTTPException(409, "İptal edilmiş hareket düzenlenemez.")
    if old.get("is_transfer"):
        raise HTTPException(409, "Virman tek taraflı düzenlenemez; eşli iptal edip yeniden oluşturun.")
    update = body.model_dump(exclude_unset=True)
    for field in ("id", "_id", "created_at", "created_by", "voided", "voided_at", "voided_by", "is_transfer", "transfer_pair_id", "transfer_from", "transfer_to"):
        update.pop(field, None)
    doc = {**old, **update}
    for name, identifier in (("payment_method", "bank_account_id"), ("vendor", "vendor_id")):
        if name in update and update[name] != old.get(name) and identifier not in update:
            doc[identifier] = None
    doc["posting_status"] = update.get("posting_status", old.get("posting_status", "posted"))
    if "approved" in update and "posting_status" not in update and update["approved"] != old.get("approved"):
        doc["posting_status"] = "posted" if update["approved"] else "draft"
    doc["approved"] = doc["posting_status"] == "posted"
    if any(field in update for field in ("amount", "currency", "fx_rate")) and "usd_amount" not in update:
        doc["usd_amount"] = 0
    await normalize_payment_amount(db, doc)
    doc["updated_at"] = _now()
    async with settlement_lock(old.get("payable_id"), doc.get("payable_id")):
        conversion_fields = ("amount", "currency", "fx_rate", "usd_fx_rate", "usd_amount", "type", "payable_id", "bank_account_id", "payment_method")
        unchanged_conversion = all(doc.get(key) == old.get(key) for key in conversion_fields)
        await prepare_payment(db, doc, pid, preserve_conversion=unchanged_conversion)
        doc.pop("_id", None)
        await db.payments.update_one({"id": pid}, {"$set": doc})
        for linked_id in set(filter(None, [old.get("payable_id"), doc.get("payable_id")])):
            await sync_payable(db, linked_id)
    await write_audit(user, "update", "payment", pid)
    return {"ok": True}


@router.delete("/{pid}")
async def delete_payment(pid: str, user: dict = Depends(require_finance)):
    return await delete_payment_record(db, pid, user)


async def delete_payment_record(store, pid: str, user: dict):
    db = store
    await require_finance(user)
    old = await db.payments.find_one({"id": pid})
    if not old:
        raise HTTPException(404, "Ödeme bulunamadı.")
    async with settlement_lock(old.get("payable_id"), old.get("transfer_pair_id"), pid):
        ids = [pid]
        if old.get("is_transfer") and old.get("transfer_pair_id"):
            pair = await db.payments.find_one({"id": old["transfer_pair_id"], "is_transfer": True, "transfer_pair_id": pid})
            if not pair:
                raise HTTPException(409, "Virmanın karşı hareketi bulunamadı; eşleştirmeyi kontrol edin.")
            ids.append(pair["id"])
        await db.payments.update_many({"id": {"$in": ids}}, {"$set": {
            "voided": True, "voided_at": _now(), "voided_by": user["email"]}})
        await sync_payable(db, old.get("payable_id"))
    await write_audit(user, "void", "payment", pid)
    return {"ok": True}
