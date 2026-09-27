# -*- coding: utf-8 -*-
"""Phase B parity gate. Experiments must not start while this is not FULL."""
from __future__ import annotations

# 2026-09-22 audit of app.py _calc_pro_scores + .score_weights_main.json
PARITY = 'PARTIAL'
PROJECTED_SCORE = 'NOT_REPRODUCIBLE'
HOLDOUT_EVAL_ALLOWED = False
EXPERIMENTS_ALLOWED = False

STOP_REASON = (
    'Live Projected Score is app.py weighted blend, not CSV ability_score. '
    'Current weights include ScoringSignal (same-day scan, no historical store) '
    'and BattleScore from scraped PastRuns. No leak-free historical rebuild.'
)


def experiments_allowed() -> bool:
    return EXPERIMENTS_ALLOWED and PARITY == 'FULL' and PROJECTED_SCORE == 'REPRODUCIBLE'


def assert_split_day_allowed(day: int, *, allow_holdout: bool = False) -> str:
    """Return split name. Raise if holdout is requested while forbidden."""
    from research.splits import split_for_day
    name = split_for_day(day)
    if name == 'holdout' and not allow_holdout and not HOLDOUT_EVAL_ALLOWED:
        raise PermissionError(f'HOLDOUT access forbidden (day={day})')
    return name
