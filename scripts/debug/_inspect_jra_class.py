# -*- coding: utf-8 -*-
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect('data/jravan.db')
cur = con.cursor()

JRA = tuple(f'{i:02d}' for i in range(1, 11))
ph = ','.join('?' * len(JRA))

print('== JRA flat races 2025 ==')
q = f"""SELECT COUNT(*) FROM races WHERE year='2025' AND jyo IN ({ph}) AND surface IN ('芝','ダート')"""
print('count:', cur.execute(q, JRA).fetchone())

print('\n== JRA 2025 grade x count ==')
q = f"""SELECT grade, COUNT(*) FROM races WHERE year='2025' AND jyo IN ({ph}) AND surface IN ('芝','ダート') GROUP BY grade"""
for r in cur.execute(q, JRA):
    print(r)

print('\n== JRA 2025 grade x sample names ==')
for g in ('', 'A', 'B', 'C', 'D', 'L'):
    q = f"""SELECT race_name, COUNT(*) FROM races WHERE year='2025' AND jyo IN ({ph})
            AND surface IN ('芝','ダート') AND grade=? GROUP BY race_name ORDER BY 2 DESC LIMIT 4"""
    rows = cur.execute(q, JRA + (g,)).fetchall()
    print(f'grade={g!r}:', rows)

print('\n== JRA 2025 kigo x count (top25) + sample name ==')
q = f"""SELECT kigo, COUNT(*), MAX(race_name) FROM races WHERE year='2025' AND jyo IN ({ph})
        AND surface IN ('芝','ダート') GROUP BY kigo ORDER BY 2 DESC LIMIT 25"""
for r in cur.execute(q, JRA):
    print(r)

print('\n== JRA 2025 shubetsu x count ==')
q = f"""SELECT shubetsu, COUNT(*) FROM races WHERE year='2025' AND jyo IN ({ph})
        AND surface IN ('芝','ダート') GROUP BY shubetsu"""
for r in cur.execute(q, JRA):
    print(r)

print('\n== JRA 2025 kigo detail: shubetsu=11 (2yo) by kigo ==')
q = f"""SELECT kigo, COUNT(*), MAX(race_name) FROM races WHERE year='2025' AND jyo IN ({ph})
        AND surface IN ('芝','ダート') AND shubetsu='11' GROUP BY kigo ORDER BY 2 DESC"""
for r in cur.execute(q, JRA):
    print(r)
con.close()
