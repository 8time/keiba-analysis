# -*- coding: utf-8 -*-
"""Phase B Baseline 集計指標。"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

UNIT_STAKE = 100


def max_drawdown(profits_in_order: list[float]) -> float:
    """時系列 profit の累積から最大ドローダウン（正=損失幅）。"""
    if not profits_in_order:
        return 0.0
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in profits_in_order:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return float(max_dd)


def max_losing_streak(hits: list[int]) -> int:
    m = c = 0
    for h in hits:
        c = 0 if h else c + 1
        m = max(m, c)
    return m


def aggregate_race_records(recs: list[dict]) -> dict:
    """レース単位記録の集計。"""
    if not recs:
        return _empty_agg()
    n = len(recs)
    bought = [r for r in recs if r.get('tc', 0) > 0]
    nb = len(bought)
    cost = sum(r.get('cost', 0) for r in bought)
    payout = sum(r.get('ret', 0) for r in bought)
    profit = payout - cost
    hits = sum(r.get('hit', 0) for r in bought)
    hit_races = [r for r in bought if r.get('hit')]
    recover_ok = sum(1 for r in bought if r.get('ret', 0) >= r.get('cost', 0))
    pays = [r['ret'] for r in hit_races if r.get('ret', 0) > 0]
    ordered = sorted(bought, key=lambda x: (x.get('day', 0), x.get('rk', '')))
    pl = [r.get('ret', 0) - r.get('cost', 0) for r in ordered]
    return {
        'races_total': n,
        'races_bet': nb,
        'bet_rate': nb / n if n else 0.0,
        'tickets': sum(r.get('tc', 0) for r in bought),
        'stake': cost,
        'payout': payout,
        'profit': profit,
        'roi': 100.0 * payout / cost if cost else 0.0,
        'hit_races': hits,
        'hit_rate': hits / nb if nb else 0.0,
        'recover_success_rate': recover_ok / nb if nb else 0.0,
        'avg_payout': float(np.mean(pays)) if pays else 0.0,
        'median_payout': float(np.median(pays)) if pays else 0.0,
        'max_drawdown': max_drawdown(pl),
        'max_losing_streak': max_losing_streak([r.get('hit', 0) for r in ordered]),
    }


def _empty_agg():
    return {
        'races_total': 0, 'races_bet': 0, 'bet_rate': 0.0, 'tickets': 0,
        'stake': 0.0, 'payout': 0.0, 'profit': 0.0, 'roi': 0.0,
        'hit_races': 0, 'hit_rate': 0.0, 'recover_success_rate': 0.0,
        'avg_payout': 0.0, 'median_payout': 0.0,
        'max_drawdown': 0.0, 'max_losing_streak': 0,
    }


def group_aggregate(recs: list[dict], key_fn) -> dict:
    buckets = defaultdict(list)
    for r in recs:
        buckets[key_fn(r)].append(r)
    return {k: aggregate_race_records(v) for k, v in sorted(buckets.items())}
