# -*- coding: utf-8 -*-
"""消去クロス新条件の検証: 「Rank下位56% かつ 穴馬ハンター圏外」。

ユーザー提案: ランク下位の馬（全体の56%）で、かつ穴馬ハンターの
🎯精鋭にも🕸️広域網にも含まれない馬を消去条件に加えたい。

消去クロスは**相手絞り**の道具（[[project_elimination_engine]]）。
+EVを狙うものではないので、見るのは「その条件の馬の3着内率がどれだけ低いか」と
「消したときに3着内馬を何頭取りこぼすか」。

⚠vh2の学習は≤2023なので、判定は**2025-2026**で行う。
⚠ability_scoreは小さいほど強い（昇順）。

Usage:
  python scripts/elim_ranklow_vhout_backtest.py
"""
import os
import sys
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import value_hunter as vh

sys.stdout.reconfigure(encoding='utf-8')

RANK_LOW = 0.56          # 下位56%


def main():
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score', 'vh2_score'])
    h = h[(h['chakujun'] > 0) & h['ability_score'].notna()].copy()
    h['year'] = h['day'].astype(str).str[:4].astype(int)
    h['field'] = h.groupby('race_key')['umaban'].transform('size')
    h = h[h['field'] >= 8]
    # ⚠小さいほど強い
    h['rank'] = h.groupby('race_key')['ability_score'].rank(method='min')
    # 下位56%: 上位 ceil(field*0.44) より下
    h['rank_cut'] = np.ceil(h['field'] * (1 - RANK_LOW))
    h['ranklow'] = h['rank'] > h['rank_cut']
    # 穴馬ハンターのtier
    p = vh.load_params() or {}
    ops = p.get('ops', {})
    th_wide = ops.get('recall0.7')
    h['vh_out'] = ~(h['vh2_score'].notna() & (h['vh2_score'] >= (th_wide or 1e9)))
    h['top3'] = (h['chakujun'] <= 3).astype(int)

    print(f'■ 対象 {len(h):,}頭 / {h["race_key"].nunique():,}レース')
    print(f'  vh 広域網のしきい値: {th_wide}')
    print(f'  Rank下位56%の該当率: {h["ranklow"].mean()*100:.1f}%')
    print(f'  vh圏外の該当率: {h["vh_out"].mean()*100:.1f}%\n')

    for wl, lo, hi in (('全期間 2016-2026', 2016, 2026),
                       ('★vh学習期間外 2025-2026', 2025, 2026)):
        d = h[(h['year'] >= lo) & (h['year'] <= hi)]
        if len(d) < 5000:
            continue
        base = d['top3'].mean() * 100
        print(f'■ {wl}  {len(d):,}頭（全体の3着内率 {base:.1f}%）')
        print(f'{"条件":34s}{"該当":>9}{"該当率":>8}{"3着内率":>9}{"取りこぼし":>10}')
        print('-' * 74)
        n3 = d['top3'].sum()
        for lbl, m in (
                ('Rank下位56% のみ', d['ranklow']),
                ('vh圏外 のみ', d['vh_out']),
                ('★Rank下位56% かつ vh圏外', d['ranklow'] & d['vh_out']),
                ('【比較】Rank下位56% かつ vh該当', d['ranklow'] & ~d['vh_out']),
                ('【比較】人気下位34%(既存poplow)',
                 d['ninki'] > np.ceil(d['field'] * 0.66))):
            s = d[m]
            if len(s) < 300:
                print(f'{lbl:34s}{len(s):>9,}{"標本不足":>27}')
                continue
            lost = s['top3'].sum() / n3 * 100
            print(f'{lbl:34s}{len(s):>9,}{len(s)/len(d)*100:>7.1f}%'
                  f'{s["top3"].mean()*100:>8.1f}%{lost:>9.1f}%')
        print()

    # 「消す価値」を測る: 同じ頭数を消すなら3着内率が低い方が良い
    d = h[h['year'] >= 2025]
    print('■ 効率の比較（同じくらい消すなら3着内率が低い方が良い）')
    print(f'{"条件":34s}{"消す割合":>10}{"3着内率":>10}{"1頭消して失う3着内馬":>20}')
    print('-' * 76)
    n3 = d['top3'].sum()
    for lbl, m in (('Rank下位56% かつ vh圏外', d['ranklow'] & d['vh_out']),
                   ('Rank下位56% のみ', d['ranklow']),
                   ('人気下位34%(既存)', d['ninki'] > np.ceil(d['field'] * 0.66))):
        s = d[m]
        if len(s) < 300:
            continue
        print(f'{lbl:34s}{len(s)/len(d)*100:>9.1f}%'
              f'{s["top3"].mean()*100:>9.1f}%{s["top3"].sum()/len(s):>19.3f}')

    print('\n※3着内率が低いほど「消して良い馬」。')
    print('※消去クロスは相手絞りの道具で+EVを狙うものではない。')


if __name__ == '__main__':
    main()
