# -*- coding: utf-8 -*-
"""part6: results スキーマ確認（trainer_code/odds の有無）。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

cols = [c[1] for c in con.execute('PRAGMA table_info(results)')]
print('results columns:', cols)

print()
q = ("SELECT ketto_num, jockey_name, trainer_code, ninki, chakujun "
     "FROM results WHERE trainer_code IS NOT NULL AND trainer_code<>'' LIMIT 3")
for r in con.execute(q):
    print(r)

# odds 系カラム
odds_cols = [c for c in cols if 'odd' in c.lower() or 'tan' in c.lower()
             or 'fuku' in c.lower() or 'pay' in c.lower()]
print('odds-like columns:', odds_cols)
if odds_cols:
    c0 = odds_cols[0]
    q = f"SELECT {c0} FROM results WHERE {c0} IS NOT NULL AND {c0}<>'' LIMIT 5"
    for r in con.execute(q):
        print(f'  {c0} sample:', r)

con.close()
