# -*- coding: utf-8 -*-
"""
直接対決(H2H)仮説の検証: 「過去にAがBに先着していると、再戦でもAが先着しやすいか」。
特に『迷う2頭＝現在のオッズが近い』ケースで、過去の対戦結果がタイブレークに使えるか。

各レースの全2頭ペアについて、それ以前の『共通出走レース(最新)』での先着馬=prior_winnerを特定し、
今回どちらが先着したかを集計。オッズ差で層別（近い＝迷うケース）。
prior_winner先着率が50%を有意に超えれば「過去対戦はタイブレークに有効」。
"""
import os
import sys
import sqlite3
import random
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj   # JV_DB_PATH 再利用

con = sqlite3.connect(jj.JV_DB_PATH)
rks = [r[0] for r in con.execute(
    "SELECT race_key FROM races WHERE year IN ('2024','2025') AND shusso_tosu>=8").fetchall()]
random.seed(5); random.shuffle(rks); rks = rks[:250]

# 集計バケツ: オッズ近接度別の prior_winner 先着率
buckets = defaultdict(lambda: [0, 0])   # key -> [prior_winner先着数, ペア数]
cur = con.cursor()

for rk in rks:
    rows = cur.execute(
        "SELECT ketto_num, chakujun, win_odds FROM results "
        "WHERE race_key=? AND chakujun>0 AND win_odds>0 AND ketto_num!=''", (rk,)).fetchall()
    if len(rows) < 8:
        continue
    # 各馬の過去走 {race_key: chakujun}（このレースより前・直近40）
    hist = {}
    for ketto, _, _ in rows:
        prs = cur.execute(
            "SELECT race_key, chakujun FROM results WHERE ketto_num=? AND race_key<? "
            "AND chakujun>0 ORDER BY race_key DESC LIMIT 40", (ketto, rk)).fetchall()
        hist[ketto] = {k: c for k, c in prs}
    info = {k: (c, o) for k, c, o in rows}

    for a, b in combinations([r[0] for r in rows], 2):
        shared = set(hist[a]) & set(hist[b])
        if not shared:
            continue
        last = max(shared)                      # 最新の共通出走レース
        ca, cb = hist[a][last], hist[b][last]
        if ca == cb:
            continue
        pw = a if ca < cb else b                # 過去の先着馬(prior winner)
        pl = b if pw == a else a
        # 今回の結果
        cur_pw, opw = info[pw]
        cur_pl, opl = info[pl]
        pw_ahead = cur_pw < cur_pl
        # オッズ近接度（迷う度）
        ratio = opw / opl if opl else 99
        if 0.67 <= ratio <= 1.5:
            band = '接戦(オッズ近い=迷う)'
        elif ratio < 0.67:
            band = 'prior_winnerが人気上位'
        else:
            band = 'prior_loserが人気上位'
        buckets[band][0] += pw_ahead
        buckets[band][1] += 1
        buckets['全体'][0] += pw_ahead
        buckets['全体'][1] += 1
con.close()

print("== 再戦での『過去に先着した馬(prior winner)』の再先着率 ==")
for k in ['全体', '接戦(オッズ近い=迷う)', 'prior_winnerが人気上位', 'prior_loserが人気上位']:
    w, n = buckets.get(k, [0, 0])
    if n:
        print(f"  {k:24s}: {w}/{n} = {w/n*100:.1f}%")
print("\n参考: 50%付近=過去対戦に予測力なし / 55%超=タイブレークに有効。"
      "『prior_loserが人気上位』で50%超なら市場以上の情報＝萎縮仮説の傍証。")
