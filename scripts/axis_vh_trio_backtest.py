# -*- coding: utf-8 -*-
"""「◎ + 〇 + 穴馬ハンター精鋭1位」の3頭が実際に来ているかを検証。

ユーザー観測(2026-08-02の7レース紙面): 軸候補◎・〇・穴馬ハンター精鋭1位の組合せが
けっこう当たっている → 少点数の3連単/3連複で定期的に買えるのでは。

紙面の定義をそのまま再現する:
  ◎ = 人気1番   〇 = 人気2番   （軸候補は固定軸=人気1+2が最適と検証済[[project_axis_selection]]）
  穴馬ハンター精鋭1位 = **人気6番以下**の中で vh2_score が最大の馬
      (core/newspaper._vh_html: cand = 人気>=6 ∪ 穴セット を vh降順で上位6頭表示)

⚠vh2モデルの学習は≤2023年(scripts/value_hunter_recall_v2.py FIT_END=2023)。
  したがって2016-2023はin-sample=甘く出る。**2025年以降を正とする**。

さらにユーザーの問い「もう1頭はどういう馬が来ているか」に答えるため、
人気1・2が3着内に入ったレースで、残り1枠を埋めた馬の人気/vh順位の分布も出す。

Usage:
  python scripts/axis_vh_trio_backtest.py
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

from scripts import csv_data as cd
from core import jockey_jv as jj

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

MIN_HORSES = 8
ANA_POP_MIN = 6          # 穴馬ハンターに載る下限人気(紙面と同じ)


def load_payouts(bet_type):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?", (bet_type,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[str(rk)].append(((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay)))
    con.close()
    return out


def build():
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'vh2_score'])
    h['race_key'] = h['race_key'].astype(str)      # int64で読まれるとDBと突合できない
    rows = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        try:
            a = int(g.loc[g['ninki'] == 1, 'umaban'].iloc[0])
            b = int(g.loc[g['ninki'] == 2, 'umaban'].iloc[0])
        except Exception:
            continue
        ana = g[(g['ninki'] >= ANA_POP_MIN) & g['vh2_score'].notna()]
        if ana.empty:
            continue
        anas = ana.sort_values('vh2_score', ascending=False)
        c1 = int(anas['umaban'].iloc[0])
        c2 = int(anas['umaban'].iloc[1]) if len(anas) > 1 else None
        c3 = int(anas['umaban'].iloc[2]) if len(anas) > 2 else None
        fin = g.sort_values('chakujun')
        top3 = [int(x) for x in fin['umaban'].tolist()[:3]]
        if len(top3) < 3:
            continue
        pop = dict(zip(g['umaban'].astype(int), g['ninki'].astype(int)))
        # vh順位(人気6+の中での順位)
        vrank = {int(u): i + 1 for i, u in enumerate(anas['umaban'].astype(int))}
        rows.append({
            'rk': rk, 'day': int(g['day'].iloc[0]), 'year': int(str(g['day'].iloc[0])[:4]),
            'a': a, 'b': b, 'c1': c1, 'c2': c2, 'c3': c3,
            'top3': tuple(top3), 'n': len(g),
            'pop': pop, 'vrank': vrank,
            'p3': int(g.loc[g['ninki'] == 3, 'umaban'].iloc[0])
            if (g['ninki'] == 3).any() else None,
        })
    return pd.DataFrame(rows)


def eval_set(df, pick_fn, pay_map, label, kind='trio'):
    """pick_fn(row)->買う組合せの集合。ROIは1組合せ100円。"""
    n = hit = 0
    spend = ret = 0.0
    pts = []
    for r in df.itertuples(index=False):
        tk = pick_fn(r)
        if not tk:
            continue
        pl = pay_map.get(r.rk)
        if not pl:
            continue
        n += 1
        pts.append(len(tk))
        spend += len(tk) * 100
        for combo, pay in pl:
            key = tuple(sorted(combo)) if kind == 'trio' else combo
            if key in tk:
                hit += 1
                ret += pay
                break
    if n < 50:
        return None
    return {'label': label, 'n': n, 'pts': float(np.mean(pts)),
            'hit': hit / n * 100, 'roi': ret / spend * 100 if spend else 0,
            'hits': hit}


def show(title, rows):
    print(f'\n■ {title}')
    print(f'{"買い方":34s}{"点":>5}{"R数":>8}{"的中数":>8}{"的中率":>8}{"ROI":>7}')
    print('-' * 72)
    for r in rows:
        if not r:
            continue
        print(f'{r["label"]:34s}{r["pts"]:>5.0f}{r["n"]:>8,}{r["hits"]:>8,}'
              f'{r["hit"]:>7.1f}%{r["roi"]:>6.0f}%')


def main():
    print('読込中...', file=sys.stderr)
    df = build()
    print(f'対象 {len(df):,}レース（{df["day"].min()}〜{df["day"].max()}）')
    trio = load_payouts('3連複')
    tri = load_payouts('3連単')

    for wlabel, sub in (('【in-sample 2016-2023｜vh2の学習期間・甘く出る】',
                         df[df['year'] <= 2023]),
                        ('【★holdout 2025-2026｜こちらが正】',
                         df[df['year'] >= 2025])):
        print(f'\n{"="*72}\n{wlabel}  {len(sub):,}レース\n{"="*72}')

        show('3連複（順不同）', [
            eval_set(sub, lambda r: {tuple(sorted((r.a, r.b, r.c1)))}, trio,
                     '◎〇+穴1位 の1点', 'trio'),
            eval_set(sub, lambda r: {tuple(sorted((r.a, r.b, x)))
                                     for x in (r.c1, r.c2, r.c3) if x},
                     trio, '◎〇+穴1-3位 の3点', 'trio'),
            eval_set(sub, lambda r: {tuple(sorted((r.a, r.b, r.p3)))} if r.p3 else None,
                     trio, '【比較】◎〇+人気3位 の1点', 'trio'),
            # 残り1枠の実測分布(3-5番人気で62.6%)に合わせた実用形
            eval_set(sub, lambda r: {tuple(sorted((r.a, r.b, u)))
                                     for u, p in r.pop.items() if 3 <= p <= 5},
                     trio, '◎〇+人気3-5位 の3点', 'trio'),
            eval_set(sub, lambda r: {tuple(sorted((r.a, r.b, u)))
                                     for u, p in r.pop.items() if 3 <= p <= 5}
                     | {tuple(sorted((r.a, r.b, r.c1)))},
                     trio, '◎〇+人気3-5位+穴1位 の4点', 'trio'),
            eval_set(sub, lambda r: {tuple(sorted((r.a, r.b, u)))
                                     for u, p in r.pop.items() if 3 <= p <= 4}
                     | {tuple(sorted((r.a, r.b, x))) for x in (r.c1, r.c2) if x},
                     trio, '◎〇+人気3-4位+穴1-2位 の4点', 'trio'),
        ])

        show('3連単（着順どおり）', [
            eval_set(sub, lambda r: {p for p in __import__('itertools').permutations(
                (r.a, r.b, r.c1))}, tri, '◎〇穴1位 のBOX 6点', 'trifecta'),
            eval_set(sub, lambda r: {(x, y, z) for x in (r.a, r.b)
                                     for y in (r.a, r.b, r.c1) for z in (r.a, r.b, r.c1)
                                     if len({x, y, z}) == 3},
                     tri, '1着◎〇 / 2-3着◎〇穴1 (4点)', 'trifecta'),
        ])

        # ── 5頭セット: ◎〇 + 人気3位 + 穴1位 + 穴2位 ──
        def five(r):
            s = [r.a, r.b]
            if r.p3:
                s.append(r.p3)
            for x in (r.c1, r.c2):
                if x and x not in s:
                    s.append(x)
            return s if len(s) == 5 else None

        def _f(r, col1_n, col2_n, col3_n, kind):
            """col*_n = 5頭セットの先頭から何頭をその着に使うか。"""
            s = five(r)
            if not s:
                return None
            A, B, C = set(s[:col1_n]), set(s[:col2_n]), set(s[:col3_n])
            if kind == 'trio':
                return {tuple(sorted((x, y, z))) for x in A for y in B for z in C
                        if len({x, y, z}) == 3}
            return {(x, y, z) for x in A for y in B for z in C if len({x, y, z}) == 3}

        show('★5頭セット（◎〇+人気3位+穴1位+穴2位）', [
            eval_set(sub, lambda r: _f(r, 5, 5, 5, 'trio'), trio,
                     '3連複 5頭BOX (10点)', 'trio'),
            eval_set(sub, lambda r: _f(r, 3, 5, 5, 'trio'), trio,
                     '3連複 3頭×5×5 (9点)', 'trio'),
            eval_set(sub, lambda r: _f(r, 5, 5, 5, 'trifecta'), tri,
                     '3連単 5頭BOX (60点)', 'trifecta'),
            eval_set(sub, lambda r: _f(r, 2, 5, 5, 'trifecta'), tri,
                     '3連単 1着◎〇 / 2-3着5頭 (24点)', 'trifecta'),
            eval_set(sub, lambda r: _f(r, 3, 5, 5, 'trifecta'), tri,
                     '3連単 1着◎〇+人気3 / 2-3着5頭 (36点)', 'trifecta'),
            eval_set(sub, lambda r: _f(r, 1, 5, 5, 'trifecta'), tri,
                     '3連単 1着◎のみ / 2-3着5頭 (12点)', 'trifecta'),
            eval_set(sub, lambda r: _f(r, 2, 3, 5, 'trifecta'), tri,
                     '3連単 1着◎〇/2着3頭/3着5頭 (14点)', 'trifecta'),
        ])

        # ── 6頭セット: ◎〇 + 人気3,4位 + 穴1,2位 ──
        # (「◎〇+人気3-4位+穴1-2位の4点」は、この6頭から◎〇を全券固定した形)
        def six(r):
            s = [r.a, r.b]
            for u, p in sorted(r.pop.items(), key=lambda kv: kv[1]):
                if p in (3, 4) and u not in s:
                    s.append(u)
            for x in (r.c1, r.c2):
                if x and x not in s:
                    s.append(x)
            return s if len(s) == 6 else None

        def _g(r, n1, n2, n3, kind):
            s = six(r)
            if not s:
                return None
            A, B, C = set(s[:n1]), set(s[:n2]), set(s[:n3])
            if kind == 'trio':
                return {tuple(sorted((x, y, z))) for x in A for y in B for z in C
                        if len({x, y, z}) == 3}
            return {(x, y, z) for x in A for y in B for z in C if len({x, y, z}) == 3}

        show('★6頭セット（◎〇+人気3-4位+穴1-2位）', [
            eval_set(sub, lambda r: _g(r, 6, 6, 6, 'trio'), trio,
                     '3連複 6頭BOX (20点)', 'trio'),
            # ◎か〇の**どちらか**を含む形(両方固定ではない)。両方固定=上の4点版
            eval_set(sub, lambda r: _g(r, 2, 6, 6, 'trio'), trio,
                     '3連複 ◎〇のどちらか必須 (16点)', 'trio'),
            eval_set(sub, lambda r: _g(r, 3, 6, 6, 'trio'), trio,
                     '3連複 上位3頭×6×6 (12点)', 'trio'),
            eval_set(sub, lambda r: _g(r, 6, 6, 6, 'trifecta'), tri,
                     '3連単 6頭BOX (120点)', 'trifecta'),
            eval_set(sub, lambda r: _g(r, 2, 6, 6, 'trifecta'), tri,
                     '3連単 1着◎〇 / 2-3着6頭 (40点)', 'trifecta'),
            eval_set(sub, lambda r: _g(r, 2, 4, 6, 'trifecta'), tri,
                     '3連単 1着◎〇/2着4頭/3着6頭 (26点)', 'trifecta'),
            eval_set(sub, lambda r: _g(r, 3, 6, 6, 'trifecta'), tri,
                     '3連単 1着3頭 / 2-3着6頭 (60点)', 'trifecta'),
        ])

        # 天井: 人気1・2がそろって3着内に入る率
        both = sub.apply(lambda r: (r['a'] in r['top3']) and (r['b'] in r['top3']), axis=1)
        c_in = sub.apply(lambda r: r['c1'] in r['top3'], axis=1)
        print(f'\n  人気1・2が**そろって**3着内: {both.mean()*100:.1f}%  ← この買い方の天井')
        print(f'  穴1位が3着内: {c_in.mean()*100:.1f}%')
        print(f'  3頭そろい(=1点的中): {(both & c_in).mean()*100:.1f}%')
        if both.sum():
            print(f'  ※人気1・2がそろった時に穴1位も来る条件付き確率: '
                  f'{(both & c_in).sum()/both.sum()*100:.1f}%')

        # 「もう1頭は何者か」
        rest = []
        for r in sub[both].itertuples(index=False):
            other = [u for u in r.top3 if u not in (r.a, r.b)]
            if not other:
                continue
            u = other[0]
            rest.append({'pop': r.pop.get(u, 99), 'vr': r.vrank.get(u)})
        if rest:
            rd = pd.DataFrame(rest)
            print(f'\n  ▼人気1・2が3着内に入った{len(rd):,}レースで、残り1枠を埋めた馬の**人気**')
            vc = rd['pop'].value_counts().sort_index()
            cum = 0
            for p in list(vc.index)[:12]:
                cum += vc[p] / len(rd) * 100
                bar = '█' * int(vc[p] / len(rd) * 100)
                print(f'    {p:>2}番人気: {vc[p]/len(rd)*100:>5.1f}%  累計{cum:>5.1f}%  {bar}')
            n6 = (rd['pop'] >= ANA_POP_MIN).mean() * 100
            print(f'    → 6番人気以下(=穴馬ハンターの守備範囲)は {n6:.1f}%'
                  f' / 3-5番人気が {((rd["pop"]>=3)&(rd["pop"]<6)).mean()*100:.1f}%')
            hv = rd[rd['pop'] >= ANA_POP_MIN]['vr'].dropna()
            if len(hv):
                print(f'\n  ▼その残り1頭が6番人気以下だった{len(hv):,}件での **vh順位**')
                for k in (1, 2, 3):
                    print(f'    vh{k}位: {(hv==k).mean()*100:>5.1f}%')
                print(f'    vh4位以下: {(hv>=4).mean()*100:>5.1f}%'
                      f'   （vh順位はランダムなら1位が約{100/hv.max():.0f}%）')


if __name__ == '__main__':
    main()
