"""Dashboard router — KPI ve grafik endpoint'leri."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from database import db
from settlements import OPEN_AMOUNT
from finance import POSTED, CASH_POSTED, OPEN, APPROVED
from dependencies import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _g(r):
    if r and r[0]:
        return {"total": float(r[0].get("total", 0) or 0), "count": int(r[0].get("count", 0) or 0)}
    return {"total": 0, "count": 0}


async def _due_window(start: str, end: str):
    rows = await db.payables.aggregate([
        {"$match": {**OPEN, "due_date": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": "$kind", "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}},
    ]).to_list(2)
    values = {row["_id"]: _g([row]) for row in rows}
    payable = values.get("PAYABLE", {"total": 0, "count": 0})
    receivable = values.get("RECEIVABLE", {"total": 0, "count": 0})
    return {
        "total": receivable["total"] - payable["total"],
        "count": receivable["count"] + payable["count"],
        "payable": payable["total"], "payable_count": payable["count"],
        "receivable": receivable["total"], "receivable_count": receivable["count"],
    }


@router.get("/kpi")
async def dashboard_kpi(user: dict = Depends(get_current_user)):
    open_payable = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE"}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    open_receivable = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "RECEIVABLE"}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    today = datetime.now(timezone.utc).date()
    week_later = (today + timedelta(days=7)).isoformat()
    month_later = (today + timedelta(days=30)).isoformat()
    today_iso = today.isoformat()
    week_due = await _due_window(today_iso, week_later)
    month_due = await _due_window(today_iso, month_later)
    overdue = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE",
                    "due_date": {"$lt": today_iso}}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    paid_total = await db.payments.aggregate([
        {"$match": {**CASH_POSTED, "type": "TEDİYE"}},
        {"$group": {"_id": None, "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    received_total = await db.payments.aggregate([
        {"$match": {**CASH_POSTED, "type": "TAHSİL"}},
        {"$group": {"_id": None, "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)

    return {
        "open_payable": _g(open_payable),
        "open_receivable": _g(open_receivable),
        "net_position": _g(received_total)["total"] - _g(paid_total)["total"],
        "open_position": _g(open_receivable)["total"] - _g(open_payable)["total"],
        "overdue": _g(overdue),
        "week_due": week_due,
        "month_due": month_due,
        "paid_total": _g(paid_total),
        "received_total": _g(received_total),
    }


@router.get("/cashflow")
async def dashboard_cashflow(months: int = 12, user: dict = Depends(get_current_user)):
    pipeline = [
        {"$match": {**CASH_POSTED, "date": {"$ne": None}}},
        {"$addFields": {"_d": {"$dateFromString": {"dateString": "$date", "onError": None}}}},
        {"$match": {"_d": {"$ne": None}}},
        {"$group": {
            "_id": {"y": {"$year": "$_d"}, "m": {"$month": "$_d"}, "t": "$type"},
            "total": {"$sum": "$usd_amount"}
        }},
        {"$sort": {"_id.y": 1, "_id.m": 1}}
    ]
    rows = await db.payments.aggregate(pipeline).to_list(2000)
    out = {}
    for r in rows:
        key = f"{r['_id']['y']:04d}-{r['_id']['m']:02d}"
        out.setdefault(key, {"month": key, "TEDİYE": 0, "TAHSİL": 0})
        out[key][r['_id']['t']] = float(r["total"] or 0)
    series = list(out.values())
    return series[-months:]


@router.get("/by-ship")
async def dashboard_by_ship(user: dict = Depends(get_current_user)):
    rows = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE"}},
        {"$group": {"_id": "$ship", "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": 15}
    ]).to_list(50)
    return [{"name": r["_id"] or "Tanımsız", "total": float(r["total"] or 0), "count": r["count"]} for r in rows]


@router.get("/by-company")
async def dashboard_by_company(user: dict = Depends(get_current_user)):
    rows = await db.payments.aggregate([
        {"$match": {**CASH_POSTED, "type": "TEDİYE"}},
        {"$group": {"_id": "$paying_company", "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": 15}
    ]).to_list(50)
    return [{"name": r["_id"] or "Tanımsız", "total": float(r["total"] or 0), "count": r["count"]} for r in rows]


@router.get("/by-expense-type")
async def dashboard_by_expense(user: dict = Depends(get_current_user)):
    rows = await db.payables.aggregate([
        {"$match": {**APPROVED, "kind": "PAYABLE"}},
        {"$group": {"_id": "$expense_type", "total": {"$sum": "$usd_amount"}}},
        {"$sort": {"total": -1}}, {"$limit": 12}
    ]).to_list(20)
    return [{"name": r["_id"] or "Tanımsız", "total": float(r["total"] or 0)} for r in rows]


@router.get("/upcoming")
async def dashboard_upcoming(days: int = 30, user: dict = Depends(get_current_user)):
    today = datetime.now(timezone.utc).date().isoformat()
    end = (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()
    return await db.payables.find({
        **OPEN,
        "due_date": {"$gte": today, "$lte": end}
    }, {"_id": 0}).sort("due_date", 1).to_list(50)


@router.get("/recent")
async def dashboard_recent(limit: int = 20, user: dict = Depends(get_current_user)):
    return await db.payments.find(POSTED, {"_id": 0}).sort("created_at", -1).to_list(limit)
