"""Restore original local transactions without replacing newly created records.

Preview: .venv/bin/python restore_local_transactions.py
Restore: .venv/bin/python restore_local_transactions.py --apply
"""
import argparse
from pathlib import Path
from urllib.parse import urlsplit
from bson import json_util
from dotenv import dotenv_values
from pymongo import MongoClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = dotenv_values(root / '.env')
    if urlsplit(config['MONGO_URL']).hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Bu araç yalnızca yerel MongoDB için kullanılabilir.')
    if config['DB_NAME'] != 'budget_reporting_editing':
        raise SystemExit('Hedef budget_reporting_editing olmalıdır.')
    backup = root.parent / '.local-backups' / '20261022-150738'
    # Read all files before writing anything. This backup contains original amounts.
    records = {name: json_util.loads((backup / f'{name}.json').read_text())
               for name in ('payables', 'payments')}
    with MongoClient(config['MONGO_URL'], serverSelectionTimeoutMS=5000) as client:
        db = client[config['DB_NAME']]
        for name, docs in records.items():
            restored = 0
            for doc in docs:
                if not doc.get('id'):
                    raise SystemExit(f'{name}: kimliksiz kayıt; işlem durduruldu.')
                if args.apply:
                    result = db[name].update_one({'id': doc['id']}, {'$setOnInsert': doc}, upsert=True)
                    restored += result.upserted_id is not None
            print(f'{name}: {len(docs)} yedek kayıt' +
                  (f', {restored} geri getirildi' if args.apply else ' (önizleme)'))
    if not args.apply:
        print('Geri getirmek için --apply ekleyin. Yeni kayıtlar korunur.')


if __name__ == '__main__':
    main()
