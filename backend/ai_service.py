"""AI servisleri — GPT-5.2 ile OCR (fatura okuma) + Asistan (function calling)."""
import os
import json
import base64
import logging
import re
from typing import List, Optional, Any
try:
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
except ModuleNotFoundError as exc:
    if exc.name != "emergentintegrations":
        raise
    LlmChat = UserMessage = FileContentWithMimeType = None

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MODEL = "gpt-5.2"
PROVIDER = "openai"


def _new_chat(session_id: str, system_message: str) -> LlmChat:
    return LlmChat(
        api_key=API_KEY,
        session_id=session_id,
        system_message=system_message,
    ).with_model(PROVIDER, MODEL)


# ============================================================
# OCR — Fatura Okuma (Vision)
# ============================================================
OCR_SYSTEM = """Sen denizcilik şirketi için fatura okuyan bir uzmansın. Sana verilen fatura görselinden aşağıdaki bilgileri çıkar ve SADECE GEÇERLİ BİR JSON döndür (başka hiçbir açıklama yok):

{
  "vendor": "Tedarikçi/firma adı",
  "invoice_no": "Fatura numarası",
  "invoice_date": "YYYY-MM-DD formatında fatura tarihi",
  "due_date": "YYYY-MM-DD formatında vade tarihi (yoksa invoice_date kullan)",
  "original_amount": 12345.67,
  "currency": "USD / EUR / TL / GBP vs.",
  "description": "Faturada bahsedilen mal/hizmet kısa açıklaması",
  "tax_amount": 0,
  "country": "Türkiye gibi",
  "confidence": 0.95
}

Eğer bir alanı tespit edemiyorsan null kullan. Tutar mutlaka sayısal olmalı (string değil).
Para birimi sembolünden (₺, $, €) veya yazıdan tespit et: ₺/TL/Lira → "TL", $/USD/Dollar → "USD", €/EUR/Euro → "EUR"."""


def _safe_json(text: str) -> dict:
    """LLM cevabından JSON'u temizleyerek parse et."""
    text = text.strip()
    # ```json fence varsa temizle
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # İlk { ile son } arasını al
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except Exception as e:
        logger.warning("JSON parse hatası: %s | text=%s", e, text[:200])
        return {}


async def ocr_invoice(file_path: str, mime_type: str = "image/jpeg") -> dict:
    """Bir fatura görselini OCR ile yapılandırılmış JSON'a çevirir."""
    if not API_KEY or LlmChat is None:
        return {"error": "AI servisi yapılandırılmamış"}
    chat = _new_chat(session_id=f"ocr-{os.path.basename(file_path)}", system_message=OCR_SYSTEM)
    file_content = FileContentWithMimeType(file_path=file_path, mime_type=mime_type)
    msg = UserMessage(
        text="Bu faturayı oku ve sadece JSON döndür. Açıklama yok.",
        file_contents=[file_content],
    )
    try:
        response = await chat.send_message(msg)
        return _safe_json(response)
    except Exception as e:
        logger.exception("OCR hatası")
        return {"error": str(e)}


