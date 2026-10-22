"""AI aksiyon handler'ları — dispatch pattern.
Her aksiyon: async def handler(params: dict, user: dict, background, db) -> {"created_id": ..., "message": ...}
"""
import logging
from io import BytesIO
from datetime import datetime, timezone, timedelta
from dependencies import _uid, _now
from email_service import send_email
from pdf_service import generate_statement_pdf
import resend
import os
import asyncio

logger = logging.getLogger(__name__)


async def _calc_usd(db, currency: str, amount: float) -> float:
    if not amount or not currency:
        return 0
    if currency.upper() == "USD":
        return float(amount)
    cur = await db.currencies.find_one({"code": currency}, {"_id": 0})
    usd_cur = await db.currencies.find_one({"code": "USD"}, {"_id": 0})
    if cur and usd_cur and usd_cur.get("rate_to_tl"):
        tl = float(amount) * float(cur.get("rate_to_tl") or 0)
        return tl / float(usd_cur["rate_to_tl"])
    return 0


async def handle_create_payable(params: dict, user: dict, background, db) -> dict:
    if not params.get("vendor") or not params.get("original_amount"):
        raise ValueError("vendor ve original_amount zorunlu")
    currency = params.get("currency", "USD")
    amount = float(params.get("original_amount") or 0)
    doc = {
        "id": _uid(), "kind": "PAYABLE",
        "vendor": params.get("vendor"), "ship": params.get("ship"),
        "armator": params.get("armator"), "expense_type": params.get("expense_type"),
        "expense_code": params.get("expense_code"), "country": params.get("country"),
        "description": params.get("description", ""), "order_date": params.get("order_date"),
        "due_date": params.get("due_date"),
        "original_amount": amount, "currency": currency,
        "usd_amount": await _calc_usd(db, currency, amount),
        "status": params.get("status", "ONAY BEKLİYOR"),
        "created_at": _now(), "created_by": user["email"], "created_by_ai": True,
    }
    if doc["due_date"]:
        try:
            d = datetime.fromisoformat(doc["due_date"])
            doc["year"] = d.year; doc["month"] = d.month
        except Exception: pass
    if doc.get("status") in {"ÖDENDİ", "KISMİ ÖDEME"}:
        raise ValueError("Ödendi ve Kısmi Ödeme durumları yalnızca bağlı ödeme/tahsilat hareketleriyle belirlenir.")
    await db.payables.insert_one(doc)
    return {"created_id": doc["id"], "message": f"✅ Yeni borç oluşturuldu: {doc['vendor']} — {amount:,.2f} {currency} (vade: {doc.get('due_date', '-')})"}


async def handle_create_payment(params: dict, user: dict, background, db) -> dict:
    currency = params.get("currency", "USD")
    amount = float(params.get("amount") or 0)
    doc = {
        "id": _uid(),
        "type": params.get("type", "TEDİYE"),
        "vendor": params.get("vendor"),
        "paying_company": params.get("paying_company"),
        "payment_method": params.get("payment_method"),
        "ship": params.get("ship"),
        "description": params.get("description", ""),
        "date": params.get("date"),
        "amount": amount, "currency": currency,
        "fx_rate": float(params.get("fx_rate") or 1),
        "usd_amount": await _calc_usd(db, currency, amount),
        "approved": False, "created_at": _now(),
        "created_by": user["email"], "created_by_ai": True,
    }
    if currency != "USD":
        cur = await db.currencies.find_one({"code": currency}, {"_id": 0})
        if cur and cur.get("rate_to_tl"):
            doc["fx_rate"] = float(cur["rate_to_tl"])
    await db.payments.insert_one(doc)
    return {"created_id": doc["id"], "message": f"✅ {doc['type']} kaydı oluşturuldu: {doc['vendor']} — {amount:,.2f} {currency}"}


async def handle_mark_payable_paid(params: dict, user: dict, background, db) -> dict:
    raise ValueError("Ödendi durumu elle değiştirilemez. Ödeme ve Tahsilat ekranından borca bağlı ödeme kaydedin.")


async def _build_payable_query(scope: str):
    today = datetime.now(timezone.utc).date().isoformat()
    q = {"kind": "PAYABLE", "status": {"$nin": ["ÖDENDİ", "İPTAL"]}}
    label = "Açık Borçlar"
    s = (scope or "").lower()
    if "vadesi_gecmis" in s or "geçmiş" in s:
        q["due_date"] = {"$lt": today}; label = "Vadesi Geçmiş Borçlar"
    elif "bu_ay" in s or "ay" in s:
        month = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        q["due_date"] = {"$gte": today, "$lte": month}; label = "Bu Ay Vadesi Gelen"
    elif s.startswith("gemi:"):
        ship = scope.split(":", 1)[1].strip().upper()
        q["ship"] = ship; label = f"{ship} Borçları"
    elif s.startswith("tedarikci:") or s.startswith("tedarikçi:"):
        vname = scope.split(":", 1)[1].strip()
        q["vendor"] = {"$regex": vname, "$options": "i"}; label = f"{vname} Borçları"
    return q, label


