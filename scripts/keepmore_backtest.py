# -*- coding: utf-8 -*-
"""半分カット後に「何頭まで戻すと得か」逓減を測る(test=2023-2025・JRA平地)。
各 keep+k の馬(人気rank=keep+k=消去ゾーンのk番目)単体の 3着内率/単勝ROI/人気補正残差 と、
keep..keep+k まで戻したときの累積recall(3着内取りこぼし)を出す。
残差が0に潰れる/負に転じる k が『戻す価値の限界』。"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
cur = con.cursor()
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


BASE = ("FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート') "
        "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 12 "
        "AND ra.year>='2023' AND r.ninki>0 AND r.win_odds>0")
rows = cur.execute(
    "SELECT r.race_key, r.chakujun, r.ninki, r.win_odds "
    f"{BASE} ORDER BY r.race_key").fetchall()
con.close()

races = defaultdict(list)
for rk, chaku, ninki, o in rows:
    races[rk].append((ninki, chaku, o))

KMAX = 4
# marginal[k] = [n, t3, w, pay, res3, resw]  (k=1..KMAX: 人気rank keep+k)
marg = {k: [0, 0, 0, 0.0, 0.0, 0.0] for k in range(1, KMAX + 1)}
t3_tot = 0
# cumulative miss when keeping up to keep+k (k=0..KMAX)
miss = {k: 0 for k in range(0, KMAX + 1)}
n_races = 0

for rk, horses in races.items():
    n = len(horses)
    if n < 6:
        continue
    n_races += 1
    hs = sorted(horses, key=lambda x: x[0])  # ninki昇順
    keep_base = (n + 1) // 2
    for idx, (ninki, chaku, o) in enumerate(hs):
        rank = idx + 1
        if chaku <= 3:
            t3_tot += 1
            for k in range(0, KMAX + 1):
                if rank > keep_base + k:
                    miss[k] += 1
        for k in range(1, KMAX + 1):
            if rank == keep_base + k:
                d = marg[k]
                d[0] += 1
                d[4] += (1 if chaku <= 3 else 0) - e3(o)
                d[5] += (1 if chaku == 1 else 0) - e1(o)
                if chaku <= 3:
                    d[1] += 1
                if chaku == 1:
                    d[2] += 1; d[3] += o

print(f"対象: {n_races} レース / 3着内総数 {t3_tot}")
print("\n=== 累積 3着内取りこぼし(残しに入らない割合) ===")
for k in range(0, KMAX + 1):
    lbl = "現行(半分)" if k == 0 else f"+{k}頭戻す"
    print(f"  keep+{k} {lbl:10s}: {miss[k]/max(t3_tot,1):.2%}")
print("\n=== 戻すk頭目(消去ゾーンk番目)単体の成績 ===")
print("  k  |   n   | 3着内率 | 単勝ROI | 3着内残差(z)")
for k in range(1, KMAX + 1):
    n_, t3, w, pay, r3, rw = marg[k]
    se = (0.22 * 0.78 / n_) ** 0.5 if n_ else 0
    z = (r3 / n_) / se if se else 0
    print(f"  +{k} | {n_:5d} | {t3/max(n_,1):6.2%} | {pay/max(n_,1):6.1%} | {r3/max(n_,1):+.4f} (z={z:+.2f})")
print("\n→ 3着内残差が +→0→− に潰れる手前までが『戻す価値』。"
      "z>0で正なら過小評価、≈0は人気どおり(recallは増えるが妙味なし)、負は戻すと損。")
