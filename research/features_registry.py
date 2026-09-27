# -*- coding: utf-8 -*-
"""Baseline 再現に使う特徴の出所・リーク注記。"""
from __future__ import annotations

REGISTRY = {
    'vscore': {
        'source': 'data/export/races.csv',
        'producer': 'core.value_scanner.race_value_score (export add_scanner_outputs)',
        'leak': 'pre-race odds only',
    },
    'vh2_score': {
        'source': 'data/export/horse_races.csv',
        'producer': 'value_hunter_recall_v2 OUT_MODEL',
        'leak': 'shift(1) leak-free in export pipeline',
    },
    'ltr_score': {
        'source': 'research/csv_ltr.predict_race_frame',
        'producer': 'data/ltr_model.lgb + CSV inputs matching ltr_meta.json',
        'leak': 'pre-race; not ability_score',
    },
    'projected_score': {
        'source': 'NOT IN CSV / no historical score_cache snapshots',
        'producer': 'app.py _calc_pro_scores (BattleScore base + .score_weights_main.json)',
        'live_weights_nonzero': ['Base', 'Popularity', 'ScoringSignal', 'JPowerTop3'],
        'status': 'NOT_REPRODUCIBLE_HISTORICAL',
        'blockers': [
            'ScoringSignal weight 1.0 requires same-day venue scan; app.py notes backtest impossible',
            'BattleScore/Ogura/Suitability need scraper PastRuns (Rank/Grade/Agari/Date) not in export',
            'data/score_cache has no historical *.full.json / score snapshots for 2016-2024',
        ],
    },
    'elim_keep': {
        'source': 'research/offline_elim.compute_elim_keep',
        'producer': 'core.elim_engine (not elim_n column)',
        'leak': 'pre-race; learning disabled in research',
    },
    'elim_n': {
        'source': 'horse_races.csv',
        'note': 'elim_cross flags count — NOT equal to elim_keep',
    },
    'payout_join': {
        'key': 'race_key',
        'db': 'data/jravan.db payouts(bet_type, combo, payout)',
    },
}
