"""Reports router — 5 rapor şablonu."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from database import db
from settlements import OPEN_AMOUNT
from finance import POSTED, OPEN, APPROVED, approved, currency, basis, allocation
from dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/by-ship-detail")
async def report_by_ship(user: dict = Depends(get_current_user)):
    return await db.payables.aggregate([
        {"$match": {**APPROVED, "kind": "PAYABLE"}},
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
        {**OPEN, "kind": "PAYABLE", "due_date": {"$ne": None}},
        {"_id": 0}
    ).to_list(5000)
    buckets = {"Vadesi gelmemiş": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    counts = {"Vadesi gelmemiş": 0, "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
    for p in payables:
        try:
            due = datetime.fromisoformat(p["due_date"]).date()
        except Exception:
            continue
        days = (today - due).days
        amt = float(p.get("remaining_usd", p.get("usd_amount", 0)) or 0)
        if days < 0: buckets["Vadesi gelmemiş"] += amt; counts["Vadesi gelmemiş"] += 1
        elif days <= 30: buckets["0-30"] += amt; counts["0-30"] += 1
        elif days <= 60: buckets["31-60"] += amt; counts["31-60"] += 1
        elif days <= 90: buckets["61-90"] += amt; counts["61-90"] += 1
        else: buckets["90+"] += amt; counts["90+"] += 1
    return [{"bucket": k, "total": v, "count": counts[k]} for k, v in buckets.items()]


@router.get("/monthly-projection")
async def report_monthly(months: int = 12, user: dict = Depends(get_current_user)):
    rows = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE", "due_date": {"$ne": None}}},
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
        {"$match": {**POSTED, "type": "TEDİYE"}},
        {"$group": {"_id": "$vendor", "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": limit}
    ]).to_list(50)
    return [{"vendor": r["_id"] or "Tanımsız", "total": float(r["total"] or 0), "count": r["count"]} for r in rows]


@router.get("/by-currency")
async def report_currency_position(user: dict = Depends(get_current_user)):
    totals = {}
    payments = await db.payments.find(POSTED).to_list(None)
    by_parent = {}
    for payment in payments:
        by_parent.setdefault(payment.get("payable_id"), []).append(payment)
    for p in await db.payables.find(APPROVED).to_list(None):
        if not approved(p) or p.get('status') == 'ÖDENDİ':
            continue
        code = currency(p.get('currency'))
        row = totals.setdefault(code, {"currency": code, "borç": 0., "alacak": 0.})
        outstanding = max(0, basis(p)[0] - sum(allocation(payment, p) for payment in by_parent.get(p['id'], [])))
        row['alacak' if p.get('kind') == 'RECEIVABLE' else 'borç'] += outstanding
    return list(totals.values())
