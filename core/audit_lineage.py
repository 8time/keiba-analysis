# -*- coding: utf-8 -*-
"""購入・snapshot の race/run/recommendation 所属検証（共通）。"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from core import audit_pipeline as ap
from core import audit_store

def resolve_analysis_run_for_purchase(
    store: audit_store.AuditStore,
    purchase_race_id: str,
    analysis_run_id: Optional[str],
    recommendation_id: Optional[str],
    recommendation_id_explicit: bool,
    session,
) -> Tuple[Optional[str], Optional[str]]:
    """run 新規作成なし。明示参照は存在検証を先に行う。"""
    rid = str(purchase_race_id or '').strip()
    if recommendation_id_explicit and recommendation_id:
        ev = store.get_event(recommendation_id)
        if not ev:
            return None, 'recommendation_not_found'
        run_id = str(ev.get('analysis_run_id') or '')
        session_run = ap.current_run_id(rid, session=session)
        if session_run and str(session_run) != run_id:
            return None, 'analysis_run_mismatch'
        if analysis_run_id and str(analysis_run_id) != run_id:
            return None, 'analysis_run_mismatch'
        ok, err, _ = validate_purchase_lineage(
            store, rid, run_id, recommendation_id)
        if not ok:
            return None, err
        return run_id, None
    if analysis_run_id:
        ok, err, _ = validate_purchase_lineage(
            store, rid, str(analysis_run_id), None)
        if not ok:
            return None, err
        return str(analysis_run_id), None
    run_id = ap.current_run_id(rid, session=session)
    if not run_id:
        return None, 'no_analysis_run_for_purchase'
    ok, err, _ = validate_purchase_lineage(store, rid, run_id, None)
    if not ok:
        return None, err
    return run_id, None


def validate_purchase_lineage(
    store: audit_store.AuditStore,
    purchase_race_id: str,
    analysis_run_id: str,
    recommendation_id: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[dict]]:
    """購入 race / run / recommendation の所属を検証。"""
    rid = str(purchase_race_id or '').strip()
    run_id = str(analysis_run_id or '').strip()
    if not rid:
        return False, 'race_id_empty', None
    if not run_id:
        return False, 'no_analysis_run', None
    run = store.get_analysis_run(run_id)
    if not run:
        return False, 'analysis_run_not_found', None
    if str(run.get('race_id') or '') != rid:
        return False, 'analysis_run_race_mismatch', None
    if not recommendation_id:
        return True, None, None
    ev = store.get_event(recommendation_id)
    if not ev:
        return False, 'recommendation_not_found', None
    if ev.get('stage') != 'recommendation':
        return False, 'not_recommendation_stage', None
    if str(ev.get('race_id') or '') != rid:
        return False, 'race_id_mismatch', None
    if str(ev.get('analysis_run_id') or '') != run_id:
        return False, 'analysis_run_mismatch', None
    return True, None, ev


def resolve_purchase_recommendation(
    store: audit_store.AuditStore,
    purchase_race_id: str,
    analysis_run_id: str,
    recommendation_id: Optional[str],
    recommendation_id_explicit: bool,
    session_hint_from_session: Optional[str],
) -> Tuple[Optional[str], Optional[dict], Optional[str]]:
    """明示 / session hint / latest いずれも同一 lineage 検証。"""
    rid = str(purchase_race_id or '').strip()
    run_id = str(analysis_run_id or '').strip()
    ok, err, _ = validate_purchase_lineage(store, rid, run_id, None)
    if not ok:
        return None, None, err
    if recommendation_id_explicit and recommendation_id:
        ok, err, ev = validate_purchase_lineage(
            store, rid, run_id, recommendation_id)
        if not ok:
            return None, None, err
        return recommendation_id, ev, None
    hint = None if recommendation_id_explicit else (
        recommendation_id or session_hint_from_session)
    if hint:
        ok, err, ev = validate_purchase_lineage(store, rid, run_id, hint)
        if not ok:
            return None, None, err
        return hint, ev, None
    rec_id, rec_ev = ap.latest_recommendation_for_run(store, run_id)
    if not rec_id:
        return None, None, 'no_recommendation_for_run'
    ok, err, ev = validate_purchase_lineage(store, rid, run_id, rec_id)
    if not ok:
        return None, None, err
    return rec_id, ev or rec_ev, None


def validate_snapshot_event_ids(
    store: audit_store.AuditStore,
    purchase_race_id: str,
    analysis_run_id: str,
    snapshot_event_ids: dict,
) -> Tuple[bool, Optional[str]]:
    """batch 固定 snapshot の event 所属・stage を検証。"""
    from core.audit_snapshot import SNAPSHOT_NOT_RUN

    rid = str(purchase_race_id or '').strip()
    run_id = str(analysis_run_id or '').strip()
    if not rid or not run_id:
        return False, 'snapshot_lineage_incomplete'
    chain = ap._parent_run_chain(store, run_id)
    chain_set = set(chain)
    snap = snapshot_event_ids or {}
    slot_expected_stage = {
        'scanner': 'scanner',
        'scanner_display': 'scanner_display',
    }

    for key, eid in snap.items():
        if not eid or eid == SNAPSHOT_NOT_RUN:
            continue
        ev = store.get_event(eid)
        if not ev:
            return False, f'snapshot_event_missing:{key}'
        ev_stage = str(ev.get('stage') or '')
        if key in slot_expected_stage:
            if ev_stage != slot_expected_stage[key]:
                return False, f'snapshot_stage_mismatch:{key}'
            if str(ev.get('race_id') or '') != rid:
                return False, f'snapshot_race_mismatch:{key}'
            if ev.get('analysis_run_id') not in chain_set:
                return False, f'snapshot_scanner_not_in_parent_chain:{key}'
            continue
        expected = key
        if ev_stage != expected:
            return False, f'snapshot_stage_mismatch:{key}'
        if str(ev.get('race_id') or '') != rid:
            return False, f'snapshot_race_mismatch:{key}'
        if str(ev.get('analysis_run_id') or '') != run_id:
            return False, f'snapshot_run_mismatch:{key}'
    return True, None
