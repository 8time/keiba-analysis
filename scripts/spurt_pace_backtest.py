# -*- coding: utf-8 -*-
"""上がり3F×レースペースの検証 — scripts/spurt_pace_backtest.py

動画『真の上がり3ハロンの使い方』の主張を検証:
  ・上がり3Fはスローペースの時だけ評価すべき(ハイの上がり上位は"バテ差し"で次走危険)
  ・狙い目=前走スロー×先行×上がり1-2位×0.3秒+勝ち で単勝回収率100%超え

結論(2016+・mae3f/ato3f coverage54%のJRA・人気統制の残差z+単勝ROI):
  ★核心の"バテ差し"は本物: 前走スロー×上がりtop3→次走 z+8.5/+6.0/+3.8(3窓安定)、
    前走ハイ×上がりtop3→z+0.6/+0.7/-0.4(織込み済み)。=末脚はスロー由来だけ信頼。
  ✗動画の狙い目(0.3秒勝ち+先行)はz+0.3=priced-in(勝ち/着差フィルタが人気馬を選ぶだけ)。
  単ROIは全帯<100%=利益でなく軸信頼度/相手の質の道具(spurt_indexと同じ性質)。
→ core/pace_spurt.py で『末脚の質(スロー由来か)』を表示補助。買い目スコアは変えない。

Usage: python scripts/spurt_pace_backtest.py
"""
import os
import sys
import sqlite3

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    ra = pd.read_sql("SELECT race_key,surface,kyori,mae3f,ato3f AS r_ato3f,shusso_tosu "
                     "FROM races WHERE race_key>='2016' AND mae3f>0 AND ato3f>0", con)
    re = pd.read_sql("SELECT race_key,ketto_num,chakujun,ninki,win_odds,ato3f AS h_ato3f,"
                     "corner1,corner2,corner3,corner4,year,monthday "
                     "FROM results WHERE race_key>='2016' AND chakujun>0", con)
    con.close()
    d = re.merge(ra, on='race_key', how='inner')
    d = d[d.h_ato3f > 0].copy()
    d['pdiff'] = d['mae3f'] - d['r_ato3f']
    d['db'] = pd.cut(d.kyori, [0, 1400, 1800, 2200, 9999], labels=['S', 'M', 'L', 'X'])
    g = d.groupby(['surface', 'db'], observed=True)['pdiff']
    d['pz'] = (d['pdiff'] - g.transform('mean')) / g.transform('std')
    d['slow'] = (d.pz >= 0.5).astype(int)
    d['high'] = (d.pz <= -0.5).astype(int)
    d['a_rank'] = d.groupby('race_key')['h_ato3f'].rank(method='min')
    cs = d[['corner1', 'corner2', 'corner3', 'corner4']].where(lambda x: x > 0)
    d['pos'] = cs.mean(axis=1) / d.shusso_tosu
    d['day'] = d.year.astype(int) * 10000 + d.monthday.astype(int)
    d = d.sort_values(['ketto_num', 'day', 'race_key'])
    for c in ['slow', 'high', 'a_rank', 'pos', 'chakujun']:
        d['p_' + c] = d.groupby('ketto_num')[c].shift(1)
    d['top3'] = (d.chakujun <= 3).astype(int)
    d['win'] = (d.chakujun == 1).astype(int)
    base = d.groupby('ninki')['top3'].mean().to_dict()

    def rep(sub, lab):
        if len(sub) < 150:
            print(f'  {lab:40s} n={len(sub)}(小)')
            return
        p = sub.ninki.map(base)
        z = (sub.top3.sum() - p.sum()) / np.sqrt((p * (1 - p)).sum())
        sroi = (sub.win * sub.win_odds.fillna(0)).sum() / len(sub)
        print(f'  {lab:40s} n={len(sub):6,} 複勝{sub.top3.mean():5.1%} z{z:+5.1f} 単ROI{sroi:5.0%}')

    print('【核心=バテ差し: 前走上がりtop3の次走(ペース別・人気統制・全期間)】')
    rep(d[(d.p_a_rank <= 3) & (d.p_slow == 1)], '前走スロー×上がりtop3')
    rep(d[(d.p_a_rank <= 3) & (d.p_high == 1)], '前走ハイ×上がりtop3(バテ差し?)')
    rep(d[d.p_a_rank <= 3], '(対照)前走上がりtop3 全ペース')
    print('【holdout安定性】')
    for era, lo, hi in (('16-23', 20160101, 20231231), ('24-25', 20240101, 20251231),
                        ('2026', 20260101, 20261231)):
        e = d[(d.day >= lo) & (d.day <= hi)]
        rep(e[(e.p_slow == 1) & (e.p_a_rank <= 3)], f'{era} スロー×上がりtop3')
        rep(e[(e.p_high == 1) & (e.p_a_rank <= 3)], f'{era} ハイ×上がりtop3')
    print('【動画の狙い目(却下=priced-in): スロー×先行×上がり1-2位×0.3秒勝ち】')
    cond = ((d.p_slow == 1) & (d.p_pos <= 0.35) & (d.p_a_rank <= 2) & (d.p_chakujun == 1))
    rep(d[cond], '狙い目(着差不問で近似)')
    print('\n判定: スロー由来の上がり上位のみ残差z+で安定→末脚の質分けは表示補助として有効。'
          '利益(単ROI)は<100%=軸信頼度の道具。')


if __name__ == '__main__':
    main()
