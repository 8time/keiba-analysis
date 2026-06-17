# -*- coding: utf-8 -*-
"""H2H仮説の追加検証（C）: 接戦(オッズ近い)ケースで、
(1)複数回の連続先着(一貫した優位) (2)前回対戦の着差(タイム差)が大きい
場合に、過去先着馬が再戦でも勝つ率が50%を有意に超えるか。
超えればその条件付きでタイブレークに使える。"""
import os
import sys
import sqlite3
import random
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import pace_map as pm

con = sqlite3.connect(jj.JV_DB_PATH)
rks = [r[0] for r in con.execute(
    "SELECT race_key FROM races WHERE year IN ('2023','2024','2025') AND shusso_tosu>=8").fetchall()]
random.seed(5); random.shuffle(rks); rks = rks[:450]

# 各バケツ [優位馬の再先着数, ペア数] ※すべて接戦(オッズ近い)のみ
B = defaultdict(lambda: [0, 0])
cur = con.cursor()

for rk in rks:
    rows = cur.execute(
        "SELECT ketto_num, chakujun, win_odds FROM results "
        "WHERE race_key=? AND chakujun>0 AND win_odds>0 AND ketto_num!=''", (rk,)).fetchall()
    if len(rows) < 8:
        continue
    hist = {}
    for ketto, _, _ in rows:
        prs = cur.execute(
            "SELECT race_key, chakujun, time FROM results WHERE ketto_num=? AND race_key<? "
            "AND chakujun>0 ORDER BY race_key DESC LIMIT 40", (ketto, rk)).fetchall()
        hist[ketto] = {k: (c, t) for k, c, t in prs}
    info = {k: (c, o) for k, c, o in rows}

    for a, b in combinations([r[0] for r in rows], 2):
        shared = set(hist[a]) & set(hist[b])
        if not shared:
            continue
        # オッズ近接(迷う)ペアのみ対象
        oa, ob = info[a][1], info[b][1]
        ratio = oa / ob if ob else 99
        if not (0.67 <= ratio <= 1.5):
            continue
        # 各共通レースでどちらが先着したか
        a_ahead = sum(1 for k in shared if hist[a][k][0] < hist[b][k][0])
        b_ahead = sum(1 for k in shared if hist[b][k][0] < hist[a][k][0])
        n_meet = a_ahead + b_ahead
        if n_meet == 0:
            continue
        last = max(shared)
        ca, ta = hist[a][last]
        cb, tb = hist[b][last]
        pw = a if ca < cb else b                  # 直近対戦の先着馬
        cur_pw = info[pw][0]
        cur_pl = info[b if pw == a else a][0]
        pw_ahead = cur_pw < cur_pl

        B['接戦・全H2H'][0] += pw_ahead; B['接戦・全H2H'][1] += 1
        # (1) 一貫優位: 2回以上対戦し片方が全勝
        if n_meet >= 2 and (a_ahead == 0 or b_ahead == 0):
            dom = a if a_ahead > b_ahead else b
            dom_ahead = info[dom][0] < info[b if dom == a else a][0]
            B['接戦・2回以上全勝(一貫)'][0] += dom_ahead; B['接戦・2回以上全勝(一貫)'][1] += 1
        # (2) 前回着差(タイム差)大: 0.4秒以上先着
        sa, sb = pm._parse_jv_time(ta), pm._parse_jv_time(tb)
        if sa is not None and sb is not None:
            gap = abs(sa - sb)
            if gap >= 0.4:
                B['接戦・前回タイム差0.4s+'][0] += pw_ahead; B['接戦・前回タイム差0.4s+'][1] += 1
            if gap >= 0.8:
                B['接戦・前回タイム差0.8s+'][0] += pw_ahead; B['接戦・前回タイム差0.8s+'][1] += 1
con.close()

print("== 接戦(オッズ近い=迷う)ケースでの 過去先着/優位馬の再先着率 ==")
for k in ['接戦・全H2H', '接戦・2回以上全勝(一貫)', '接戦・前回タイム差0.4s+', '接戦・前回タイム差0.8s+']:
    w, n = B.get(k, [0, 0])
    if n:
        print(f"  {k:24s}: {w}/{n} = {w/n*100:.1f}%")
    else:
        print(f"  {k:24s}: データ無し")
print("\n50%付近=無効 / 55%超(かつnが十分)=その条件でタイブレークに使える。")