async def handle_send_summary_email(params: dict, user: dict, background, db) -> dict:
    q, label = await _build_payable_query(params.get("scope") or "")
    items = await db.payables.find(q, {"_id": 0}).sort("due_date", 1).to_list(50)
    total = sum(float(p.get("usd_amount", 0) or 0) for p in items)
    rows = "".join([
        f"<tr><td style='padding:8px;border-bottom:1px solid #E5E5EA;'>{p.get('vendor', '-')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #E5E5EA;'>{p.get('description', '-')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #E5E5EA;text-align:right;'>{(p.get('due_date', '') or '')[:10]}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #E5E5EA;text-align:right;font-weight:600;'>${p.get('usd_amount', 0):,.2f}</td></tr>"
        for p in items[:30]
    ])
    body_html = f"""
    <p><strong>{label}</strong> raporu hazırlandı. Toplam: <strong>${total:,.2f}</strong> · {len(items)} kayıt</p>
    <table cellpadding='0' cellspacing='0' border='0' width='100%' style='margin-top:16px;border:1px solid #E5E5EA;border-radius:8px;border-collapse:separate;border-spacing:0;'>
      <thead>
        <tr style='background:#FAFAFA;'>
          <th style='padding:10px;text-align:left;font-size:11px;'>Tedarikçi</th>
          <th style='padding:10px;text-align:left;font-size:11px;'>Açıklama</th>
          <th style='padding:10px;text-align:right;font-size:11px;'>Vade</th>
          <th style='padding:10px;text-align:right;font-size:11px;'>USD</th>
        </tr>
      </thead>
      <tbody>{rows or '<tr><td colspan=4 style=padding:16px;text-align:center;color:#86868B>Kayıt yok</td></tr>'}</tbody>
    </table>
    """
    background.add_task(send_email, user["email"], f"MARTI Denizcilik · {label}", body_html, label)
    return {"created_id": None, "message": f"✅ {label} özet emaili {user['email']} adresine gönderildi ({len(items)} kayıt, toplam ${total:,.2f})"}


# ============================================================
# YENİ AKSİYONLAR
# ============================================================

async def handle_update_payable(params: dict, user: dict, background, db) -> dict:
    """Mevcut borcu güncelle. payable_id veya search ile borcu bul."""
    target = None
    if params.get("payable_id"):
        target = await db.payables.find_one({"id": params["payable_id"]}, {"_id": 0})
    elif params.get("search"):
        target = await db.payables.find_one({
            "kind": "PAYABLE",
            "$or": [
                {"vendor": {"$regex": params["search"], "$options": "i"}},
                {"description": {"$regex": params["search"], "$options": "i"}},
            ]
        }, {"_id": 0})
    if not target:
        raise ValueError("Güncellenecek borç bulunamadı")
    # Güncelleme alanları
    allowed = ["vendor", "ship", "armator", "expense_type", "expense_code", "description",
               "due_date", "original_amount", "currency", "status", "country"]
    update = {k: params[k] for k in allowed if k in params and params[k] is not None}
    if not update:
        raise ValueError("Güncellenecek alan belirtilmedi")
    # USD karşılığı yeniden hesapla
    if "original_amount" in update or "currency" in update:
        new_currency = update.get("currency", target.get("currency", "USD"))
        new_amount = update.get("original_amount", target.get("original_amount", 0))
        update["usd_amount"] = await _calc_usd(db, new_currency, float(new_amount or 0))
    # Vade değiştiyse year/month
    if update.get("due_date"):
        try:
            d = datetime.fromisoformat(update["due_date"])
            update["year"] = d.year; update["month"] = d.month
        except Exception: pass
    update["updated_at"] = _now()
    update["updated_by_ai"] = True
    await db.payables.update_one({"id": target["id"]}, {"$set": update})
    changes = ", ".join([f"{k}={v}" for k, v in update.items() if k not in ("updated_at", "updated_by_ai")])
    return {"created_id": target["id"], "message": f"✅ Borç güncellendi: {target.get('vendor', '?')} → {changes}"}


