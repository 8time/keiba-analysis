# -*- coding: utf-8 -*-
"""N6: 消去該当Rank末列の入替を McNemar 検定。

Usage: python scripts/elim_swap_paired_test.py
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import hitrate_common as hc


def is_elim_target(elim_n, ninki):
    if elim_n is None:
        return False
    try:
        elim_n = int(elim_n)
        ninki = int(ninki)
    except (TypeError, ValueError):
        return False
    if elim_n >= 3 and ninki >= 6:
        return True
    if elim_n >= 5 and ninki <= 5:
        return True
    return False


def swap_last(rank, elim_map, ninki_map, last_idx, search_from):
    rank = list(rank)
    if len(rank) <= last_idx:
        return rank, False
    u = rank[last_idx]
    if not is_elim_target(elim_map.get(u), ninki_map.get(u, 99)):
        return rank, False
    for j in range(search_from, min(len(rank), 10)):
        u2 = rank[j]
        if not is_elim_target(elim_map.get(u2), ninki_map.get(u2, 99)):
            rank[last_idx], rank[j] = rank[j], rank[last_idx]
            return rank, True
    return rank, False


def eval_cell(races, cell, pall_tri, pall_tri_o):
    base_hits, test_hits = [], []
    recs_base, recs_test = [], []
    swapped = 0
    eligible = 0
    for race in races:
        if race['zone'] != 'C':
            continue
        if cell == 'tri' and race['cross_n'] >= 3:
            continue
        if cell == 'trio' and race['cross_n'] < 3:
            continue
        rank = list(race['rank_ord'])
        if cell == 'tri':
            if len(rank) < 7:
                continue
            last_idx, search_from = 6, 7
            pb = hc.PLAYBOOK_C_TRI
        else:
            if len(rank) < 6:
                continue
            last_idx, search_from = 5, 6
            pb = hc.PLAYBOOK_C_TRIO

        rank_sw, did = swap_last(rank, race['elim_map'], race['ninki_map'],
                                 last_idx, search_from)
        if is_elim_target(race['elim_map'].get(rank[last_idx]),
                          race['ninki_map'].get(rank[last_idx], 99)):
            eligible += 1
        if did:
            swapped += 1

        r_base = dict(race, rank_ord=rank)
        r_test = dict(race, rank_ord=rank_sw)
        kind_b, tix_b = hc.live_tickets(r_base, pb)
        kind_t, tix_t = hc.live_tickets(r_test, pb)
        if not tix_b or not tix_t:
            continue
        pall = pall_tri_o if kind_b == '3連単' else pall_tri
        sc_b = hc.score_race(tix_b, kind_b, race['top3'], pall.get(race['rk']))
        sc_t = hc.score_race(tix_t, kind_t, race['top3'], pall.get(race['rk']))
        base_hits.append(sc_b['hit'])
        test_hits.append(sc_t['hit'])
        base = dict(day=race['day'], year=race['year'], rk=race['rk'], **sc_b)
        test = dict(day=race['day'], year=race['year'], rk=race['rk'], **sc_t)
        recs_base.append(base)
        recs_test.append(test)

    s_base = hc.summarise(recs_base)
    s_test = hc.summarise(recs_test)
    mcn = hc.mcnemar(base_hits, test_hits)
    swap_pct = swapped / eligible * 100 if eligible else 0.0
    return s_base, s_test, mcn, swapped, eligible, swap_pct


def print_period(label, cell, s_base, s_test, mcn, swapped, eligible, swap_pct):
    cname = '3連単2-4-7' if cell == 'tri' else '3連複2-3-6'
    print(f'\n=== {label} / {cname} ===')
    print('候補 | 券種 | 点 | n | 的中率 | ROI | 損失/100円 | 投資/1的中 | 最大連敗 | ROI 95%CI | 年別')
    print(hc.fmt_row('基準', cname, s_base['avg_pts'], s_base))
    print(hc.fmt_row('入替', cname, s_test['avg_pts'], s_test))
    print(f'入替発生: {swapped}/{eligible} ({swap_pct:.1f}%)')
    print(f"McNemar b={mcn['b']} c={mcn['c']} z={mcn['z']:.3f} p={mcn['p']:.4f}")
    return mcn, s_base, s_test


def main():
    races = hc.build_races(zones=('C',))
    pall_tri = hc.load_payouts('3連複')
    pall_tri_o = hc.load_payouts('3連単')

    results = {}
    for cell in ('tri', 'trio'):
        tr = eval_cell([r for r in races if r['period'] == 'train'], cell, pall_tri, pall_tri_o)
        ho = eval_cell([r for r in races if r['period'] == 'holdout'], cell, pall_tri, pall_tri_o)
        print_period('train', cell, *tr)
        mcn_h, sb_h, st_h = print_period('holdout', cell, *ho)
        results[cell] = dict(train=tr, holdout=ho, mcn_h=mcn_h, sb_h=sb_h, st_h=st_h)

    for cell in ('tri', 'trio'):
        mcn_tr = results[cell]['train'][2]
        mcn_ho = results[cell]['mcn_h']
        sb, st = results[cell]['sb_h'], results[cell]['st_h']
        same_sign = (mcn_tr['z'] == 0 or mcn_ho['z'] == 0 or
                     (mcn_tr['z'] > 0) == (mcn_ho['z'] > 0))
        roi_diff = st['roi'] - sb['roi']
        ok = abs(mcn_ho['z']) >= 1.96 and same_sign and roi_diff >= -2.0
        print(
            f"\n{cell} holdout: 入替のみ的中 c={mcn_ho['c']} / 基準のみ的中 b={mcn_ho['b']}、"
            f"z={mcn_ho['z']:.3f}。train も同符号: {'はい' if same_sign else 'いいえ'}。"
            f" ROI 差 {roi_diff:+.1f}pp。"
            f" 条件充足(z≥1.96 & train同符号 & ROI差≥-2pp): {'はい' if ok else 'いいえ'}"
        )

    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_elim_swap_paired.md')
    lines = ['## N6 消去入替 McNemar']
    for cell in ('tri', 'trio'):
        m = results[cell]['mcn_h']
        sb, st = results[cell]['sb_h'], results[cell]['st_h']
        lines.append(
            f"- {cell}: holdout b={m['b']} c={m['c']} z={m['z']:.3f}, "
            f"ROI {sb['roi']:.1f}%→{st['roi']:.1f}%"
        )
    hc.write_memo(memo, 'verified_elim_swap_paired', 'N6 消去Rank入替ペア検定', lines)
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
