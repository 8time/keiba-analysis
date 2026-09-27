# -*- coding: utf-8 -*-
"""part4: kigo の月別分布で新馬/未勝利を同定 + 新馬1番人気の強さをJRA規模で測る。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

print('=== 2歳戦 kigo 下2桁 × 月 分布（2024 JRA）===')
q = ("""
SELECT SUBSTR(kigo, -2) AS tail, SUBSTR(monthday,1,2) AS m, COUNT(*)
FROM races
WHERE year='2024' AND jyo BETWEEN '01' AND '10' AND shubetsu='11'
GROUP BY tail, m ORDER BY tail, m
""")
rows = {}
for tail, m, c in con.execute(q):
    rows.setdefault(tail, {})[m] = c
months = [f'{i:02d}' for i in range(1, 13)]
print('tail | ' + ' '.join(f'{m:>4}' for m in months) + ' | total')
for tail, mm in sorted(rows.items(), key=lambda x: -sum(x[1].values())):
    tot = sum(mm.values())
    print(f'{tail:>4} | ' + ' '.join(f'{mm.get(m, 0):>4}' for m in months) + f' | {tot}')

print()
print('=== 仮説: tail=00 が新馬（6月以降のみのはず）===')
q = ("""
SELECT SUBSTR(monthday,1,2), COUNT(*) FROM races
WHERE year='2024' AND jyo BETWEEN '01' AND '10' AND shubetsu='11'
  AND SUBSTR(kigo,-2)='00'
GROUP BY 1 ORDER BY 1
""")
for m, c in con.execute(q):
    print(f'  {m}月: {c}')

con.close()
