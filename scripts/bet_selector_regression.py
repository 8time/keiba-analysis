# -*- coding: utf-8 -*-
"""旧 live（zone のみ）vs bet_selector_v1 回帰比較。

ルール再調整はしない。phase2 と同じ build_races 母集団で比較する。
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from core import bettype_selector as bts
from scripts.bettype_selector_phase2 import (
    TRAIN_END_DAY, build_races, load_payouts, agg_single, eval_rule,
)

HOLDOUT_START = 20240101


def pick_old_live(r):
    if r['zone'] == 'D':
        return 'trio'
    if r['zone'] == 'C':
        return 'trifecta_rrr'
    return None


def pick_new_selector(r):
    bt = bts.select_bet_type(r['zone'], r['cross_n'])
    if bt == bts.BET_TRIO:
        return 'trio'
    if bt == bts.BET_TRIFECTA:
        return 'trifecta_rrr'
    return None


def bet_key(kind):
    if kind == 'trio':
        return 'trio'
    if kind == 'trifecta_rrr':
        return 'trifecta_rrr'
    return None


def summarize_rows(rows, picker, label):
    sub = [r for r in rows if picker(r)]
    if not sub:
        print(f'\n=== {label} === (対象0)')
        return
    kinds = {}
    for r in sub:
        k = picker(r)
        kinds[k] = kinds.get(k, 0) + 1
    e = eval_rule(sub, lambda r, p=picker: p(r))
    print(f'\n=== {label} ===')
    print(f"  対象レース数: {len(sub)}")
    print(f"  券種内訳: {kinds}")
    print(f"  3連複件数: {kinds.get('trio', 0)}")
    print(f"  3連単件数: {kinds.get('trifecta_rrr', 0)}")
    print(f"  見送り件数: {len(rows) - len(sub)}")
    if e:
        print(f"  推奨投資額(平均/レース): {e.get('avg_cost', 0):.0f}円")
        print(f"  ROI: {e['roi']:.1f}%  的中率: {e['hit_rate']:.1f}%")
        print(f"  CI95: {e['roi_lo95']:.1f}-{e['roi_hi95']:.1f}%")
    by_year = {}
    for r in sub:
        y = r['year']
        by_year.setdefault(y, []).append(r)
    print('  年別ROI:')
    for y in sorted(by_year):
        ey = eval_rule(by_year[y], lambda r, p=picker: p(r))
        if ey:
            print(f"    {y}: n={ey['n']} ROI={ey['roi']:.1f}% 的中={ey['hit_rate']:.1f}%")


def main():
    print('bet_selector_v1 回帰: 旧live vs 新selector')
    print(f'ルール版: {bts.SELECTOR_RULE_VERSION}')
    print('旧live: D→3連複 / C→3連単RRR固定')
    print('新selector: D→3連複 / C+cross≥3→3連複 / C+cross<3→3連単RRR / BA除外')
    pall = load_payouts()
    rows = build_races(pall)
    hold = [r for r in rows if r['day'] >= HOLDOUT_START]
    print(f'\nholdout races (day>={HOLDOUT_START}): {len(hold)}')
    summarize_rows(hold, pick_old_live, '旧 live')
    summarize_rows(hold, pick_new_selector, '新 selector')
    c_hold = [r for r in hold if r['zone'] == 'C']
    c_trio_new = sum(1 for r in c_hold if pick_new_selector(r) == 'trio')
    c_tri_new = sum(1 for r in c_hold if pick_new_selector(r) == 'trifecta_rrr')
    print(f'\nC zone 分岐 (holdout): cross<3→3連単 {c_tri_new} / cross≥3→3連複 {c_trio_new}')


if __name__ == '__main__':
    main()
