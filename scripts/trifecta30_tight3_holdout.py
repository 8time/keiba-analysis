# -*- coding: utf-8 -*-
"""堅帯だけ③(2着から人気4〜5を落とさない) vs 現行。holdout比較。

本番は払戻金額で分けられないので、既存の荒れ確率・堅帯(ap<0.42)だけに③を載せる。
中庸・荒れは現行のまま。①(1軸)と②は載せない。

Usage: python scripts/trifecta30_tight3_holdout.py
"""
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import trio_engine as te
from core import value_scanner as vs
from scripts.trifecta30_cover_backtest import (
    MIN_HORSES, PAY_HI, STAKE, DAY0, SHUBETSU_SKIP,
    _i, _f, load_trifecta_payouts, build_horses, ninki_axis, elim_keep,
    period_of, eval_result,
)
from scripts.trifecta30_hit3_steps import recommend_step, pay_band


class Agg:
    def __init__(self):
        self.n = 0
        self.hit3 = 0
        self.exact = 0
        self.cost = 0.0
        self.ret = 0.0
        self.pts = 0

    def add(self, ev, pay):
        self.n += 1
        self.hit3 += int(ev['any_order'])
        self.exact += int(ev['exact'])
        n_pts = ev['n'] or 30
        self.pts += n_pts
        self.cost += n_pts * STAKE
        if ev['exact']:
            self.ret += pay


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def roi(ret, cost):
    return 100.0 * ret / cost if cost else 0.0


def rec_tight3(horses, ap):
    bf = te.formation_for_arare(ap)
    if bf is not None and bf[0] == 'tight':
        return recommend_step(horses, ap, second_ninki=5)
    return te.recommend_trifecta(
        horses, axis_umaban=ninki_axis(horses, 2), n_points=30, arare_prob=ap)


def print_row(label, a0, a1):
    if a0.n == 0:
        return
    print(f"{label:<22} {a0.n:5d}  "
          f"{pct(a0.hit3, a0.n):5.1f}→{pct(a1.hit3, a1.n):5.1f} ({a1.hit3 - a0.hit3:+4d})  "
          f"{pct(a0.exact, a0.n):5.1f}→{pct(a1.exact, a1.n):5.1f}  "
          f"{roi(a0.ret, a0.cost):6.1f}→{roi(a1.ret, a1.cost):6.1f}  "
          f"{a0.pts / a0.n:4.1f}→{a1.pts / a1.n:4.1f}")


