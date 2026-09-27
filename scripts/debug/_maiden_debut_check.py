# -*- coding: utf-8 -*-
"""part5: デビュー戦定義での検証可能性チェック。
- 各馬の初出走(=新馬/メイクデビュー相当)を時系列で特定
- 1番人気の強さ（動画主張: 勝率38-42%, 複勝率71-75%）を再現
- 生まれ月シグナルの birth カバレッジをデビュー年別に測定
"""
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

print('=== JRA全出走レコード読み込み（障害除外）===')
rows = con.execute(
    "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, ra.year, ra.monthday "
    "FROM results r JOIN races ra ON ra.race_key=r.race_key "
    "WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート') "
    "AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ketto_num<>''"
).fetchall()
print(f'  {len(rows):,} 件')

by_horse = defaultdict(list)
for rk, kt, ch, nk, y, md in rows:
    by_horse[str(kt)].append((int(str(y) + str(md).zfill(4)), str(rk),
                              int(ch), (int(nk) if nk else None), int(y)))
debut = {}
for kt, lst in by_horse.items():
    lst.sort()
    d = lst[0]
    debut[kt] = dict(day=d[0], rk=d[1], ch=d[2], nk=d[3], y=d[4])

# デビュー戦レースをユニーク化
debut_races = defaultdict(list)  # race_key -> [(ch, nk)]
for kt, d in debut.items():
    debut_races[d['rk']].append((d['ch'], d['nk']))
print(f'  デビュー馬 {len(debut):,}頭 / デビュー戦レース {len(debut_races):,}')

# 年別レース数
by_year = defaultdict(int)
for kt, d in debut.items():
    by_year[d['y']] += 1
print('  デビュー馬の年別:', dict(sorted(by_year.items())[-8:]))

print()
print('=== 1番人気の強さ（デビュー戦定義）===')
# 各デビュー戦レースの1番人気「デビュー馬」…ではなくレース全体の1番人気を取る
rk_set = set(debut_races.keys())
placeholders_meta = {}
q = ("SELECT r.race_key, r.chakujun, r.ninki, ra.year "
     "FROM results r JOIN races ra ON ra.race_key=r.race_key "
     "WHERE r.ninki=1 AND r.chakujun>0")
n_all = w_all = p_all = 0
by_y = defaultdict(lambda: [0, 0, 0])
for rk, ch, nk, y in con.execute(q):
    if rk not in rk_set:
        continue
    n_all += 1
    w_all += 1 if ch == 1 else 0
    p_all += 1 if ch <= 3 else 0
    by_y[y][0] += 1
    by_y[y][1] += 1 if ch == 1 else 0
    by_y[y][2] += 1 if ch <= 3 else 0
print(f'  全期間: n={n_all:,} 勝率={w_all/n_all*100:.1f}% 複勝率={p_all/n_all*100:.1f}%')
print('  （動画主張: 勝率38-42%, 複勝率71-75%）')
for y in sorted(by_y)[-6:]:
    n, w, p = by_y[y]
    print(f'  {y}: n={n:,} 勝率={w/n*100:.1f}% 複勝率={p/n*100:.1f}%')

print()
print('=== birth カバレッジ（デビュー年別・JRA 2歳デビュー馬）===')
birth_of = {}
for kt, b in con.execute(
        "SELECT ketto_num, birth FROM horses WHERE LENGTH(birth)>=8"):
    birth_of[str(kt)] = str(b)
by_yb = defaultdict(lambda: [0, 0])
for kt, d in debut.items():
    by_yb[d['y']][1] += 1
    if kt in birth_of:
        by_yb[d['y']][0] += 1
for y in sorted(by_yb):
    w, t = by_yb[y]
    if y >= 2010:
        print(f'  {y}: {t:,}頭中 {w:,} ({w/t*100:.1f}%)')

con.close()
