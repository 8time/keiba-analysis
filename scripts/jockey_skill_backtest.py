# -*- coding: utf-8 -*-
"""
J4検証: 「USM(騎手の実力) / 黄金ライン(騎手×調教師) の上位は、人気(オッズ)以上に来るか」。

各騎乗の『直前まで』の実績でUSM・コンビ強度を算出（リーク無し）し、
オッズ期待値で補正した残差 = (実績) − (オッズ別期待) を層別平均。
  residual_win  = (1着なら1) − 期待勝率
  residual_top3 = (3着内なら1) − 期待複勝率
残差>0 = 市場(人気)が織り込めていない上振れ＝本物のエッジ。平坦なら市場が既に織込み済み。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e_of(o):
    e = exp.get(jj._odds_band(o))
    return (e['win'], e['top2'], e['top3']) if e else (0.08, 0.15, 0.22)


jockeys = [r[0] for r in con.execute("""
    SELECT jockey_name FROM results WHERE year IN ('2024','2025') AND jockey_name!=''
    GROUP BY jockey_name HAVING COUNT(*)>=300""").fetchall()]
print(f"対象騎手: {len(jockeys)}人 / オッズ帯実勝率: "
      f"{ {k: v['win'] for k,v in sorted(exp.items())} }")

usm_buckets = defaultdict(lambda: [0.0, 0.0, 0])   # [resid_win合計, resid_top3合計, n]
gold_buckets = defaultdict(lambda: [0.0, 0.0, 0])  # 黄金ライン top2強度別 [resid_win, resid_top2, n]
MIN_HIST = 150     # USM算出に必要な直前騎乗数
MIN_COMBO = 15     # 黄金ライン判定に必要な同調教師での直前騎乗数

for jk in jockeys:
    rows = con.execute("""SELECT r.chakujun, r.win_odds, r.trainer_code
        FROM results r JOIN races ra ON ra.race_key=r.race_key
        WHERE r.jockey_name=? AND r.chakujun>0 AND r.win_odds>0
          AND ra.year IN ('2022','2023','2024','2025')
        ORDER BY r.race_key ASC""", (jk,)).fetchall()
    if len(rows) < MIN_HIST + 50:
        continue
    # 累積（USM用）
    cum_aw = cum_a3 = 0.0
    cum_ew = cum_e3 = 0.0
    # 調教師別 累積（黄金ライン用）
    tr_n = defaultdict(int); tr_top2 = defaultdict(int)

    for i, (c, o, tr) in enumerate(rows):
        ew, e2, e3 = e_of(o)
        # ── 評価（直前までの状態で層別、結果は当該レース） ──
        if i >= MIN_HIST and cum_ew > 0 and cum_e3 > 0:
            usm_win = cum_aw / cum_ew * 100
            usm_top3 = cum_a3 / cum_e3 * 100
            b = ('<90' if usm_top3 < 90 else '90-100' if usm_top3 < 100 else
                 '100-110' if usm_top3 < 110 else '110-120' if usm_top3 < 120 else '120+')
            rw = (1 if c == 1 else 0) - ew
            r3 = (1 if c <= 3 else 0) - e3
            usm_buckets[b][0] += rw; usm_buckets[b][1] += r3; usm_buckets[b][2] += 1
        # 黄金ライン: この騎乗の調教師での直前 top2率
        if tr and tr_n[tr] >= MIN_COMBO:
            ct2 = tr_top2[tr] / tr_n[tr]
            gb = ('<20%' if ct2 < 0.20 else '20-30%' if ct2 < 0.30 else
                  '30-40%' if ct2 < 0.40 else '40%+')
            rw = (1 if c == 1 else 0) - ew
            r2 = (1 if c <= 2 else 0) - e2
            gold_buckets[gb][0] += rw; gold_buckets[gb][1] += r2; gold_buckets[gb][2] += 1

        # ── 累積を更新（このレースを履歴に加える） ──
        cum_aw += 1 if c == 1 else 0
        cum_a3 += 1 if c <= 3 else 0
        cum_ew += ew; cum_e3 += e3
        if tr:
            tr_n[tr] += 1
            tr_top2[tr] += 1 if c <= 2 else 0
con.close()

print("\n== USM(複勝・直前まで)別 → 次走の残差（人気以上に来るか）==")
for b in ['<90', '90-100', '100-110', '110-120', '120+']:
    rw, r3, n = usm_buckets.get(b, [0, 0, 0])
    if n:
        print(f"  USM複勝 {b:8s}: 勝ち残差{rw/n:+.4f} / 複勝残差{r3/n:+.4f}  (n={n})")

print("\n== 黄金ライン(騎手×調教師 直前top2率)別 → 残差 ==")
for b in ['<20%', '20-30%', '30-40%', '40%+']:
    rw, r2, n = gold_buckets.get(b, [0, 0, 0])
    if n:
        print(f"  対調教師連対 {b:6s}: 勝ち残差{rw/n:+.4f} / 連対残差{r2/n:+.4f}  (n={n})")
