"""Excel'den çıkarılmış gerçek verileri MongoDB'ye yükler (idempotent + versiyonlu)."""
import os
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
SEED_FILE = ROOT / "seed" / "data.json"

# Bu versiyon değiştiğinde startup'ta DB'deki data otomatik temizlenir ve yeniden seed olur.
# YENİ DATA EKLEDİĞİNDE BURAYI BUMP ET (örn. v2 → v3)
CURRENT_SEED_VERSION = "marti-2026-05-30-v1"

# Re-seed sırasında temizlenecek koleksiyonlar (kullanıcı verileri korunur)
RESET_COLLECTIONS = [
    "companies", "armators", "managers", "ships", "people", "countries",
    "banks", "expense_types", "accounting_codes", "vendors", "currencies",
    "payment_statuses", "payment_methods", "budget_categories", "payables", "payments", "fx_rates",
    "notifications", "ai_sessions", "ai_messages", "ai_pending_actions", "uploads"
]
# Korunan koleksiyonlar (asla silinmez): users, audit_logs, app_meta,
# password_reset_tokens, login_attempts


async def maybe_reset_for_new_seed(db):
    """Eğer current seed version DB'dekinden farklıysa, tüm seed-edilen koleksiyonları temizle.
    Böylece bir sonraki seed_all() çağrısı taze veri yükler.
    Kullanıcı tarafından eklenen veriler de bu temizlikte gider — bu yüzden seed_version
    sadece kasıtlı veri sıfırlamalarında değiştirilmelidir.
    """
    meta = await db.app_meta.find_one({"key": "seed_version"})
    db_version = (meta or {}).get("value")
    if db_version == CURRENT_SEED_VERSION:
        logger.info("Seed version aynı (%s), reset atlanıyor", db_version)
        return False

    logger.warning("Seed version değişti (%s → %s) — koleksiyonlar temizleniyor...",
                   db_version, CURRENT_SEED_VERSION)
    for col in RESET_COLLECTIONS:
        try:
            result = await db[col].delete_many({})
            if result.deleted_count > 0:
                logger.info("  ✗ %s: %d kayıt silindi", col, result.deleted_count)
        except Exception as e:
            logger.warning("  %s temizlenemedi: %s", col, e)

    # Versiyonu güncelle
    await db.app_meta.update_one(
        {"key": "seed_version"},
        {"$set": {"key": "seed_version", "value": CURRENT_SEED_VERSION,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    logger.info("Seed version DB'ye yazıldı: %s", CURRENT_SEED_VERSION)
    return True


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def seed_all(db):
    """Tüm master data + örnek borç/ödeme verilerini yükle. İdempotent."""
    if not SEED_FILE.exists():
        logger.warning("Seed dosyası yok: %s", SEED_FILE)
        return

    with open(SEED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ---- Companies (Şirketler) ----
    if await db.companies.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": c, "active": True, "created_at": _now()} for c in data.get("companies", []) if c and c != "HEPSİ"]
        if docs:
            await db.companies.insert_many(docs)
            logger.info("Seed: %d şirket", len(docs))

    # ---- Armators ----
    if await db.armators.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": a, "active": True, "created_at": _now()} for a in data.get("armators", []) if a and a != "HEPSİ"]
        if docs:
            await db.armators.insert_many(docs)
            logger.info("Seed: %d armatör", len(docs))

    # ---- Managers ----
    if await db.managers.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": m, "active": True, "created_at": _now()} for m in data.get("managers", []) if m]
        if docs:
            await db.managers.insert_many(docs)
            logger.info("Seed: %d manager", len(docs))

    # ---- Ships (Birimler / Gemiler) ----
    if await db.ships.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": s, "active": True, "manager": None, "armator": None, "created_at": _now()}
                for s in data.get("ships", []) if s and s != "HEPSİ"]
        if docs:
            await db.ships.insert_many(docs)
            logger.info("Seed: %d gemi", len(docs))

    # ---- People (Kişi & Alt Şirketler) ----
    if await db.people.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": p, "active": True, "created_at": _now()} for p in data.get("people", []) if p and p != "HEPSİ"]
        if docs:
            await db.people.insert_many(docs)
            logger.info("Seed: %d kişi/şirket", len(docs))

    # ---- Countries ----
    if await db.countries.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": c, "active": True, "created_at": _now()} for c in data.get("countries", []) if c]
        if docs:
            await db.countries.insert_many(docs)
            logger.info("Seed: %d ülke", len(docs))

    # ---- Banks (Banka & Kasa) ----
    if await db.banks.count_documents({}) == 0:
        docs = [{"id": _uid(), "name": b, "type": "Banka", "currency": "TL", "balance": 0, "active": True, "created_at": _now()}
                for b in data.get("banks", []) if b and b != "HEPSİ"]
        if docs:
            await db.banks.insert_many(docs)
            logger.info("Seed: %d banka", len(docs))

    # ---- Expense Types ----
    if await db.expense_types.count_documents({}) == 0:
        docs = []
        for e in data.get("expense_types", []):
            if not e.get("code") or not e.get("name"): continue
            docs.append({"id": _uid(), "code": str(e["code"]).strip(), "name": e["name"], "active": True, "created_at": _now()})
        if docs:
            await db.expense_types.insert_many(docs)
            logger.info("Seed: %d masraf türü", len(docs))

    # ---- Accounting Codes ----
    if await db.accounting_codes.count_documents({}) == 0:
        docs = []
        for e in data.get("accounting_codes", []):
            if not e.get("code") or not e.get("name"): continue
            docs.append({"id": _uid(), "code": str(e["code"]).strip(), "name": e["name"], "active": True, "created_at": _now()})
        if docs:
            await db.accounting_codes.insert_many(docs)
            logger.info("Seed: %d muhasebe kodu", len(docs))

    # ---- Budget Categories (Günlük ofis ödemeleri rapor sınıfları) ----
    if await db.budget_categories.count_documents({}) == 0:
        defaults = ["BANKA", "OPERASYON", "DİĞER"]
        docs = [{"id": _uid(), "name": name, "active": True, "created_at": _now()} for name in defaults]
        await db.budget_categories.insert_many(docs)
        logger.info("Seed: %d bütçe sınıfı", len(docs))

    # ---- Vendors ----
    if await db.vendors.count_documents({}) == 0:
        docs = []
        for v in data.get("vendors", []):
            if not v.get("name"): continue
            docs.append({"id": _uid(), "name": v["name"], "country": v.get("country"), "active": True, "created_at": _now()})
        if docs:
            await db.vendors.insert_many(docs)
            logger.info("Seed: %d tedarikçi", len(docs))

    # ---- Currencies ----
    if await db.currencies.count_documents({}) == 0:
        docs = []
        for c in data.get("currencies", []):
            if not c.get("code"): continue
            try:
                rate = float(c.get("rate_to_tl") or 0)
            except (TypeError, ValueError):
                rate = 0
            docs.append({"id": _uid(), "code": str(c["code"]).strip(), "rate_to_tl": rate, "active": True, "created_at": _now()})
        if docs:
            await db.currencies.insert_many(docs)
            logger.info("Seed: %d para birimi", len(docs))

    # ---- Payment Statuses ----
    if await db.payment_statuses.count_documents({}) == 0:
        default_statuses = [
            {"name": "TASLAK", "color": "neutral", "order": 1},
            {"name": "ONAY BEKLİYOR", "color": "warning", "order": 2},
            {"name": "ONAYLANDI", "color": "info", "order": 3},
            {"name": "VADESİ GELDİ", "color": "warning", "order": 4},
            {"name": "VADESİ GEÇTİ", "color": "danger", "order": 5},
            {"name": "ÖDENDİ", "color": "success", "order": 6},
            {"name": "KISMİ ÖDEME", "color": "info", "order": 7},
            {"name": "İPTAL", "color": "neutral", "order": 8},
        ]
        docs = [{"id": _uid(), **s, "active": True, "created_at": _now()} for s in default_statuses]
        await db.payment_statuses.insert_many(docs)
        logger.info("Seed: %d ödeme durumu", len(docs))

    # ---- Payment Methods ----
    if await db.payment_methods.count_documents({}) == 0:
        defaults = ["YAPI KREDİ", "DENİZBANK", "AKBANK", "ZİRAAT", "GARANTİ", "İŞ BANKASI", "NAKİT", "ÇEK", "SENET", "KREDİ KARTI", "HAVALE/EFT", "TRANSFER"]
        docs = [{"id": _uid(), "name": m, "active": True, "created_at": _now()} for m in defaults]
        await db.payment_methods.insert_many(docs)
        logger.info("Seed: %d ödeme şekli", len(docs))

    # ---- FX Rates (güncel) ----
    if await db.fx_rates.count_documents({}) == 0:
        today = _now()
        docs = []
        for fx in data.get("fx_rates", []):
            try:
                rate = float(fx.get("rate") or 0)
            except (TypeError, ValueError):
                rate = 0
            if rate > 0:
                docs.append({"id": _uid(), "code": fx["code"], "name": fx.get("name"), "rate_to_tl": rate, "date": today, "created_at": today})
        if docs:
            await db.fx_rates.insert_many(docs)
            logger.info("Seed: %d döviz kuru", len(docs))

    # ---- Payments (Ödeme/Tahsilat hareketleri) ----
    if os.environ.get("SEED_TRANSACTIONS", "true").lower() != "false" and await db.payments.count_documents({}) == 0:
        docs = []
        for p in data.get("payments", []):
            try:
                amount = float(p.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            try:
                fx_rate = float(p.get("fx_rate") or 0)
            except (TypeError, ValueError):
                fx_rate = 0
            try:
                usd = float(p.get("usd_amount") or 0)
            except (TypeError, ValueError):
                usd = 0
            doc = {
                "id": _uid(),
                "external_no": p.get("no"),
                "type": p.get("type"),  # TEDİYE / TAHSİL
                "ship": p.get("ship"),
                "vendor": p.get("vendor"),
                "manager": p.get("manager"),
                "description": p.get("description"),
                "date": p.get("date"),
                "paying_company": p.get("paying_company"),
                "payment_method": p.get("payment_method"),
                "amount": amount,
                "currency": p.get("currency"),
                "fx_rate": fx_rate,
                "usd_amount": usd,
                "approved": p.get("approved", False),
                "created_at": _now(),
            }
            docs.append(doc)
        if docs:
            await db.payments.insert_many(docs)
            logger.info("Seed: %d ödeme", len(docs))

    # ---- Payables (Borçlar) ----
    if os.environ.get("SEED_TRANSACTIONS", "true").lower() != "false" and await db.payables.count_documents({}) == 0:
        # Excel'deki status değerlerini sistemdekine map et
        STATUS_MAP = {
            "ÖDENMEDİ": "VADESİ GEÇTİ",
            "ÖDENDİ": "ÖDENDİ",
            "İPTAL": "İPTAL",
            "SİPARİŞ": "ONAY BEKLİYOR",
            "ONAY BEKLİYOR": "ONAY BEKLİYOR",
            "KISMİ ÖDEME": "KISMİ ÖDEME",
        }
        docs = []
        for p in data.get("payables", []):
            try:
                amount = float(p.get("original_amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            try:
                usd = float(p.get("usd_amount") or 0)
            except (TypeError, ValueError):
                usd = 0
            raw_status = (p.get("status") or "ÖDENMEDİ").upper()
            mapped_status = STATUS_MAP.get(raw_status, raw_status)
            doc = {
                "id": _uid(),
                "external_no": p.get("no"),
                "order_date": p.get("order_date"),
                "due_date": (p.get("due_date") or "")[:10] if p.get("due_date") else None,
                "expense_code": p.get("expense_code"),
                "expense_type": p.get("expense_type"),
                "vendor": p.get("vendor"),
                "country": p.get("country"),
                "person_company": p.get("person_company"),
                "ship": p.get("ship"),
                "armator": p.get("armator"),
                "description": p.get("description") or p.get("expense_type"),
                "year": p.get("year"),
                "month": p.get("month"),
                "status": mapped_status,
                "original_amount": amount,
                "currency": p.get("currency") or "USD",
                "usd_amount": usd,
                "kind": "PAYABLE",
                "source_sheet": p.get("source_sheet"),
                "paying_company": p.get("paying_company"),
                "created_at": _now(),
            }
            docs.append(doc)
        if docs:
            await db.payables.insert_many(docs)
            logger.info("Seed: %d borç (Excel'den)", len(docs))


async def ensure_indexes(db):
    """MongoDB indexleri."""
    await db.users.create_index("email", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")
    await db.app_meta.create_index("key", unique=True)
    # collection bazlı id (uuid string)
    for col in ["companies", "armators", "managers", "ships", "people", "countries",
                "banks", "expense_types", "accounting_codes", "vendors", "currencies",
                "payment_statuses", "payment_methods", "payables", "payments", "fx_rates",
                "notifications", "audit_logs"]:
        await db[col].create_index("id", unique=True)
