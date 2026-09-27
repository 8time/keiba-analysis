# -*- coding: utf-8 -*-
"""研究用: score_cache.read_scores を差し替えて Projected を elim_engine に渡す。

本番 score_cache.py は変更しない（unittest.mock でパッチ）。
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

_race_proj: dict[str, dict[int, float]] = {}


def set_race_scores(race_id: str, proj: dict[int, float]) -> None:
    _race_proj[str(race_id)] = {int(k): float(v) for k, v in (proj or {}).items()}


def clear_race(race_id: str) -> None:
    _race_proj.pop(str(race_id), None)


def _patched_read_scores(race_id, *args, **kwargs):
    from core import score_cache as sc
    base = sc.read_scores(race_id, *args, **kwargs) or {}
    extra = _race_proj.get(str(race_id))
    if not extra:
        return base or None
    out = dict(base) if base else {}
    for u, p in extra.items():
        out[int(u)] = {'proj': float(p), 'battle': None}
    return out or None


@contextmanager
def patch_score_cache():
    with patch('core.score_cache.read_scores', side_effect=_patched_read_scores):
        yield
