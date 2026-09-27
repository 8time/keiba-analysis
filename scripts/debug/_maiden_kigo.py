# -*- coding: utf-8 -*-
"""新馬戦シグナル 実現可能性チェック part3（調査専用）: kigo から新馬特定。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

print('=== 2歳戦(shubetsu=11) の kigo 分布（2024 JRA）===')
q = ("SELECT kigo, COUNT(*) FROM races WHERE year='2024' "
     "AND jyo BETWEEN '01' AND '10' AND shubetsu='11' "
     "GROUP BY kigo ORDER BY COUNT(*) DESC")
for k, c in con.execute(q):
    print(f'  kigo={k!r}: {c:,}')

print()
print('=== kigo 先頭1-2文字の分布（2歳戦・全年・JRA）===')
q = ("SELECT SUBSTR(kigo,1,2), COUNT(*) FROM races "
     "WHERE jyo BETWEEN '01' AND '10' AND shubetsu='11' "
     "GROUP BY SUBSTR(kigo,1,2) ORDER BY COUNT(*) DESC LIMIT 20")
for k, c in con.execute(q):
    print(f'  {k!r}: {c:,}')

con.close()
