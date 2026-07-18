# -*- coding: utf-8 -*-
"""厩舎「当コース勝率」の妙味ゲートを 生の勝率 → 縮小推定(shrinkage) に変えて劣化しないか検証。

背景: 生の勝率は 5戦1勝でも 20% と出るため 🔴(妙味マーク・閾値≥20%) が誤発火する。
縮小推定は少ない出走数を『そのコースの全体平均勝率』へ引き寄せ、過信を防ぐ。

問い: shrunk≥20% ゲートの妙味(オッズ超え残差)は 生≥20% と同等以上か？

設計(リーク防止):
  train(〜2022)で厩舎の当コース成績と、コース別の全体平均勝率(prior)を構築。
  test(2023-2025)で、各騎乗がゲートに該当するか判定し、オッズ補正残差を集計。
  残差 = 実績(3着内/勝ち) − そのオッズ帯の期待値。>0 なら市場を超えている=妙味。

使い方: python scripts/trainer_shrinkage_backtest.py
"""
import os
import sys
import math
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core.bayes_stats import shrink_rate

con = sqlite3.connect(jj.JV_DB_PATH)
cur = con.cursor()
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o))
    return e['win'] if e else 0.08


BASE = ("FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "WHERE r.trainer_code!='00000' AND r.chakujun>0 "
        "AND ra.surface IN ('芝','ダート') "
        "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10")

# ---- train(〜2022): 厩舎×コース成績 + コース別の全体平均勝率(prior) ----
crs = defaultdict(lambda: [0, 0])          # (tc,jyo,surf) -> [runs, wins]
course_all = defaultdict(lambda: [0, 0])   # (jyo,surf)    -> [runs, wins]
print("train(〜2022)構築中...")
for tc, jyo, surf, chaku in cur.execute(
        f"SELECT r.trainer_code, ra.jyo, ra.surface, r.chakujun {BASE} AND ra.year<'2023'"):
    w = 1 if chaku == 1 else 0
    crs[(tc, jyo, surf)][0] += 1
    crs[(tc, jyo, surf)][1] += w
    course_all[(jyo, surf)][0] += 1
    course_all[(jyo, surf)][1] += w

prior = {k: (v[1] / v[0]) for k, v in course_all.items() if v[0] > 0}
print(f"  厩舎×コース組: {len(crs)} / コース数: {len(prior)}")
_pv = sorted(prior.values())
if _pv:
    print(f"  コース平均勝率(prior)の中央値: {_pv[len(_pv) // 2]:.4f}")

# ---- test(2023-2025): ゲート別に残差集計 ----
# 本番のゲート条件: runs>=10(value_scanner/app) と runs>=5(consensus_view) の2種
MIN_RUNS = (5, 10)
THRESHOLDS = (0.16, 0.18, 0.20, 0.22)
# key=(min_runs, th, 'raw'|'shrunk') -> [sum_r3, sum_rw, n]
fired = defaultdict(lambda: [0.0, 0.0, 0])
n_test = 0

print("test(2023-2025)評価中...")
for tc, jyo, surf, chaku, o in cur.execute(
        f"SELECT r.trainer_code, ra.jyo, ra.surface, r.chakujun, r.win_odds "
        f"{BASE} AND ra.year>='2023' AND r.win_odds>0"):
    n_test += 1
    v = crs.get((tc, jyo, surf))
    if not v or v[0] == 0:
        continue
    runs, wins = v
    raw = wins / runs
    pm = prior.get((jyo, surf), 0.08)
    shr = shrink_rate(wins, runs, pm)          # prior_strength=20(デフォルト)

    r3 = (1 if chaku <= 3 else 0) - e3(o)
    rw = (1 if chaku == 1 else 0) - e1(o)
    for mr in MIN_RUNS:
        if runs < mr:
            continue
        for th in THRESHOLDS:
            if raw >= th:
                b = fired[(mr, th, 'raw')]
                b[0] += r3; b[1] += rw; b[2] += 1
            if shr >= th:
                b = fired[(mr, th, 'shrunk')]
                b[0] += r3; b[1] += rw; b[2] += 1
con.close()


def zstat(total, n, sd=0.42):
    """残差平均のz(概算)。sd=3着内0/1指標の標準偏差の目安。"""
    if not n:
        return 0.0
    return (total / n) / (sd / math.sqrt(n))


print(f"\ntest対象騎乗(延べ): {n_test:,}\n")
print("残差>0 = 市場(オッズ)を超えて来る = 妙味あり。n=ゲート発火数。")
print("=" * 78)
for mr in MIN_RUNS:
    print(f"\n■ 最低出走数 runs>={mr}（本番ゲート: {'value_scanner/app' if mr == 10 else 'consensus_view'}）")
    print(f"  {'閾値':>6} {'方式':>7} | {'n(発火)':>8} | {'3着内残差':>10} {'z':>6} | {'勝利残差':>9}")
    print("  " + "-" * 70)
    for th in THRESHOLDS:
        for mode in ('raw', 'shrunk'):
            s3, sw, n = fired[(mr, th, mode)]
            if not n:
                print(f"  {th:>5.0%} {mode:>7} | {0:>8} | {'—':>10} {'—':>6} | {'—':>9}")
                continue
            m3 = s3 / n
            mw = sw / n
            z = zstat(s3, n)
            print(f"  {th:>5.0%} {mode:>7} | {n:>8,} | {m3:>+10.4f} {z:>+6.2f} | {mw:>+9.4f}")
        print()

print("=" * 78)
print("読み方: 同じ閾値で raw と shrunk を比べる。")
print("  - shrunk の n が減る = 少サンプルの誤発火が除かれた分。")
print("  - shrunk の残差が raw 以上 = 除かれたのはノイズで、妙味は落ちていない(採用OK)。")
print("  - shrunk の残差が raw より明確に低い = 引き寄せすぎ。閾値の再調整が必要。")
