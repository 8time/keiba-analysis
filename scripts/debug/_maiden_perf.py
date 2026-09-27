# -*- coding: utf-8 -*-
"""part13: results/races のインデックス確認（maiden_score_backtest の性能見積もり用）。"""
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

for tbl in ('results', 'races'):
    print(f'=== indexes on {tbl} ===')
    for name, sql in con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (tbl,)):
        print(' ', name, ':', (sql or '')[:140])

# 実測: jockey_factor 1回のコスト（before_key 付き）
sys.path.insert(0, ROOT)
from core import jockey_jv as jv  # noqa: E402

exp = jv.calibrate_odds_expectation()
t0 = time.time()
fac = jv.jockey_factor('川田将雅', venue='阪神', distance=1600,
                       trainer_code='01144', before_key='2020010100000000',
                       expected=exp)
t1 = time.time()
print(f'\njockey_factor(before_key付き): {t1 - t0:.3f}s -> mult={fac["mult"]} note={fac["note"]}')

t0 = time.time()
cw = jv.trainer_course_winrate('01144', '09', '芝',
                               before_key='2020010100000000', min_year='2017')
t1 = time.time()
print(f'trainer_course_winrate: {t1 - t0:.3f}s -> {cw}')
con.close()
