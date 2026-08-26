# -*- coding: utf-8 -*-
"""3連複 10点圧縮: 順位付けモデル比較。

主指標 = 使う馬(人気1-K)に正解3頭が揃っているレースの **10点的中**。
20点は救済性能。ROIは1点100円フラット。
現行エンジンは変えず、並べ方だけ holdout で比較する。

モデル:
  ①能力+本線   現行(ability合計 + 人気1-4頭数×6)
  ②複勝率の積   各馬の推定3着内確率の積
  ③最弱複勝     積 × (一番低い複勝率)^2
  ④役割分離     能力上位2頭の合計 + 一番弱い馬の複勝率
  ⑤人気合計     人気番号の合計が小さい順（市場の箱）
  ⑥軸2×3着     人気1-2を軸に固定し、3頭目を複勝率順

Usage: python scripts/trio_rank10_backtest.py
"""
import math
import os
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.axis_selector import fuku_rate
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd


def load_pays():
    con = sqlite3.connect(f'file:{JV_DB_PATH}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        "SELECT race_key, combo, payout FROM payouts "
        "WHERE bet_type='3連複' AND payout>0"
    ).fetchall()
    con.close()
    out = {}
    for rk, combo, p in rows:
        try:
            fs = frozenset(int(combo[i:i + 2]) for i in range(0, 6, 2))
            if len(fs) == 3:
                out[str(rk)] = (fs, float(p))
        except Exception:
            continue
    return out


def fuku_of(ninki, odds):
    v = fuku_rate(ninki, odds)
    if v is None:
        v = fuku_rate(ninki, None)
    return max(1.0, float(v or 8.0)) / 100.0


def keep_ninki(g, k):
    sub = g[g['ninki'] <= k]
    return sub.nsmallest(min(k, len(sub)), 'ninki')


def all_combos(ums):
    return [frozenset(c) for c in combinations(ums, 3)]


def rank_top(combos, score_fn, n):
    ordered = sorted(combos, key=score_fn, reverse=True)
    return ordered[:n]


def models_for(ab, nk, fk):
    """各モデル: combo(frozenset) -> score。高いほど先。"""

    def ability_honsen(fs):
        s = sum(ab[u] for u in fs)
        n_pop = sum(1 for u in fs if nk[u] <= 4)
        return s + 6.0 * n_pop

    def fuku_prod(fs):
        p = 1.0
        for u in fs:
            p *= fk[u]
        return p

    def fuku_min_w(fs):
        vs = [fk[u] for u in fs]
        p = vs[0] * vs[1] * vs[2]
        return p * (min(vs) ** 2)

    def role_ab_fuku(fs):
        # 能力で2頭、残り1頭は「3着候補」として複勝率だけ見る
        legs = sorted(fs, key=lambda u: -ab[u])
        return ab[legs[0]] + ab[legs[1]] + 3.0 * fk[legs[2]]

    def ninki_sum(fs):
        return -sum(nk[u] for u in fs)

    def role_fuku_pair(fs):
        vs = sorted((fk[u] for u in fs), reverse=True)
        return (vs[0] * vs[1]) * (vs[2] ** 2)

    return [
        ('①能力+本線', ability_honsen, 'rank'),
        ('②複勝率の積', fuku_prod, 'rank'),
        ('③最弱複勝', fuku_min_w, 'rank'),
        ('④役割分離', role_ab_fuku, 'rank'),
        ('⑤人気合計', ninki_sum, 'rank'),
        ('⑥軸2×3着', None, 'axis'),
    ]


