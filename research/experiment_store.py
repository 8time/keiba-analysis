# -*- coding: utf-8 -*-
"""実験台帳（最小版）。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEDGER = os.path.join(_ROOT, 'data', 'research', 'experiments.jsonl')


def append_experiment(record: dict) -> str:
    os.makedirs(os.path.dirname(_LEDGER), exist_ok=True)
    eid = record.get('experiment_id') or datetime.now(timezone.utc).strftime('exp_%Y%m%d_%H%M%S')
    record = dict(record)
    record['experiment_id'] = eid
    record.setdefault('ts_utc', datetime.now(timezone.utc).isoformat())
    with open(_LEDGER, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    return eid
