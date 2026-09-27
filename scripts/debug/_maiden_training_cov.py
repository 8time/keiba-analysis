# -*- coding: utf-8 -*-
"""part12: JV training テーブルがデビュー前調教を持つか（V6a候補の実現性チェック）。"""
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

# training の年月レンジ
lo, hi = con.execute('SELECT MIN(cho_date), MAX(cho_date) FROM training').fetchone()
print(f'training 期間: {lo} 〜 {hi}')

# 2020年デビュー馬をサンプル: デビュー日より前の調教レコードがあるか
rows = con.execute(
    "SELECT r.ketto_num, r.race_key, ra.year, ra.monthday FROM results r "
    "JOIN races ra ON ra.race_key=r.race_key "
    "WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート') "
    "AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ketto_num<>'' "
    "AND ra.year BETWEEN '2018' AND '2022'").fetchall()

by_horse = defaultdict(list)
for kt, rk, y, md in rows:
    by_horse[kt].append((int(str(y) + str(md).zfill(4)), rk))

debut = {}  # ketto -> debut yyyymmdd (2020年デビューのみ抽出して軽量化)
for kt, lst in by_horse.items():
    lst.sort()
    if lst[0][0] // 10000 == 2020:
        debut[kt] = lst[0][0]
print(f'2020年デビュー馬: {len(debut):,}頭')

# デビュー前の調教レコード
n_with = 0
n_checked = 0
for kt, dday in list(debut.items()):
    n_checked += 1
    c = con.execute(
        'SELECT COUNT(*) FROM training WHERE ketto_num=? AND cho_date<?',
        (kt, str(dday))).fetchone()[0]
    if c > 0:
        n_with += 1
print(f'デビュー前調教あり: {n_with:,}/{n_checked:,} ({n_with / max(n_checked, 1) * 100:.1f}%)')

# 中央値的な本数感
if n_with:
    sample_counts = []
    for kt, dday in list(debut.items())[:3000]:
        c = con.execute(
            'SELECT COUNT(*) FROM training WHERE ketto_num=? AND cho_date<?',
            (kt, str(dday))).fetchone()[0]
        sample_counts.append(c)
    sample_counts.sort()
    n = len(sample_counts)
    print(f'調教本数分布(n={n}): min={sample_counts[0]} p25={sample_counts[n // 4]} '
          f'median={sample_counts[n // 2]} p75={sample_counts[3 * n // 4]} max={sample_counts[-1]}')
con.close()
