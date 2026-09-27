# -*- coding: utf-8 -*-
"""SRA の DataFrame から判断スナップショットを作る。列が無ければ欠測のまま。"""
from __future__ import annotations

import pandas as pd

from research.forward.snapshot import capture_decision


def _col(df, name):
    return df[name] if name in df.columns else None


def _as_int(value):
    try:
        if value is None or value != value:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _rank_map(scores: dict) -> dict:
    ordered = sorted(
        ((u, s) for u, s in (scores or {}).items() if s is not None),
        key=lambda x: -float(x[1]),
    )
    return {u: i + 1 for i, (u, _) in enumerate(ordered)}


def capture_sra(race_id, df, extra: dict | None = None) -> None:
    extra = extra or {}
    ltr_scores = extra.get('ltr_scores') or {}
    vh_scores = extra.get('vh_scores') or {}
    ltr_rank = _rank_map(ltr_scores)
    vh_rank = _rank_map(vh_scores)
    horses = []
    if df is not None and not df.empty and 'Umaban' in df.columns:
        for _, row in df.iterrows():
            um = _as_int(row.get('Umaban'))
            horses.append({
                'umaban': row.get('Umaban'),
                'name': row.get('Name'),
                'popularity': row.get('Popularity'),
                'decision_time_popularity': row.get('Popularity'),
                'decision_time_odds': row.get('Odds'),
                'odds_source': 'core.scraper shutuba/API odds at SRA time',
                'final_odds': None,
                'ltr_score': None if um is None else ltr_scores.get(um, row.get('LTR')),
                'ltr_rank': None if um is None else ltr_rank.get(um),
                'vh_score': None if um is None else vh_scores.get(um),
                'vh_rank': None if um is None else vh_rank.get(um),
                'weight_history': row.get('WeightHistory'),
                'waku': row.get('Waku'),
                'battle_score': row.get('BattleScore'),
                'projected_score': row.get('Projected Score'),
                'ltr': row.get('LTR'),
                'past_runs': row.get('PastRuns'),
                'jockey': row.get('Jockey'),
                'signal': row.get('Signal'),
            })
    capture_decision({
        'odds_source': 'netkeiba_shutuba_scrape',
        'gate': extra.get('gate'),
        'ltr_rank_note': 'ranks stored per horse when scores are passed',
        'race_id': str(race_id),
        'race_key': str(race_id),
        'rule_version': extra.get('rule_version') or 'live_sra_observe',
        'score_weights': extra.get('score_weights'),
        'model_versions': extra.get('model_versions'),
        'zone': extra.get('zone'),
        'vscore': extra.get('vscore'),
        'cross_n': extra.get('cross_n'),
        'playbook_id': extra.get('playbook_id'),
        'bet_type': extra.get('bet_type'),
        'tickets': extra.get('tickets'),
        'skip_reason': extra.get('skip_reason'),
        'gate': extra.get('gate'),
        'elim_keep': extra.get('elim_keep'),
        'elim_rows': extra.get('elim_rows'),
        'horses': horses,
    })
    del pd
