# -*- coding: utf-8 -*-
"""
フェーズA: 工程監査・推奨/購入追跡（観測のみ・計算ロジックは変更しない）。

Streamlit session_state に analysis_run_id を race_id 単位で保持する。
推奨は audit_events.stage=recommendation（event_id = recommendation_id）。
実購入は purchase_batches（bets 台帳は購入確定時のみ既存どおり）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from core import audit_store


def _run_key(race_id: str) -> str:
    rid = ''.join(ch for ch in str(race_id or '') if ch.isalnum())
    return f'audit_analysis_run_id_{rid}'


def _dedupe_key(race_id: str, stage: str, analysis_run_id: Optional[str] = None) -> str:
    rid = ''.join(ch for ch in str(race_id or '') if ch.isalnum())
    run = ''.join(ch for ch in str(analysis_run_id or '') if ch.isalnum()) or 'norun'
    return f'audit_dedupe_sig_{rid}_{stage}_{run}'


def _errors_key() -> str:
    return 'audit_record_errors'


def _recommendation_key(race_id: str) -> str:
    rid = ''.join(ch for ch in str(race_id or '') if ch.isalnum())
    return f'audit_latest_recommendation_id_{rid}'


EXPECTED_RUN_STAGES = (
    'scanner', 'scanner_display', 'elim', 'sra',
    'anabaka_hunter', 'recommendation',
)

EXTERNAL_CONFIRM_APP = 'app_declared'
EXTERNAL_CONFIRM_VERIFIED = 'externally_verified'

ACCIDENT_DUP_WINDOW_SEC = 120


def normalize_bet_label_text(label):
    """比較用（UI表示は変更しない）。"""
    import unicodedata
    s = unicodedata.normalize('NFKC', str(label or ''))
    return s.replace(' ', '').replace('\u3000', '')


def _purchase_nonce_session_key(race_id, submit_nonce):
    rid = ''.join(ch for ch in str(race_id or '') if ch.isalnum())
    return f'audit_purchase_done_{rid}_{submit_nonce}'


def _session_state(session=None):
    if session is not None:
        return session
    try:
        import streamlit as st
        return st.session_state
    except Exception:
        return {}


def json_safe(obj, max_list=200):
    """監査 payload 用に JSON 化可能な形へ（サイズ上限あり）。"""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): json_safe(v, max_list=max_list) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(json_safe(list(obj), max_list=max_list))
    if isinstance(obj, (list, tuple)):
        out = [json_safe(x, max_list=max_list) for x in obj[:max_list]]
        if len(obj) > max_list:
            out.append(f'…truncated({len(obj) - max_list} more)')
        return out
    try:
        if hasattr(obj, 'item'):
            return obj.item()
    except Exception:
        pass
    return str(obj)


@dataclass
class RecordOutcome:
    ok: bool
    event_id: Optional[str] = None
    error: Optional[str] = None
    analysis_run_id: Optional[str] = None


def _append_error(session, race_id, stage, message):
    errs = session.setdefault(_errors_key(), [])
    errs.append({
        'race_id': str(race_id or ''),
        'stage': stage,
        'error': str(message),
    })


def current_run_id(race_id, session=None) -> Optional[str]:
    ss = _session_state(session)
    return ss.get(_run_key(race_id))


def begin_new_run(
    race_id,
    source,
    settings=None,
    meta=None,
    session=None,
    store: Optional[audit_store.AuditStore] = None,
) -> str:
    """新しい analysis_run_id を発行し session に保存。"""
    rid = str(race_id or '').strip()
    ss = _session_state(session)
    owned = store is None
    st = store or audit_store.AuditStore()
    try:
        parent_run = ss.get(_run_key(rid))
        run_meta = dict(meta or {})
        if parent_run:
            run_meta['parent_analysis_run_id'] = parent_run
        run_id = st.create_analysis_run(
            rid,
            input_hash=None,
            rule_version='phase_a',
            settings=json_safe({'source': source, **(settings or {})}),
            meta=run_meta,
        )
        ss[_run_key(rid)] = run_id
        ss.pop(_recommendation_key(rid), None)
        ss.pop(f'audit_recommendation_payload_{rid}', None)
        return run_id
    finally:
        if owned:
            st.close()


def ensure_run_id(
    race_id,
    source='continued',
    session=None,
    store: Optional[audit_store.AuditStore] = None,
) -> str:
    rid = str(race_id or '').strip()
    ss = _session_state(session)
    existing = ss.get(_run_key(rid))
    if existing:
        return existing
    return begin_new_run(rid, source, session=ss, store=store)


def record_event(
    race_id,
    stage,
    payload=None,
    status='ok',
    analysis_run_id=None,
    session=None,
    store: Optional[audit_store.AuditStore] = None,
) -> RecordOutcome:
    rid = str(race_id or '').strip()
    if not rid:
        out = RecordOutcome(False, error='race_id empty')
        _append_error(_session_state(session), rid, stage, out.error)
        return out
    ss = _session_state(session)
    owned = store is None
    st = store or audit_store.AuditStore()
    try:
        run_id = analysis_run_id or ensure_run_id(rid, session=ss, store=st)
        event_id = st.append_event(
            run_id, rid, stage,
            payload=json_safe(payload),
            status=status,
        )
        return RecordOutcome(True, event_id=event_id, analysis_run_id=run_id)
    except Exception as e:
        _append_error(ss, rid, stage, e)
        return RecordOutcome(False, error=str(e), analysis_run_id=ss.get(_run_key(rid)))
    finally:
        if owned:
            st.close()


def record_event_deduped(
    race_id,
    stage,
    signature,
    payload=None,
    status='ok',
    analysis_run_id=None,
    session=None,
    store: Optional[audit_store.AuditStore] = None,
) -> RecordOutcome:
    """同一 signature の連続 rerun では追記しない（消去スライダー等）。"""
    ss = _session_state(session)
    sig = hashlib.sha256(
        json.dumps(json_safe(signature), sort_keys=True, default=str).encode('utf-8')
    ).hexdigest()[:24]
    run_id = analysis_run_id or current_run_id(race_id, session=ss)
    if not run_id:
        run_id = ensure_run_id(race_id, session=ss, store=store)
    dk = _dedupe_key(race_id, stage, run_id)
    if ss.get(dk) == sig:
        return RecordOutcome(
            True,
            event_id=None,
            analysis_run_id=run_id,
        )
    out = record_event(
        race_id, stage, payload=payload, status=status,
        analysis_run_id=run_id, session=ss, store=store,
    )
    if out.ok and out.event_id:
        ss[dk] = sig
    return out


def last_record_errors(session=None):
    return list(_session_state(session).get(_errors_key()) or [])


def clear_record_errors(session=None):
    ss = _session_state(session)
    ss[_errors_key()] = []


def build_elim_payload(erows, edf, border_cnt, race_id):
    from core import elim_engine as ee
    all_um = sorted(int(r['馬番']) for r in (erows or []) if r.get('馬番') is not None)
    keep = ee.keep_umaban_from_edf(edf) if edf is not None else []
    elim = sorted(set(all_um) - set(keep))
    rows = []
    if edf is not None and not getattr(edf, 'empty', True):
        for rank_i, (_, rr) in enumerate(edf.iterrows(), start=1):
            rows.append({
                'umaban': int(rr['馬番']),
                'score': float(rr.get('score') or 0),
                'rank': rank_i,
                'verdict': str(rr.get('判定') or ''),
                'learning': str(rr.get('学習残し') or ''),
                'rescue_reason': str(rr.get('妙味材料') or '') if rr.get('判定') != '🧹消し' else '',
            })
    rescued = [
        r for r in rows
        if r['verdict'] in ('✅残し', '🛟ボーダー残し') and '🛟' in r.get('learning', '')
        or (r['verdict'] == '🛟ボーダー残し')
    ]
    return {
        'border_cnt': int(border_cnt or 0),
        'all_umaban': all_um,
        'before_set': all_um,
        'after_set': sorted(keep),
        'eliminated_set': elim,
        'rescued_border': [r['umaban'] for r in rows if r['verdict'] == '🛟ボーダー残し'],
        'learning_rescue': [
            {'umaban': r['umaban'], 'learning': r['learning']}
            for r in rows if r.get('learning')
        ],
        'ranked_rows': rows,
    }


def build_sra_payload(df, race_id, elim_before, elim_after, meta=None):
    import pandas as pd
    scores = []
    if df is not None and not getattr(df, 'empty', True):
        for _, r in df.iterrows():
            try:
                u = int(pd.to_numeric(r.get('Umaban'), errors='coerce'))
            except Exception:
                continue
            proj = pd.to_numeric(
                r.get('Projected Score', r.get('BattleScore')), errors='coerce')
            ltr = pd.to_numeric(r.get('LTR'), errors='coerce') if 'LTR' in df.columns else None
            scores.append({
                'umaban': u,
                'projected': float(proj) if pd.notnull(proj) else None,
                'ltr': float(ltr) if ltr is not None and pd.notnull(ltr) else None,
            })
        scores.sort(key=lambda x: (-(x['projected'] or -1), x['umaban']))
    return {
        'candidate_pool_all': sorted(s['umaban'] for s in scores),
        'elim_keep_before_sra_recalc': sorted(elim_before or []),
        'elim_keep_after_sra_recalc': sorted(elim_after or []),
        'pool_changed': sorted(elim_before or []) != sorted(elim_after or []),
        'top_scores': scores[:20],
        'meta_keys': sorted(list((meta or {}).keys()))[:40],
    }


def build_playbook_payload(pb_rec, horses_in, cross_n, vscore, zone_hint=None):
    pb = pb_rec or {}
    tickets = []
    for key in ('trio', 'trifecta', 'umaren', 'wide'):
        for row in (pb.get(key) or []):
            tickets.append({
                'kind': row.get('kind') or key,
                'label': row.get('label'),
                'combo': list(row.get('combo') or []),
            })
    return {
        'input_horses_umaban': sorted(int(h['umaban']) for h in (horses_in or []) if h.get('umaban')),
        'input_horse_count': len(horses_in or []),
        'zone': zone_hint or pb.get('zone'),
        'vscore': vscore,
        'cross_n': cross_n,
        'selected_bet_type': pb.get('selected_bet_type'),
        'selected_playbook': pb.get('selected_playbook'),
        'selection_reason': pb.get('selection_reason'),
        'n_points': pb.get('n_points'),
        'skip': bool(pb.get('skip')),
        'fallback': pb.get('fallback') or pb.get('skip_reason'),
        'ticket_labels': [t['label'] for t in tickets[:50]],
        'ticket_count': len(tickets),
    }


def build_hunter_payload(candidates, elite, net, other, race_id, pop_threshold, analysis_run_id_ref):
    def _summ(c):
        return {
            'umaban': c.get('umaban'),
            'pop': c.get('pop'),
            'vh_score': c.get('vh_score'),
            'vh_tier': c.get('vh_tier'),
            'n_verified': c.get('n_verified'),
        }
    return {
        'analysis_run_id_ref': analysis_run_id_ref,
        'data_source': 'live_scrape',
        'pop_threshold': pop_threshold,
        'evaluated_count': len(candidates or []),
        'candidates': [_summ(c) for c in (candidates or [])[:40]],
        'elite_cards': [_summ(c) for c in (elite or [])],
        'net_cards': [_summ(c) for c in (net or [])],
        'not_passed_to_playbook': [_summ(c) for c in (other or [])],
    }


def reconstruct_pool_trace(events):
    """監査イベント列から候補集合の変遷を再構成（テスト・回顧用）。"""
    trace = []
    for ev in events or []:
        stage = ev.get('stage')
        try:
            payload = json.loads(ev.get('payload_json') or '{}')
        except Exception:
            payload = {}
        entry = {'stage': stage, 'status': ev.get('status')}
        if stage == 'scanner':
            entry['pool'] = payload.get('race_id')
        elif stage == 'elim':
            entry['before'] = payload.get('before_set')
            entry['after'] = payload.get('after_set')
        elif stage == 'sra':
            entry['before'] = payload.get('elim_keep_before_sra_recalc')
            entry['after'] = payload.get('elim_keep_after_sra_recalc')
        elif stage == 'buy_method':
            entry['pool'] = payload.get('input_horses_umaban')
        trace.append(entry)
    return trace


def playbook_to_recommendation_lines(pb_rec):
    """playbook 結果から推奨券行（金額なし・構造のみ）。"""
    pb = pb_rec or {}
    lines = []
    for key in ('trio', 'trifecta', 'umaren', 'wide'):
        for row in (pb.get(key) or []):
            kind = str(row.get('kind') or key)
            label = str(row.get('label') or '')
            lines.append({
                'kind': kind,
                'label': label,
                'combo': list(row.get('combo') or []),
                'stake_suggested': 0,
            })
    return lines


def build_recommendation_payload(
    pb_rec,
    horses_in,
    cross_n,
    vscore,
    zone_hint=None,
    gate=None,
):
    """推奨確定イベント用 payload。"""
    lines = playbook_to_recommendation_lines(pb_rec)
    pb = pb_rec or {}
    gate = gate or {}
    return {
        'race_id': pb.get('race_id'),
        'lines': lines,
        'ticket_count': len(lines),
        'n_points': pb.get('n_points'),
        'total_stake_suggested': 0,
        'selected_bet_type': pb.get('selected_bet_type'),
        'selected_playbook': pb.get('selected_playbook'),
        'selection_reason': pb.get('selection_reason'),
        'zone': zone_hint or pb.get('zone'),
        'vscore': vscore,
        'cross_n': cross_n,
        'skip': bool(pb.get('skip')),
        'input_horses_umaban': sorted(
            int(h['umaban']) for h in (horses_in or []) if h.get('umaban')),
        'gate_status': gate.get('status'),
        'gate_lean': gate.get('lean'),
        'gate_severity': gate.get('severity'),
    }


def ticket_identity(kind, label):
    """券種+買い目の比較キー（canonical）。"""
    from core import money as _money
    k = str(kind or '').strip()
    lab = normalize_bet_label_text(label)
    parsed = _money.parse_bet_label(k, lab)
    if parsed:
        return (k, parsed)
    return (k, lab)


def purchase_lines_from_kelly(lines):
    """BetSync ケリー行 → 監査用購入行（canonical 経由）。"""
    from core import audit_purchase as apur
    canonical, _err = apur.canonicalize_purchase_input(lines)
    if not canonical:
        return []
    return apur.canonical_lines_to_storage_lines(canonical)


def _ledger_lines_from_canonical(canonical):
    out = []
    for c in canonical or []:
        row = {
            'kind': c['bet_type'],
            'label': c['bamei'],
            'stake': int(c['stake']),
        }
        if c.get('umaban') is not None:
            row['umaban'] = int(c['umaban'])
        out.append(row)
    return out


def _purchase_request_from_ctx(ctx) -> 'apur.PurchaseRequestContext':
    from core import audit_purchase as apur
    return apur.PurchaseRequestContext(
        race_id=str(ctx['rid']),
        operation_id=str(ctx['purchase_operation_id']),
        purchase_mode=str(ctx['purchase_mode']),
        analysis_run_id=str(ctx['run_id']),
        recommendation_id=str(ctx['rec_id']),
        purchase_fingerprint=str(ctx.get('fp') or '') or None,
    )


def diff_recommendation_vs_purchase(rec_lines, purchase_lines):
    """推奨と実購入の差分（後から判定用）。"""
    rec_map = {}
    for r in rec_lines or []:
        key = ticket_identity(r.get('kind'), r.get('label'))
        rec_map[key] = {
            'kind': r.get('kind'),
            'label': r.get('label'),
            'stake_suggested': int(r.get('stake_suggested') or r.get('stake') or 0),
        }
    pur_map = {}
    for p in purchase_lines or []:
        key = ticket_identity(p.get('kind'), p.get('label'))
        pur_map[key] = {
            'kind': p.get('kind'),
            'label': p.get('label'),
            'stake': int(p.get('stake') or 0),
        }
    rec_keys = set(rec_map)
    pur_keys = set(pur_map)
    matched = []
    stake_changed = []
    for k in sorted(rec_keys & pur_keys):
        rs = rec_map[k]['stake_suggested']
        ps = pur_map[k]['stake']
        matched.append({'kind': rec_map[k]['kind'], 'label': rec_map[k]['label'],
                        'stake_suggested': rs, 'stake_purchased': ps})
        if rs != ps:
            stake_changed.append(matched[-1])
    removed = [rec_map[k] for k in sorted(rec_keys - pur_keys)]
    added = [pur_map[k] for k in sorted(pur_keys - rec_keys)]
    unpurchased_rec = list(removed)
    flags = {
        'purchased_as_recommended': (
            not added and not removed and not stake_changed and bool(matched)),
        'removed_from_recommendation': bool(removed),
        'added_not_in_recommendation': bool(added),
        'stake_changed': bool(stake_changed),
        'unpurchased_recommendation_tickets': bool(unpurchased_rec),
    }
    if flags['purchased_as_recommended']:
        summary = '推奨どおり購入'
    elif removed and not added and not stake_changed:
        summary = '推奨券を削除'
    elif added and not removed and not stake_changed:
        summary = '推奨外の券を追加'
    elif stake_changed and not removed and not added:
        summary = '金額変更'
    else:
        summary = '複合差分'
    return {
        'summary': summary,
        'flags': flags,
        'matched': matched,
        'removed_from_recommendation': removed,
        'added_not_in_recommendation': added,
        'stake_changed': stake_changed,
        'unpurchased_recommendation_tickets': unpurchased_rec,
    }


def validate_explicit_recommendation(store, recommendation_id, analysis_run_id, race_id):
    from core.audit_lineage import validate_purchase_lineage
    ok, err, ev = validate_purchase_lineage(
        store, race_id, analysis_run_id, recommendation_id)
    if not ok:
        return False, err, None
    return True, None, ev


def latest_recommendation_for_run(store, analysis_run_id):
    recs = store.list_recommendations(analysis_run_id) if analysis_run_id else []
    if not recs:
        return None, None
    ev = recs[-1]
    return ev.get('event_id'), ev


def _parent_run_chain(store, analysis_run_id):
    chain = []
    rid = analysis_run_id
    seen = set()
    while rid and rid not in seen:
        seen.add(rid)
        chain.append(rid)
        row = store.get_analysis_run(rid)
        if not row:
            break
        try:
            meta = json.loads(row.get('meta_json') or '{}')
        except Exception:
            meta = {}
        rid = meta.get('parent_analysis_run_id')
    return chain


def capture_purchase_snapshot_event_ids(store, analysis_run_id, recommendation_id=None):
    """購入確定時点の event_id 固定（未実行工程は NOT_RUN_AT_PURCHASE）。"""
    from core.audit_snapshot import SNAPSHOT_NOT_RUN
    out = {}
    chain = _parent_run_chain(store, analysis_run_id)
    if recommendation_id:
        out['recommendation'] = recommendation_id
    else:
        recs = store.list_recommendations(analysis_run_id) if analysis_run_id else []
        out['recommendation'] = recs[-1]['event_id'] if recs else SNAPSHOT_NOT_RUN
    for stage in ('scanner', 'scanner_display'):
        eid = SNAPSHOT_NOT_RUN
        for run_id in chain:
            evs = [e for e in store.list_events(run_id) if e.get('stage') == stage]
            if evs:
                eid = evs[-1]['event_id']
                break
        out[stage] = eid
    for stage in ('elim', 'sra', 'anabaka_hunter'):
        evs = []
        if analysis_run_id:
            evs = [e for e in store.list_events(analysis_run_id) if e.get('stage') == stage]
        out[stage] = evs[-1]['event_id'] if evs else SNAPSHOT_NOT_RUN
    return out


def purchase_fingerprint(recommendation_id, purchase_lines, analysis_run_id=None):
    body = {
        'analysis_run_id': analysis_run_id,
        'recommendation_id': recommendation_id,
        'lines': sorted(
            [
                {
                    'kind': p.get('kind'),
                    'label': p.get('label'),
                    'stake': int(p.get('stake') or 0),
                }
                for p in (purchase_lines or [])
            ],
            key=lambda x: (x['kind'], x['label'], x['stake']),
        ),
    }
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@dataclass
class PurchaseOutcome:
    ok: bool
    purchase_batch_id: Optional[str] = None
    duplicate: bool = False
    error: Optional[str] = None
    analysis_run_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    diff: Optional[dict] = None
    bets_recorded: int = 0
    duplicate_reason: Optional[str] = None


def _prepare_purchase_context(
    race_id,
    kelly_lines,
    recommendation_id=None,
    analysis_run_id=None,
    intentional_repurchase=False,
    submit_nonce=None,
    session=None,
    store=None,
    recommendation_id_explicit=False,
    ledger=None,
    purchase_mode=None,
):
    """購入確定の共通前処理（batch 未作成）。"""
    from core import audit_purchase as apur
    from core.audit_lineage import (
        resolve_analysis_run_for_purchase,
        resolve_purchase_recommendation,
    )
    rid = str(race_id or '').strip()
    ss = _session_state(session)
    st = store
    conn_err = apur.require_shared_connection(
        ledger, st, require_ledger=(ledger is not None))
    if conn_err:
        return None, PurchaseOutcome(False, error=conn_err)
    canonical, c_err = apur.canonicalize_purchase_input(kelly_lines)
    if c_err:
        return None, PurchaseOutcome(False, error=c_err)
    purchase_lines = apur.canonical_lines_to_storage_lines(canonical)
    ledger_lines = _ledger_lines_from_canonical(canonical)
    mode = purchase_mode or apur.PURCHASE_MODE_LEDGER_LINKED
    op_id, op_err = apur.normalize_purchase_operation_id(submit_nonce)
    if op_err:
        return None, PurchaseOutcome(False, error=op_err)
    existing_hit = st.find_purchase_batch_by_operation_id(op_id) if op_id else None
    existing_op = (
        st.get_purchase_batch(existing_hit['purchase_batch_id'])
        if existing_hit else None)
    if existing_op and str(existing_op.get('race_id') or '') != rid:
        return None, PurchaseOutcome(False, error='operation_id_race_conflict')
    run_id, run_err = resolve_analysis_run_for_purchase(
        st, rid, analysis_run_id, recommendation_id,
        recommendation_id_explicit, ss)
    rec_id = None
    rec_ev = None
    adopted_stored_request = False
    if (
        run_err == 'no_analysis_run_for_purchase'
        and existing_op
        and not analysis_run_id
        and not recommendation_id_explicit
    ):
        run_id = str(existing_op.get('analysis_run_id') or '').strip()
        try:
            ref = json.loads(existing_op.get('recommended_ref_json') or '{}')
        except Exception:
            ref = {}
        rec_id = str(ref.get('recommendation_id') or '').strip()
        rec_ev = st.get_event(rec_id) if rec_id else None
        if run_id and rec_id:
            run_err = None
            adopted_stored_request = True
    if run_err:
        return None, PurchaseOutcome(
            False, error=run_err,
            recommendation_id=recommendation_id if recommendation_id_explicit else None)
    if not adopted_stored_request:
        session_hint = latest_recommendation_id(rid, session=ss)
        rec_id, rec_ev, rec_err = resolve_purchase_recommendation(
            st, rid, run_id, recommendation_id, recommendation_id_explicit, session_hint)
        if rec_err:
            return None, PurchaseOutcome(
                False, error=rec_err, analysis_run_id=run_id,
                recommendation_id=recommendation_id if recommendation_id_explicit else None)
    fp = purchase_fingerprint(rec_id, purchase_lines, analysis_run_id=run_id)
    manifest = apur.manifest_from_canonical_lines(canonical)
    ctx_base = {
        'rid': rid, 'ss': ss, 'st': st, 'run_id': run_id, 'rec_id': rec_id,
        'purchase_lines': purchase_lines, 'ledger_lines': ledger_lines,
        'canonical': canonical, 'fp': fp, 'total': sum(p['stake'] for p in purchase_lines),
        'purchase_operation_id': op_id, 'purchase_mode': mode,
        'purchase_manifest': manifest,
        'purchase_manifest_hash': apur.purchase_manifest_hash(manifest),
    }
    req = _purchase_request_from_ctx({**ctx_base, 'fp': fp})
    if existing_op:
        bid, replay_kind, replay_err = apur.evaluate_operation_id_replay(
            st, ledger, op_id, rid, purchase_mode=mode, request=req)
        if replay_err:
            return None, PurchaseOutcome(False, error=replay_err)
        if replay_kind == 'duplicate_ok' and bid:
            return None, PurchaseOutcome(
                True, purchase_batch_id=bid, duplicate=True,
                duplicate_reason='operation_id_db',
                analysis_run_id=run_id, recommendation_id=rec_id,
            )
    if ss.get(_purchase_nonce_session_key(rid, op_id)):
        dup = ss.get(_purchase_nonce_session_key(rid, op_id))
        if isinstance(dup, str):
            dup_ok, dup_err = apur.duplicate_success_for_batch(
                st, ledger, dup, purchase_mode=mode, request=req)
            if dup_ok:
                return None, PurchaseOutcome(
                    True, purchase_batch_id=dup, duplicate=True,
                    duplicate_reason='submit_nonce_replay',
                )
            return None, PurchaseOutcome(False, error=dup_err or 'purchase_incomplete')
    if not intentional_repurchase:
        # fingerprint は committed のみ対象（pending/failed は誤ダブルクリック防止の別軸）
        recent_id = st.find_purchase_by_fingerprint(
            rid, fp, committed_only=True, within_seconds=ACCIDENT_DUP_WINDOW_SEC)
        if recent_id:
            fp_ok, fp_err = apur.duplicate_success_for_batch(
                st, ledger, recent_id, purchase_mode=mode, request=req,
                match_operation_id=False)
            if fp_ok:
                return None, PurchaseOutcome(
                    True, purchase_batch_id=recent_id, duplicate=True,
                    duplicate_reason='recent_fingerprint',
                    analysis_run_id=run_id, recommendation_id=rec_id)
            return None, PurchaseOutcome(
                False, error=fp_err or 'purchase_inconsistent',
                analysis_run_id=run_id, recommendation_id=rec_id)
    rec_lines = []
    if rec_ev:
        try:
            pl = json.loads(rec_ev.get('payload_json') or '{}')
            rec_lines = pl.get('lines') or []
        except Exception:
            rec_lines = []
    snapshot_ids = capture_purchase_snapshot_event_ids(st, run_id, rec_id)
    diff = diff_recommendation_vs_purchase(rec_lines, purchase_lines)
    ctx = {
        **ctx_base,
        'diff': diff,
        'intentional_repurchase': intentional_repurchase,
        'submit_nonce': submit_nonce,
        'snapshot_event_ids': snapshot_ids,
    }
    return ctx, None


def record_recommendation(
    race_id,
    pb_rec,
    horses_in,
    cross_n,
    vscore,
    zone_hint=None,
    gate=None,
    analysis_run_id=None,
    session=None,
    store: Optional[audit_store.AuditStore] = None,
) -> RecordOutcome:
    """推奨を追記（上書きしない）。recommendation_id = event_id。"""
    rid = str(race_id or '').strip()
    payload = build_recommendation_payload(
        pb_rec, horses_in, cross_n, vscore, zone_hint=zone_hint, gate=gate)
    payload['race_id'] = rid
    out = record_event(
        rid, 'recommendation', payload=payload, status='ok',
        analysis_run_id=analysis_run_id, session=session, store=store,
    )
    if out.ok and out.event_id:
        ss = _session_state(session)
        ss[_recommendation_key(rid)] = out.event_id
        ss[f'audit_recommendation_payload_{rid}'] = payload
    return out


def latest_recommendation_id(race_id, session=None):
    return _session_state(session).get(_recommendation_key(race_id))


def confirm_app_purchase(
    race_id,
    kelly_lines,
    recommendation_id=None,
    analysis_run_id=None,
    allow_duplicate=False,
    intentional_repurchase=False,
    submit_nonce=None,
    session=None,
    store: Optional[audit_store.AuditStore] = None,
    ledger=None,
) -> PurchaseOutcome:
    """アプリ内購入確定（batch のみ。テスト互換・bets 非連携）。"""
    from core import audit_purchase as apur
    ss = _session_state(session)
    owned = store is None and ledger is None
    st = store
    if st is None and ledger is not None:
        st = audit_store.AuditStore(con=ledger.con)
    if st is None:
        return PurchaseOutcome(False, error='audit_store_required')
    conn_err = apur.require_shared_connection(
        ledger, st, require_ledger=False)
    if conn_err:
        return PurchaseOutcome(False, error=conn_err)
    ctx = None
    try:
        ctx, early = _prepare_purchase_context(
            race_id, kelly_lines,
            recommendation_id=recommendation_id,
            analysis_run_id=analysis_run_id,
            intentional_repurchase=(allow_duplicate or intentional_repurchase),
            submit_nonce=submit_nonce,
            session=ss, store=st,
            recommendation_id_explicit=(recommendation_id is not None),
            ledger=ledger,
            purchase_mode=apur.PURCHASE_MODE_BATCH_ONLY)
        if early:
            return early
        rid = ctx['rid']
        batch_id = st.create_purchase_batch(
            rid,
            lines=ctx['purchase_lines'],
            analysis_run_id=ctx['run_id'],
            recommended_ref={
                'recommendation_id': ctx['rec_id'],
                'analysis_run_id': ctx['run_id'],
            },
            meta={
                'fingerprint': ctx['fp'],
                'external_confirm': EXTERNAL_CONFIRM_APP,
                'total_stake': ctx['total'],
                'diff': ctx['diff'],
                'intentional_repurchase': bool(ctx['intentional_repurchase']),
                'ledger_linked': False,
                'completion_scope': apur.COMPLETION_SCOPE_BATCH_ONLY,
                'record_kind': apur.RECORD_KIND_AUDIT_BATCH,
                'purchase_manifest': ctx.get('purchase_manifest'),
                'purchase_manifest_hash': ctx.get('purchase_manifest_hash'),
                'snapshot_event_ids': ctx.get('snapshot_event_ids'),
                'purchase_operation_id': ctx.get('purchase_operation_id'),
            },
            record_status=audit_store.BATCH_COMMITTED_NEW,
            purchase_operation_id=ctx.get('purchase_operation_id'),
        )
        if ctx['submit_nonce']:
            ss[_purchase_nonce_session_key(rid, ctx['submit_nonce'])] = batch_id
        return PurchaseOutcome(
            True, purchase_batch_id=batch_id, duplicate=False,
            analysis_run_id=ctx['run_id'], recommendation_id=ctx['rec_id'],
            diff=ctx['diff'])
    except sqlite3.IntegrityError:
        if ctx and ctx.get('purchase_operation_id'):
            dup_row = st.find_purchase_batch_by_operation_id(
                ctx['purchase_operation_id'])
            if dup_row and str(dup_row.get('race_id') or '') == ctx['rid']:
                dup_ok, dup_err = apur.duplicate_success_for_batch(
                    st, ledger, dup_row['purchase_batch_id'],
                    purchase_mode=apur.PURCHASE_MODE_BATCH_ONLY,
                    request=_purchase_request_from_ctx(ctx) if ctx else None)
                if dup_ok:
                    return PurchaseOutcome(
                        True, purchase_batch_id=dup_row['purchase_batch_id'],
                        duplicate=True, duplicate_reason='operation_id_db')
                return PurchaseOutcome(False, error=dup_err or 'purchase_inconsistent')
        raise
    except Exception as e:
        _append_error(ss, str(race_id or ''), 'purchase_confirm', e)
        return PurchaseOutcome(False, error=str(e))
    finally:
        if owned:
            st.close()


def confirm_app_purchase_with_bets(
    race_id,
    kelly_lines,
    ledger,
    recommendation_id=None,
    analysis_run_id=None,
    intentional_repurchase=False,
    submit_nonce=None,
    session=None,
    store: Optional[audit_store.AuditStore] = None,
    **ledger_kw,
) -> PurchaseOutcome:
    """purchase_batch + bets を同一 DB トランザクションで確定。"""
    from core import audit_purchase as apur
    from core import audit_store as _ast
    ss = _session_state(session)
    st = store if store is not None else _ast.AuditStore(con=ledger.con)
    conn_err = apur.require_shared_connection(ledger, st)
    if conn_err:
        return PurchaseOutcome(False, error=conn_err)
    ctx = None
    try:
        ctx, early = _prepare_purchase_context(
            race_id, kelly_lines,
            recommendation_id=recommendation_id,
            analysis_run_id=analysis_run_id,
            intentional_repurchase=intentional_repurchase,
            submit_nonce=submit_nonce,
            session=ss, store=st,
            recommendation_id_explicit=(recommendation_id is not None),
            ledger=ledger,
            purchase_mode=apur.PURCHASE_MODE_LEDGER_LINKED)
        if early:
            return early
        rid = ctx['rid']
        expected = len(ctx['purchase_lines'])
        batch_id = None
        n = 0
        ledger.con.execute('BEGIN IMMEDIATE')
        try:
            batch_id = st.create_purchase_batch(
                rid,
                lines=ctx['purchase_lines'],
                analysis_run_id=ctx['run_id'],
                recommended_ref={
                    'recommendation_id': ctx['rec_id'],
                    'analysis_run_id': ctx['run_id'],
                },
                meta={
                    'fingerprint': ctx['fp'],
                    'external_confirm': EXTERNAL_CONFIRM_APP,
                    'total_stake': ctx['total'],
                    'diff': ctx['diff'],
                    'intentional_repurchase': bool(ctx['intentional_repurchase']),
                    'ledger_linked': True,
                    'completion_scope': apur.COMPLETION_SCOPE_LEDGER_LINKED,
                    'record_kind': apur.RECORD_KIND_ACTUAL_PURCHASE,
                    'purchase_manifest': ctx.get('purchase_manifest'),
                    'purchase_manifest_hash': ctx.get('purchase_manifest_hash'),
                    'snapshot_event_ids': ctx.get('snapshot_event_ids'),
                    'purchase_operation_id': ctx.get('purchase_operation_id'),
                },
                record_status=_ast.BATCH_PENDING,
                purchase_operation_id=ctx.get('purchase_operation_id'),
                _commit=False,
            )
            n = ledger.record_kelly_bets(
                rid, ctx['ledger_lines'],
                purchase_batch_id=batch_id,
                recommendation_id=ctx['rec_id'],
                analysis_run_id=ctx['run_id'],
                audit_link='linked',
                _commit=False,
                **ledger_kw,
            )
            if n != expected:
                raise apur.PurchaseIntegrityError(
                    f'bets count mismatch expected={expected} recorded={n}')
            st.set_purchase_batch_status(
                batch_id, _ast.BATCH_COMMITTED_NEW, _commit=False)
            apur.assert_api_success_implies_committed_actual(st, ledger, batch_id)
            ledger.con.commit()
        except apur.PurchaseIntegrityError:
            ledger.con.rollback()
            return PurchaseOutcome(False, error='purchase_inconsistent')
        except Exception:
            ledger.con.rollback()
            raise
        if ctx['submit_nonce']:
            ss[_purchase_nonce_session_key(rid, ctx['submit_nonce'])] = batch_id
        return PurchaseOutcome(
            True, purchase_batch_id=batch_id, duplicate=False,
            analysis_run_id=ctx['run_id'], recommendation_id=ctx['rec_id'],
            diff=ctx['diff'], bets_recorded=n)
    except sqlite3.IntegrityError:
        if ctx and ctx.get('purchase_operation_id'):
            bid, replay_kind, replay_err = apur.evaluate_operation_id_replay(
                st, ledger, ctx['purchase_operation_id'], ctx['rid'],
                purchase_mode=apur.PURCHASE_MODE_LEDGER_LINKED,
                request=_purchase_request_from_ctx(ctx))
            if replay_kind == 'duplicate_ok' and bid:
                return PurchaseOutcome(
                    True, purchase_batch_id=bid, duplicate=True,
                    duplicate_reason='operation_id_db')
            if replay_err:
                return PurchaseOutcome(False, error=replay_err)
        return PurchaseOutcome(False, error='operation_id_conflict')
    except Exception as e:
        _append_error(ss, str(race_id or ''), 'purchase_confirm', e)
        return PurchaseOutcome(False, error=str(e))


def _stage_has_no_candidates(stage, payload, status):
    if status == 'not_run':
        return False
    if stage == 'recommendation' and payload.get('skip'):
        return True
    if stage == 'anabaka_hunter' and int(payload.get('evaluated_count') or 0) == 0:
        return True
    if stage == 'elim' and not (payload.get('after_set') or payload.get('ranked_rows')):
        return True
    return False


def run_stage_summary(
    analysis_run_id,
    store: Optional[audit_store.AuditStore] = None,
    record_errors=None,
):
    """期待工程と audit_events / 記録失敗を照合。"""
    owned = store is None
    st = store or audit_store.AuditStore()
    try:
        events = st.list_events(analysis_run_id)
        by_stage = {}
        for ev in events:
            by_stage.setdefault(ev['stage'], []).append(ev)
        err_stages = set()
        for err in record_errors or []:
            if err.get('stage'):
                err_stages.add(err['stage'])
        summary = {}
        for stage in EXPECTED_RUN_STAGES:
            evs = by_stage.get(stage) or []
            if not evs:
                if stage in err_stages:
                    state = 'audit_failed'
                else:
                    state = 'not_run'
                summary[stage] = {'state': state, 'event_count': 0}
                continue
            last = evs[-1]
            status = last.get('status') or 'ok'
            try:
                payload = json.loads(last.get('payload_json') or '{}')
            except Exception:
                payload = {}
            if status == 'failed' or stage in err_stages:
                state = 'audit_failed'
            elif _stage_has_no_candidates(stage, payload, status):
                state = 'no_candidates'
            elif status == 'not_run':
                state = 'not_run'
            else:
                state = 'executed_ok'
            summary[stage] = {
                'state': state,
                'event_count': len(evs),
                'last_status': status,
                'last_event_id': last.get('event_id'),
            }
        return summary
    finally:
        if owned:
            st.close()
