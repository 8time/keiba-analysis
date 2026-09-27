# -*- coding: utf-8 -*-
"""part11: 実在の2026年新馬レースで collect_maiden_rows の出力を確認（表示品質チェック）。"""
import os
import sqlite3
import sys

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from core import maiden_mode as mm  # noqa: E402
from core import jockey_jv as jv  # noqa: E402

DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

# 直近の新馬(shubetsu='11')を1レース取得
rk = con.execute(
    "SELECT race_key FROM races WHERE shubetsu='11' AND year='2026' "
    "AND jyo BETWEEN '01' AND '10' ORDER BY race_key DESC LIMIT 1").fetchone()[0]
meta_r = con.execute(
    "SELECT jyo, kyori, surface FROM races WHERE race_key=?", (rk,)).fetchone()
rows = con.execute(
    "SELECT bamei, jockey_name, trainer_code FROM results WHERE race_key=? "
    "ORDER BY CAST(umaban AS INTEGER)", (rk,)).fetchall()
con.close()
print(f'race_key={rk} jyo={meta_r[0]} dist={meta_r[1]} surf={meta_r[2]} 頭数={len(rows)}')

df = pd.DataFrame([
    {'Umaban': i + 1, 'Name': b, 'Jockey': j, 'Trainer': t, 'TrainerID': t,
     'CurrentSurface': meta_r[2]}
    for i, (b, j, t) in enumerate(rows)
])
meta = {'class': '新馬', 'distance': int(meta_r[1]) if meta_r[1] else None}
exp = jv.calibrate_odds_expectation()

out = mm.collect_maiden_rows(df, race_id=rk, meta=meta, expected=exp, min_year='2023')
for r in out:
    print(f"  {r['馬番']:>2} {r['馬名']:<12} {r['騎手']:<8} [{r['騎手の評価']}] "
          f"{r['騎手の内訳']:<28} 厩舎勝率={r['厩舎の勝率(3年)']:<14} "
          f"コース={r['当コース勝率']:<24} 黄金={r['黄金ライン']}")
