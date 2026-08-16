# -*- coding: utf-8 -*-
"""3頭目を「人気3・4位」から「アプリRank3・4位」に置き換えたらROIは上がるか。

ユーザーの問い: 最良の買い方(◎〇固定+4通り)の3頭目が人気ベースだった。
  アプリのRank(ability_score=LTR代理)を使う形にできないか。

比較する形（すべて ◎=人気1 / 〇=人気2 を全券固定・3頭目だけ差し替え）:
  A 人気3-4位 + 穴1-2位      … 現行の最良形(4点)。D鉄板でROI89%
  B Rank3-4位 + 穴1-2位      … 3頭目をアプリRankに置換(4点)
  C 人気3-5位 + 穴1位        … 人気を1段広げる(4点)
  D Rank3-5位 + 穴1位        … Rankを1段広げる(4点)
  E 人気3-5位のみ            … 穴を入れない(3点)
  F Rank3-5位のみ            … 同上のRank版(3点)

⚠ability_scoreは**小さいほど強い**（1着平均0.380/10着以下0.562）。
  昇順に並べること。降順にすると最弱馬から選ぶことになる（実際に踏んだ）。
⚠Rank1・2位は使わない。軸は人気1・2に固定したまま3頭目だけを比べる
  （軸まで変えると何が効いたのか分からなくなる）。

Usage:
  python scripts/rank_vs_ninki_legs.py
"""
import os
import sys
import math
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

MIN_HORSES = 8
ANA_POP_MIN = 6


def load_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連複'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[str(rk)].append((tuple(sorted((int(c[:2]), int(c[2:4]), int(c[4:6])))),
                                 float(pay)))
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
        try:
            a = int(g.loc[g['ninki'] == 1, 'umaban'].iloc[0])
            b = int(g.loc[g['ninki'] == 2, 'umaban'].iloc[0])
        except Exception:
            continue
        # 妙味度（D鉄板ゾーンだけを見るため）
        m = meta.get(rk)
        odds = g['win_odds'].tolist()
        rv = vs.race_value_score(
            odds, {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                   'kigo': str(getattr(m, 'kigo', '') or '')},
            n_horses=len(g)) if m is not None else None
        if not rv:
            continue

        pop = dict(zip(g['umaban'].astype(int), g['ninki'].astype(int)))
        # ⚠ability_scoreは小さいほど強い
        gg = g.sort_values('ability_score', ascending=True)
        rank_order = gg['umaban'].astype(int).tolist()

        def pop_at(n):
            for u, p in pop.items():
                if p == n:
                    return u
            return None

        # ⚠公平な比較のため**軸(人気1・2)を除いた順位**で取る。
        #   素のRank3・4位は軸と重複しがちで、除外されると点数が減って
        #   カバー頭数が変わり比較にならない（実際に踏んだ: 4.0点 vs 3.2点）。
        rank_wo_axis = [u for u in rank_order if u not in (a, b)]
        pop_wo_axis = [u for u, _p in sorted(pop.items(), key=lambda kv: kv[1])
                       if u not in (a, b)]

        def rank_at(n):           # 軸を除いたRankのn番目（n=1が実質Rank3位相当）
            return rank_wo_axis[n - 1] if len(rank_wo_axis) >= n else None

        def popx_at(n):           # 軸を除いた人気のn番目（n=1が人気3位）
            return pop_wo_axis[n - 1] if len(pop_wo_axis) >= n else None

        ana = g[(g['ninki'] >= ANA_POP_MIN) & g['vh2_score'].notna()] \
            .sort_values('vh2_score', ascending=False)
        c1 = int(ana['umaban'].iloc[0]) if len(ana) >= 1 else None
        c2 = int(ana['umaban'].iloc[1]) if len(ana) >= 2 else None

        fin = g.sort_values('chakujun')
        top3 = tuple(sorted(int(x) for x in fin['umaban'].tolist()[:3]))
        if len(top3) < 3:
            continue
        rows.append({'rk': rk, 'vscore': rv['score'], 'top3': top3,
                     'a': a, 'b': b, 'c1': c1, 'c2': c2,
                     'p3': popx_at(1), 'p4': popx_at(2), 'p5': popx_at(3),
                     'r3': rank_at(1), 'r4': rank_at(2), 'r5': rank_at(3)})
    return pd.DataFrame(rows)


CASES = [
    ('A 人気3-4位 + 穴1-2位', ['p3', 'p4', 'c1', 'c2']),   # 軸を除いた人気上位2頭
    ('B Rank3-4位 + 穴1-2位', ['r3', 'r4', 'c1', 'c2']),
    ('C 人気3-5位 + 穴1位',   ['p3', 'p4', 'p5', 'c1']),
    ('D Rank3-5位 + 穴1位',   ['r3', 'r4', 'r5', 'c1']),
    ('E 人気3-5位のみ',       ['p3', 'p4', 'p5']),
    ('F Rank3-5位のみ',       ['r3', 'r4', 'r5']),
    ('G 人気3-4位のみ',       ['p3', 'p4']),
    ('H Rank3-4位のみ',       ['r3', 'r4']),
]


def evaluate(df, pay, legs, lo, hi):
    n = hit = 0
    spend = ret = 0.0
    pts = 0
    for r in df.itertuples(index=False):
        if not (lo <= r.vscore < hi):
            continue
        pl = pay.get(r.rk)
        if not pl:
            continue
        third = []
        for c in legs:
            v = getattr(r, c)
            # 欠損(該当人気/Rankの馬がいない)は NaN で来るので弾く
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            v = int(v)
            if v not in (r.a, r.b) and v not in third:
                third.append(v)
        if not third:
            continue
        tickets = {tuple(sorted((r.a, r.b, t))) for t in third}
        n += 1
        pts += len(tickets)
        spend += len(tickets) * 100
        for combo, p in pl:
            if combo in tickets:
                hit += 1
                ret += p
                break
    if n < 150:
        return None
    return {'n': n, 'pts': pts / n, 'hit': hit / n * 100,
            'roi': ret / spend * 100 if spend else 0}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print('読込中...', file=sys.stderr)
    df = build()
    pay = load_payouts()
    print(f'対象 {len(df):,}レース（2025-2026）\n')

    for zl, lo, hi in (('D 鉄板 (妙味度0-49)', 0, 50),
                       ('C 中庸 (50-69)', 50, 70),
                       ('全レース', 0, 201)):
        print(f'■ {zl}')
        print(f'{"買い方":26s}{"点":>5}{"R数":>8}{"的中率":>9}{"ROI":>8}')
        print('-' * 58)
        base = None
        for name, legs in CASES:
            e = evaluate(df, pay, legs, lo, hi)
            if not e:
                print(f'{name:26s}{"標本不足":>10}')
                continue
            if base is None:
                base = e['roi']
            d = e['roi'] - base
            mark = '' if name.startswith('A') else f'  ({d:+.0f}pp)'
            print(f'{name:26s}{e["pts"]:>5.1f}{e["n"]:>8,}'
                  f'{e["hit"]:>8.1f}%{e["roi"]:>7.0f}%{mark}')
        print()

    print('※Aが現行の最良形。BとDがそれを上回ればRankを使う価値がある。')
    print('※ability_scoreは小さいほど強いので昇順で並べている。')


if __name__ == '__main__':
    main()
