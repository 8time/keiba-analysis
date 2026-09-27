# -*- coding: utf-8 -*-
"""現行本番の推奨を SHADOW として記録する。実購入フラグは立てない。"""
from __future__ import annotations

import hashlib
import json

from research.forward.snapshot import capture_decision


def _weights_version(weights) -> str:
    raw = json.dumps(weights or {}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]


def observe_production(race_id, playbook: dict, extra: dict | None = None, directory: str | None = None) -> None:
    extra = extra or {}
    capture_decision({
        'race_id': str(race_id),
        'race_key': str(race_id),
        'purpose': 'shadow_observation',
        'purchased': False,
        'rule_version': 'production_playbook_observe',
        'weights_version': extra.get('weights_version') or _weights_version(extra.get('score_weights')),
        'zone': (playbook or {}).get('zone') or extra.get('zone'),
        'cross_n': (playbook or {}).get('cross_n'),
        'bet_type': (playbook or {}).get('selected_bet_type'),
        'playbook_id': (playbook or {}).get('selected_playbook'),
        'tickets': extra.get('tickets'),
        'skip_reason': (playbook or {}).get('skip_reason'),
        'gate': extra.get('gate'),
        'horses': extra.get('horses') or [],
    }, directory=directory)
