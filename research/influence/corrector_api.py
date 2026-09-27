# -*- coding: utf-8 -*-
"""Research-only contract for a frozen top3 residual corrector.

Not imported by app.py. Historical odds in the research fit are final odds.
A forward call must pass decision-time popularity and decision-time odds.
"""
from __future__ import annotations

INDEPENDENT_FEATURES = (
    'vh2_score', 'ability_inv', 'h7_fig', 'spurt_mean3', 'prior_top3_rate',
    'jockey_jyo_win', 'trainer_jyo_t3', 'elim_inv',
)


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    from math import log
    return log(p / (1 - p))
