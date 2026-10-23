"""Payables / Receivables router."""
from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from database import db
from finance import POSTED, approval, APPROVAL_LABELS, resolve_vendor, number, basis, allocation
from settlements import settlement_lock, sync_payable, DERIVED_STATUSES
from dependencies import require_writer, require_approver, get_current_user, write_audit, _uid, _now

router = APIRouter(prefix="/payables", tags=["payables"])


class PayableInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    order_date: Optional[str] = None
    due_date: Optional[str] = None
    expense_code: Optional[str] = None
    expense_type: Optional[str] = None
    vendor: Optional[str] = None
    country: Optional[str] = None
    person_company: Optional[str] = None
    ship: Optional[str] = None
    armator: Optional[str] = None
    description: Optional[str] = None
    original_amount: Optional[float] = 0
    currency: Optional[str] = "USD"
    usd_amount: Optional[float] = 0
    status: Optional[str] = "ONAY BEKLİYOR"
    kind: Optional[str] = "PAYABLE"
    approval_status: Optional[Literal["draft", "pending", "approved"]] = None
    vendor_id: Optional[str] = None


def _apply_year_month(doc: dict):
    if doc.get("due_date"):
        try:
            d = datetime.fromisoformat(doc["due_date"])
            doc["year"] = d.year
            doc["month"] = d.month
        except Exception:
            pass


@router.get("")
async def list_payables(
    kind: str = "PAYABLE",
    status: Optional[str] = None,
    ship: Optional[str] = None,
    vendor: Optional[str] = None,
    year: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 500,
    user: dict = Depends(get_current_user),
):
    q: dict = {"kind": kind}
    if status: q["status"] = status
    if ship: q["ship"] = ship
    if vendor: q["vendor"] = vendor
    if year: q["year"] = year
    if search:
        q["$or"] = [
            {"description": {"$regex": search, "$options": "i"}},
            {"vendor": {"$regex": search, "$options": "i"}},
            {"ship": {"$regex": search, "$options": "i"}},
        ]
    return await db.payables.find(q, {"_id": 0}).sort("due_date", -1).to_list(limit)


@router.post("")
async def create_payable(body: PayableInput, user: dict = Depends(require_writer)):
    return await create_payable_record(db, body, user)


async def create_payable_record(store, body: PayableInput, user: dict):
    db = store
    await require_writer(user)
    doc = body.model_dump()
    if doc.get("status") in DERIVED_STATUSES:
        raise HTTPException(400, "Ödendi ve Kısmi Ödeme durumları ödeme/tahsilat hareketlerinden otomatik belirlenir.")
    for field in ("paid_usd", "remaining_usd", "_status_before_payments", "remaining_amount", "paid_original", "cash_paid_usd", "fx_difference_usd", "payment_status"):
        doc.pop(field, None)
    number(doc.get("original_amount"))
    number(doc.get("usd_amount"))
    doc["approval_status"] = approval(doc)
    doc["payment_status"] = "unpaid"
    if doc["approval_status"] == "approved":
        await require_approver(user)
    await resolve_vendor(db, doc)
    doc["id"] = _uid()
    _apply_year_month(doc)
    doc["created_at"] = _now()
    doc["created_by"] = user["email"]
    await db.payables.insert_one(doc)
    await write_audit(user, "create", "payable", doc["id"])
    doc.pop("_id", None)
    return doc


@router.get("/{pid}")
async def get_payable(pid: str, user: dict = Depends(get_current_user)):
    item = await db.payables.find_one({"id": pid}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Bulunamadı")
    payments = await db.payments.find({"payable_id": pid}, {"_id": 0}).to_list(100)
    item["payments"] = payments
    return item


@router.put("/{pid}")
async def update_payable(pid: str, body: PayableInput, user: dict = Depends(require_writer)):
    return await update_payable_record(db, pid, body, user)


async def update_payable_record(store, pid: str, body: PayableInput, user: dict):
    db = store
    await require_writer(user)
    update = body.model_dump(exclude_unset=True)
    for field in ("id", "_id", "paid_usd", "remaining_usd", "_status_before_payments", "remaining_amount", "paid_original", "cash_paid_usd", "fx_difference_usd", "payment_status"):
        update.pop(field, None)
    update["updated_at"] = _now()
    _apply_year_month(update)
    async with settlement_lock(pid):
        existing = await db.payables.find_one({"id": pid})
        if not existing:
            raise HTTPException(404, "Bulunamadı")
        if update.get("status") in DERIVED_STATUSES and update["status"] != existing.get("status"):
            raise HTTPException(400, "Ödendi ve Kısmi Ödeme durumları ödeme/tahsilat hareketlerinden otomatik belirlenir.")
        for field in ("original_amount", "usd_amount"):
            if field in update:
                number(update[field])
        merged = {**existing, **update}
        if update.get("status") in APPROVAL_LABELS.values() and "approval_status" not in update:
            merged["approval_status"] = {v: k for k, v in APPROVAL_LABELS.items()}[update["status"]]
        new_approval = approval(merged)
        if new_approval == "approved" and approval(existing) != "approved":
            await require_approver(user)
        update["approval_status"] = new_approval
        linked = await db.payments.find_one({**POSTED, "payable_id": pid})
        if linked:
            if update.get("status") == "İPTAL":
                raise HTTPException(409, "Ödemesi olan kayıt doğrudan iptal edilemez. Önce bağlı hareketi iptal edin veya iade/mahsup kaydedin.")
            if new_approval != "approved":
                raise HTTPException(409, "Ödemesi olan belgenin onayı kaldırılamaz.")
            if any(field in update and update[field] != existing.get(field) for field in ("kind", "vendor_id", "ship", "currency")):
                raise HTTPException(400, "Ödemesi olan kaydın türü, firması, gemisi ve para birimi değiştirilemez.")
            if "vendor" in update and not existing.get("vendor_id") and update['vendor'] != existing.get('vendor'):
                raise HTTPException(400, "Ödemesi olan kaydın firması değiştirilemez.")
            rows = await db.payments.find({**POSTED, "payable_id": pid}).to_list(None)
            if basis(merged)[0] + 0.005 < sum(allocation(p, existing) for p in rows):
                raise HTTPException(400, "Belge tutarı mahsup edilen tutardan küçük olamaz.")
        if merged.get("status") != "İPTAL" and (not linked or update.get("status") in APPROVAL_LABELS.values()):
            update["status"] = APPROVAL_LABELS[new_approval]
        await resolve_vendor(db, merged)
        if merged.get("vendor_id"):
            update["vendor_id"], update["vendor"] = merged['vendor_id'], merged['vendor']
        await db.payables.update_one({"id": pid}, {"$set": update})
        await sync_payable(db, pid)
    await write_audit(user, "update", "payable", pid)
    return {"ok": True}


@router.delete("/{pid}")
async def delete_payable(pid: str, user: dict = Depends(require_writer)):
    return await delete_payable_record(db, pid, user)


async def delete_payable_record(store, pid: str, user: dict):
    db = store
    await require_writer(user)
    async with settlement_lock(pid):
        if await db.payments.find_one({"payable_id": pid}):
            raise HTTPException(409, "Önce bu kayda bağlı ödemeleri kaldırın veya bağlantılarını değiştirin.")
        await db.payables.delete_one({"id": pid})
    await write_audit(user, "delete", "payable", pid)
    return {"ok": True}
