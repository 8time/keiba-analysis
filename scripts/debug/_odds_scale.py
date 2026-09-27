# -*- coding: utf-8 -*-
"""part7: win_odds のスケール確認。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

vals = [r[0] for r in con.execute(
    "SELECT win_odds FROM results WHERE year='2022' AND ninki=1 "
    "AND win_odds IS NOT NULL LIMIT 2000")]
vals = [float(v) for v in vals if v]
vals.sort()
n = len(vals)
print(f'ninki=1 win_odds: n={n} min={vals[0]} p25={vals[n//4]} '
      f'median={vals[n//2]} p75={vals[3*n//4]} max={vals[-1]}')

vals2 = [r[0] for r in con.execute(
    "SELECT win_odds FROM results WHERE year='2022' AND ninki=10 "
    "AND win_odds IS NOT NULL LIMIT 2000")]
vals2 = sorted(float(v) for v in vals2 if v)
n2 = len(vals2)
print(f'ninki=10 win_odds: n={n2} min={vals2[0]} median={vals2[n2//2]} max={vals2[-1]}')
con.close()
