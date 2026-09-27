# -*- coding: utf-8 -*-
"""購入前スナップショットのスキーマ。結果テーブルとはファイルを分ける。"""
from __future__ import annotations

SNAPSHOT_VERSION = 'forward_snapshot_v2'

# 判断時点だけ。着順・払戻は入れない。
DECISION_FIELDS = (
    'race_id',
    'race_key',
    'captured_at',
    'score_weights',
    'model_versions',
    'rule_version',
    'code_version',
    'horses',          # PastRuns, BattleScore, pop, odds, weight, frame, signals, LTR, VH, proj
    'elim_rows',
    'elim_keep',
    'zone',
    'vscore',
    'cross_n',
    'cross_n_source',
    'playbook_id',
    'bet_type',
    'tickets',
    'skip_reason',
    'gate',
)

RESULT_FIELDS = ('race_id', 'race_key', 'settled_at', 'finish', 'payouts')
