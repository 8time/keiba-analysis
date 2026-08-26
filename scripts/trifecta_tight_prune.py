# -*- coding: utf-8 -*-
"""堅帯30点を上から削って Hit3 がどこまで残るか。

本番はまだ30点のまま。エンジンの並び(スコア上位)で
30 → 28 → 26 → 25 → 24 と切ったときの Hit3 / 着順的中 / 回収。

Usage: python scripts/trifecta_tight_prune.py
"""
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import trio_engine as te
from core import value_scanner as vs
from scripts import csv_data as cd
from scripts.trifecta30_cover_backtest import (
    MIN_HORSES, PAY_HI, STAKE, DAY0, SHUBETSU_SKIP,
    _i, _f, load_trifecta_payouts, build_horses, ninki_axis, elim_keep,
    period_of,
)

KS = (30, 28, 26, 25, 24)


def hit_rank(bets, win, unordered=True):
    """1-indexed。無ければ None。"""
    win_set = frozenset(win)
    for i, b in enumerate(bets, 1):
        c = tuple(b['combo'])
        if unordered and frozenset(c) == win_set:
            return i
        if not unordered and c == win:
            return i
    return None


class Agg:
    def __init__(self):
        self.n = 0
        self.hit3 = 0
        self.exact = 0
        self.cost = 0.0
        self.ret = 0.0

    def add(self, hit3, exact, k, pay):
        self.n += 1
        self.hit3 += int(hit3)
        self.exact += int(exact)
        self.cost += k * STAKE
        if exact:
            self.ret += pay


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def roi(ret, cost):
    return 100.0 * ret / cost if cost else 0.0


def print_tbl(title, by_k):
    print(f'\n=== {title} ===')
    print(f"{'点':>4} {'R':>5} {'Hit3%':>8} {'30点差':>8} {'厳密%':>7} {'回収%':>7} {'損益':>10}")
    a30 = by_k[30]
    for k in KS:
        a = by_k[k]
        if a.n == 0:
            continue
        d = a.hit3 - a30.hit3
        print(f"{k:4d} {a.n:5d} {pct(a.hit3, a.n):7.1f}% {d:+6d}R "
              f"{pct(a.exact, a.n):6.1f}% {roi(a.ret, a.cost):6.1f}% "
              f"{a.ret - a.cost:10.0f}")