def axis2_third(ums, nk, fk, n_points):
    """人気1・2を軸、3頭目を複勝率順。足りなければ人気1・3を次軸。"""
    by_nk = sorted(ums, key=lambda u: nk[u])
    if len(by_nk) < 3:
        return []
    rest = sorted([u for u in ums if u not in by_nk[:2]], key=lambda u: -fk[u])
    out = []
    a, b = by_nk[0], by_nk[1]
    for t in rest:
        out.append(frozenset((a, b, t)))
        if len(out) >= n_points:
            return out[:n_points]
    if len(by_nk) >= 3:
        c = by_nk[2]
        rest2 = sorted([u for u in ums if u not in (a, c)], key=lambda u: -fk[u])
        for t in rest2:
            fs = frozenset((a, c, t))
            if fs not in out:
                out.append(fs)
            if len(out) >= n_points:
                break
    return out[:n_points]


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'ability_score', 'top3',
    ])
    rmeta = cd.load_races(cols=['race_key', 'vscore'])
    vsmap = rmeta.drop_duplicates('race_key').set_index('race_key')['vscore'].to_dict()
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    # cell[(period, zone, k, model, n_points)] = [n, hits, cost, ret]
    # n = 残し内レース数
    cell = defaultdict(lambda: [0, 0, 0, 0])
    n_ok = defaultdict(int)

    for rk, g in h.groupby('race_key', sort=False):
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if not pay:
            try:
                pay = pays.get(int(rk))
            except (TypeError, ValueError):
                pay = None
        if not pay or pay[0] != win:
            continue
        payout = pay[1]
        period = str(g['period'].iloc[0])
        vs = vsmap.get(rk)
        if vs is None:
            try:
                vs = vsmap.get(int(rk))
            except (TypeError, ValueError):
                vs = None
        try:
            vs = float(vs) if vs == vs else None
        except (TypeError, ValueError):
            vs = None
        skip = bool(vs is not None and vs >= 70)
        zones = ['all', 'BA見送り' if skip else '非見送り']

        for k in (6, 7, 8, 9):
            kg = keep_ninki(g, k)
            if len(kg) < 3:
                continue
            ums = [int(x) for x in kg['umaban']]
            keep = set(ums)
            if not win <= keep:
                continue
            ab, nk, fk = {}, {}, {}
            for r in kg.itertuples(index=False):
                u = int(r.umaban)
                ab[u] = float(r.ability_score) if r.ability_score == r.ability_score else 0.0
                nk[u] = int(r.ninki)
                fk[u] = fuku_of(r.ninki, r.win_odds)
            combos = all_combos(ums)
            mdls = models_for(ab, nk, fk)
            for z in zones:
                n_ok[(period, z, k)] += 1
            for name, fn, kind in mdls:
                for n_points in (10, 20):
                    if kind == 'axis':
                        top = axis2_third(ums, nk, fk, n_points)
                    else:
                        top = rank_top(combos, fn, n_points)
                    hit = win in top
                    cost = max(len(top), 1) * 100
                    # 点数不足のモデルは実際の点数でコストを付ける
                    ret = payout if hit else 0.0
                    for z in zones:
                        for per in (period, 'ALL'):
                            c = cell[(per, z, k, name, n_points)]
                            c[0] += 1
                            c[1] += int(hit)
                            c[2] += cost
                            c[3] += ret

    def pr_block(period, zone, title):
        print(f'\n=== {title} ===')
        names = [m[0] for m in models_for({}, {}, {})]
        for k in (6, 7, 8, 9):
            n = cell[(period, zone, k, names[0], 10)][0]
            if n == 0:
                continue
            print(f'\n-- 人気1-{k} に正解あり  {n:,}R --')
            print(f'{"モデル":<12}{"10点的中":>10}{"20点的中":>10}{"10点ROI":>10}{"20点ROI":>10}')
            for name in names:
                a = cell[(period, zone, k, name, 10)]
                b = cell[(period, zone, k, name, 20)]
                if a[0] == 0:
                    continue
                h10 = a[1] / a[0] * 100
                h20 = b[1] / b[0] * 100
                r10 = a[3] / a[2] * 100 if a[2] else 0
                r20 = b[3] / b[2] * 100 if b[2] else 0
                mark = ' ←' if name == '①能力+本線' else ''
                print(f'{name:<12}{h10:9.1f}%{h20:9.1f}%{r10:9.1f}%{r20:9.1f}%{mark}')

    pr_block('holdout', 'all', 'holdout 全（正解が使う馬にいる）← 採用判定')
    pr_block('holdout', 'BA見送り', 'holdout 見送り推奨(妙味度70+)')
    pr_block('holdout', '非見送り', 'holdout 見送り以外')
    pr_block('train', 'all', 'train 参考（同じ条件）')
    print('\n主指標は10点的中。20点で勝って10点で負ける方式は不採用。')
    print('⑥軸2×3着は点数=軸の3頭目の本数（6頭なら最大4点）で、足りない分だけ1-3軸を足す。')


if __name__ == '__main__':
    main()