def main():
    print('堅帯だけ③ holdout (本番未変更)', flush=True)
    payout = load_trifecta_payouts()
    from scripts import csv_data as cd
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

    cells = defaultdict(lambda: {'cur': Agg(), 't3': Agg()})
    n_done = 0
    for rk, g in h.groupby('race_key', sort=False):
        rk = str(rk)
        if rk not in payout or len(g) < MIN_HORSES:
            continue
        jyo = int(g['jyo'].iloc[0])
        if not (1 <= jyo <= 10):
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
        horses = build_horses(rows)
        if len(horses) < 3:
            continue
        keep = elim_keep(rows, kigo, is_handi)
        horses_elim = [x for x in horses if x['umaban'] in keep]
        elim_ok = len(horses_elim) >= 3 and all(u in keep for u in win)

        bf = te.formation_for_arare(ap)
        band = bf[0] if bf else 'none'
        pb = pay_band(pay)
        r0 = te.recommend_trifecta(
            horses, axis_umaban=ninki_axis(horses, 2), n_points=30, arare_prob=ap)
        r1 = rec_tight3(horses, ap)
        e0, e1 = eval_result(r0, win), eval_result(r1, win)

        keys = [
            f'full|{per}|ALL|{band}',
            f'full|{per}|{pb}|{band}',
            f'full|{per}|le70k|{band}' if pay <= PAY_HI else f'full|{per}|gt70k|{band}',
            f'full|ALL|ALL|{band}',
            f'full|ALL|{pb}|ALL',
            f'full|ALL|le70k|ALL' if pay <= PAY_HI else f'full|ALL|gt70k|ALL',
            f'full|ALL|ALL|ALL',
            f'full|{per}|ALL|ALL',
        ]
        if pay <= PAY_HI:
            keys.append(f'full|ALL|le70k|{band}')
            keys.append(f'full|{per}|le70k|ALL')
        for k in keys:
            cells[k]['cur'].add(e0, pay)
            cells[k]['t3'].add(e1, pay)

        if elim_ok:
            r0e = te.recommend_trifecta(
                horses_elim, axis_umaban=ninki_axis(horses_elim, 2),
                n_points=30, arare_prob=ap)
            r1e = rec_tight3(horses_elim, ap)
            e0e, e1e = eval_result(r0e, win), eval_result(r1e, win)
            ek = [f'elim|ALL|ALL|ALL']
            if pay <= PAY_HI:
                ek += [f'elim|ALL|le70k|ALL', f'elim|ALL|le70k|{band}']
            ek.append(f'elim|ALL|ALL|{band}')
            for k in ek:
                cells[k]['cur'].add(e0e, pay)
                cells[k]['t3'].add(e1e, pay)

        n_done += 1
        if n_done % 500 == 0:
            print(f'  ... {n_done}R', flush=True)

    print(f'\n走査 {n_done}R')
    print('列: Hit3% 現行→堅帯③ (差R) / 厳密% / 回収% / 点/R')
    print('\n=== 全頭 ===')
    print_row('全体', cells['full|ALL|ALL|ALL']['cur'], cells['full|ALL|ALL|ALL']['t3'])
    print_row('2025 holdout', cells['full|2025|ALL|ALL']['cur'], cells['full|2025|ALL|ALL']['t3'])
    print_row('2026', cells['full|2026|ALL|ALL']['cur'], cells['full|2026|ALL|ALL']['t3'])
    print('\n=== 全頭 × 帯 (③は堅帯だけ変わるはず) ===')
    for b in ('tight', 'mid', 'arare', 'none'):
        print_row(f'帯={b}', cells[f'full|ALL|ALL|{b}']['cur'], cells[f'full|ALL|ALL|{b}']['t3'])
    print('\n=== 全頭 × 払戻 ===')
    print_row('≤7万', cells['full|ALL|le70k|ALL']['cur'], cells['full|ALL|le70k|ALL']['t3'])
    print_row('≤7万×堅帯', cells['full|ALL|le70k|tight']['cur'], cells['full|ALL|le70k|tight']['t3'])
    print_row('0-3万', cells['full|ALL|0-3万|ALL']['cur'], cells['full|ALL|0-3万|ALL']['t3'])
    print_row('3-7万', cells['full|ALL|3-7万|ALL']['cur'], cells['full|ALL|3-7万|ALL']['t3'])
    print_row('7万超', cells['full|ALL|gt70k|ALL']['cur'], cells['full|ALL|gt70k|ALL']['t3'])
    print('\n=== 2025 holdout 詳細 ===')
    print_row('2025 全体', cells['full|2025|ALL|ALL']['cur'], cells['full|2025|ALL|ALL']['t3'])
    print_row('2025 ≤7万', cells['full|2025|le70k|ALL']['cur'], cells['full|2025|le70k|ALL']['t3'])
    print_row('2025 堅帯', cells['full|2025|ALL|tight']['cur'], cells['full|2025|ALL|tight']['t3'])
    print('\n=== 消去で3頭残 ===')
    print_row('elim 全体', cells['elim|ALL|ALL|ALL']['cur'], cells['elim|ALL|ALL|ALL']['t3'])
    print_row('elim ≤7万', cells['elim|ALL|le70k|ALL']['cur'], cells['elim|ALL|le70k|ALL']['t3'])
    print_row('elim ≤7万×堅帯', cells['elim|ALL|le70k|tight']['cur'], cells['elim|ALL|le70k|tight']['t3'])
    print('\n中庸・荒れのHit3差が0なら、切り替えは堅帯だけに効いている。')


if __name__ == '__main__':
    main()
