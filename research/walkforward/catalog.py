# -*- coding: utf-8 -*-
"""B5 事前登録カタログ。TEST を見て増やさない。

VH_TOP2_POP6_WIN_V1 は FAILED reference。促進対象にしない。
"""
from __future__ import annotations

FAILED_REFERENCE = 'vh_rank2_ninki_ge6'

# (rule_id, family)
RULES = [
    ('fav', 'popularity'),
    ('vh_top', 'VH'),
    ('ability_top', 'ability'),
    ('h7_top', 'ability'),
    ('spurt_top', 'spurt'),
    ('jockey_top', 'jockey'),
    ('trainer_top', 'trainer'),
    ('prior_top3_top', 'ability'),
    ('elim_le1_ninki_le3', 'elim'),
    ('vh_rank2_ninki_ge6', 'VH'),
    ('fav_odds_ge3', 'odds'),
    ('fav_field_le12', 'field_size'),
    ('fav_fillies', 'sex_restriction'),
    ('fav_dirt', 'surface'),
    ('fav_turf', 'surface'),
    ('fav_sprint', 'distance'),
    ('fav_vscore_lt50', 'zone'),
    ('fav_vscore_50_70', 'zone'),
    ('fav_entropy_hi', 'odds_entropy'),
    ('fav_mean_elim_hi', 'elim'),
    ('fav_age_le3', 'age'),
]

FOLDS = [
    ('WF1', 20160101, 20191231, 20200101, 20201231),
    ('WF2', 20160101, 20201231, 20210101, 20211231),
    ('WF3', 20160101, 20211231, 20220101, 20221231),
    ('WF4', 20160101, 20221231, 20230101, 20231231),
    ('WF5', 20160101, 20231231, 20240101, 20241231),
    ('WF6', 20160101, 20241231, 20250101, 20251231),
]

# 2026 は選択に使わない（既観測・途中年度）。
SELECT_MAX_DAY = 20251231

# 促進条件（TEST を見る前に固定）
MIN_TEST_YEARS = 4
MIN_TEST_N = 80
MIN_YEARS_ROI_100 = 4
WORST_ROI_FLOOR = 80.0
BH_Q = 0.10
