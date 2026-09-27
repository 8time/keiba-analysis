# -*- coding: utf-8 -*-
"""ライブ判断時点の観測保存。戦略の戻り値は変えない。Phase A ledger は触らない。"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from research.forward.schema import SNAPSHOT_VERSION

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DIR = os.path.join(_ROOT, 'data', 'research', 'forward')
_DECISIONS = os.path.join(_DIR, 'decisions.jsonl')
_RESULTS = os.path.join(_DIR, 'results.jsonl')


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=_ROOT, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return 'unknown'


def capture_decision(payload: dict, directory: str | None = None) -> None:
    """判断に使った入力と出力だけを追記する。finish/payout キーは拒否。"""
    banned = {'finish', 'chakujun', 'payout', 'payouts', 'won'}
    bad = banned & set(payload)
    if bad:
        raise ValueError(f'decision snapshot must not contain {sorted(bad)}')
    base = directory or _DIR
    os.makedirs(base, exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()
    row = {
        'snapshot_version': SNAPSHOT_VERSION,
        'captured_at': captured,
        'odds_snapshot_timestamp': payload.get('odds_snapshot_timestamp') or captured,
        'code_version': payload.get('code_version') or _git_rev(),
        'record_kind': 'decision',
        **{k: payload.get(k) for k in payload if k not in banned},
    }
    with open(os.path.join(base, 'decisions.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')


def append_result(race_id: str, race_key: str, finish, payouts, directory: str | None = None,
                  final_odds=None, refund_status=None) -> None:
    """結果は別ファイル。判断 JSONL には書かない。"""
    base = directory or _DIR
    os.makedirs(base, exist_ok=True)
    row = {
        'record_kind': 'result',
        'race_id': str(race_id),
        'race_key': str(race_key),
        'settled_at': datetime.now(timezone.utc).isoformat(),
        'finish': finish,
        'payouts': payouts,
        'final_odds': final_odds,
        'refund_status': refund_status,
    }
    with open(os.path.join(base, 'results.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
