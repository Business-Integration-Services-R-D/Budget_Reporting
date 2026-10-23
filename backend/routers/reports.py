"""Reports router — operational and management report templates."""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from database import db
from settlements import OPEN_AMOUNT
from finance import POSTED, CASH_POSTED, OPEN, APPROVED, approved, currency, basis, allocation
from dependencies import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])


def _date_query(field: str, start: str | None, end: str | None):
    bounds = {}
    if start:
        bounds["$gte"] = start
    if end:
        bounds["$lte"] = end
    return {field: bounds} if bounds else {}


async def cash_report_data(start: str | None = None, end: str | None = None):
    """Posted cash movements and current balances, matching the cash report layout."""
    from routers.accounts import _bank_rows
    query = {**CASH_POSTED, **_date_query("date", start, end)}
    movements = await db.payments.find(query, {"_id": 0}).sort("date", 1).to_list(10000)
    balances = await _bank_rows()
    return {"movements": movements, "balances": balances}


async def office_payments_data(start: str | None = None, end: str | None = None):
    """Open/approved debts grouped into ISO weeks for the office payment plan."""
    query = {**OPEN, "kind": "PAYABLE", **_date_query("due_date", start, end)}
    payables = await db.payables.find(query, {"_id": 0}).sort("due_date", 1).to_list(10000)
    groups = defaultdict(lambda: {"rows": [], "total_usd": 0.0})
    for item in payables:
        try:
            due = datetime.fromisoformat(item.get("due_date") or "").date()
        except ValueError:
            continue
        monday = due - timedelta(days=due.weekday())
        sunday = monday + timedelta(days=6)
        key = f"{due.isocalendar().year}-W{due.isocalendar().week:02d}"
        amount = float(item.get("remaining_usd", item.get("usd_amount", 0)) or 0)
        row = {
            "id": item.get("id"), "date": item.get("due_date"),
            "description": item.get("description") or item.get("vendor") or "—",
            "vendor": item.get("vendor"), "company_ship": item.get("person_company") or item.get("ship") or "—",
            "amount": item.get("original_amount", 0), "currency": currency(item.get("currency")),
            "usd_amount": round(amount, 2), "budget_category": item.get("budget_category") or "DİĞER",
        }
        groups[key]["rows"].append(row)
        groups[key]["total_usd"] += amount
        groups[key]["start"], groups[key]["end"], groups[key]["week"] = monday.isoformat(), sunday.isoformat(), key
    return {"weeks": [{**group, "total_usd": round(group["total_usd"], 2)} for _, group in sorted(groups.items())]}


def _month_keys(count: int):
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    result = []
    for _ in range(max(1, min(count, 60))):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return result


async def all_debts_data(months: int = 30):
    """Open debts as a due-month matrix. Installments appear separately when entered separately."""
    month_keys = _month_keys(months)
    today_month = month_keys[0]
    payables = await db.payables.find({**OPEN, "kind": "PAYABLE"}, {"_id": 0}).sort("due_date", 1).to_list(20000)
    rows = []
    totals = {key: 0.0 for key in month_keys}
    overdue_total = 0.0
    for item in payables:
        amount = float(item.get("remaining_usd", item.get("usd_amount", 0)) or 0)
        due_month = (item.get("due_date") or "")[:7]
        monthly = {key: 0.0 for key in month_keys}
        overdue = amount if due_month and due_month < today_month else 0.0
        if due_month in monthly:
            monthly[due_month] = round(amount, 2)
            totals[due_month] += amount
        elif overdue:
            overdue_total += amount
        rows.append({
            "id": item.get("id"), "group": item.get("expense_type") or "SINIFLANDIRILMAMIŞ",
            "description": item.get("description") or item.get("vendor") or "—", "vendor": item.get("vendor"),
            "ship": item.get("ship") or "—", "debt_type": item.get("budget_category") or "DİĞER",
            "due_date": item.get("due_date"), "overdue": round(overdue, 2), "total": round(amount, 2), "monthly": monthly,
        })
    return {"months": month_keys, "rows": rows, "totals": {k: round(v, 2) for k, v in totals.items()}, "overdue_total": round(overdue_total, 2)}


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
        {"$match": {**CASH_POSTED, "type": "TEDİYE"}},
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


@router.get("/cash-report")
async def report_cash(start: str | None = None, end: str | None = None, user: dict = Depends(get_current_user)):
    return await cash_report_data(start, end)


@router.get("/office-payments")
async def report_office_payments(start: str | None = None, end: str | None = None, user: dict = Depends(get_current_user)):
    return await office_payments_data(start, end)


@router.get("/all-debts")
async def report_all_debts(months: int = 30, user: dict = Depends(get_current_user)):
    return await all_debts_data(months)
