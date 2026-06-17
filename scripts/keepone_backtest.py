# -*- coding: utf-8 -*-
"""「半分消去のあと1頭だけ残しに戻す」と勝率/取りこぼしは改善するか(test=2023-2025・JRA平地)。

エンジンの消去スコアは支配項が -人気 なので、戻す1頭 ≒ 人気で (keep+1) 番目の馬(消去ゾーン最上位)。
  keep_base = (n+1)//2   … 現行(下位半分カット)
  keep_plus = keep_base + 1 … 1頭戻す案
測るもの:
  ① recall(3着内取りこぼし): base残し vs +1残し で、3着内馬を取り返せる量。
  ② 戻す1頭(=人気rank keep+1)単体の: 3着内率 / 勝率 / 単勝ROI / 人気補正残差。
     残差が ~0 なら「人気どおり=妙味ではないが、recallは増える(取りこぼし減)」。
  ③ 参考: 軸候補(人気1)からの相対。
人気補正の期待値は jockey_jv.calibrate_odds_expectation。
"""
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
    "SELECT r.race_key, r.chakujun, r.ninki, r.win_odds, ra.shusso_tosu "
    f"{BASE} ORDER BY r.race_key").fetchall()
con.close()

# レース単位に集約
races = defaultdict(list)
for rk, chaku, ninki, o, tousu in rows:
    races[rk].append((ninki, chaku, o))

# 全体(母数)
t3_tot = w_tot = 0
# base残し / +1残し が取りこぼす(=残しに入れられなかった)3着内・勝ち馬
t3_miss_base = t3_miss_plus = 0
w_miss_base = w_miss_plus = 0
# 戻す1頭(人気rank == keep_base+1)単体
m_n = m_t3 = m_w = 0
m_pay = 0.0
m_res3 = m_resw = 0.0
n_races = 0

for rk, horses in races.items():
    n = len(horses)
    if n < 6:
        continue
    n_races += 1
    horses_sorted = sorted(horses, key=lambda x: x[0])  # ninki昇順(1=人気)
    keep_base = (n + 1) // 2
    keep_plus = keep_base + 1
    for idx, (ninki, chaku, o) in enumerate(horses_sorted):
        rank = idx + 1  # 1=最上位人気
        if chaku == 1:
            w_tot += 1
            if rank > keep_base:
                w_miss_base += 1
            if rank > keep_plus:
                w_miss_plus += 1
        if chaku <= 3:
            t3_tot += 1
            if rank > keep_base:
                t3_miss_base += 1
            if rank > keep_plus:
                t3_miss_plus += 1
        # 戻す1頭 = 消去ゾーン最上位 = 人気rank keep_base+1
        if rank == keep_plus:
            m_n += 1
            m_res3 += (1 if chaku <= 3 else 0) - e3(o)
            m_resw += (1 if chaku == 1 else 0) - e1(o)
            if chaku <= 3:
                m_t3 += 1
            if chaku == 1:
                m_w += 1
                m_pay += o

print(f"対象: {n_races} レース (6頭以上, 2023-2025, 芝ダ平地)")
print("\n================ ① 3着内・勝ち馬の取りこぼし(残しに入らなかった割合) ================")
print(f"  3着内 総数 {t3_tot}")
print(f"    現行(半分カット) 取りこぼし : {t3_miss_base:6d}  = {t3_miss_base/max(t3_tot,1):.2%}")
print(f"    +1頭戻す         取りこぼし : {t3_miss_plus:6d}  = {t3_miss_plus/max(t3_tot,1):.2%}")
print(f"    → 改善(取り返した3着内)     : {t3_miss_base - t3_miss_plus} 頭 "
      f"({(t3_miss_base-t3_miss_plus)/max(t3_tot,1):.2%}pt)")
print(f"  勝ち馬 総数 {w_tot}")
print(f"    現行 取りこぼし : {w_miss_base:6d} = {w_miss_base/max(w_tot,1):.2%}")
print(f"    +1頭 取りこぼし : {w_miss_plus:6d} = {w_miss_plus/max(w_tot,1):.2%}")
print(f"    → 取り返した勝ち馬 : {w_miss_base - w_miss_plus} 頭")

se3 = (0.22 * 0.78 / m_n) ** 0.5 if m_n else 0
print("\n================ ② 戻す1頭(人気rank keep+1=消去ゾーン最上位)単体の成績 ================")
print(f"  n           : {m_n}")
print(f"  3着内率     : {m_t3/max(m_n,1):.2%}   (勝率 {m_w/max(m_n,1):.2%})")
print(f"  単勝ROI     : {m_pay/max(m_n,1):.1%}")
print(f"  3着内 人気補正残差 : {m_res3/max(m_n,1):+.4f}  (z={ (m_res3/m_n)/se3 if se3 else 0:+.2f})")
print(f"  勝利 人気補正残差   : {m_resw/max(m_n,1):+.4f}")
print("\n→ 残差≈0なら『人気どおり(妙味ではない)』だが recall(取りこぼし)は確実に増える。")
print("  残差が明確にプラスなら『過小評価=戻す価値あり』。マイナスなら戻すと損。")
