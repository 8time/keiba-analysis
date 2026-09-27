# -*- coding: utf-8 -*-
"""Phase B 標準時系列分割（全研究でこの定義のみを使う）。"""

from __future__ import annotations

BASELINE_VERSION = 'phase_b_baseline_v1'

# day = YYYYMMDD (int)
TRAIN_DAY_FROM = 20160101
TRAIN_DAY_TO = 20231231
VALIDATION_DAY_FROM = 20240101
VALIDATION_DAY_TO = 20241231
HOLDOUT_DAY_FROM = 20250101
# HOLDOUT_DAY_TO = export 最新日（実行時に races.csv から取得）

SPLIT_NAMES = ('train', 'validation', 'holdout', 'other')


def split_for_day(day) -> str:
    """レース日から split 名を返す。"""
    try:
        d = int(day)
    except (TypeError, ValueError):
        return 'other'
    if TRAIN_DAY_FROM <= d <= TRAIN_DAY_TO:
        return 'train'
    if VALIDATION_DAY_FROM <= d <= VALIDATION_DAY_TO:
        return 'validation'
    if d >= HOLDOUT_DAY_FROM:
        return 'holdout'
    return 'other'


def split_doc() -> dict:
    return {
        'baseline_version': BASELINE_VERSION,
        'train': {'from': TRAIN_DAY_FROM, 'to': TRAIN_DAY_TO},
        'validation': {'from': VALIDATION_DAY_FROM, 'to': VALIDATION_DAY_TO},
        'holdout': {'from': HOLDOUT_DAY_FROM, 'to': 'export_latest_day'},
    }
