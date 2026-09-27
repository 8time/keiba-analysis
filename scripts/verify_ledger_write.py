# -*- coding: utf-8 -*-
"""ledger.db への購入/見送り書き込みを検証する（手動テスト用）。

使い方:
  python scripts/verify_ledger_write.py          # スキーマ表示 + テスト1件ずつ書いて件数確認
  python scripts/verify_ledger_write.py --schema # スキーマのみ
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import sqlite3
from core import money


def dump_schema(db_path):
    print('=== ledger.db schema ===')
    print('path:', db_path)
    if not os.path.exists(db_path):
        print('(file not found — Ledger() creates on first open)')
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall() if not r[0].startswith('sqlite_')]
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        n = cur.fetchone()[0]
        cur.execute(f'PRAGMA table_info("{t}")')
        cols = [x[1] for x in cur.fetchall()]
        print(f'  {t}: {n} rows')
        print(f'    cols: {cols}')
    con.close()


def main():
    schema_only = '--schema' in sys.argv
    db = money.LEDGER_DB
    dump_schema(db)
    if schema_only:
        return

    lg = money.Ledger(db)
    before_b = lg.con.execute('SELECT COUNT(*) FROM bets').fetchone()[0]
    before_s = lg.con.execute('SELECT COUNT(*) FROM skips').fetchone()[0]

    test_rid = '209912319999'
    n = lg.record_kelly_bets(
        test_rid,
        [{'kind': '単勝', 'label': '5', 'odds': 12.0, 'stake': 100, 'p': 0.08}],
        gate_status='buy')
    lg.record_skip(test_rid.replace('9999', '9998'), reason='verify_ledger_write.py テスト',
                   vscore=75.0, zone='C')
    lg.close()

    lg2 = money.Ledger(db)
    after_b = lg2.con.execute('SELECT COUNT(*) FROM bets').fetchone()[0]
    after_s = lg2.con.execute('SELECT COUNT(*) FROM skips').fetchone()[0]
    lg2.close()

    print()
    print('=== write test ===')
    print(f'bets:  {before_b} -> {after_b} (+{after_b - before_b}, kelly={n})')
    print(f'skips: {before_s} -> {after_s} (+{after_s - before_s})')
    ok = (after_b > before_b) and (after_s > before_s)
    print('RESULT:', 'OK' if ok else 'FAIL')
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
