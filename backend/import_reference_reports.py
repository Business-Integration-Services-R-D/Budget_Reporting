"""Import the three supplied legacy PDFs as reproducible report snapshots.

Run with the Python runtime that provides pdfplumber. The imported documents are
kept separate from operational payables/payments so historical report figures do
not change dashboard balances.
"""
import argparse
import asyncio
import re
from datetime import datetime, timezone

import pdfplumber

from database import db


def number(value):
    text = str(value or "").strip().replace("$", "").replace("₺", "").replace("€", "").replace("£", "")
    text = text.replace(",", "")
    if not text or text == "-":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def iso_date(value):
    return datetime.strptime(value, "%d.%m.%Y").date().isoformat()


def read_tables(path):
    with pdfplumber.open(path) as pdf:
        return [table for page in pdf.pages for table in page.extract_tables()]


def cash_snapshot(path):
    tables = read_tables(path)
    filters = dict(zip(tables[0][0], tables[0][1]))
    movements = []
    for row in tables[2]:
        if not str(row[0] or "").isdigit():
            continue
        movements.append({
            "sequence": int(row[0]), "type": row[1], "date": iso_date(row[2]),
            "description": row[3], "payment_method": row[4], "paying_company": row[5],
            "currency": row[6], "fx_rate": number(row[7]), "amount": number(row[8]),
            "usd_amount": round(number(row[8]) / number(row[7]), 2) if number(row[7]) else number(row[8]),
            "ship": row[9],
        })
    balances = []
    for row in tables[3][1:]:
        balances.append({
            "name": row[0], "tl": row[1] or "-", "usd": row[2] or "-", "eur": row[3] or "-",
            "pound": row[4] or "-", "yapi_kredi": row[5] or "-", "yapi_kredi_company": row[6] or "",
        })
    return {"report_id": "cash-report", "source": path, "filters": filters,
            "movements": movements, "balances": balances}


def office_snapshot(path):
    tables = read_tables(path)
    weeks = []

    def add_pair(left, categories):
        header_index = next(index for index, row in enumerate(left) if "HAFTA" in str(row[0] or ""))
        label, period = left[header_index][0], left[header_index][1]
        start_text, end_text = [part.strip() for part in period.split(" - ")]
        rows = []
        data_rows = left[header_index + 1:-1]
        category_rows = categories[1:1 + len(data_rows)]
        for item, category_row in zip(data_rows, category_rows):
            category = next((name for name, value in zip(("BANKA", "OPERASYON", "DİĞER"), category_row) if value), "DİĞER")
            rows.append({"date": iso_date(item[0]), "description": item[1], "company_ship": item[2],
                         "amount": number(item[3]), "currency": item[4], "usd_amount": number(item[5]),
                         "budget_category": category})
        totals = {name: number(value) for name, value in zip(("BANKA", "OPERASYON", "DİĞER"), categories[-1])}
        weeks.append({"week": label, "start": start_text, "end": end_text,
                      "rows": rows, "total_usd": number(left[-1][5]), "category_totals": totals})

    add_pair(tables[0], tables[1])
    add_pair(tables[2], tables[3])
    combined = tables[4]
    label, period = combined[1][0], combined[1][1]
    start_text, end_text = [part.strip() for part in period.split(" - ")]
    rows = []
    for row in combined[2:-1]:
        category = next((name for name, value in zip(("BANKA", "OPERASYON", "DİĞER"), row[7:10]) if value), "DİĞER")
        rows.append({"date": iso_date(row[0]), "description": row[1], "company_ship": row[2],
                     "amount": number(row[3]), "currency": row[4], "usd_amount": number(row[5]),
                     "budget_category": category})
    weeks.append({"week": label, "start": start_text, "end": end_text, "rows": rows,
                  "total_usd": number(combined[-1][5]),
                  "category_totals": dict(zip(("BANKA", "OPERASYON", "DİĞER"), map(number, combined[-1][7:10])))})
    add_pair(tables[5], tables[6])
    add_pair(tables[7], tables[8])
    add_pair(tables[9], tables[10])
    return {"report_id": "office-payments", "source": path, "weeks": weeks,
            "source_grand_total": tables[11][0][1]}


GROUPS = {
    "I": "LİMAN MASRAFLARI", "II": "ADRES KOMİSYONLARI", "III": "GEMİ GİDERLERİ",
    "IV": "YAKIT BORÇLARI", "V": "EU ETS / FUEL EU", "VI": "PİYASA BORÇLARI",
    "VII": "BANKA BORÇLARI", "VIII": "ESKİ PİYASA VE EL BORÇLARI", "IX": "OFİS BÜTÇESİ",
}


def debt_snapshot(path):
    tables = read_tables(path)
    months = tables[0][0][5:]
    rows = []
    active_group = None
    for table in tables:
        for raw in table:
            first = str(raw[0] or "").strip()
            if raw[3] == "BORÇ TÜRÜ" or first == "B A N K A B O R Ç L A R I" or first == "ESKİ PİYASA VE EL BORÇLARI" or first == "O F İ S B Ü T Ç E S İ":
                continue
            total_match = re.search(r"T O P L A M\s*-\s*([IVX]+)", first)
            if total_match:
                roman = total_match.group(1)
                active_group = GROUPS[roman]
                # Assign the group to rows collected since the previous total.
                for item in reversed(rows):
                    if item.get("group"):
                        break
                    item["group"] = active_group
                rows.append({"group": active_group, "is_total": True, "description": f"TOPLAM - {roman}",
                             "ship": "", "debt_type": "", "total": number(raw[4]),
                             "monthly": dict(zip(months, map(number, raw[5:])))})
                active_group = None
                continue
            if first == "G E N E L T O P L A M":
                rows.append({"group": "GENEL", "is_total": True, "is_grand_total": True,
                             "description": "GENEL TOPLAM", "ship": "", "debt_type": "",
                             "total": number(raw[4]), "monthly": dict(zip(months, map(number, raw[5:])))})
                continue
            if not raw[1] and first != "AYLIK OFİS İHTİYAÇLARI İÇİN KAYNAK İHTİYACI":
                continue
            description = raw[1] or first
            rows.append({"group": "", "is_total": False, "description": description,
                         "ship": raw[2] or "", "debt_type": raw[3] or "", "total": number(raw[4]),
                         "monthly": dict(zip(months, map(number, raw[5:])))})
    return {"report_id": "all-debts", "source": path, "months": months, "rows": rows}


async def main(args):
    snapshots = [cash_snapshot(args.cash), office_snapshot(args.office), debt_snapshot(args.debts)]
    now = datetime.now(timezone.utc).isoformat()
    for snapshot in snapshots:
        snapshot["imported_at"] = now
        await db.report_snapshots.replace_one({"report_id": snapshot["report_id"]}, snapshot, upsert=True)
        print(snapshot["report_id"], "imported")
    print("cash movements", len(snapshots[0]["movements"]), "balances", len(snapshots[0]["balances"]))
    print("office rows", sum(len(w["rows"]) for w in snapshots[1]["weeks"]), "weeks", len(snapshots[1]["weeks"]))
    print("debt rows", sum(not r["is_total"] for r in snapshots[2]["rows"]), "sections", sum(r["is_total"] and not r.get("is_grand_total") for r in snapshots[2]["rows"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cash", required=True)
    parser.add_argument("--office", required=True)
    parser.add_argument("--debts", required=True)
    asyncio.run(main(parser.parse_args()))
