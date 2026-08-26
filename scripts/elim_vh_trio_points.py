# -*- coding: utf-8 -*-
"""A（残し）と A＋VH網 を候補集合にして、複勝積で10点/15点にしたときの
的中とROI。相手順位は市場（複勝積）のみ。アプリは変更しない。

Usage: python scripts/elim_vh_trio_points.py
"""
import os
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import formation_stats as fs
from core.axis_selector import fuku_rate
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd
from scripts.elim_cross_keep_top3_2026h1 import (
    DAY0, DAY1, _num, flag_counts, hunter_elite_top3, add_rklow_vh,
    edf_rank_and_surv, recommend_n, apply_flow,
)
from scripts.elim_miss1_hunter import hunter_ranks
from scripts.trio_rank10_backtest import load_pays, fuku_of

POINTS = (10, 15)
STAKE = 100.0


def pct(a, b):
    return a / b * 100 if b else 0.0


def top_n_fuku(pool, fk, n):
    ums = list(pool)
    if len(ums) < 3:
        return []
    combos = [frozenset(c) for c in combinations(ums, 3)]

    def score(fs):
        p = 1.0
        for u in fs:
            p *= fk.get(u, 0.01)
        return p

    combos.sort(key=score, reverse=True)
    return combos[:n]


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ])
    h = h[(h['day'] >= DAY0) & (h['day'] <= DAY1)]
    h['jyo'] = h['jyo'].astype(float)
    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))
    vs_map = dict(zip(races['race_key'].astype(str), races['vscore']))
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    # methods: name -> pool builder key
    methods = ('Aだけ', 'A＋主要3枠', 'A＋VH網', '参考:人気1-7')

    # st[zone][method][n_points] = n, cover, hit, cost, ret, pool_sum
    st = defaultdict(lambda: {
        m: {p: dict(n=0, cover=0, hit=0, cost=0.0, ret=0.0, pool=0.0)
            for p in POINTS}
        for m in methods
    })
    skip_pay = 0

    for rk, g in h.groupby('race_key', sort=False):
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3 or len(g) < 5:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if not pay:
            try:
                pay = pays.get(int(rk))
            except (TypeError, ValueError):
                pay = None
        if not pay or pay[0] != win:
            skip_pay += 1
            continue
        payout = pay[1]
        z = fs.ZONE_SHORT.get(fs.zone_of(vs_map.get(str(rk))), '不明')
        rows = g.to_dict('records')
        flags, ninki = flag_counts(rows)
        elite_top3, scored = hunter_elite_top3(rows)
        rk_edf, _surv = edf_rank_and_surv(rows, border=3)
        add_rklow_vh(flags, len(rows), rk_edf, scored)
        order = sorted(flags, key=lambda u: (-flags[u], -ninki.get(u, 0)))
        kigo = kigo_map.get(str(rk), '')
        is_handi = bool(handi_map.get(str(rk), int(_num(g['is_handi1'].iloc[0]) or 0)))
        tgt, _ = recommend_n(rows, kigo, is_handi)
        keep, _, _ = apply_flow(order, tgt, rows, elite_top3, pool=None)
        _lab, elite, net = hunter_ranks(ninki, scored)
        fk = {}
        for r in rows:
            u = int(r['umaban'])
            fk[u] = fuku_of(int(r['ninki']), _num(r.get('win_odds')))
        by_nk = sorted(ninki, key=lambda u: ninki[u])
        pools = {
            'Aだけ': set(keep),
            'A＋主要3枠': set(keep) | set(elite[:2]) | set(net[:1]),
            'A＋VH網': set(keep) | set(elite) | set(net),
            '参考:人気1-7': set(by_nk[:7]),
        }
        for zone_key in (z, '全体'):
            for m, pool in pools.items():
                for npt in POINTS:
                    bets = top_n_fuku(pool, fk, npt)
                    cell = st[zone_key][m][npt]
                    cell['n'] += 1
                    cell['pool'] += len(pool)
                    cell['cost'] += STAKE * len(bets)
                    if win <= pool:
                        cell['cover'] += 1
                    if win in bets:
                        cell['hit'] += 1
                        cell['ret'] += payout

    print(f'配当なし/不一致スキップ {skip_pay}')
    print('1点100円フラット。順位は複勝積のみ。アプリ未変更。')
    print()
    for z in ('D 鉄板', 'C 中庸', 'B/A 荒れ', '全体'):
        print(f'=== {z} ===')
        for npt in POINTS:
            print(f'  -- {npt}点 --')
            print(f'  {"方法":<16} カバー   的中     ROI    平均頭数  カバー内的中')
            for m in methods:
                c = st[z][m][npt]
                n = c['n']
                if not n:
                    continue
                roi = pct(c['ret'], c['cost'])
                cov_hit = pct(c['hit'], c['cover'])
                print(f'  {m:<16} {pct(c["cover"], n):5.1f}%  '
                      f'{pct(c["hit"], n):5.1f}%  {roi:5.1f}%  '
                      f'{c["pool"]/n:5.1f}頭  {cov_hit:5.1f}%'
                      f'  ({c["hit"]}/{n})')
            print()


if __name__ == '__main__':
    main()