async def handle_delete_payable(params: dict, user: dict, background, db) -> dict:
    """Borcu sil. payable_id veya search ile bul."""
    target = None
    if params.get("payable_id"):
        target = await db.payables.find_one({"id": params["payable_id"]}, {"_id": 0})
    elif params.get("search"):
        target = await db.payables.find_one({
            "kind": "PAYABLE",
            "$or": [
                {"vendor": {"$regex": params["search"], "$options": "i"}},
                {"description": {"$regex": params["search"], "$options": "i"}},
            ]
        }, {"_id": 0})
    if not target:
        raise ValueError("Silinecek borç bulunamadı")
    # Bağlı ödeme varsa uyar — sadece status=İPTAL'a çekelim
    has_payments = await db.payments.find_one({"payable_id": target["id"]})
    if has_payments:
        await db.payables.update_one({"id": target["id"]}, {"$set": {"status": "İPTAL", "updated_at": _now(), "updated_by_ai": True}})
        return {"created_id": target["id"], "message": f"⚠️ Borca bağlı ödeme olduğu için silinmedi, durumu İPTAL'e alındı: {target.get('vendor', '?')}"}
    await db.payables.delete_one({"id": target["id"]})
    return {"created_id": target["id"], "message": f"🗑️ Borç silindi: {target.get('vendor', '?')} — ${target.get('usd_amount', 0):,.2f}"}


async def handle_transfer_between_banks(params: dict, user: dict, background, db) -> dict:
    """Bankalar arası virman. İki kayıt oluşturur: çıkan ve giren."""
    from_bank = params.get("from_bank")
    to_bank = params.get("to_bank")
    amount = float(params.get("amount") or 0)
    currency = params.get("currency", "USD")
    date = params.get("date") or _now()[:10]
    description = params.get("description") or f"Virman: {from_bank} → {to_bank}"
    if not from_bank or not to_bank or amount <= 0:
        raise ValueError("from_bank, to_bank ve amount zorunlu")
    if from_bank == to_bank:
        raise ValueError("Aynı banka olamaz")

    usd_amount = await _calc_usd(db, currency, amount)
    # Çıkan (TEDİYE)
    out_doc = {
        "id": _uid(), "type": "TEDİYE",
        "payment_method": from_bank,
        "description": description + " (çıkış)",
        "vendor": f"[VIRMAN] {to_bank}",
        "date": date, "amount": amount, "currency": currency,
        "usd_amount": usd_amount,
        "fx_rate": 1, "approved": True,
        "is_transfer": True, "transfer_to": to_bank,
        "created_at": _now(), "created_by": user["email"], "created_by_ai": True,
    }
    in_doc = {
        "id": _uid(), "type": "TAHSİL",
        "payment_method": to_bank,
        "description": description + " (giriş)",
        "vendor": f"[VIRMAN] {from_bank}",
        "date": date, "amount": amount, "currency": currency,
        "usd_amount": usd_amount,
        "fx_rate": 1, "approved": True,
        "is_transfer": True, "transfer_from": from_bank,
        "transfer_pair_id": out_doc["id"],
        "created_at": _now(), "created_by": user["email"], "created_by_ai": True,
    }
    out_doc["transfer_pair_id"] = in_doc["id"]
    await db.payments.insert_many([out_doc, in_doc])
    return {"created_id": out_doc["id"],
            "message": f"🔄 Virman tamam: {from_bank} → {to_bank} · {amount:,.2f} {currency} (${usd_amount:,.2f})"}


