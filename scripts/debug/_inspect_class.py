# -*- coding: utf-8 -*-
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect('data/jravan.db')
cur = con.cursor()

print('== 2025 grade x sample race_name ==')
for g in ('', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'L'):
    rows = cur.execute(
        "SELECT race_name, COUNT(*) FROM races WHERE year='2025' AND grade=? "
        "GROUP BY race_name ORDER BY 2 DESC LIMIT 3", (g,)).fetchall()
    tot = cur.execute("SELECT COUNT(*) FROM races WHERE year='2025' AND grade=?", (g,)).fetchone()[0]
    print(f'grade={g!r} total={tot}')
    for r in rows:
        print('   ', r)

print('\n== 2025 race_name contains 新馬/未勝利 counts ==')
for r in cur.execute("SELECT grade, COUNT(*) FROM races WHERE year='2025' AND race_name LIKE '%新馬%' GROUP BY grade"):
    print('新馬', r)
for r in cur.execute("SELECT grade, COUNT(*) FROM races WHERE year='2025' AND race_name LIKE '%未勝利%' GROUP BY grade"):
    print('未勝利', r)
for r in cur.execute("SELECT grade, COUNT(*) FROM races WHERE year='2025' AND race_name LIKE '%勝クラス%' GROUP BY grade"):
    print('勝クラス', r)

print('\n== 2025 新馬 races x 1番人気 join check ==')
q = """
SELECT COUNT(*) FROM results r JOIN races ra ON r.race_key=ra.race_key
WHERE ra.year='2025' AND ra.race_name LIKE '%新馬%' AND r.ninki=1 AND r.chakujun>0
"""
print(cur.execute(q).fetchone())

print('\n== age values 2025 ==')
for r in cur.execute("SELECT age, COUNT(*) FROM results WHERE year='2025' GROUP BY age ORDER BY 1 LIMIT 12"):
    print(r)

print('\n== kigo second char (fillies) 2025 ==')
for r in cur.execute("SELECT substr(kigo,2,1), COUNT(*) FROM races WHERE year='2025' GROUP BY 1"):
    print(r)
con.close()
