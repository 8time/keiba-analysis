# -*- coding: utf-8 -*-
"""「◎〇固定+4通り(3連複4点)」を妙味度ゾーン別に測る。

問い: 全レースだとROI82%。妙味度50-69(C中庸)に絞れば上がるのか。

⚠検出力の限界を先に書く: 対象は2025-2026の約4,700レース(vh2の学習≤2023を避けるため)。
  3ゾーンに割ると各1,500前後・的中は各300前後しかない。3連複の配当は裾が重いので
  ROIの点推定は簡単に±10pp動く。そこで
    ・ブートストラップ90%信頼区間を併記
    ・2025年と2026年に割って符号が一貫するか確認
  の2つを必ず見る。「3ゾーンから一番良いものを選ぶ」時点で軽い多重検定でもある。

Usage:
  python scripts/axis_vh_zone_split.py
"""
import os
import sys
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import axis_vh_trio_backtest as AV
from core import value_scanner as vs
from scripts import csv_data as cd

ZONES = [('D 鉄板 (0-49)', 0, 50), ('C 中庸 (50-69)', 50, 70), ('B/A 荒れ (70-)', 70, 201)]
LEGS = ['人気3位', '人気4位', '穴1位', '穴2位']


def legs_of(pop, c1, c2):
    p3 = p4 = None
    for u, p in pop.items():
        if p == 3:
            p3 = u
        elif p == 4:
            p4 = u
    out = [p3, p4, c1, c2]
    return out if all(x is not None for x in out) and len(set(out)) == 4 else None


def add_vscore(df):
    """レースごとの妙味度(荒れ確率×100)を付ける。"""
    h = cd.load_horses(cols=['race_key', 'win_odds'])
    h['race_key'] = h['race_key'].astype(str)
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1'])
    r['race_key'] = r['race_key'].astype(str)
    meta = {x.race_key: x for x in r.itertuples(index=False)}
    odds = {k: g['win_odds'].tolist() for k, g in h.groupby('race_key', sort=False)}
    out = []
    for rk in df['rk']:
        od = odds.get(rk)
        m = meta.get(rk)
        if not od or m is None:
            out.append(np.nan)
            continue
        rv = vs.race_value_score(
            od, {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                 'kigo': str(getattr(m, 'kigo', '') or '')}, n_horses=len(od))
        out.append(rv['score'] if rv else np.nan)
    df = df.copy()
    df['vscore'] = out
    return df


def boot_roi(spend, ret, n_boot=4000, seed=11):
    """レース単位のブートストラップでROIの90%信頼区間。"""
    rng = np.random.default_rng(seed)
    n = len(spend)
    if n < 100:
        return (np.nan, np.nan)
    idx = rng.integers(0, n, size=(n_boot, n))
    r = ret[idx].sum(axis=1) / spend[idx].sum(axis=1) * 100
    return float(np.percentile(r, 5)), float(np.percentile(r, 95))


def evaluate(d, lo, hi, y0=2025, y1=2026):
    s = d[(d['vscore'] >= lo) & (d['vscore'] < hi) &
          (d['year'] >= y0) & (d['year'] <= y1)]
    if len(s) < 100:
        return None
    ret = s[[f'pay{i}' for i in range(4)]].sum(axis=1).to_numpy()
    spend = np.full(len(s), 400.0)
    hit = s[[f'hit{i}' for i in range(4)]].max(axis=1)
    lo_ci, hi_ci = boot_roi(spend, ret)
    return {'n': len(s), 'hit': hit.mean() * 100,
            'roi': ret.sum() / spend.sum() * 100, 'ci': (lo_ci, hi_ci),
            'legs': [s[f'hit{i}'].mean() * 100 for i in range(4)]}


