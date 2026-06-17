# -*- coding: utf-8 -*-
"""3連複パターン検証: 勝ち3頭(1-2-3着)の人気構成で
 ①人気-人気-穴 ②人気-穴-穴 等の出現頻度・配当・戦略ROIを測る。
人気=ninki<=POP_TH, 穴=ninki>=ANA_TH。payout は100円あたり配当(円)。
戦略ROI = Σ(的中レースのpayout) / Σ(全レースの賭け点数×100) ×100。"""
import os
import sys
import sqlite3
import statistics
from math import comb
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
# 各レースの 1-3着馬の人気 + 頭数 + 3連複配当 を一括取得（2018年以降）
rows = con.execute("""
    SELECT r.race_key, r.ninki, ra.shusso_tosu, p.payout
    FROM results r
    JOIN races ra ON ra.race_key=r.race_key
    JOIN payouts p ON p.race_key=r.race_key AND p.bet_type='3連複'
    WHERE r.chakujun IN (1,2,3) AND r.ninki>0 AND p.payout>0 AND ra.year>='2018'
""").fetchall()
con.close()

races = defaultdict(lambda: {'ninki': [], 'tosu': 0, 'pay': 0})
for rk, ninki, tosu, pay in rows:
    races[rk]['ninki'].append(ninki)
    races[rk]['tosu'] = tosu or 0
    races[rk]['pay'] = pay
races = {k: v for k, v in races.items() if len(v['ninki']) == 3}
N = len(races)
print(f"対象レース(3連複・1-3着人気揃い): {N}")

POP_TH = 5   # 人気: ninki<=5
# ── 1) 勝ち3連複の人気構成分布 ＋ 配当 ──
classes = defaultdict(lambda: {'n': 0, 'pays': []})
for v in races.values():
    pops = sum(1 for x in v['ninki'] if x <= POP_TH)
    lbl = {3: '鉄板(人気3)', 2: '①人気2-穴1', 1: '②人気1-穴2', 0: '大穴(人気0)'}[pops]
    classes[lbl]['n'] += 1
    classes[lbl]['pays'].append(v['pay'])

print(f"\n=== 勝ち3連複の人気構成分布（人気=ninki<={POP_TH}）===")
for lbl in ['鉄板(人気3)', '①人気2-穴1', '②人気1-穴2', '大穴(人気0)']:
    c = classes[lbl]
    if c['n']:
        md = statistics.median(c['pays']) / 100
        av = sum(c['pays']) / c['n'] / 100
        print(f"  {lbl:12s}: {c['n']:6d} ({c['n']/N*100:4.1f}%)  配当 中央値{md:7.1f}倍 / 平均{av:8.1f}倍")


# ── 2) 戦略ROI: 人気pool=[1..P], 穴pool=[A1..A2] で買う ──
def strat_roi(P, A1, A2, mode):
    """mode='①'(人気2+穴1) or '②'(人気1+穴2)。"""
    tot_cost = 0
    tot_ret = 0
    hits = 0
    for v in races.values():
        t = v['tosu']
        psz = min(P, t)                      # 人気pool頭数
        asz = max(0, min(A2, t) - A1 + 1)    # 穴pool頭数
        if mode == '①':
            if psz < 2 or asz < 1:
                continue
            combos = comb(psz, 2) * asz
        else:
            if psz < 1 or asz < 2:
                continue
            combos = psz * comb(asz, 2)
        tot_cost += combos * 100
        # 的中判定: 勝ち3頭の人気が条件を満たすか
        ninki = v['ninki']
        n_pop = sum(1 for x in ninki if 1 <= x <= P)
        n_ana = sum(1 for x in ninki if A1 <= x <= A2)
        if mode == '①' and n_pop == 2 and n_ana == 1:
            tot_ret += v['pay']; hits += 1
        elif mode == '②' and n_pop == 1 and n_ana == 2:
            tot_ret += v['pay']; hits += 1
    roi = tot_ret / tot_cost * 100 if tot_cost else 0
    avg_combos = tot_cost / 100 / N
    return roi, hits, hits / N * 100, avg_combos


print("\n=== 戦略ROI（買い続けた場合の回収率）===")
for (P, A1, A2) in [(4, 5, 10), (5, 6, 12), (4, 6, 15)]:
    for mode in ['①', '②']:
        roi, hits, hr, ac = strat_roi(P, A1, A2, mode)
        print(f"  {mode} 人気1-{P}/穴{A1}-{A2}: ROI {roi:5.1f}% / 的中{hr:4.1f}%({hits}) / 平均{ac:.0f}点買い")
print("\n※ROI100%超なら理論上プラス。控除率約25%なので80%前後が普通。相対比較で①②どちらが良いかを見る。")
