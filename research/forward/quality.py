# -*- coding: utf-8 -*-
"""Forward snapshot の品質。異常は valid に混ぜない。"""
from __future__ import annotations

REQUIRED = (
    'race_id',
    'captured_at',
    'horses',
)


def classify_decision(row: dict) -> str:
    if not isinstance(row, dict):
        return 'invalid'
    if row.get('record_kind') == 'result':
        return 'invalid'
    for key in ('finish', 'chakujun', 'payout', 'payouts', 'won'):
        if key in row and row.get(key) not in (None, '', [], {}):
            return 'invalid'
    if any(not row.get(k) for k in ('race_id', 'captured_at')):
        return 'invalid'
    horses = row.get('horses') or []
    if not horses:
        return 'partial'
    missing_odds = 0
    for h in horses:
        if h.get('decision_time_odds') in (None, '', 0):
            missing_odds += 1
        if h.get('final_odds') not in (None, ''):
            return 'invalid'
    if missing_odds == len(horses):
        return 'partial'
    if missing_odds:
        return 'partial'
    return 'valid'


def classify_result(row: dict) -> str:
    if not isinstance(row, dict) or row.get('record_kind') != 'result':
        return 'invalid'
    if not row.get('race_id') or row.get('finish') is None:
        return 'partial'
    if not row.get('payouts'):
        return 'partial'
    return 'valid'