# ============================================================
# AI Asistan — Function Calling pattern (2-step)
# ============================================================
ASSISTANT_SYSTEM = """Sen MARTI Denizcilik Finans Platformu'nun yapay zeka asistanısın. Türkçe konuş.

Bu denizcilik finansman yönetim sisteminde:
- "Birim/Gemi" = ship (örn: VICTORIA, MORNING, VALENTINA1, CENDA, GEMİ DIŞI)
- "Şirket" = paying company (örn: MARTI, MAKRO, SPOT A.Ş., MORNING, VICTORIA, VALENTINA, CENDA)
- "Tedarikçi/Firma" = vendor (örn: HEMPEL BOYA, AVS KÜRESEL GEMİ, SHANGHAI MARINE)
- "Borç" = payable (kind=PAYABLE), "Alacak" = receivable (kind=RECEIVABLE)
- "Tediye" = ödeme yapılan, "Tahsil" = tahsilat alınan

# AKSİYON MODU
Eğer kullanıcı SADECE BİR AKSİYON ALMANI istiyorsa (yeni borç ekle, borcu ödendi işaretle, hesap özetini email gönder), CEVAP OLARAK YALNIZCA AŞAĞIDAKİ FORMATTA JSON DÖNDÜR (başka açıklama yok, kod bloğu yok):

{"action": "create_payable", "params": {"vendor": "...", "ship": "...", "expense_type": "...", "original_amount": 50000, "currency": "USD", "due_date": "2026-03-30", "description": "..."}, "summary": "İnsan dili kısa açıklama"}

Desteklenen aksiyonlar:
1. **create_payable** — Yeni borç ekle
   params: vendor (zorunlu), ship, expense_type, original_amount (sayı), currency (TL/USD/EUR/GBP), due_date (YYYY-MM-DD), description, country, armator
2. **create_payment** — Tediye/Tahsil hareketi ekle
   params: type (TEDİYE veya TAHSİL), vendor, paying_company, payment_method (banka adı), amount (sayı), currency, date (YYYY-MM-DD), description, ship
3. **mark_payable_paid** — Bir borcu ödendi olarak işaretle
   params: search (vendor veya açıklama içinde geçen kelime ile arar) VEYA payable_id
4. **send_summary_email** — Kullanıcının email adresine özet gönder
   params: to_self (true), scope (örn: "vadesi_gecmis", "bu_ay_vadesi", "gemi:VICTORIA", "tedarikci:HEMPEL")
5. **update_payable** — Mevcut borcu güncelle
   params: search VEYA payable_id (zorunlu) + güncellenecek alanlar (vendor, ship, expense_type, due_date, original_amount, currency, status, description, country, armator)
6. **delete_payable** — Borcu sil (bağlı ödeme varsa İPTAL'e alır)
   params: search VEYA payable_id
7. **transfer_between_banks** — Bankalar/kasalar arası virman
   params: from_bank (zorunlu), to_bank (zorunlu), amount (zorunlu sayı), currency, date (YYYY-MM-DD), description
8. **generate_pdf_statement** — PDF hesap özeti üret ve emaile gönder
   params: scope_type ("vendor" veya "ship"), scope_value (örn: "HEMPEL BOYA" veya "VICTORIA")

Aksiyon JSON'ı dönerken:
- Eksik zorunlu alan varsa AKSİYON DEĞİL — normal dilde "şu bilgi eksik, paylaşır mısın?" diye sor
- Para birimi belirtilmemişse USD varsayma, kullanıcıya sor
- Tarih relatife ise (örn: "yarın", "gelecek hafta") gerçek YYYY-MM-DD'ye çevir

# SORGU MODU
Eğer kullanıcı sadece bilgi/sorgu istiyorsa (kaç, hangi, ne kadar, listele vs.), context'teki gerçek veriden NORMAL TÜRKÇE CEVAP ver — JSON DEĞİL.

# Cevap kuralları (sorgu modu için):
- Net, sayısal, kısa cevaplar ver
- USD tutarlarda $ işareti ve binlik ayırıcı: $1,234,567
- Liste için madde madde max 10 satır
- Veride olmayan bilgi için "bu bilgiye sahip değilim" de
- Veri yoksa "kayıt bulunamadı" de
- Profesyonel finans dili"""


