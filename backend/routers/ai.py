"""AI router — chat, sessions, execute-action."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from database import db
from finance import OPEN, POSTED, APPROVED
from settlements import OPEN_AMOUNT
from dependencies import get_current_user, write_audit, _uid, _now
from ai_service import chat_with_assistant
from ai_actions import ACTION_HANDLERS, ALLOWED_ACTIONS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


class ChatInput(BaseModel):
    session_id: Optional[str] = None
    message: str


class ExecuteActionInput(BaseModel):
    action_id: str
    confirmed: bool = True
    params_override: Optional[dict] = None


async def _build_assistant_context() -> dict:
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()
    week = (today + timedelta(days=7)).isoformat()
    month = (today + timedelta(days=30)).isoformat()

    open_p = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE"}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    open_r = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "RECEIVABLE"}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    overdue = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE", "due_date": {"$lt": today_iso}}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    week_due = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE", "due_date": {"$gte": today_iso, "$lte": week}}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    month_due = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE", "due_date": {"$gte": today_iso, "$lte": month}}},
        {"$group": {"_id": None, "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}}
    ]).to_list(1)
    paid_total = await db.payments.aggregate([
        {"$match": {**POSTED, "type": "TEDİYE"}},
        {"$group": {"_id": None, "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}}
    ]).to_list(1)

    def g(r):
        if r and r[0]:
            return {"total": float(r[0].get("total", 0) or 0), "count": int(r[0].get("count", 0) or 0)}
        return {"total": 0, "count": 0}

    by_ship = await db.payables.aggregate([
        {"$match": {**OPEN, "kind": "PAYABLE"}},
        {"$group": {"_id": "$ship", "total": {"$sum": OPEN_AMOUNT}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": 15}
    ]).to_list(20)
    by_company = await db.payments.aggregate([
        {"$match": {**POSTED, "type": "TEDİYE"}},
        {"$group": {"_id": "$paying_company", "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": 15}
    ]).to_list(20)
    by_expense = await db.payables.aggregate([
        {"$match": {**APPROVED, "kind": "PAYABLE"}},
        {"$group": {"_id": "$expense_type", "total": {"$sum": "$usd_amount"}}},
        {"$sort": {"total": -1}}, {"$limit": 15}
    ]).to_list(20)
    top_vendors = await db.payments.aggregate([
        {"$match": {**POSTED, "type": "TEDİYE"}},
        {"$group": {"_id": "$vendor", "total": {"$sum": "$usd_amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}}, {"$limit": 15}
    ]).to_list(20)

    aging_raw = await db.payables.find(
        {**OPEN, "kind": "PAYABLE", "due_date": {"$ne": None}},
        {"_id": 0, "due_date": 1, "usd_amount": 1, "remaining_usd": 1}
    ).to_list(5000)
    buckets = {"Vadesi gelmemiş": [0, 0], "0-30": [0, 0], "31-60": [0, 0], "61-90": [0, 0], "90+": [0, 0]}
    for p in aging_raw:
        try: due = datetime.fromisoformat(p["due_date"]).date()
        except Exception: continue
        days = (today - due).days
        amt = float(p.get("remaining_usd", p.get("usd_amount", 0)) or 0)
        if days < 0: buckets["Vadesi gelmemiş"][0] += amt; buckets["Vadesi gelmemiş"][1] += 1
        elif days <= 30: buckets["0-30"][0] += amt; buckets["0-30"][1] += 1
        elif days <= 60: buckets["31-60"][0] += amt; buckets["31-60"][1] += 1
        elif days <= 90: buckets["61-90"][0] += amt; buckets["61-90"][1] += 1
        else: buckets["90+"][0] += amt; buckets["90+"][1] += 1

    upcoming = await db.payables.find({
        **OPEN, "kind": "PAYABLE",
        "due_date": {"$gte": today_iso, "$lte": month}
    }, {"_id": 0}).sort("due_date", 1).to_list(20)

    recent_payments = await db.payments.find(POSTED, {"_id": 0}).sort("created_at", -1).to_list(25)

    cashflow = await db.payments.aggregate([
        {"$match": {**POSTED, "date": {"$ne": None}}},
        {"$addFields": {"_d": {"$dateFromString": {"dateString": "$date", "onError": None}}}},
        {"$match": {"_d": {"$ne": None}}},
        {"$group": {"_id": {"y": {"$year": "$_d"}, "m": {"$month": "$_d"}, "t": "$type"}, "total": {"$sum": "$usd_amount"}}},
        {"$sort": {"_id.y": 1, "_id.m": 1}}
    ]).to_list(200)
    cf_map = {}
    for r in cashflow:
        k = f"{r['_id']['y']:04d}-{r['_id']['m']:02d}"
        cf_map.setdefault(k, {"month": k, "TEDİYE": 0, "TAHSİL": 0})
        cf_map[k][r['_id']['t']] = float(r["total"] or 0)
    monthly_cashflow = list(cf_map.values())[-12:]

    fx_latest = await db.currencies.find({}, {"_id": 0}).to_list(20)

    from routers.reports import report_currency_position as currency_report
    by_currency = await currency_report({})

    return {
        "kpi": {
            "open_payable": g(open_p), "open_receivable": g(open_r),
            "overdue": g(overdue), "week_due": g(week_due), "month_due": g(month_due),
            "paid_total": g(paid_total),
        },
        "by_ship": [{"name": r["_id"] or "Tanımsız", "total": r["total"], "count": r["count"]} for r in by_ship],
        "by_company": [{"name": r["_id"] or "Tanımsız", "total": r["total"], "count": r["count"]} for r in by_company],
        "by_expense": [{"name": r["_id"] or "Tanımsız", "total": r["total"]} for r in by_expense],
        "top_vendors": [{"vendor": r["_id"] or "Tanımsız", "total": r["total"], "count": r["count"]} for r in top_vendors],
        "aging": [{"bucket": k, "total": v[0], "count": v[1]} for k, v in buckets.items()],
        "upcoming": upcoming,
        "recent_payments": recent_payments,
        "monthly_cashflow": monthly_cashflow,
        "fx_latest": fx_latest,
        "by_currency": by_currency,
    }


@router.post("/chat")
async def ai_chat(body: ChatInput, user: dict = Depends(get_current_user)):
    sid = body.session_id or _uid()
    history_docs = await db.ai_messages.find({"session_id": sid}, {"_id": 0}).sort("created_at", 1).to_list(50)
    history = [{"role": h["role"], "content": h["content"]} for h in history_docs]
    context = await _build_assistant_context()
    await db.ai_messages.insert_one({
        "id": _uid(), "session_id": sid, "user_id": user["id"],
        "role": "user", "content": body.message, "created_at": _now()
    })
    result = await chat_with_assistant(sid, body.message, context, history)

    if result.get("type") == "action" and result.get("action") in ALLOWED_ACTIONS:
        action_id = _uid()
        await db.ai_pending_actions.insert_one({
            "id": action_id, "session_id": sid, "user_id": user["id"],
            "action": result.get("action"), "params": result.get("params", {}),
            "summary": result.get("summary"), "status": "pending", "created_at": _now(),
        })
        await db.ai_messages.insert_one({
            "id": _uid(), "session_id": sid, "user_id": user["id"],
            "role": "assistant", "content": result.get("summary") or "Aksiyon önerildi",
            "message_type": "action_proposal", "action_id": action_id,
            "action": result.get("action"), "params": result.get("params", {}),
            "created_at": _now()
        })
        response_content = result.get("summary") or "Aksiyon önerildi"
        response_meta = {
            "type": "action", "action_id": action_id,
            "action": result.get("action"), "params": result.get("params", {}),
            "summary": result.get("summary"),
        }
    else:
        # Action ama bilinmeyen action → text olarak gönder
        response_content = result.get("content") if result.get("type") == "text" else (result.get("summary") or "")
        if result.get("type") == "action" and result.get("action") not in ALLOWED_ACTIONS:
            response_content = f"Üzgünüm, '{result.get('action')}' aksiyonu desteklenmiyor. Sorgu için tekrar deneyin."
        await db.ai_messages.insert_one({
            "id": _uid(), "session_id": sid, "user_id": user["id"],
            "role": "assistant", "content": response_content,
            "message_type": "text", "created_at": _now()
        })
        response_meta = {"type": "text"}

    await db.ai_sessions.update_one(
        {"id": sid},
        {"$set": {"id": sid, "user_id": user["id"], "last_message": body.message[:120], "updated_at": _now()},
         "$setOnInsert": {"created_at": _now(), "title": body.message[:60]}},
        upsert=True,
    )
    return {"session_id": sid, "response": response_content, **response_meta}


@router.post("/execute-action")
async def execute_ai_action(body: ExecuteActionInput, background: BackgroundTasks, user: dict = Depends(get_current_user)):
    pending = await db.ai_pending_actions.find_one({"id": body.action_id, "user_id": user["id"]}, {"_id": 0})
    if not pending:
        raise HTTPException(status_code=404, detail="Aksiyon bulunamadı")
    if pending["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Aksiyon zaten {pending['status']}")
    if not body.confirmed:
        await db.ai_pending_actions.update_one({"id": body.action_id}, {"$set": {"status": "rejected", "rejected_at": _now()}})
        return {"ok": True, "status": "rejected"}

    action = pending["action"]
    params = dict(pending.get("params", {}))
    if body.params_override:
        params.update(body.params_override)

    handler = ACTION_HANDLERS.get(action)
    if not handler:
        await db.ai_pending_actions.update_one({"id": body.action_id}, {"$set": {"status": "failed", "error": "unknown_action"}})
        return {"ok": False, "status": "failed", "error": f"Bilinmeyen aksiyon: {action}"}

    try:
        result = await handler(params, user, background, db)
        await db.ai_pending_actions.update_one({"id": body.action_id}, {"$set": {"status": "completed", "executed_at": _now(), "result_id": result.get("created_id")}})
        await db.ai_messages.insert_one({
            "id": _uid(), "session_id": pending["session_id"], "user_id": user["id"],
            "role": "assistant", "content": result["message"],
            "message_type": "action_result", "created_at": _now()
        })
        await write_audit(user, action, "ai_action", body.action_id, {"params": params, "result_id": result.get("created_id")})
        out = {"ok": True, "status": "completed", "message": result["message"], "created_id": result.get("created_id")}
        if result.get("download_url"):
            out["download_url"] = result["download_url"]
        return out
    except Exception as e:
        logger.exception("Aksiyon execute hatası")
        await db.ai_pending_actions.update_one({"id": body.action_id}, {"$set": {"status": "failed", "error": str(e)}})
        return {"ok": False, "status": "failed", "error": str(e)}


@router.get("/sessions")
async def list_ai_sessions(user: dict = Depends(get_current_user)):
    return await db.ai_sessions.find({"user_id": user["id"]}, {"_id": 0}).sort("updated_at", -1).to_list(50)


@router.get("/sessions/{sid}/messages")
async def ai_session_messages(sid: str, user: dict = Depends(get_current_user)):
    return await db.ai_messages.find({"session_id": sid, "user_id": user["id"]}, {"_id": 0}).sort("created_at", 1).to_list(500)


@router.delete("/sessions/{sid}")
async def delete_ai_session(sid: str, user: dict = Depends(get_current_user)):
    await db.ai_sessions.delete_one({"id": sid, "user_id": user["id"]})
    await db.ai_messages.delete_many({"session_id": sid, "user_id": user["id"]})
    return {"ok": True}
