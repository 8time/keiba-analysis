# -*- coding: utf-8 -*-
"""ゾーン別フォーメーションを「年単位で評価」するための分布統計。

vscore_zone_formation.py は的中率とROIしか出していなかった。
月/年単位で運用を判断するには、それだけでは足りない:
  ・平均配当と中央値配当(ROIが万馬券1本で作られていないか)
  ・最大連敗(必要資金の下限を決める)
  ・年ごとのROIばらつき(たまたま良い年だったのか)
  ・モンテカルロによる年間収支の分布と破産率

⚠前提: vscore_zone_formation.py の結果では全ゾーン・全形でROI<100%。
  資金管理は-EVを+EVに変えられないので、ここで測るのは
  「どれだけ長く生き残れるか」であって「勝てるか」ではない。

Usage:
  python scripts/formation_distribution.py
"""
import os
import sys
import io
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import vscore_zone_formation as VZ

# ⚠ VZ はインポート時に sys.stdout を差し替える(そのラッパを閉じると以降書けない)。
#    VZ が張ったラッパをそのまま使えば良いので、ここでは何も差し替えない。

# vscore_zone_formation の結果から各ゾーンの最良形を採用
BEST = [
    ('D 鉄板 (1-49)', 0, 50, 'trio', (1, 3, 6)),
    ('C 中庸 (50-69)', 50, 70, 'trio', (1, 3, 6)),
    ('B/A 荒れ (70-)', 70, 201, 'trio', (2, 3, 6)),
    ('D 鉄板 (1-49)', 0, 50, 'trifecta', (1, 4, 8)),
    ('C 中庸 (50-69)', 50, 70, 'trifecta', (2, 4, 7)),
    ('B/A 荒れ (70-)', 70, 201, 'trifecta', (2, 5, 8)),
]
KIND_JP = {'trio': '3連複', 'trifecta': '3連単'}


def collect(races, pay_map, kind, shape, lo, hi):
    """1レースずつ (投資, 払戻, 年) を出す。"""
    a, b, c = shape
    rec = []
    for d in sorted([x for x in races.values() if lo <= x['vscore'] < hi],
                    key=lambda x: x['day']):
        tk = (VZ.trifecta_tickets(d['ranks'], a, b, c) if kind == 'trifecta'
              else VZ.trio_tickets(d['ranks'], a, b, c))
        pl = pay_map.get(d['_rk'])
        if not tk or not pl:
            continue
        spend = len(tk) * 100
        ret = 0.0
        for combo, pay in pl:
            key = combo if kind == 'trifecta' else tuple(sorted(combo))
            if key in tk:
                ret = pay
                break
        rec.append({'day': d['day'], 'year': int(str(d['day'])[:4]),
                    'spend': spend, 'ret': ret, 'hit': int(ret > 0)})
    return pd.DataFrame(rec)


def max_losing_streak(hits):
    m = c = 0
    for h in hits:
        c = 0 if h else c + 1
        m = max(m, c)
    return m


def monte_carlo(df, n_year=1200, n_sim=3000, seed=7, ruin_frac=0.5):
    """1年ぶんをブートストラップして年間収支の分布と破産率を出す。"""
    rng = np.random.default_rng(seed)
    net = (df['ret'] - df['spend']).to_numpy()
    spend = df['spend'].to_numpy()
    if len(net) < 100:
        return None
    idx = rng.integers(0, len(net), size=(n_sim, n_year))
    paths = net[idx]
    totals = paths.sum(axis=1)
    invested = spend[idx].sum(axis=1)
    roi = (invested + totals) / invested * 100
    # 破産率: 年内の累積が「年間投資額×ruin_frac」ぶん沈んだら退場とみなす
    cum = np.cumsum(paths, axis=1)
    floor = -(invested * ruin_frac / 1.0)
    ruined = (cum.min(axis=1) <= floor).mean() * 100
    return {'roi_med': float(np.median(roi)),
            'roi_p5': float(np.percentile(roi, 5)),
            'roi_p95': float(np.percentile(roi, 95)),
            'plus_rate': float((roi >= 100).mean() * 100),
            'ruin': float(ruined)}