def _build_context(stats: dict) -> str:
    """MongoDB'den toplanan istatistikleri AI için context metnine çevir."""
    parts = []
    if stats.get("kpi"):
        k = stats["kpi"]
        parts.append("## GENEL DURUM (USD):")
        parts.append(f"- Açık borç toplamı: ${k.get('open_payable', {}).get('total', 0):,.0f} ({k.get('open_payable', {}).get('count', 0)} kayıt)")
        parts.append(f"- Açık alacak toplamı: ${k.get('open_receivable', {}).get('total', 0):,.0f}")
        parts.append(f"- Vadesi geçmiş: ${k.get('overdue', {}).get('total', 0):,.0f} ({k.get('overdue', {}).get('count', 0)} kayıt)")
        parts.append(f"- Bu hafta vadesi: ${k.get('week_due', {}).get('total', 0):,.0f}")
        parts.append(f"- Bu ay vadesi: ${k.get('month_due', {}).get('total', 0):,.0f}")
        parts.append(f"- Tüm zamanlar ödenen: ${k.get('paid_total', {}).get('total', 0):,.0f}")
        parts.append("")

    if stats.get("by_ship"):
        parts.append("## GEMİ BAZINDA AÇIK BORÇ (USD):")
        for r in stats["by_ship"][:15]:
            parts.append(f"- {r.get('name')}: ${r.get('total', 0):,.0f} ({r.get('count', 0)} kayıt)")
        parts.append("")

    if stats.get("by_company"):
        parts.append("## ŞİRKET BAZINDA TOPLAM ÖDEME (USD):")
        for r in stats["by_company"][:15]:
            parts.append(f"- {r.get('name')}: ${r.get('total', 0):,.0f} ({r.get('count', 0)} işlem)")
        parts.append("")

    if stats.get("by_expense"):
        parts.append("## MASRAF TÜRÜ BAZINDA BORÇ (USD):")
        for r in stats["by_expense"][:15]:
            parts.append(f"- {r.get('name')}: ${r.get('total', 0):,.0f}")
        parts.append("")

    if stats.get("top_vendors"):
        parts.append("## EN ÇOK ÖDEME YAPILAN İLK 15 TEDARİKÇİ:")
        for r in stats["top_vendors"][:15]:
            parts.append(f"- {r.get('vendor')}: ${r.get('total', 0):,.0f} ({r.get('count', 0)} işlem)")
        parts.append("")

    if stats.get("aging"):
        parts.append("## YAŞLANDIRMA (Vadesi geçen borçlar):")
        for r in stats["aging"]:
            parts.append(f"- {r.get('bucket')} gün: ${r.get('total', 0):,.0f} ({r.get('count', 0)} kayıt)")
        parts.append("")

    if stats.get("upcoming"):
        parts.append("## YAKLAŞAN VADELER (sonraki 30 gün):")
        for p in stats["upcoming"][:15]:
            parts.append(f"- {p.get('due_date', '')[:10]} | {p.get('vendor', '?')} | {p.get('ship', '?')} | ${p.get('usd_amount', 0):,.0f} | {p.get('status', '?')}")
        parts.append("")

    if stats.get("recent_payments"):
        parts.append("## SON 20 ÖDEME/TAHSİLAT:")
        for p in stats["recent_payments"][:20]:
            parts.append(f"- {(p.get('date') or '')[:10]} | {p.get('type', '?')} | {p.get('vendor', '?')} | {p.get('paying_company', '?')} | ${p.get('usd_amount', 0):,.0f}")
        parts.append("")

    if stats.get("monthly_cashflow"):
        parts.append("## SON 12 AY NAKİT AKIŞI (USD):")
        for m in stats["monthly_cashflow"]:
            parts.append(f"- {m.get('month')}: Tediye ${m.get('TEDİYE', 0):,.0f} / Tahsil ${m.get('TAHSİL', 0):,.0f}")
        parts.append("")

    if stats.get("by_currency"):
        parts.append("## DÖVİZ POZİSYON:")
        for c in stats["by_currency"]:
            parts.append(f"- {c.get('currency')}: Borç {c.get('borç', 0):,.0f}, Alacak {c.get('alacak', 0):,.0f}")
        parts.append("")

    if stats.get("fx_latest"):
        parts.append("## GÜNCEL TCMB KURLARI (TL karşılığı):")
        for f in stats["fx_latest"][:6]:
            parts.append(f"- {f.get('code')}: {f.get('rate_to_tl', 0):.4f} ₺")
        parts.append("")

    return "\n".join(parts) if parts else "Veri bulunamadı."


async def chat_with_assistant(session_id: str, user_text: str, context_stats: dict, history: list = None) -> dict:
    """AI asistana soru sor. Dönüş:
       - {"type": "text", "content": "..."} → düz cevap
       - {"type": "action", "action": "...", "params": {...}, "summary": "..."} → kullanıcıdan onay bekleyen aksiyon
    """
    if not API_KEY or LlmChat is None:
        return {"type": "text", "content": "AI servisi yapılandırılmamış. Lütfen sistem yöneticisine başvurun."}
    context_text = _build_context(context_stats)
    full_system = ASSISTANT_SYSTEM + "\n\n# GÜNCEL FİNANSAL VERİ\n\n" + context_text

    if history:
        recap = "\n\n# ÖNCEKİ KONUŞMA\n"
        for h in history[-6:]:
            role = "Kullanıcı" if h.get("role") == "user" else "Asistan"
            recap += f"{role}: {h.get('content', '')[:300]}\n"
        full_system += recap

    chat = _new_chat(session_id=session_id, system_message=full_system)
    try:
        resp = await chat.send_message(UserMessage(text=user_text))
        text = resp.strip()
        # JSON aksiyon mu kontrol et
        parsed = _safe_json(text)
        if parsed and isinstance(parsed, dict) and parsed.get("action") and parsed.get("params") is not None:
            return {
                "type": "action",
                "action": parsed.get("action"),
                "params": parsed.get("params", {}),
                "summary": parsed.get("summary", "Bu aksiyonu onaylıyor musunuz?"),
            }
        return {"type": "text", "content": text}
    except Exception as e:
        logger.exception("Asistan hatası")
        return {"type": "text", "content": f"Hata: {str(e)}"}
