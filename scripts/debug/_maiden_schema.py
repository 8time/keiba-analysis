# -*- coding: utf-8 -*-
"""新馬戦シグナル 実現可能性チェック part2（調査専用）。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

print('=== races 全カラム ===')
cols = [c[1] for c in con.execute('PRAGMA table_info(races)')]
print(cols)

print()
print('=== カラム値サンプル（2024 JRA）===')
q = ("SELECT * FROM races WHERE year='2024' AND jyo BETWEEN '01' AND '10' LIMIT 3")
cnames = [d[0] for d in con.execute(q).description]
for row in con.execute(q):
    print(dict(zip(cnames, row)))

print()
print('=== shubetsu × jyo(JRA) 分布 2024 ===')
q = ("SELECT shubetsu, COUNT(*) FROM races "
     "WHERE year='2024' AND jyo BETWEEN '01' AND '10' GROUP BY shubetsu")
for s, c in con.execute(q):
    print(f'  shubetsu={s!r}: {c:,}')

print()
print('=== 新馬戦の特定: 条件名カラムを探す ===')
for col in cols:
    if any(k in col.lower() for k in ('joken', 'class', 'kubun', 'syokai', 'cond', 'naiyo', 'grade')):
        q = (f"SELECT {col}, COUNT(*) FROM races WHERE year='2024' "
             f"AND jyo BETWEEN '01' AND '10' GROUP BY {col} LIMIT 12")
        print(f'--- {col} ---')
        for v, c in con.execute(q):
            print(f'  {v!r}: {c:,}')

con.close()
