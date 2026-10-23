"""Idempotent representative data for validating the three operational report templates."""
import asyncio
from datetime import datetime, timezone
from database import db, client

NOW = datetime.now(timezone.utc).isoformat()


def payable(index, due_date, vendor, ship, group, category, usd, amount=None, currency="USD"):
    return {
        "id": f"report-demo-payable-{index}", "report_demo": True, "kind": "PAYABLE",
        "order_date": "2026-10-23", "due_date": due_date, "vendor": vendor, "ship": ship,
        "expense_type": group, "budget_category": category, "description": vendor,
        "original_amount": amount if amount is not None else usd, "currency": currency,
        "usd_amount": usd, "remaining_usd": usd, "status": "ONAYLANDI",
        "approval_status": "approved", "payment_status": "unpaid",
        "year": int(due_date[:4]), "month": int(due_date[5:7]),
        "created_at": NOW, "created_by": "report-demo@local",
    }


def payment(index, movement_type, description, amount, currency, usd, fx, ship):
    return {
        "id": f"report-demo-payment-{index}", "report_demo": True, "type": movement_type,
        "date": "2026-10-23", "description": description, "vendor": description,
        "payment_method": "RAPOR DEMO KASA", "bank_account_id": "report-demo-bank",
        "paying_company": "MARTI", "ship": ship, "amount": amount, "currency": currency,
        "fx_rate": fx, "usd_amount": usd, "approved": True, "posting_status": "posted",
        "voided": False, "is_offset": False, "created_at": NOW, "created_by": "report-demo@local",
    }


async def main():
    await db.banks.replace_one({"id": "report-demo-bank"}, {
        "id": "report-demo-bank", "name": "RAPOR DEMO KASA", "type": "Kasa", "currency": "USD",
        "balance": 250000, "company": "MARTI", "notes": "Üç rapor şablonunun kontrol verisi",
        "active": True, "report_demo": True, "created_at": NOW,
    }, upsert=True)
    for name in ("VICTORIA", "VALENTINA1", "MORNING", "CENDA", "MARTI"):
        await db.ships.update_one({"name": name}, {"$setOnInsert": {"id": f"report-demo-ship-{name}", "name": name, "active": True, "created_at": NOW}}, upsert=True)
    debts = [
        payable(1, "2026-10-27", "YAPI VE KREDİ A.Ş. KREDİ", "MARTI", "BANKA BORÇLARI", "BANKA", 5531.88, 259998.18, "TL"),
        payable(2, "2026-10-28", "ZİRAAT KATILIM A.Ş. KREDİ", "MARTI", "BANKA BORÇLARI", "BANKA", 8172.76, 384119.59, "TL"),
        payable(3, "2026-10-29", "BUSINESS İSTANBUL AİDAT", "MARTI", "OFİS BÜTÇESİ", "DİĞER", 1595.74, 75000, "TL"),
        payable(4, "2026-11-02", "GULF AGENCY - SUEZ", "VALENTINA1", "LİMAN MASRAFLARI", "OPERASYON", 296003.82),
        payable(5, "2026-11-03", "GEMİ ÜZERİNDEKİ PERSONEL ÜCRETİ", "VICTORIA", "GEMİ BORÇLARI", "DİĞER", 95926),
        payable(6, "2026-11-04", "JUPITER SHIPPING", "MORNING", "YAKIT BORÇLARI", "OPERASYON", 103752.02),
        payable(7, "2026-11-09", "MRI 1 LTD. LEASE", "VALENTINA1", "GEMİ BORÇLARI", "DİĞER", 92400),
        payable(8, "2026-12-10", "MRI 2 LTD. LEASE", "VICTORIA", "GEMİ BORÇLARI", "DİĞER", 89400),
        payable(9, "2027-01-15", "LOCKTON OMNI H&M", "VALENTINA1", "SİGORTA BORÇLARI", "OPERASYON", 28023),
        payable(10, "2027-02-15", "THE LONDON P&I", "VICTORIA", "SİGORTA BORÇLARI", "OPERASYON", 61758),
    ]
    for doc in debts:
        await db.payables.replace_one({"id": doc["id"]}, doc, upsert=True)
        await db.vendors.update_one({"name": doc["vendor"]}, {"$setOnInsert": {"id": f"report-demo-vendor-{doc['id']}", "name": doc["vendor"], "active": True, "created_at": NOW}}, upsert=True)
    movements = [
        payment(1, "TAHSİL", "USD HESAPTAN RAPOR DEMO KASA", 21000, "USD", 21000, 1, "VICTORIA"),
        payment(2, "TEDİYE", "GEMİ PERSONEL ÜCRETİ", 3500, "USD", 3500, 1, "VICTORIA"),
        payment(3, "TAHSİL", "TL HESAPTAN RAPOR DEMO KASA", 75563.52, "TL", 1602.78, 47.1647, "VICTORIA"),
        payment(4, "TEDİYE", "LİMAN MASRAFI", 42000, "USD", 42000, 1, "VALENTINA1"),
        payment(5, "TAHSİL", "GBP HESAPTAN RAPOR DEMO KASA", 7000, "GBP", 9441.12, 0.7414, "VALENTINA1"),
        payment(6, "TEDİYE", "EFT MASRAFI", 55.61, "TL", 1.18, 47.1647, "MARTI"),
    ]
    for doc in movements:
        await db.payments.replace_one({"id": doc["id"]}, doc, upsert=True)
    print(f"Rapor demo verisi hazır: {len(debts)} borç, {len(movements)} kasa hareketi, 1 demo kasa.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