def main():
    print('読込中...', file=sys.stderr)
    base = AV.build()
    trio = AV.load_payouts('3連複')
    rows = []
    for r in base.itertuples(index=False):
        lg = legs_of(r.pop, r.c1, r.c2)
        pl = trio.get(r.rk)
        if not lg or not pl:
            continue
        win = {tuple(sorted(c)): p for c, p in pl}
        rec = {'rk': r.rk, 'year': r.year, 'n': r.n}
        for i, u in enumerate(lg):
            t = tuple(sorted((r.a, r.b, u)))
            rec[f'hit{i}'] = int(t in win)
            rec[f'pay{i}'] = win.get(t, 0.0)
        rows.append(rec)
    d = add_vscore(pd.DataFrame(rows)).dropna(subset=['vscore'])
    hold = d[(d['year'] >= 2025)]
    print(f'対象 {len(hold):,}レース（2025-2026・vh2の学習期間外）\n')

    def _line(lbl, e):
        ci = f'{e["ci"][0]:.0f}〜{e["ci"][1]:.0f}%'
        print(f'{lbl:16s}{e["n"]:>7,}{e["hit"]:>7.1f}%{e["roi"]:>6.0f}%{ci:>20}')

    print('■ 妙味度ゾーン別（3連複4点・◎〇固定+人気3/人気4/穴1/穴2）')
    print(f'{"ゾーン":16s}{"R数":>7}{"的中率":>8}{"ROI":>7}{"ROIの90%信頼区間":>18}')
    print('-' * 60)
    allr = evaluate(d, 0, 201)
    if allr:
        _line('（全レース）', allr)
    for lbl, lo, hi in ZONES:
        e = evaluate(d, lo, hi)
        if not e:
            print(f'{lbl:16s}{"標本不足":>7}')
            continue
        _line(lbl, e)

    print('\n■ 年ごとに割って符号が一貫するか（1年だけの偶然でないか）')
    print(f'{"ゾーン":16s}{"2025 R数":>10}{"2025 ROI":>10}{"2026 R数":>10}{"2026 ROI":>10}')
    print('-' * 58)
    for lbl, lo, hi in ZONES:
        a = evaluate(d, lo, hi, 2025, 2025)
        b = evaluate(d, lo, hi, 2026, 2026)
        f1 = f'{a["n"]:,}' if a else '-'
        f2 = f'{a["roi"]:.0f}%' if a else '-'
        f3 = f'{b["n"]:,}' if b else '-'
        f4 = f'{b["roi"]:.0f}%' if b else '-'
        print(f'{lbl:16s}{f1:>10}{f2:>10}{f3:>10}{f4:>10}')

    print('\n■ ゾーン別・4枚それぞれの的中率（どの脚が効いているか）')
    print(f'{"ゾーン":16s}' + ''.join(f'{x:>10}' for x in LEGS))
    print('-' * 58)
    for lbl, lo, hi in ZONES:
        e = evaluate(d, lo, hi)
        if not e:
            continue
        print(f'{lbl:16s}' + ''.join(f'{v:>9.1f}%' for v in e['legs']))

    # ── 同じ6頭を3連単で買った場合（券種が変わると最適ゾーンも変わるか） ──
    tri = AV.load_payouts('3連単')
    rows2 = []
    for r in base.itertuples(index=False):
        lg = legs_of(r.pop, r.c1, r.c2)
        pl = tri.get(r.rk)
        if not lg or not pl or r.year < 2025:
            continue
        win = {c: p for c, p in pl}
        # (a) ◎〇が1-2着(順不同) / 3着に4候補 = 8点
        ta = {(x, y, z) for x in (r.a, r.b) for y in (r.a, r.b) for z in lg
              if x != y and z not in (x, y)}
        # (b) ◎〇+3頭目 の6通り並べ替え × 4候補 = 24点
        tb = set()
        for z in lg:
            for p in __import__('itertools').permutations((r.a, r.b, z)):
                tb.add(p)
        rec = {'rk': r.rk, 'year': r.year}
        for key, tk in (('a', ta), ('b', tb)):
            rec[f'pts_{key}'] = len(tk)
            got = next((win[t] for t in tk if t in win), 0.0)
            rec[f'hit_{key}'] = int(got > 0)
            rec[f'pay_{key}'] = got
        rows2.append(rec)
    d2 = add_vscore(pd.DataFrame(rows2)).dropna(subset=['vscore'])

    for key, name in (('a', '3連単 ◎〇が1-2着(順不同)/3着4候補'),
                      ('b', '3連単 ◎〇+3頭目のBOX×4候補')):
        pts = int(d2[f'pts_{key}'].median())
        print(f'\n■ {name}（{pts}点）')
        print(f'{"ゾーン":16s}{"R数":>7}{"的中率":>8}{"ROI":>7}{"90%CI":>18}')
        print('-' * 58)
        for lbl, lo, hi in [('（全レース）', 0, 201)] + ZONES:
            s = d2[(d2['vscore'] >= lo) & (d2['vscore'] < hi)]
            if len(s) < 100:
                continue
            ret = s[f'pay_{key}'].to_numpy()
            spend = s[f'pts_{key}'].to_numpy() * 100.0
            ci = boot_roi(spend, ret)
            print(f'{lbl:16s}{len(s):>7,}{s[f"hit_{key}"].mean()*100:>7.1f}%'
                  f'{ret.sum()/spend.sum()*100:>6.0f}%'
                  f'{f"{ci[0]:.0f}〜{ci[1]:.0f}%":>18}')

    print('\n※信頼区間が100%をまたぐ／年で符号が割れる場合は「効いている」と読まないこと。')


if __name__ == '__main__':
    main()