async def handle_generate_pdf_statement(params: dict, user: dict, background, db) -> dict:
    """Bir cari hesap/gemi/tedarikçi için PDF özeti üret + emaile gönder."""
    scope_type = params.get("scope_type", "vendor")  # vendor / ship / all
    scope_value = params.get("scope_value")
    if not scope_value:
        raise ValueError("scope_value (örn. 'HEMPEL BOYA' veya 'VICTORIA') zorunlu")

    # Veri çek
    if scope_type == "vendor":
        title = f"{scope_value} — Hesap Özeti"
        payables = await db.payables.find({"vendor": {"$regex": scope_value, "$options": "i"}}, {"_id": 0}).sort("due_date", -1).to_list(200)
        payments = await db.payments.find({"vendor": {"$regex": scope_value, "$options": "i"}}, {"_id": 0}).sort("date", -1).to_list(200)
    elif scope_type == "ship":
        title = f"{scope_value} — Gemi Hesap Özeti"
        payables = await db.payables.find({"ship": scope_value.upper()}, {"_id": 0}).sort("due_date", -1).to_list(500)
        payments = await db.payments.find({"ship": scope_value.upper()}, {"_id": 0}).sort("date", -1).to_list(500)
    else:
        raise ValueError("scope_type vendor veya ship olmalı")

    debt = sum(float(p.get("usd_amount", 0) or 0) for p in payables if p.get("kind") == "PAYABLE")
    paid = sum(float(p.get("usd_amount", 0) or 0) for p in payments if p.get("type") == "TEDİYE")
    balance = debt - paid

    summary_rows = [
        {"label": "Toplam Borç (USD)", "value": f"${debt:,.2f}"},
        {"label": "Toplam Ödenen (USD)", "value": f"${paid:,.2f}"},
        {"label": "Bakiye (USD)", "value": f"${balance:,.2f}"},
        {"label": "Kayıt Sayısı", "value": f"{len(payables)} borç · {len(payments)} ödeme"},
    ]
    # Detay rows - en son 30 hareket
    detail_rows = []
    for p in payables[:20]:
        detail_rows.append({
            "Tarih": (p.get("due_date") or "")[:10],
            "Tip": "BORÇ",
            "Açıklama": (p.get("description") or p.get("expense_type") or "")[:60],
            "USD": f"${float(p.get('usd_amount', 0) or 0):,.2f}",
        })
    for p in payments[:20]:
        detail_rows.append({
            "Tarih": (p.get("date") or "")[:10],
            "Tip": p.get("type", "?"),
            "Açıklama": (p.get("description") or p.get("payment_method") or "")[:60],
            "USD": f"${float(p.get('usd_amount', 0) or 0):,.2f}",
        })
    detail_rows.sort(key=lambda x: x.get("Tarih") or "", reverse=True)

    pdf_bytes = generate_statement_pdf(
        title=title,
        subtitle=f"Oluşturulma: {datetime.now().strftime('%d.%m.%Y %H:%M')} · {len(detail_rows)} hareket",
        summary_rows=summary_rows,
        detail_rows=detail_rows[:40],
        detail_headers=["Tarih", "Tip", "Açıklama", "USD"],
    )

    # PDF'i upload olarak kaydet (kullanıcı sonradan indirebilsin)
    from pathlib import Path
    upload_dir = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
    fid = _uid()
    fname = f"{fid}.pdf"
    fpath = upload_dir / fname
    fpath.write_bytes(pdf_bytes)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in scope_value)
    pretty_name = f"hesap-ozeti-{safe_name}-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
    await db.uploads.insert_one({
        "id": fid, "filename": pretty_name, "stored_as": fname,
        "mime": "application/pdf", "size": len(pdf_bytes),
        "attached_to": "ai_statement", "attached_id": None,
        "uploaded_by": user["email"], "created_at": _now(),
    })

    # Email gönder
    body_html = f"""
    <p>Talep ettiğiniz <strong>{title}</strong> hazırlandı.</p>
    <p>Özet:</p>
    <ul>
      <li>Toplam Borç: <strong>${debt:,.2f}</strong></li>
      <li>Toplam Ödenen: <strong>${paid:,.2f}</strong></li>
      <li>Bakiye: <strong>${balance:,.2f}</strong></li>
    </ul>
    <p>PDF rapor ektedir.</p>
    """

    # Resend ile attachment (async direct call)
    api_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
    sender_name = os.environ.get("SENDER_NAME", "MARTI Denizcilik Finans")
    if api_key:
        resend.api_key = api_key
        try:
            import base64
            attach_b64 = base64.b64encode(pdf_bytes).decode("ascii")
            params_email = {
                "from": f"{sender_name} <{sender}>",
                "to": [user["email"]],
                "subject": f"MARTI Denizcilik · {title}",
                "html": body_html,
                "attachments": [{"filename": pretty_name, "content": attach_b64}],
            }
            background.add_task(resend.Emails.send, params_email)
        except Exception as e:
            logger.warning("PDF email gönderme hatası: %s", e)

    return {
        "created_id": fid,
        "message": f"📄 PDF özet oluşturuldu ({len(pdf_bytes)/1024:.0f} KB) ve {user['email']} adresine gönderildi. Sistemde de kayıtlı (uploads).",
        "download_url": f"/api/uploads/{fid}",
    }


# Dispatch dict
ACTION_HANDLERS = {
    "create_payable": handle_create_payable,
    "create_payment": handle_create_payment,
    "mark_payable_paid": handle_mark_payable_paid,
    "send_summary_email": handle_send_summary_email,
    "update_payable": handle_update_payable,
    "delete_payable": handle_delete_payable,
    "transfer_between_banks": handle_transfer_between_banks,
    "generate_pdf_statement": handle_generate_pdf_statement,
}

ALLOWED_ACTIONS = set(ACTION_HANDLERS.keys())
