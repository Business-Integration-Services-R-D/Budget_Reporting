"""Master data router — parametrik referans verileri (generic CRUD)."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, ConfigDict
from database import db
from dependencies import require_writer, require_finance, get_current_user, write_audit, _uid, _now

router = APIRouter(prefix="/master", tags=["master"])

MASTER_COLLECTIONS = {
    "companies", "armators", "managers", "ships", "people", "countries",
    "banks", "expense_types", "accounting_codes", "vendors", "currencies",
    "payment_statuses", "payment_methods", "budget_categories",
}


class MasterItem(BaseModel):
    model_config = ConfigDict(extra="allow")


def _check_collection(collection: str):
    if collection not in MASTER_COLLECTIONS:
        raise HTTPException(status_code=404, detail="Bilinmeyen koleksiyon")


@router.get("/{collection}")
async def list_master(collection: str, user: dict = Depends(get_current_user)):
    _check_collection(collection)
    return await db[collection].find({}, {"_id": 0}).sort("created_at", 1).to_list(5000)


@router.post("/{collection}")
async def create_master(collection: str, body: MasterItem, user: dict = Depends(require_writer)):
    _check_collection(collection)
    if collection == "banks":
        await require_finance(user)
    doc = body.model_dump()
    doc.pop("aliases", None)
    if collection in {"vendors", "banks"} and doc.get("name"):
        if await db[collection].find_one({"$or": [{"name": doc['name']}, {"aliases": doc['name']}] }):
            raise HTTPException(409, "Bu ad başka bir tanımda kullanılıyor.")
    if collection == "banks":
        from finance import number
        doc['balance'] = number(doc.get('balance'), allow_negative=True)
    doc["id"] = _uid()
    doc["active"] = doc.get("active", True)
    doc["created_at"] = _now()
    await db[collection].insert_one(doc)
    await write_audit(user, "create", collection, doc["id"])
    doc.pop("_id", None)
    return doc


@router.put("/{collection}/{item_id}")
async def update_master(collection: str, item_id: str, body: MasterItem, user: dict = Depends(require_writer)):
    _check_collection(collection)
    if collection == "banks":
        await require_finance(user)
    existing = await db[collection].find_one({"id": item_id})
    if not existing:
        raise HTTPException(404, "Tanım bulunamadı.")
    update = body.model_dump(exclude_unset=True)
    update.pop("aliases", None)
    if collection == "banks" and "balance" in update:
        from finance import number
        update["balance"] = number(update["balance"], allow_negative=True)
    if collection == "banks" and "currency" in update:
        from finance import currency
        if currency(update["currency"]) != currency(existing.get("currency")):
            names = [existing['name'], *existing.get('aliases', [])]
            if await db.payments.find_one({'$or': [{'bank_account_id': item_id}, {'payment_method': {'$in': names}}]}):
                raise HTTPException(409, "Hareketi olan hesabın para birimi değiştirilemez; yeni hesap açın.")
    update.pop("id", None); update.pop("_id", None); update.pop("created_at", None)
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    mutation = {"$set": update}
    if collection in {"vendors", "banks"} and update.get("name") and update['name'] != existing.get('name'):
        duplicate = await db[collection].find_one({"id": {"$ne": item_id}, "$or": [{"name": update['name']}, {"aliases": update['name']}]})
        if duplicate:
            raise HTTPException(409, "Bu ad başka bir tanımda kullanılıyor.")
        mutation['$addToSet'] = {'aliases': existing['name']}
        update.pop('aliases', None)
    await db[collection].update_one({"id": item_id}, mutation)
    await write_audit(user, "update", collection, item_id)
    return {"ok": True}


@router.delete("/{collection}/{item_id}")
async def delete_master(collection: str, item_id: str, user: dict = Depends(require_writer)):
    _check_collection(collection)
    if collection in {"vendors", "banks"}:
        if collection == "banks":
            await require_finance(user)
        await db[collection].update_one({"id": item_id}, {"$set": {"active": False, "updated_at": _now()}})
    else:
        await db[collection].delete_one({"id": item_id})
    await write_audit(user, "delete", collection, item_id)
    return {"ok": True}