def main():
    print('読込中...', file=sys.stderr)
    races = VZ.build_races()
    for rk in races:
        races[rk]['_rk'] = rk
    pays = {k: VZ.load_payouts(KIND_JP[k]) for k in ('trio', 'trifecta')}

    print('■ ゾーン別フォーメーションの分布統計（年単位の判断材料）\n')
    print(f'{"ゾーン/券種":26s}{"形":>7}{"R数":>7}{"的中":>7}{"ROI":>6}'
          f'{"平均配当":>9}{"中央値":>8}{"最大連敗":>8}')
    print('-' * 82)
    keep = {}
    for zlbl, lo, hi, kind, shape in BEST:
        df = collect(races, pays[kind], kind, shape, lo, hi)
        if df.empty:
            continue
        keep[(zlbl, kind)] = df
        hits = df[df['hit'] == 1]['ret']
        roi = df['ret'].sum() / df['spend'].sum() * 100
        lbl = f'{zlbl[:8]} {KIND_JP[kind]}'
        print(f'{lbl:26s}{"-".join(map(str,shape)):>7}{len(df):>7,}'
              f'{df["hit"].mean()*100:>6.1f}%{roi:>5.0f}%'
              f'{hits.mean():>9,.0f}{hits.median():>8,.0f}'
              f'{max_losing_streak(df["hit"].tolist()):>8}')

    print('\n■ 年ごとのROIばらつき（たまたま良い年ではないか）')
    print(f'{"ゾーン/券種":26s}' + ''.join(f'{y:>6}' for y in range(2016, 2027)))
    print('-' * 92)
    for (zlbl, kind), df in keep.items():
        row = f'{zlbl[:8]} {KIND_JP[kind]:>4}'.ljust(26)
        for y in range(2016, 2027):
            s = df[df['year'] == y]
            row += f'{(s["ret"].sum()/s["spend"].sum()*100):>6.0f}' if len(s) > 30 else f'{"-":>6}'
        print(row)

    print('\n■ モンテカルロ: 1年1,200レース買った場合の年間収支分布（3,000回試行）')
    print(f'{"ゾーン/券種":26s}{"ROI中央":>9}{"5%点":>8}{"95%点":>8}{"プラス年率":>12}{"退場率":>8}')
    print('-' * 76)
    for (zlbl, kind), df in keep.items():
        mc = monte_carlo(df)
        if not mc:
            continue
        lbl = f'{zlbl[:8]} {KIND_JP[kind]}'
        print(f'{lbl:26s}{mc["roi_med"]:>8.0f}%{mc["roi_p5"]:>7.0f}%{mc["roi_p95"]:>7.0f}%'
              f'{mc["plus_rate"]:>11.1f}%{mc["ruin"]:>7.1f}%')

    # アプリから引くための参照テーブルを書き出す
    import json
    out = {}
    for (zlbl, kind), df in keep.items():
        shape = next(s for z, _lo, _hi, k, s in BEST if z == zlbl and k == kind)
        hits = df[df['hit'] == 1]['ret']
        mc = monte_carlo(df) or {}
        yr = [float(g['ret'].sum() / g['spend'].sum() * 100)
              for _y, g in df.groupby('year') if len(g) > 30]
        out[f'{zlbl}|{kind}'] = {
            'zone': zlbl, 'kind': kind, 'kind_jp': KIND_JP[kind],
            'shape': '-'.join(map(str, shape)),
            'points': int(round(df['spend'].mean() / 100)),
            'races': int(len(df)),
            'hit_rate': float(df['hit'].mean() * 100),
            'roi': float(df['ret'].sum() / df['spend'].sum() * 100),
            'pay_mean': float(hits.mean()), 'pay_median': float(hits.median()),
            'max_streak': int(max_losing_streak(df['hit'].tolist())),
            'year_roi_min': float(min(yr)) if yr else None,
            'year_roi_max': float(max(yr)) if yr else None,
            'plus_year_rate': mc.get('plus_rate'), 'ruin_rate': mc.get('ruin'),
        }
    path = os.path.join(ROOT, 'data', 'formation_stats.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\n参照テーブルを保存: {os.path.relpath(path, ROOT)}')

    print('\n※プラス年率＝3,000回のうち年間ROIが100%を超えた割合。')
    print('※退場率＝年内に「年間投資額の50%」ぶん沈んだ試行の割合。')
    print('※ROI<100%の買い方は資金管理をどう工夫してもプラスにはならない。'
          'ここで見るのは"どれだけ長く遊べるか"であって"勝てるか"ではない。')


if __name__ == '__main__':
    main()
