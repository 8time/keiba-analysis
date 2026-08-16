# -*- coding: utf-8 -*-
"""妙味度70以上（荒れゾーン）専用の買い方を探す。

これまでの結果では荒れゾーンは一貫して最悪だった:
  ◎〇固定4点 → ROI **55%**（D鉄板89%/C中庸83%に対して壊滅）
  3連複2-3-6 → 76% ／ 3連単2-5-8 → 68%
理由は明快で、**荒れる＝人気1・2が飛ぶ**ので軸固定型が全部死ぬ。

そこで荒れ専用に「軸を置かない/穴を軸にする」形を含めて総当たりする:
  ①Rank形(a-b-c) を点数別に掃引（3連複・3連単）
  ②穴馬ハンター(vh2)を軸に据えた形
  ③人気を捨てた形（人気1・2を外す）

⚠ability_scoreは小さいほど強い（昇順）。
⚠vh2は≤2023学習なので2025-2026のみで評価する。

Usage:
  python scripts/arare_zone_buy.py
"""
import os
import sys
import sqlite3
from itertools import combinations, permutations
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8
ARARE_LO = 70.0


def load_pay(bet):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?", (bet,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            t = (int(c[:2]), int(c[2:4]), int(c[4:6]))
            out.setdefault(str(rk), []).append(
                (tuple(sorted(t)) if bet == '3連複' else t, float(pay)))
    con.close()
    return out


def build():
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score', 'vh2_score'])
    h['race_key'] = h['race_key'].astype(str)
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1'])
    r['race_key'] = r['race_key'].astype(str)
    meta = {x.race_key: x for x in r.itertuples(index=False)}
    rows = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES or int(str(g['day'].iloc[0])[:4]) < 2025:
            continue
        m = meta.get(rk)
        if m is None:
            continue
        rv = vs.race_value_score(
            g['win_odds'].tolist(),
            {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
             'kigo': str(getattr(m, 'kigo', '') or '')}, n_horses=len(g))
        if not rv or rv['score'] < ARARE_LO:
            continue
        gg = g.sort_values('ability_score', ascending=True)      # 小さいほど強い
        ranks = gg['umaban'].astype(int).tolist()
        pops = [u for u, _ in sorted(zip(g['umaban'].astype(int),
                                         g['ninki'].astype(int)),
                                     key=lambda kv: kv[1])]
        ana = g[(g['ninki'] >= 6) & g['vh2_score'].notna()] \
            .sort_values('vh2_score', ascending=False)
        vh = ana['umaban'].astype(int).tolist()
        fin = g.sort_values('chakujun')
        top3 = [int(x) for x in fin['umaban'].tolist()[:3]]
        if len(top3) < 3:
            continue
        rows.append({'rk': rk, 'n': len(g), 'ranks': ranks, 'pops': pops,
                     'vh': vh, 'top3': tuple(sorted(top3))})
    return rows


def score(rows, pay, mk, kind):
    n = hit = pts = 0
    spend = ret = 0.0
    for r in rows:
        tk = mk(r)
        pl = pay.get(r['rk'])
        if not tk or not pl:
            continue
        n += 1
        pts += len(tk)
        spend += len(tk) * 100
        for combo, p in pl:
            if combo in tk:
                hit += 1
                ret += p
                break
    if n < 200:
        return None
    return {'n': n, 'pts': pts / n, 'hit': hit / n * 100,
            'roi': ret / spend * 100 if spend else 0}


def trio(seq, a, b, c):
    A, B, C = set(seq[:a]), set(seq[:b]), set(seq[:c])
    return {tuple(sorted((x, y, z))) for x in A for y in B for z in C
            if len({x, y, z}) == 3}


def tri(seq, a, b, c):
    A, B, C = set(seq[:a]), set(seq[:b]), set(seq[:c])
    return {(x, y, z) for x in A for y in B for z in C if len({x, y, z}) == 3}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('読込中...', file=sys.stderr)
    rows = build()
    p3 = load_pay('3連複')
    p1 = load_pay('3連単')
    print(f'■ 荒れゾーン（妙味度{ARARE_LO:.0f}以上）{len(rows):,}レース（2025-2026）\n')

    HDR = f'{"買い方":34s}{"点":>6}{"R数":>7}{"的中率":>9}{"ROI":>8}'

    def show(title, cases, pay, kind):
        print(f'■ {title}')
        print(HDR)
        print('-' * 66)
        out = []
        for name, mk in cases:
            e = score(rows, pay, mk, kind)
            if e:
                out.append((name, e))
        for name, e in sorted(out, key=lambda x: -x[1]['roi']):
            print(f'{name:34s}{e["pts"]:>6.0f}{e["n"]:>7,}'
                  f'{e["hit"]:>8.1f}%{e["roi"]:>7.0f}%')
        print()

    # ① Rank形の掃引（3連複）
    shapes = [(1, 3, 6), (2, 3, 6), (2, 4, 7), (2, 5, 8), (3, 5, 8),
              (3, 6, 9), (4, 6, 9), (4, 7, 10), (5, 8, 11)]
    show('① Rank形（3連複）',
         [(f'Rank {a}-{b}-{c}', (lambda r, a=a, b=b, c=c: trio(r['ranks'], a, b, c)))
          for a, b, c in shapes], p3, 'trio')

    # ② 人気形（比較用）
    show('② 人気形（3連複・比較用）',
         [(f'人気 {a}-{b}-{c}', (lambda r, a=a, b=b, c=c: trio(r['pops'], a, b, c)))
          for a, b, c in shapes], p3, 'trio')

    # ③ 穴馬ハンター中心（vh上位を軸に据える）
    def vh_axis(r, nv, no):
        """vh上位nv頭 × 人気上位no頭 から3頭"""
        pool = r['vh'][:nv] + [u for u in r['pops'][:no] if u not in r['vh'][:nv]]
        return {tuple(sorted(c)) for c in combinations(dict.fromkeys(pool), 3)}
    show('③ 穴馬ハンター中心（3連複）',
         [(f'vh上位{nv} + 人気上位{no}',
           (lambda r, nv=nv, no=no: vh_axis(r, nv, no)))
          for nv, no in ((2, 3), (2, 4), (3, 3), (3, 4), (1, 4), (1, 5))],
         p3, 'trio')

    # ④ 人気1・2を外す（荒れは本命が飛ぶ前提）
    def no_fav(r, k):
        pool = [u for u in r['ranks'] if u not in r['pops'][:2]][:k]
        return {tuple(sorted(c)) for c in combinations(pool, 3)}
    show('④ 人気1・2を外す（3連複）',
         [(f'人気1-2除外 × Rank上位{k}', (lambda r, k=k: no_fav(r, k)))
          for k in (4, 5, 6, 7)], p3, 'trio')

    # ⑤ 3連単
    show('⑤ 3連単（Rank形）',
         [(f'Rank {a}-{b}-{c}', (lambda r, a=a, b=b, c=c: tri(r['ranks'], a, b, c)))
          for a, b, c in [(2, 5, 8), (3, 6, 8), (4, 6, 8), (3, 6, 9), (4, 7, 10)]],
         p1, 'tri')

    print('※荒れゾーンは母数が少ない（1年半で数百レース）。')
    print('※控除率25%＝ROI75%が基準。それを大きく超えないなら意味がない。')


if __name__ == '__main__':
    main()
