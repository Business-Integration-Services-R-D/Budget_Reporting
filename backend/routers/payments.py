"""Payments router."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from database import db
from dependencies import get_current_user, write_audit, _uid, _now

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
    approved: Optional[bool] = False


@router.get("")
async def list_payments(
    type: Optional[str] = None,
    bank: Optional[str] = None,
    ship: Optional[str] = None,
    company: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 1000,
    user: dict = Depends(get_current_user),
):
    q: dict = {}
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
async def create_payment(body: PaymentInput, user: dict = Depends(get_current_user)):
    doc = body.model_dump()
    doc["id"] = _uid()
    doc["created_at"] = _now()
    doc["created_by"] = user["email"]
    await normalize_payment_amount(db, doc)
    async with settlement_lock(doc.get("payable_id")):
        await prepare_payment(db, doc)
        await db.payments.insert_one(doc)
        await sync_payable(db, doc.get("payable_id"))
    await write_audit(user, "create", "payment", doc["id"])
    doc.pop("_id", None)
    return doc


@router.put("/{pid}")
async def update_payment(pid: str, body: PaymentInput, user: dict = Depends(get_current_user)):
    old = await db.payments.find_one({"id": pid})
    if not old:
        raise HTTPException(404, "Ödeme bulunamadı.")
    update = body.model_dump(exclude_unset=True)
    for field in ("id", "_id", "created_at", "created_by"):
        update.pop(field, None)
    doc = {**old, **update}
    if any(field in update for field in ("amount", "currency", "fx_rate")) and "usd_amount" not in update:
        doc["usd_amount"] = 0
    await normalize_payment_amount(db, doc)
    doc["updated_at"] = _now()
    async with settlement_lock(old.get("payable_id"), doc.get("payable_id")):
        await prepare_payment(db, doc, pid)
        doc.pop("_id", None)
        await db.payments.update_one({"id": pid}, {"$set": doc})
        for linked_id in set(filter(None, [old.get("payable_id"), doc.get("payable_id")])):
            await sync_payable(db, linked_id)
    await write_audit(user, "update", "payment", pid)
    return {"ok": True}


@router.delete("/{pid}")
async def delete_payment(pid: str, user: dict = Depends(get_current_user)):
    old = await db.payments.find_one({"id": pid})
    if not old:
        raise HTTPException(404, "Ödeme bulunamadı.")
    async with settlement_lock(old.get("payable_id")):
        await db.payments.delete_one({"id": pid})
        await sync_payable(db, old.get("payable_id"))
    await write_audit(user, "delete", "payment", pid)
    return {"ok": True}
