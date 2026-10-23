"""AI aksiyon handler'ları — dispatch pattern.
Her aksiyon: async def handler(params: dict, user: dict, background, db) -> {"created_id": ..., "message": ...}
"""
import logging
from io import BytesIO
from datetime import datetime, timezone, timedelta
from dependencies import _uid, _now, require_finance
from finance import OPEN, POSTED, APPROVED, rate, number, basis, allocation
from settlements import normalize_payment_amount, prepare_payment
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
    return float(amount) * await rate(db, currency) / await rate(db, "USD")


async def handle_create_payable(params: dict, user: dict, background, db) -> dict:
    from routers.payables import PayableInput, create_payable_record
    payload = dict(params)
    payload['usd_amount'] = await _calc_usd(db, payload.get('currency', 'USD'), float(payload.get('original_amount') or 0))
    payload['created_by_ai'] = True
    doc = await create_payable_record(db, PayableInput(**payload), user)
    return {'created_id': doc['id'], 'message': f"Borç oluşturuldu: {doc.get('vendor', '')}"}


async def handle_create_payment(params: dict, user: dict, background, db) -> dict:
    from routers.payments import PaymentInput, create_payment_record
    payload = dict(params)
    # AI proposals remain drafts until an explicit posting request.
    payload.setdefault('posting_status', 'draft')
    payload['created_by_ai'] = True
    if payload.get('currency', 'USD') != 'USD' and not payload.get('fx_rate'):
        payload['fx_rate'] = await rate(db, payload['currency'])
    doc = await create_payment_record(db, PaymentInput(**payload), user)
    return {'created_id': doc['id'], 'message': f"{doc['type']} kaydedildi ({doc['posting_status']})."}


async def handle_mark_payable_paid(params: dict, user: dict, background, db) -> dict:
    raise ValueError("Ödendi durumu elle değiştirilemez. Ödeme ve Tahsilat ekranından borca bağlı ödeme kaydedin.")


async def _build_payable_query(scope: str):
    today = datetime.now(timezone.utc).date().isoformat()
    q = {**OPEN, "kind": "PAYABLE"}
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
    total = sum(float(p.get("remaining_usd", p.get("usd_amount", 0)) or 0) for p in items)
    rows = "".join([
        f"<tr><td style='padding:8px;border-bottom:1px solid #E5E5EA;'>{p.get('vendor', '-')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #E5E5EA;'>{p.get('description', '-')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #E5E5EA;text-align:right;'>{(p.get('due_date', '') or '')[:10]}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #E5E5EA;text-align:right;font-weight:600;'>${p.get('remaining_usd', p.get('usd_amount', 0)):,.2f}</td></tr>"
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
    from routers.payables import PayableInput, update_payable_record
    if "vendor" in update and update["vendor"] != target.get("vendor"):
        update["vendor_id"] = None
    await update_payable_record(db, target['id'], PayableInput(**update), user)
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
    from routers.payables import delete_payable_record
    await delete_payable_record(db, target['id'], user)
    return {"created_id": target["id"], "message": f"🗑️ Borç silindi: {target.get('vendor', '?')} — ${target.get('usd_amount', 0):,.2f}"}


async def handle_transfer_between_banks(params: dict, user: dict, background, db) -> dict:
    """Bankalar arası virman. İki kayıt oluşturur: çıkan ve giren."""
    await require_finance(user)
    from_bank = params.get("from_bank")
    to_bank = params.get("to_bank")
    amount = number(params.get("amount"), positive=True)
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
    for doc in (out_doc, in_doc):
        doc["posting_status"] = "posted"
        doc["fx_rate"] = await rate(db, currency)
        await normalize_payment_amount(db, doc)
        await prepare_payment(db, doc)
    if out_doc["bank_account_id"] == in_doc["bank_account_id"]:
        raise ValueError("Aynı banka olamaz")
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
        reference = await db.vendors.find_one({"$or": [{"name": scope_value}, {"aliases": scope_value}, {"id": scope_value}]})
        vendor_query = ({"$or": [{"vendor_id": reference["id"]}, {"vendor": {"$in": [reference["name"], *reference.get("aliases", [])]}}]} if reference else {"vendor": {"$regex": scope_value, "$options": "i"}})
        title = f"{scope_value} — Hesap Özeti"
        payables = await db.payables.find({**APPROVED, **vendor_query}, {"_id": 0}).sort("due_date", -1).to_list(200)
        payments = await db.payments.find({**POSTED, "is_transfer": {"$ne": True}, **vendor_query}, {"_id": 0}).sort("date", -1).to_list(200)
    elif scope_type == "ship":
        title = f"{scope_value} — Gemi Hesap Özeti"
        payables = await db.payables.find({**APPROVED, "ship": scope_value.upper()}, {"_id": 0}).sort("due_date", -1).to_list(500)
        payments = await db.payments.find({**POSTED, "is_transfer": {"$ne": True}, "ship": scope_value.upper()}, {"_id": 0}).sort("date", -1).to_list(500)
    else:
        raise ValueError("scope_type vendor veya ship olmalı")

    debt = sum(float(p.get("usd_amount", 0) or 0) for p in payables if p.get("kind") == "PAYABLE")
    receivable = sum(float(p.get("usd_amount") or 0) for p in payables if p.get("kind") == "RECEIVABLE")
    carrying = {}
    for movement in payments:
        parent = await db.payables.find_one({'id': movement.get('payable_id')}) if movement.get('payable_id') else None
        total, book = basis(parent) if parent and parent.get('status') != 'İPTAL' else (0, 0)
        carrying[movement['id']] = allocation(movement, parent) * book / total if total else float(movement.get('usd_amount') or 0)
    paid = sum(carrying[p['id']] for p in payments if p.get('type') == 'TEDİYE')
    received = sum(carrying[p['id']] for p in payments if p.get('type') == 'TAHSİL')
    balance = debt - paid - receivable + received

    summary_rows = [
        {"label": "Toplam Alacak (USD)", "value": f"${receivable:,.2f}"},
        {"label": "Tahsil Mahsup (USD)", "value": f"${received:,.2f}"},
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
            "Tip": "ALACAK" if p.get("kind") == "RECEIVABLE" else "BORÇ",
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
