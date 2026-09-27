# -*- coding: utf-8 -*-
"""新馬戦シグナルのデータ実現可能性チェック（調査専用）。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')

con = sqlite3.connect(DB)

print('=== horses.birth カバレッジ ===')
total, missing = con.execute(
    "SELECT COUNT(*), SUM(birth IS NULL OR LENGTH(TRIM(birth))<8) FROM horses").fetchone()
print(f'  horses: {total:,} / birth欠損: {missing:,} ({(missing or 0)/total*100:.1f}%)')
for b, in con.execute("SELECT birth FROM horses WHERE LENGTH(birth)>=8 LIMIT 5"):
    print('  sample:', b)

print()
print('=== 新馬戦の母数（jravan）===')
n = con.execute("SELECT COUNT(*) FROM races WHERE race_name LIKE '%新馬%'").fetchone()[0]
print(f'  新馬戦レース数: {n:,}')
for y, c in con.execute(
        "SELECT year, COUNT(*) FROM races WHERE race_name LIKE '%新馬%' "
        "GROUP BY year ORDER BY year DESC LIMIT 6"):
    print(f'  {y}: {c:,}')

print()
print('=== 新馬戦 出走馬の birth 取得率 ===')
tot = con.execute(
    "SELECT COUNT(*) FROM results rs JOIN races ra ON ra.race_key=rs.race_key "
    "WHERE ra.race_name LIKE '%新馬%'").fetchone()[0]
withb = con.execute(
    "SELECT COUNT(*) FROM results rs JOIN races ra ON ra.race_key=rs.race_key "
    "JOIN horses h ON h.ketto_num=rs.ketto_num "
    "WHERE ra.race_name LIKE '%新馬%' AND LENGTH(h.birth)>=8").fetchone()[0]
print(f'  出走馬総数: {tot:,} / birthあり: {withb:,} ({withb/tot*100:.1f}%)')

# 年別の取得率（直近が重要）
print()
print('=== 年別 birth 取得率（新馬戦出走馬）===')
for y, t, w in con.execute(
        "SELECT ra.year, COUNT(*), SUM(LENGTH(h.birth)>=8) "
        "FROM results rs JOIN races ra ON ra.race_key=rs.race_key "
        "LEFT JOIN horses h ON h.ketto_num=rs.ketto_num "
        "WHERE ra.race_name LIKE '%新馬%' GROUP BY ra.year ORDER BY ra.year DESC LIMIT 6"):
    print(f'  {y}: {t:,}頭中 birthあり {w or 0:,} ({(w or 0)/t*100:.1f}%)')

print()
print('=== 月齢（race_date - birth）の分布 sanity（2024年新馬）===')
rows = con.execute(
    "SELECT ra.year, ra.monthday, h.birth FROM results rs "
    "JOIN races ra ON ra.race_key=rs.race_key "
    "JOIN horses h ON h.ketto_num=rs.ketto_num "
    "WHERE ra.race_name LIKE '%新馬%' AND ra.year='2024' AND LENGTH(h.birth)>=8 "
    "LIMIT 100000").fetchall()
diffs = []
for y, md, b in rows:
    try:
        rd = int(str(y) + str(md).zfill(4))
        bd = int(b)
        months = (rd // 10000 - bd // 10000) * 12 + ((rd // 100) % 100 - (bd // 100) % 100)
        diffs.append(months)
    except Exception:
        pass
if diffs:
    diffs.sort()
    n = len(diffs)
    print(f'  n={n:,} 月齢 min={diffs[0]} p25={diffs[n//4]} median={diffs[n//2]} '
          f'p75={diffs[3*n//4]} max={diffs[-1]}')

con.close()


def check2():
    con = sqlite3.connect(DB)
    print()
    print('=== race_name パターン（2024年 上位15）===')
    q = ("SELECT race_name, COUNT(*) FROM races WHERE year='2024' "
         "GROUP BY race_name ORDER BY COUNT(*) DESC LIMIT 15")
    for name, c in con.execute(q):
        print(f'  {c:5d}  {name}')
    print()
    print('=== メイクデビュー / 新馬 名称 ===')
    for pat in ('%メイクデビュー%', '%新馬%'):
        n = con.execute(
            "SELECT COUNT(*) FROM races WHERE race_name LIKE ?", (pat,)).fetchone()[0]
        print(f'  {pat}: {n:,}')
    print()
    print('=== 新馬系レースの shubetsu 分布 ===')
    q = ("SELECT shubetsu, COUNT(*) FROM races "
         "WHERE race_name LIKE '%新馬%' OR race_name LIKE '%メイクデビュー%' "
         "GROUP BY shubetsu")
    for s, c in con.execute(q):
        print(f'  shubetsu={s}: {c:,}')
    print()
    print('=== 年別（メイクデビュー+新馬）===')
    q = ("SELECT year, COUNT(*) FROM races "
         "WHERE race_name LIKE '%新馬%' OR race_name LIKE '%メイクデビュー%' "
         "GROUP BY year ORDER BY year DESC LIMIT 8")
    for y, c in con.execute(q):
        print(f'  {y}: {c:,}')
    print()
    print('=== 1番人気の強さ（メイクデビュー+新馬、全期間）===')
    q = ("""
        SELECT COUNT(*),
               SUM(CASE WHEN rs.chakujun=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN rs.chakujun<=3 THEN 1 ELSE 0 END)
        FROM results rs JOIN races ra ON ra.race_key=rs.race_key
        WHERE (ra.race_name LIKE '%新馬%' OR ra.race_name LIKE '%メイクデビュー%')
          AND rs.ninki=1 AND rs.chakujun>0
        """)
    n, w, t3 = con.execute(q).fetchone()
    print(f'  1番人気 n={n:,} 勝率={(w or 0)/n*100:.1f}% 複勝率={(t3 or 0)/n*100:.1f}%')
    q2 = ("""
        SELECT ra.year, COUNT(*),
               SUM(CASE WHEN rs.chakujun=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN rs.chakujun<=3 THEN 1 ELSE 0 END)
        FROM results rs JOIN races ra ON ra.race_key=rs.race_key
        WHERE (ra.race_name LIKE '%新馬%' OR ra.race_name LIKE '%メイクデビュー%')
          AND rs.ninki=1 AND rs.chakujun>0
        GROUP BY ra.year ORDER BY ra.year DESC LIMIT 6
        """)
    for y, n2, w2, t32 in con.execute(q2):
        print(f'  {y}: n={n2:,} 勝率={(w2 or 0)/n2*100:.1f}% 複勝率={(t32 or 0)/n2*100:.1f}%')
    con.close()


check2()
