# -*- coding: utf-8 -*-
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect('data/jravan.db')
cur = con.cursor()

print('== year x count (results, chakujun>0) ==')
for r in cur.execute("SELECT year, COUNT(*) FROM results WHERE chakujun>0 GROUP BY year ORDER BY year"):
    print(r)

print('\n== grade values ==')
for r in cur.execute("SELECT grade, COUNT(*) FROM races GROUP BY grade ORDER BY 2 DESC LIMIT 30"):
    print(r)

print('\n== surface ==')
for r in cur.execute("SELECT surface, COUNT(*) FROM races GROUP BY surface"):
    print(r)

print('\n== baba_shiba / baba_dirt ==')
for r in cur.execute("SELECT baba_shiba, COUNT(*) FROM races GROUP BY baba_shiba"):
    print(r)
for r in cur.execute("SELECT baba_dirt, COUNT(*) FROM races GROUP BY baba_dirt"):
    print(r)

print('\n== sex (results) ==')
for r in cur.execute("SELECT sex, COUNT(*) FROM results GROUP BY sex"):
    print(r)

print('\n== kyakushitsu ==')
for r in cur.execute("SELECT kyakushitsu, COUNT(*) FROM results GROUP BY kyakushitsu"):
    print(r)

print('\n== blinker ==')
for r in cur.execute("SELECT blinker, COUNT(*) FROM results GROUP BY blinker"):
    print(r)

print('\n== time samples ==')
for r in cur.execute("SELECT DISTINCT time FROM results WHERE time IS NOT NULL LIMIT 8"):
    print(r)

print('\n== kigo samples ==')
for r in cur.execute("SELECT kigo, COUNT(*) FROM races GROUP BY kigo ORDER BY 2 DESC LIMIT 15"):
    print(r)

print('\n== shubetsu samples ==')
for r in cur.execute("SELECT shubetsu, COUNT(*) FROM races GROUP BY shubetsu ORDER BY 2 DESC LIMIT 15"):
    print(r)

print('\n== race_name samples (maiden/fillies) ==')
for r in cur.execute("SELECT race_name FROM races WHERE race_name LIKE '%牝%' LIMIT 5"):
    print(r)
for r in cur.execute("SELECT race_name FROM races WHERE race_name LIKE '%新馬%' LIMIT 3"):
    print(r)
for r in cur.execute("SELECT race_name FROM races WHERE race_name LIKE '%未勝利%' LIMIT 3"):
    print(r)

print('\n== minarai ==')
for r in cur.execute("SELECT minarai, COUNT(*) FROM results GROUP BY minarai"):
    print(r)

print('\n== ijo ==')
for r in cur.execute("SELECT ijo, COUNT(*) FROM results GROUP BY ijo ORDER BY 2 DESC LIMIT 10"):
    print(r)

print('\n== tozai ==')
for r in cur.execute("SELECT tozai, COUNT(*) FROM results GROUP BY tozai"):
    print(r)

print('\n== ninki sanity (2025) ==')
for r in cur.execute("SELECT MIN(ninki), MAX(ninki), AVG(ninki) FROM results WHERE year='2025' AND chakujun>0 AND ninki>0"):
    print(r)

print('\n== races 2025 count JRA ==')
for r in cur.execute("SELECT COUNT(*) FROM races WHERE year='2025'"):
    print(r)

print('\n== corner sample ==')
for r in cur.execute("SELECT corner1,corner2,corner3,corner4 FROM results WHERE year='2025' AND corner4 IS NOT NULL LIMIT 5"):
    print(r)

con.close()