def main():
    print('堅帯30点の上からの削り (本番は未変更)', flush=True)
    payout = load_trifecta_payouts()
    cols = [
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ]
    h = cd.load_horses(cols=cols)
    h = h[h['day'] >= DAY0]
    h['jyo'] = h['jyo'].astype(float)
    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'shubetsu'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))
    shu_map = dict(zip(races['race_key'].astype(str),
                       races['shubetsu'].fillna('').astype(str)))

    # cells[uni][slice][k]
    cells = defaultdict(lambda: defaultdict(lambda: {k: Agg() for k in KS}))
    ranks_h3 = []
    ranks_ex = []
    n_tight = 0
    n_skip_short = 0

    for rk, g in h.groupby('race_key', sort=False):
        rk = str(rk)
        if rk not in payout or len(g) < MIN_HORSES:
            continue
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        if str(shu_map.get(rk, '') or '') in SHUBETSU_SKIP:
            continue
        per = period_of(int(g['day'].iloc[0]))
        if per is None:
            continue
        rows = g.to_dict('records')
        win, pay = payout[rk]
        umas = {_i(r['umaban']) for r in rows}
        if any(u not in umas for u in win):
            continue
        odds_list = [o for o in (_f(r.get('win_odds')) for r in rows) if o and o > 0]
        if len(odds_list) < 3:
            continue
        kigo = kigo_map.get(rk, '')
        is_handi = bool(handi_map.get(rk, _i(g['is_handi1'].iloc[0])))
        ap = vs.arare_prob(odds_list, {'is_handicap': is_handi, 'kigo': kigo or ''},
                           len(rows))
        bf = te.formation_for_arare(ap)
        if bf is None or bf[0] != 'tight':
            continue
        horses = build_horses(rows)
        if len(horses) < 3:
            continue
        res = te.recommend_trifecta(
            horses, axis_umaban=ninki_axis(horses, 2), n_points=30, arare_prob=ap)
        bets = list(res.get('bets') or [])
        if len(bets) < 24:
            n_skip_short += 1
        n_tight += 1
        rh = hit_rank(bets, win, True)
        re = hit_rank(bets, win, False)
        if rh:
            ranks_h3.append(rh)
        if re:
            ranks_ex.append(re)
        sls = ['ALL', per]
        if pay <= PAY_HI:
            sls.append('le70k')
            sls.append(f'{per}|le70k')
        else:
            sls.append('gt70k')

        keep = elim_keep(rows, kigo, is_handi)
        horses_elim = [x for x in horses if x['umaban'] in keep]
        elim_ok = len(horses_elim) >= 3 and all(u in keep for u in win)
        elim_bets = None
        if elim_ok:
            re2 = te.recommend_trifecta(
                horses_elim, axis_umaban=ninki_axis(horses_elim, 2),
                n_points=30, arare_prob=ap)
            elim_bets = list(re2.get('bets') or [])

        for k in KS:
            top = bets[:k]
            h3 = hit_rank(top, win, True) is not None
            ex = hit_rank(top, win, False) is not None
            for sl in sls:
                cells['full'][sl][k].add(h3, ex, k, pay)
            if elim_bets is not None:
                top_e = elim_bets[:k]
                h3e = hit_rank(top_e, win, True) is not None
                exe = hit_rank(top_e, win, False) is not None
                for sl in sls:
                    cells['elim'][sl][k].add(h3e, exe, k, pay)

        if n_tight % 400 == 0:
            print(f'  ... 堅帯 {n_tight}R', flush=True)

    print(f'\n堅帯 {n_tight}R (点<24は {n_skip_short}R、切らずに含める)')
    print('削り方=エンジンのスコア上位を残す。下位点を落とす。')

    print_tbl('堅帯・全頭・2025+2026', cells['full']['ALL'])
    print_tbl('堅帯・2025 holdout', cells['full']['2025'])
    print_tbl('堅帯・2026', cells['full']['2026'])
    print_tbl('堅帯・≤7万', cells['full']['le70k'])
    print_tbl('堅帯・7万超', cells['full']['gt70k'])
    print_tbl('堅帯・消去で3頭残・全頭', cells['elim']['ALL'])
    print_tbl('堅帯・消去で3頭残・≤7万', cells['elim']['le70k'])

    def cdf(title, ranks, n_race):
        print(f'\n=== {title} (30点に入ったレースの順位分布) ===')
        if not ranks:
            return
        print(f'  30点内 {len(ranks)}/{n_race} = {pct(len(ranks), n_race):.1f}%')
        for k in KS:
            in_k = sum(1 for r in ranks if r <= k)
            print(f'  上位{k:2d}点に入る: {in_k:4d}  '
                  f'Hit3相当 {pct(in_k, n_race):.1f}%  '
                  f'(30点内のうち {pct(in_k, len(ranks)):.1f}% がこの点数で残る)')

    cdf('Hit3の最上位点', ranks_h3, n_tight)
    cdf('着順どおりの点', ranks_ex, n_tight)

    a30 = cells['full']['ALL'][30]
    a25 = cells['full']['ALL'][25]
    print('\n【判定】堅帯・全頭 30点 vs 25点')
    print(f'  Hit3  {pct(a30.hit3, a30.n):.1f}% → {pct(a25.hit3, a25.n):.1f}% '
          f'({a25.hit3 - a30.hit3:+d}R / {a30.n}R)')
    print(f'  厳密  {pct(a30.exact, a30.n):.1f}% → {pct(a25.exact, a25.n):.1f}%')
    print(f'  回収  {roi(a30.ret, a30.cost):.1f}% → {roi(a25.ret, a25.cost):.1f}%')
    print('  まだ点数は変えていません。')


if __name__ == '__main__':
    main()
