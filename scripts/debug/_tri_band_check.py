# -*- coding: utf-8 -*-
"""堅い(C/D)・中庸(B)の勝ち3連単配当の分布。画面の妙味度ラベルで分ける。"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

sys.stdout.reconfigure(encoding='utf-8')
from core.jockey_jv import JV_DB_PATH

r = pd.read_csv('data/export/races.csv', usecols=['race_key', 'day', 'vlabel'])
r = r[r['day'] >= 20240101].copy()
r['race_key'] = r['race_key'].astype(str)
lab = r.set_index('race_key')['vlabel'].astype(str).str[:1]

con = sqlite3.connect(f'file:{JV_DB_PATH}?mode=ro', uri=True)
rows = con.execute(
    "SELECT race_key, payout FROM payouts WHERE bet_type='3連単' AND payout>0"
).fetchall()
con.close()

by = {k: [] for k in ('D', 'C', 'B', 'A', 'S')}
for rk, pay in rows:
    g = lab.get(str(rk))
    if g in by:
        by[g].append(float(pay))

for name, xs in by.items():
    s = pd.Series(xs)
    q = s.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    n = len(s)
    in_user = ((s >= 10000) & (s <= 80000)).mean() * 100
    print(f'{name} n={n}')
    print(f'  10% {q[0.1]:.0f}  25% {q[0.25]:.0f}  中央 {q[0.5]:.0f}  '
          f'75% {q[0.75]:.0f}  90% {q[0.9]:.0f}')
    print(f'  1万〜8万円に入る割合 {in_user:.1f}%')
