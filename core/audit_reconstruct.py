# -*- coding: utf-8 -*-
"""
フェーズA: 監査記録のみから購入判断を再構成（推測・事後再計算なし）。
"""
from __future__ import annotations

import json
from typing import Optional

from core import audit_review as ar
from core import audit_store
from core import money


def _parse(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or '{}')
    except Exception:
        return {}


def reconstruct_race_story(
    race_id,
    purchase_batch_id=None,
    ledger: Optional[money.Ledger] = None,
    store: Optional[audit_store.AuditStore] = None,
):
    """監査DB + bets から説明用ストーリーを組み立てる。"""
    owned_l = ledger is None
    owned_s = store is None
    lg = ledger or money.Ledger()
    st = store or audit_store.AuditStore()
    rid = str(race_id or '').strip()
    try:
        pre = ar.load_pre_race_snapshot(
            rid, purchase_batch_id=purchase_batch_id, store=st)
        settled = ar.load_settled_result(
            lg, rid,
            purchase_batch_id=purchase_batch_id or '__all__')
        run_id = pre.get('analysis_run_id')
        scanner = pre.get('scanner_payload') or {}
        scanner_display = pre.get('scanner_display_payload') or {}
        elim = pre.get('elim_payload') or {}
        sra = pre.get('sra_payload') or {}
        hunter = pre.get('hunter_payload') or {}
        rec = pre.get('recommendation') or {}

        return {
            'race_id': rid,
            'analysis_run_id': run_id,
            'recommendation_id': pre.get('recommendation_id'),
            'purchase_batch_id': pre.get('purchase_batch_id'),
            'pre_race_status': pre.get('status'),
            'scanner': scanner,
            'scanner_display': scanner_display,
            'elim_before_after': {
                'before': elim.get('before_set') or elim.get('ranked_rows'),
                'after': elim.get('after_set'),
            },
            'sra': sra,
            'anabaka_hunter': hunter,
            'recommendation_lines': rec.get('lines') or [],
            'human_changes': pre.get('diff'),
            'purchased_lines': (pre.get('purchase_batch') or {}).get('lines') or [],
            'settlement': settled,
            'narrative_checks': {
                'has_pre_race': pre.get('status') == 'available',
                'has_recommendation': bool(rec.get('lines')),
                'has_purchase': bool(settled.get('bets')),
                'legacy_bets_only': any(
                    b.get('audit_link') == ar.AUDIT_LINK_LEGACY
                    for b in (settled.get('bets') or [])),
            },
        }
    finally:
        if owned_l:
            lg.close()
        if owned_s:
            st.close()
