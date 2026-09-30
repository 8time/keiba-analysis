# -*- coding: utf-8 -*-
"""Join key between Forward Collector decisions and Prediction Time Machine.

Does not change prediction math or GREEN rules. Append-only link log.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DIR = os.path.join(_ROOT, 'data', 'research', 'forward')
_LINKS = os.path.join(_DIR, 'ptm_links.jsonl')


def record_link(race_id, analysis_run_id, *, ptm_snapshot_id=None,
                forward_captured_at=None, directory: str | None = None) -> dict:
    """One row tying race + analysis run to optional snapshot ids."""
    if not race_id or not analysis_run_id:
        raise ValueError('race_id and analysis_run_id required')
    base = directory or _DIR
    os.makedirs(base, exist_ok=True)
    row = {
        'record_kind': 'ptm_forward_link',
        'linked_at': datetime.now(timezone.utc).isoformat(),
        'race_id': str(race_id),
        'analysis_run_id': str(analysis_run_id),
        'ptm_snapshot_id': ptm_snapshot_id,
        'forward_captured_at': forward_captured_at,
    }
    path = os.path.join(base, 'ptm_links.jsonl')
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


def links_for(race_id, analysis_run_id=None, directory: str | None = None) -> list[dict]:
    path = os.path.join(directory or _DIR, 'ptm_links.jsonl')
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get('race_id')) != str(race_id):
                continue
            if analysis_run_id and str(row.get('analysis_run_id')) != str(analysis_run_id):
                continue
            out.append(row)
    return out
