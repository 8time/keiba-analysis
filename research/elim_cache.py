# -*- coding: utf-8 -*-
"""elim_keep 計算結果のディスクキャッシュ（JSONL）。"""
from __future__ import annotations

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_ROOT, 'data', 'research', 'elim_keep_cache.jsonl')


def cache_path() -> str:
    return _CACHE_PATH


def load_cache() -> dict[str, set[int]]:
    if not os.path.exists(_CACHE_PATH):
        return {}
    out = {}
    with open(_CACHE_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            out[str(o['race_key'])] = set(int(x) for x in o['keep'])
    return out


def append_race(race_key: str, keep: set[int]) -> None:
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    with open(_CACHE_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'race_key': str(race_key), 'keep': sorted(keep)},
                           ensure_ascii=False) + '\n')


def rebuild_from_lines() -> dict[str, set[int]]:
    return load_cache()
