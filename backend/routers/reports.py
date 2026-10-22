"""Reports router — 5 rapor şablonu."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from database import db
from settlements import OPEN_AMOUNT
from dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/by-ship-detail")
async def report_by_ship(user: dict = Depends(get_current_user)):
    return await db.payables.aggregate([
        {"$match": {"kind": "PAYABLE"}},
        {"$group": {
            "_id": "$ship",
            "total_debt": {"$sum": "$usd_amount"},
            "paid": {"$sum": {"$cond": [{"$eq": ["$status", "ÖDENDİ"]}, "$usd_amount", {"$ifNull": ["$paid_usd", 0]}]}},
            "open": {"$sum": {"$cond": [{"$in": ["$status", ["ÖDENDİ", "İPTAL"]]}, 0, OPEN_AMOUNT]}},
            "count": {"$sum": 1}
        }},
        {"$sort": {"total_debt": -1}}
    ]).to_list(100)


@router.get("/aging")
async def report_aging(user: dict = Depends(get_current_user)):
    today = datetime.now(timezone.utc).date()
    payables = await db.payables.find(
        {"kind": "PAYABLE", "status": {"$nin": ["ÖDENDİ", "İPTAL"]}, "due_date": {"$ne": None}},
        {"_id": 0}
    ).to_list(5000)
    buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    counts = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    for p in payables:
        try:
            due = datetime.fromisoformat(p["due_date"]).date()
        except Exception:
            continue
        days = (today - due).days
        amt = float(p.get("remaining_usd", p.get("usd_amount", 0)) or 0)
        if days <= 30: buckets["0-30"] += amt; counts["0-30"] += 1
        elif days <= 60: buckets["31-60"] += amt; counts["31-60"] += 1
        elif days <= 90: buckets["61-90"] += amt; counts["61-90"] += 1
        else: buckets["90+"] += amt; counts["90+"] += 1
    return [{"bucket": k, "total": v, "count": counts[k]} for k, v in buckets.items()]


@router.get("/monthly-projection")
async def report_monthly(months: int = 12, user: dict = Depends(get_current_user)):
    rows = await db.payables.aggregate([
        {"$match": {"kind": "PAYABLE", "status": {"$nin": ["ÖDENDİ", "İPTAL"]}, "due_date": {"$ne": None}}},
        {"$addFields": {"_d": {"$dateFromString": {"dateString": "$due_date", "onError": None}}}},
        {"$match": {"_d": {"$ne": None}}},
        {"$group": {
            "_id": {"y": {"$year": "$_d"}, "m": {"$month": "$_d"}},
            "total": {"$sum": OPEN_AMOUNT},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.y": 1, "_id.m": 1}}
    ]).to_list(100)
    return [{"month": f"{r['_id']['y']:04d}-{r['_id']['m']:02d}", "total": float(r["total"] or 0), "count": r["count"]} for r in rows]


@router.get("/top-vendors")
async def report_top_vendors(limit: int = 20, user: dict = Depends(get_current_user)):
    rows = await db.payments.aggregate([
        {"$match": {"type": "TEDİYE"}},
        {"$group": {"_id": "$vendor", "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": limit}
    ]).to_list(50)
    return [{"vendor": r["_id"] or "Tanımsız", "total": float(r["total"] or 0), "count": r["count"]} for r in rows]


@router.get("/by-currency")
async def report_currency_position(user: dict = Depends(get_current_user)):
    rows = await db.payables.aggregate([
        {"$group": {
            "_id": "$currency",
            "borç": {"$sum": {"$cond": [{"$eq": ["$kind", "PAYABLE"]}, "$original_amount", 0]}},
            "alacak": {"$sum": {"$cond": [{"$eq": ["$kind", "RECEIVABLE"]}, "$original_amount", 0]}}
        }}
    ]).to_list(20)
    return [{"currency": r["_id"] or "?", "borç": float(r["borç"] or 0), "alacak": float(r["alacak"] or 0)} for r in rows]
