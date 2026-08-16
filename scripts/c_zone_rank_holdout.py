# -*- coding: utf-8 -*-
"""C中庸ゾーンでの「Rank > 人気」を窓を分けて追試する。

[[verified_rank_vs_ninki_legs]]でC中庸だけRankが+3〜8pp勝ったが、
2025-2026の窓内での比較でholdout分割をしていなかった。

**LTRの学習は TRAIN_END=2023**（scripts/build_ltr_model.py）。したがって
  2016-2020 / 2021-2023 … in-sample（甘く出る）
  **2024-2026 … out-of-sample（ここが本番）**

穴(vh2)を含む形はvh2も≤2023学習なので窓が汚れる。
そこで**穴を使わない純粋な比較**（人気3-5位のみ vs Rank3-5位のみ）で判定する。
軸は人気1・2に固定したまま3頭目だけを差し替え、**軸を除いた順位**で同点数にする。

Usage:
  python scripts/c_zone_rank_holdout.py
"""
import os
import sys
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

sys.stdout.reconfigure(encoding='utf-8')

MIN_HORSES = 8
WINDOWS = [('2016-2020 (LTR学習内)', 2016, 2020),
           ('2021-2023 (LTR学習内)', 2021, 2023),
           ('★2024-2026 (学習期間外)', 2024, 2026)]
ZONES = [('D 鉄板 (0-49)', 0, 50), ('C 中庸 (50-69)', 50, 70),
         ('B/A 荒れ (70-)', 70, 201)]


def load_pay(bet):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?", (bet,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            t = (int(c[:2]), int(c[2:4]), int(c[4:6]))
            out[str(rk)].append(
                (tuple(sorted(t)) if bet == '3連複' else t, float(pay)))
    con.close()
    return out


def build():
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score'])
    h['race_key'] = h['race_key'].astype(str)
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1'])
    r['race_key'] = r['race_key'].astype(str)
    meta = {x.race_key: x for x in r.itertuples(index=False)}
    rows = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES or g['ability_score'].isna().any():
            continue
        try:
            a = int(g.loc[g['ninki'] == 1, 'umaban'].iloc[0])
            b = int(g.loc[g['ninki'] == 2, 'umaban'].iloc[0])
        except Exception:
            continue
        m = meta.get(rk)
        if m is None:
            continue
        rv = vs.race_value_score(
            g['win_odds'].tolist(),
            {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
             'kigo': str(getattr(m, 'kigo', '') or '')}, n_horses=len(g))
        if not rv:
            continue
        # ⚠ability_scoreは小さいほど強い
        rank_all = g.sort_values('ability_score', ascending=True)['umaban'] \
                    .astype(int).tolist()
        pop_all = [u for u, _p in sorted(zip(g['umaban'].astype(int),
                                             g['ninki'].astype(int)),
                                         key=lambda kv: kv[1])]
        rk_wo = [u for u in rank_all if u not in (a, b)]
        pp_wo = [u for u in pop_all if u not in (a, b)]
        rows.append({'rk': rk, 'year': int(str(g['day'].iloc[0])[:4]),
                     'vscore': rv['score'], 'a': a, 'b': b,
                     'rk_wo': rk_wo, 'pp_wo': pp_wo,
                     'rank_all': rank_all})
    return rows


def trio_axis(r, seq, k):
    """◎〇固定 + seq の上位k頭を3頭目に。"""
    return {tuple(sorted((r['a'], r['b'], u))) for u in seq[:k]}


def tri_shape(r, a, b, c):
    A, B, C = set(r['rank_all'][:a]), set(r['rank_all'][:b]), set(r['rank_all'][:c])
    return {(x, y, z) for x in A for y in B for z in C if len({x, y, z}) == 3}


def score(rows, pay, mk, lo, hi, y0, y1):
    n = hit = pts = 0
    spend = ret = 0.0
    for r in rows:
        if not (lo <= r['vscore'] < hi) or not (y0 <= r['year'] <= y1):
            continue
        pl = pay.get(r['rk'])
        tk = mk(r)
        if not pl or not tk:
            continue
        n += 1
        pts += len(tk)
        spend += len(tk) * 100
        for combo, p in pl:
            if combo in tk:
                hit += 1
                ret += p
                break
    if n < 250:
        return None
    return {'n': n, 'pts': pts / n, 'hit': hit / n * 100,
            'roi': ret / spend * 100 if spend else 0}


def main():
    print('読込中...', file=sys.stderr)
    rows = build()
    p3 = load_pay('3連複')
    p1 = load_pay('3連単')
    print(f'対象 {len(rows):,}レース\n')

    print('■ ① ◎〇固定+3頭目（3連複3点）: 人気 vs Rank をゾーン×窓で')
    print(f'{"ゾーン":16s}{"窓":24s}{"R数":>7}{"人気ROI":>9}{"RankROI":>9}{"差":>8}')
    print('-' * 76)
    for zl, lo, hi in ZONES:
        for wl, y0, y1 in WINDOWS:
            e_p = score(rows, p3, lambda r: trio_axis(r, r['pp_wo'], 3), lo, hi, y0, y1)
            e_r = score(rows, p3, lambda r: trio_axis(r, r['rk_wo'], 3), lo, hi, y0, y1)
            if not e_p or not e_r:
                continue
            d = e_r['roi'] - e_p['roi']
            mark = '★Rank' if d >= 3 else ('★人気' if d <= -3 else '')
            print(f'{zl:16s}{wl:24s}{e_p["n"]:>7,}{e_p["roi"]:>8.0f}%'
                  f'{e_r["roi"]:>8.0f}%{d:>+7.1f}  {mark}')
        print()

    print('■ ② C中庸の3連単 Rank2-4-7 を窓で（全レースとの比較つき）')
    print(f'{"窓":24s}{"C中庸R数":>10}{"C中庸ROI":>10}{"全レースROI":>12}{"差":>8}')
    print('-' * 66)
    for wl, y0, y1 in WINDOWS:
        e_c = score(rows, p1, lambda r: tri_shape(r, 2, 4, 7), 50, 70, y0, y1)
        e_a = score(rows, p1, lambda r: tri_shape(r, 2, 4, 7), 0, 201, y0, y1)
        if not e_c or not e_a:
            continue
        print(f'{wl:24s}{e_c["n"]:>10,}{e_c["roi"]:>9.0f}%'
              f'{e_a["roi"]:>11.0f}%{e_c["roi"]-e_a["roi"]:>+7.1f}')

    print('\n■ ③ C中庸の3連複でも同じか（人気3点 vs Rank3点・的中率も）')
    print(f'{"窓":24s}{"R数":>7}{"人気的中":>9}{"人気ROI":>9}{"Rank的中":>10}{"RankROI":>9}')
    print('-' * 72)
    for wl, y0, y1 in WINDOWS:
        e_p = score(rows, p3, lambda r: trio_axis(r, r['pp_wo'], 3), 50, 70, y0, y1)
        e_r = score(rows, p3, lambda r: trio_axis(r, r['rk_wo'], 3), 50, 70, y0, y1)
        if not e_p or not e_r:
            continue
        print(f'{wl:24s}{e_p["n"]:>7,}{e_p["hit"]:>8.1f}%{e_p["roi"]:>8.0f}%'
              f'{e_r["hit"]:>9.1f}%{e_r["roi"]:>8.0f}%')

    print('\n※LTRの学習は≤2023。2024-2026だけが学習期間外＝本番。')
    print('※2024-2026でもRankが勝てば本物。そこで消えるならin-sampleの幻。')


if __name__ == '__main__':
    main()
