"""Payables / Receivables router."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from database import db
from settlements import settlement_lock, sync_payable, DERIVED_STATUSES
from dependencies import get_current_user, write_audit, _uid, _now

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
async def create_payable(body: PayableInput, user: dict = Depends(get_current_user)):
    doc = body.model_dump()
    if doc.get("status") in DERIVED_STATUSES:
        raise HTTPException(400, "Ödendi ve Kısmi Ödeme durumları ödeme/tahsilat hareketlerinden otomatik belirlenir.")
    for field in ("paid_usd", "remaining_usd", "_status_before_payments"):
        doc.pop(field, None)
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
async def update_payable(pid: str, body: PayableInput, user: dict = Depends(get_current_user)):
    update = body.model_dump(exclude_unset=True)
    for field in ("id", "_id", "paid_usd", "remaining_usd", "_status_before_payments"):
        update.pop(field, None)
    update["updated_at"] = _now()
    _apply_year_month(update)
    async with settlement_lock(pid):
        existing = await db.payables.find_one({"id": pid})
        if not existing:
            raise HTTPException(404, "Bulunamadı")
        if update.get("status") in DERIVED_STATUSES and update["status"] != existing.get("status"):
            raise HTTPException(400, "Ödendi ve Kısmi Ödeme durumları ödeme/tahsilat hareketlerinden otomatik belirlenir.")
        linked = await db.payments.find_one({"payable_id": pid})
        if linked:
            if any(field in update and update[field] != existing.get(field) for field in ("kind", "vendor", "ship")):
                raise HTTPException(400, "Bağlı ödemesi olan kaydın türü, firması ve gemisi değiştirilemez.")
            paid = await db.payments.aggregate([
                {"$match": {"payable_id": pid}}, {"$group": {"_id": None, "total": {"$sum": "$usd_amount"}}}
            ]).to_list(1)
            if float(update.get("usd_amount", existing.get("usd_amount")) or 0) + 0.005 < float(paid[0]["total"] or 0):
                raise HTTPException(400, "Borç tutarı bağlı ödeme toplamından küçük olamaz.")
        await db.payables.update_one({"id": pid}, {"$set": update})
        await sync_payable(db, pid)
    await write_audit(user, "update", "payable", pid)
    return {"ok": True}


@router.delete("/{pid}")
async def delete_payable(pid: str, user: dict = Depends(get_current_user)):
    async with settlement_lock(pid):
        if await db.payments.find_one({"payable_id": pid}):
            raise HTTPException(409, "Önce bu kayda bağlı ödemeleri kaldırın veya bağlantılarını değiştirin.")
        await db.payables.delete_one({"id": pid})
    await write_audit(user, "delete", "payable", pid)
    return {"ok": True}
