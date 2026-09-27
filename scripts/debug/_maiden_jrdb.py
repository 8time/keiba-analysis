# -*- coding: utf-8 -*-
"""part9: horses_jrdb / training テーブルで未デビュー馬の trainer_code を引けるか。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

for t in ('horses_jrdb', 'training'):
    print(f'=== {t} スキーマ ===')
    cols = [c[1] for c in con.execute(f'PRAGMA table_info({t})')]
    print(' ', cols)
    n = con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  rows: {n:,}')
    if n:
        row = con.execute(f'SELECT * FROM {t} LIMIT 1').fetchone()
        print('  sample:', dict(zip(cols, row)))
    print()

# horses_jrdb に調教師っぽいカラムがあるか
cols = [c[1] for c in con.execute('PRAGMA table_info(horses_jrdb)')]
tr_cols = [c for c in cols if any(k in c.lower() for k in ('tr', 'chok', 'stable', 'name'))]
print('horses_jrdb trainer/name候補:', tr_cols)

con.close()
