"""Notifications + reminders router."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, BackgroundTasks
from database import db
from finance import OPEN
from dependencies import get_current_user, _uid, _now
from email_service import send_payment_reminder

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(unread_only: bool = False, user: dict = Depends(get_current_user)):
    q = {"$or": [{"user_id": user["id"]}, {"user_id": None}]}
    if unread_only:
        q["read"] = False
    return await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/notifications/{nid}/read")
async def mark_read(nid: str, user: dict = Depends(get_current_user)):
    await db.notifications.update_one({"id": nid}, {"$set": {"read": True, "read_at": _now()}})
    return {"ok": True}


@router.post("/notifications/mark-all-read")
async def mark_all_read(user: dict = Depends(get_current_user)):
    await db.notifications.update_many(
        {"$or": [{"user_id": user["id"]}, {"user_id": None}]},
        {"$set": {"read": True, "read_at": _now()}}
    )
    return {"ok": True}


@router.post("/reminders/check-due")
async def check_due_reminders(background: BackgroundTasks, user: dict = Depends(get_current_user)):
    today = datetime.now(timezone.utc).date()
    days_thresholds = [7, 3, 1, 0, -1, -3]
    created = 0
    for delta in days_thresholds:
        target_date = (today + timedelta(days=delta)).isoformat()
        payables = await db.payables.find({
            **OPEN, "kind": "PAYABLE",
            "due_date": target_date
        }, {"_id": 0}).to_list(200)
        for p in payables:
            existing = await db.notifications.find_one({"resource_id": p["id"], "meta.days_until": delta})
            if existing:
                continue
            title = f"Vade {'yaklaşıyor' if delta > 0 else 'geldi/geçti'}: {p.get('vendor', '?')}"
            msg = f"{p.get('vendor')} - {p.get('description', '')} - {p.get('remaining_usd', p.get('usd_amount', 0)):.2f} USD - Vade: {p.get('due_date')}"
            await db.notifications.insert_one({
                "id": _uid(),
                "type": "due_reminder",
                "title": title,
                "message": msg,
                "resource": "payable",
                "resource_id": p["id"],
                "user_id": None,
                "meta": {"days_until": delta, "amount": p.get("remaining_usd", p.get("usd_amount", 0))},
                "read": False,
                "created_at": _now(),
            })
            created += 1
            admins = await db.users.find({"role": "admin"}, {"_id": 0, "email": 1}).to_list(20)
            for a in admins:
                background.add_task(send_payment_reminder, a["email"], p, delta)
    return {"created": created}
