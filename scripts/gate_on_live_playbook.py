# -*- coding: utf-8 -*-
"""N3: ゲートを現行 Rule B 券に掛け直す。

Usage: python scripts/gate_on_live_playbook.py
"""
import io
import math
import os
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import hitrate_common as hc

S_LEVELS = (100, 50, 30, 20, 10, 5)
GATE_FEATURES = ['mean_elim', 'n_elim3', 'odds_entropy', 'field_size', 'vscore']
ROI_FLOOR = hc.ROI_FLOOR_DEFAULT


def eval_subset(df, s_pct):
    n = len(df)
    if n == 0:
        return None
    k = max(1, int(math.ceil(n * s_pct / 100.0)))
    sub = df.iloc[:k]
    stake = sub['cost'].sum()
    payout = sub['ret'].sum()
    hits = int(sub['hit'].sum())
    roi = payout / stake * 100 if stake else 0.0
    hit_rate = hits / len(sub) * 100
    cost_per_hit = stake / hits if hits else float('nan')
    return {
        'n_races': len(sub),
        'hit_rate': hit_rate,
        'roi': roi,
        'loss_per_100': 100.0 - roi,
        'cost_per_hit': cost_per_hit,
        'max_losing_streak': hc.max_losing_streak(sub['hit'].tolist()),
        'purchase_rate': len(sub) / n * 100,
        'recs': sub.to_dict('records'),
    }


def ci_overlap(recs_a, recs_b):
    lo_a, hi_a = hc.block_ci_roi(recs_a)
    lo_b, hi_b = hc.block_ci_roi(recs_b)
    return not (hi_a < lo_b or hi_b < lo_a)


def build_race_rows(races, pall_tri, pall_tri_o):
    rows = []
    skipped = 0
    for race in races:
        pb = hc.rule_b_playbook(race)
        kind, tix = hc.live_tickets(race, pb)
        if not tix:
            skipped += 1
            continue
        pall = pall_tri_o if kind == '3連単' else pall_tri
        sc = hc.score_race(tix, kind, race['top3'], pall.get(race['rk']))
        rows.append({
            'rk': race['rk'], 'day': race['day'], 'zone': race['zone'],
            'cost': sc['cost'], 'ret': sc['ret'], 'hit': sc['hit'],
            **{k: race['gate'].get(k) for k in GATE_FEATURES},
        })
    return pd.DataFrame(rows), skipped


def eval_zone_gate(df, zone, feature, direction, roi_floor=ROI_FLOOR):
    sub = df[df['zone'] == zone].copy()
    if sub.empty:
        return []
    sub = sub.dropna(subset=[feature])
    if sub.empty:
        return []
    asc = direction == 'asc'
    sub = sub.sort_values(feature, ascending=asc).reset_index(drop=True)
    base = eval_subset(sub, 100)
    base_recs = [{'day': r['day'], 'cost': r['cost'], 'ret': r['ret'], 'hit': r['hit']}
                 for r in base['recs']]
    results = []
    for s in S_LEVELS:
        ev = eval_subset(sub, s)
        if not ev:
            continue
        recs = [{'day': r['day'], 'cost': r['cost'], 'ret': r['ret'], 'hit': r['hit']}
                for r in ev['recs']]
        overlap = ci_overlap(base_recs, recs) if s < 100 else True
        results.append(dict(
            zone=zone, feature=feature, direction=direction, s=s,
            overlap='あり' if overlap else 'なし',
            **{k: ev[k] for k in ('n_races', 'hit_rate', 'roi', 'loss_per_100',
                                   'cost_per_hit', 'max_losing_streak', 'purchase_rate')},
        ))
    return results


def main():
    races = [r for r in hc.build_races() if r['period'] == 'holdout']
    pall_tri = hc.load_payouts('3連複')
    pall_tri_o = hc.load_payouts('3連単')
    df, skipped = build_race_rows(races, pall_tri, pall_tri_o)
    print(f'holdout レース {len(races)} / 券組み可 {len(df)} / 見送り相当 {skipped}')

    all_rows = []
    for zone in ('D', 'C'):
        for feat in GATE_FEATURES:
            for direction in ('desc', 'asc'):
                all_rows.extend(eval_zone_gate(df, zone, feat, direction))

    print('\nzone | 特徴 | 方向 | s | n | 的中率 | ROI | 損失/100 | 投資/1的中 | 連敗 | 購入率 | CI重なり')
    print('-' * 100)
    for r in all_rows:
        cph = f"{r['cost_per_hit']:.0f}" if r['cost_per_hit'] == r['cost_per_hit'] else '—'
        print(
            f"{r['zone']} | {r['feature']} | {r['direction']} | {r['s']} | {r['n_races']} | "
            f"{r['hit_rate']:.1f}% | {r['roi']:.1f}% | {r['loss_per_100']:.1f} | {cph} | "
            f"{r['max_losing_streak']} | {r['purchase_rate']:.1f}% | {r['overlap']}"
        )

    good = [r for r in all_rows if r['s'] < 100 and r['hit_rate'] > next(
        (x['hit_rate'] for x in all_rows
         if x['zone'] == r['zone'] and x['feature'] == r['feature']
         and x['direction'] == r['direction'] and x['s'] == 100), 0)
        and r['roi'] >= ROI_FLOOR]
    ci_strict = [r for r in good if r['overlap'] == 'なし']
    print(
        f"\n的中率が s=100 より上がり、かつ ROI が下限{ROI_FLOOR}%以上のセル: "
        f"{len(good)} 件。CI が s=100 と重ならないもの: {len(ci_strict)} 件"
    )
    if not good:
        print('該当セルは 0 件')

    sections = [
        '## 対象', 'holdout 2024+、Rule B 現行券',
        f'## 見送り', f'券が組めないレース {skipped} 件（分母外）',
        '## 結論',
        (
            f"的中率↑かつ ROI≥{ROI_FLOOR}%: {len(good)} 件。"
            f" CI非重なり: {len(ci_strict)} 件。"
        ),
    ]
    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_gate_on_live_playbook.md')
    hc.write_memo(memo, 'verified_gate_on_live_playbook', 'N3 ゲート×現行プレイブック', sections)
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
