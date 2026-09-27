# -*- coding: utf-8 -*-
"""
フェーズA step6: 監査IDチェーン・MAGI回顧の pre/post 分離。

推論ロジックは変更せず、入力の出所を固定する。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from core import audit_pipeline as ap
from core import audit_purchase as apur
from core import audit_store
from core import money


AUDIT_LINK_LINKED = 'linked'
AUDIT_LINK_LEGACY = 'legacy_unknown'


def classify_bet_settlement(bet: dict) -> str:
    """pending / hit / miss / refund / unknown"""
    bet = money.bet_row_dict(bet)
    if not int(bet.get('settled') or 0):
        return 'pending'
    try:
        payout = int(bet.get('payout') or 0)
    except (TypeError, ValueError):
        payout = 0
    won = int(bet.get('won') or 0)
    if payout > 0 and won == 0:
        return 'refund'
    if won == 1 and payout > 0:
        return 'hit'
    if won == 0 and payout == 0:
        return 'miss'
    return 'pending'


def _parse_json_field(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def load_pre_race_snapshot(
    race_id,
    analysis_run_id=None,
    purchase_batch_id=None,
    recommendation_id=None,
    store: Optional[audit_store.AuditStore] = None,
):
    """監査DBから購入前記録を組み立て。推測で埋めない。"""
    owned = store is None
    st = store or audit_store.AuditStore()
    rid = str(race_id or '').strip()
    try:
        batch = None
        if purchase_batch_id:
            row = st.con.execute(
                "SELECT * FROM purchase_batches WHERE purchase_batch_id=?",
                (purchase_batch_id,)).fetchone()
            batch = dict(row) if row else None
            if batch and rid and str(batch.get('race_id') or '') != rid:
                return {
                    'status': 'unavailable',
                    'reason': 'purchase_batch_race_mismatch',
                }
            if batch and not analysis_run_id:
                analysis_run_id = batch.get('analysis_run_id')
            ref = _parse_json_field(batch.get('recommended_ref_json') if batch else None)
            if not recommendation_id:
                recommendation_id = ref.get('recommendation_id')

        run_id = analysis_run_id
        if not run_id and recommendation_id:
            ev = st.get_event(recommendation_id)
            if ev:
                run_id = ev.get('analysis_run_id')

        batch_lines = _parse_json_field(batch.get('lines_json') if batch else None)
        batch_meta = _parse_json_field(batch.get('meta_json') if batch else None)
        diff = batch_meta.get('diff') if batch else None
        snap_ids = (batch_meta or {}).get('snapshot_event_ids') or {}

        if not batch or not snap_ids:
            if not batch_lines:
                return {'status': 'unavailable', 'reason': 'no_purchase_snapshot'}
        from core.audit_snapshot import resolve_snapshot_payloads, SNAPSHOT_NOT_RUN
        from core.audit_lineage import validate_snapshot_event_ids
        if snap_ids and batch:
            ok_snap, snap_err = validate_snapshot_event_ids(
                st, str(batch.get('race_id') or rid),
                str(batch.get('analysis_run_id') or analysis_run_id or ''),
                snap_ids)
            if not ok_snap:
                return {'status': 'unavailable', 'reason': snap_err or 'snapshot_invalid'}
        resolved = resolve_snapshot_payloads(snap_ids, st) if snap_ids else {}
        rec_payload = resolved.get('recommendation_payload') or {}
        elim_payload = resolved.get('elim_payload') or {}
        sra_payload = resolved.get('sra_payload') or {}
        hunter_payload = (
            resolved.get('anabaka_hunter_payload')
            or resolved.get('hunter_payload')
            or {})
        scanner_payload = resolved.get('scanner_payload') or {}
        scanner_display_payload = resolved.get('scanner_display_payload') or {}
        rec_ev_id = resolved.get('recommendation_id') or snap_ids.get('recommendation')
        if rec_ev_id == SNAPSHOT_NOT_RUN:
            rec_ev_id = None
        if not rec_payload and not batch_lines:
            return {
                'status': 'unavailable',
                'reason': 'no_pre_race_recommendation',
                'analysis_run_id': run_id,
            }

        summary_lines = []
        if rec_payload.get('selected_playbook'):
            summary_lines.append(
                f"playbook={rec_payload.get('selected_playbook')} "
                f"zone={rec_payload.get('zone')} cross_n={rec_payload.get('cross_n')} "
                f"点数={rec_payload.get('n_points')}")
        if rec_payload.get('lines'):
            summary_lines.append(
                "推奨券: " + ", ".join(
                    f"{x.get('kind')}:{x.get('label')}" for x in rec_payload['lines'][:12]))
        if batch_lines:
            summary_lines.append(
                "実購入(確定): " + ", ".join(
                    f"{x.get('kind')}:{x.get('label')}¥{x.get('stake')}"
                    for x in batch_lines[:12]))
        if diff and diff.get('summary'):
            summary_lines.append(f"差分: {diff.get('summary')}")

        return {
            'status': 'available',
            'analysis_run_id': run_id,
            'recommendation_id': rec_ev_id,
            'purchase_batch_id': (batch or {}).get('purchase_batch_id'),
            'recommendation': rec_payload,
            'purchase_batch': {
                'lines': batch_lines,
                'meta': batch_meta,
                'created_ts': (batch or {}).get('created_ts'),
            } if batch else None,
            'diff': diff,
            'elim_event_id': resolved.get('elim_event_id'),
            'elim_payload': elim_payload,
            'sra_payload': sra_payload,
            'hunter_payload': hunter_payload,
            'scanner_payload': scanner_payload,
            'scanner_display_payload': scanner_display_payload,
            'snapshot_event_ids': snap_ids,
            'summary_text': "\n".join(summary_lines),
        }
    finally:
        if owned:
            st.close()


def _find_latest_committed_actual_batch_id(store, ledger, race_id):
    for b in store.iter_purchase_batches(race_id, committed_only=True, page_size=50):
        val = apur.validate_committed_actual_purchase(
            store, ledger, b['purchase_batch_id'])
        if val.get('valid') and val.get('state') == 'committed_actual':
            return b['purchase_batch_id']
    return None


def _committed_actual_batch_ids(store, ledger, race_id):
    out = []
    for b in store.iter_purchase_batches(race_id, committed_only=True, page_size=50):
        val = apur.validate_committed_actual_purchase(
            store, ledger, b['purchase_batch_id'])
        if val.get('valid') and val.get('state') == 'committed_actual':
            out.append(b['purchase_batch_id'])
    return out


def load_settled_result(ledger: money.Ledger, race_id, purchase_batch_id=None, store=None):
    """bets + settlement_log から確定収支。

    purchase_batch_id が None または '__all__' のとき、
    committed_actual と検証できた batch の actual bets だけを合算する。
    batch 無し・legacy_unverified・pending/failed は含めない。
    """
    rid = str(race_id or '').strip()
    all_batches = purchase_batch_id in (None, '', '__all__')
    st = store
    owned_store = False
    if st is None and not all_batches:
        st = audit_store.AuditStore(con=ledger.con)
        owned_store = True
    if all_batches:
        if st is None:
            st = audit_store.AuditStore(con=ledger.con)
            owned_store = True
        actual_batch_ids = set(_committed_actual_batch_ids(st, ledger, rid))
        if not actual_batch_ids:
            rows = []
        else:
            sql = f"""
                SELECT b.* FROM bets b
                WHERE b.race_id=?
                  AND b.bet_purpose = ?
                  AND b.purchase_batch_id IN ({','.join('?' * len(actual_batch_ids))})
            """
            args = [rid, money.BET_PURPOSE_ACTUAL, *sorted(actual_batch_ids)]
            rows = [money.bet_row_dict(r) for r in ledger.con.execute(sql, args)]
        purchase_batch_id = None
        if owned_store:
            st.close()
            owned_store = False
    else:
        if st is None:
            st = audit_store.AuditStore(con=ledger.con)
            owned_store = True
        val = apur.validate_committed_actual_purchase(st, ledger, purchase_batch_id)
        if val.get('valid') and val.get('state') == 'committed_actual':
            q = (f"SELECT * FROM bets WHERE race_id=? AND purchase_batch_id=? "
                 f"AND {money.ACTUAL_PURCHASE_SQL}")
            args = [rid, purchase_batch_id, money.BET_PURPOSE_ACTUAL]
            rows = [money.bet_row_dict(r) for r in ledger.con.execute(q, args)]
        else:
            rows = []
        if owned_store:
            st.close()
    bets_out = []
    total_stake = total_payout = 0
    confirmed_stake = confirmed_payout = 0
    unsettled_stake = 0
    for b in rows:
        st_label = classify_bet_settlement(b)
        stake = int(b.get('stake') or 0)
        payout = int(b.get('payout') or 0)
        total_stake += stake
        total_payout += payout
        if st_label == 'pending':
            unsettled_stake += stake
        else:
            confirmed_stake += stake
            confirmed_payout += payout
        logs = list(ledger.con.execute(
            "SELECT * FROM bet_settlement_log WHERE bet_id=? ORDER BY log_id",
            (b.get('bet_id'),)))
        bets_out.append({
            'bet_id': b.get('bet_id'),
            'bet_type': b.get('bet_type'),
            'bamei': b.get('bamei'),
            'stake': stake,
            'settlement_state': st_label,
            'won': b.get('won'),
            'payout': payout,
            'purchase_batch_id': b.get('purchase_batch_id'),
            'recommendation_id': b.get('recommendation_id'),
            'analysis_run_id': b.get('analysis_run_id'),
            'audit_link': b.get('audit_link'),
            'settlement_log_count': len(logs),
            'has_correction_log': any(
                (money.bet_row_dict(l).get('action') in ('reversal', 'correct'))
                for l in logs),
        })
    batch_totals = {}
    for b in bets_out:
        bid = b.get('purchase_batch_id') or '__legacy__'
        batch_totals.setdefault(bid, {'stake': 0, 'payout': 0, 'bet_count': 0})
        batch_totals[bid]['stake'] += b['stake']
        batch_totals[bid]['payout'] += b['payout']
        batch_totals[bid]['bet_count'] += 1
    return {
        'race_id': rid,
        'purchase_batch_id': purchase_batch_id,
        'scope': 'all_committed' if all_batches else 'single_batch',
        'bets': bets_out,
        'batch_totals': batch_totals,
        'total_stake': total_stake,
        'total_payout': total_payout,
        'confirmed_stake': confirmed_stake,
        'unsettled_stake': unsettled_stake,
        'confirmed_payout': confirmed_payout,
        'confirmed_pnl': confirmed_payout - confirmed_stake,
        'race_pnl': confirmed_payout - confirmed_stake,
        'result_fetched_at': datetime.now().isoformat(timespec='seconds'),
    }


def build_post_race_recalculation(df=None, magi_pred=None, source='live_fetch'):
    """事後再計算ブロック（pre-race の代替に使わない）。"""
    out = {
        'kind': 'post_race_recalculation',
        'source': source,
        'available': bool(df is not None and not getattr(df, 'empty', True)),
        'magi_pred_included': bool(magi_pred),
    }
    if out['available']:
        try:
            import pandas as pd
            cols = [c for c in ('Umaban', 'Name', 'Popularity', 'Odds', 'Projected Score', 'BattleScore')
                    if c in df.columns]
            preview = []
            for _, r in df.head(8).iterrows():
                preview.append({c: r.get(c) for c in cols})
            out['horse_preview'] = preview
        except Exception:
            out['horse_preview'] = []
    return out


def assemble_magi_review_bundle(
    race_id,
    purchase_batch_id=None,
    analysis_run_id=None,
    recommendation_id=None,
    post_df=None,
    post_magi_pred=None,
    actual_result=None,
    ledger: Optional[money.Ledger] = None,
    store: Optional[audit_store.AuditStore] = None,
):
    """MAGI用 A/B/C ブロック。

    purchase_batch_id='__all__' … 全 committed batch 合算（pre は最新 batch 基準）。
    """
    owned_ledger = ledger is None
    owned_store = store is None
    lg = ledger or money.Ledger()
    st = store or audit_store.AuditStore()
    try:
        pre_batch = purchase_batch_id
        if pre_batch in (None, '', '__all__'):
            pre_batch = _find_latest_committed_actual_batch_id(st, lg, race_id)
        pre = load_pre_race_snapshot(
            race_id, analysis_run_id=analysis_run_id,
            purchase_batch_id=pre_batch,
            recommendation_id=recommendation_id,
            store=st,
        )
        settled_scope = purchase_batch_id if purchase_batch_id else '__all__'
        settled = load_settled_result(
            lg, race_id, purchase_batch_id=settled_scope, store=st)
        post = build_post_race_recalculation(post_df, post_magi_pred)
        if actual_result:
            post['actual_result_attached'] = True
        return {
            'race_id': str(race_id),
            'pre_race_snapshot': pre,
            'settled_result': settled,
            'post_race_recalculation': post,
            'ids': {
                'analysis_run_id': pre.get('analysis_run_id'),
                'recommendation_id': pre.get('recommendation_id'),
                'purchase_batch_id': pre_batch,
                'purchase_scope': settled.get('scope'),
            },
            'purchase_batches_committed': _committed_actual_batch_ids(
                st, lg, race_id),
        }
    finally:
        if owned_ledger:
            lg.close()
        if owned_store:
            st.close()


def resolve_id_chain(
    bet_id=None,
    purchase_batch_id=None,
    race_id=None,
    ledger: Optional[money.Ledger] = None,
    store: Optional[audit_store.AuditStore] = None,
):
    """bet / batch から ID チェーンを逆引き。legacy は推測リンクしない。"""
    owned_l = ledger is None
    owned_s = store is None
    lg = ledger or money.Ledger()
    st = store or audit_store.AuditStore()
    try:
        bet = None
        if bet_id is not None:
            bet = money.bet_row_dict(lg.con.execute(
                "SELECT * FROM bets WHERE bet_id=?", (bet_id,)).fetchone())
        if bet:
            race_id = bet.get('race_id')
            purchase_batch_id = bet.get('purchase_batch_id') or purchase_batch_id
        batch = None
        if purchase_batch_id:
            row = st.con.execute(
                "SELECT * FROM purchase_batches WHERE purchase_batch_id=?",
                (purchase_batch_id,)).fetchone()
            batch = dict(row) if row else None
        ref = _parse_json_field((batch or {}).get('recommended_ref_json'))
        chain = {
            'race_id': race_id,
            'bet_id': (bet or {}).get('bet_id'),
            'purchase_batch_id': purchase_batch_id or (bet or {}).get('purchase_batch_id'),
            'recommendation_id': (
                (bet or {}).get('recommendation_id') or ref.get('recommendation_id')),
            'analysis_run_id': (
                (bet or {}).get('analysis_run_id')
                or (batch or {}).get('analysis_run_id')
                or ref.get('analysis_run_id')),
            'audit_link': (bet or {}).get('audit_link'),
        }
        if bet and not chain['audit_link'] and not chain['purchase_batch_id']:
            chain['audit_link'] = AUDIT_LINK_LEGACY
        if bet:
            chain['settlement_state'] = classify_bet_settlement(bet)
        return chain
    finally:
        if owned_l:
            lg.close()
        if owned_s:
            st.close()


def detect_settlement_correction_after_review(
    bet_id,
    review_created_ts,
    ledger: Optional[money.Ledger] = None,
):
    """回顧作成後の精算訂正を検出。"""
    lg = ledger or money.Ledger()
    owned = ledger is None
    try:
        logs = [money.bet_row_dict(r) for r in lg.con.execute(
            "SELECT * FROM bet_settlement_log WHERE bet_id=? ORDER BY ts",
            (bet_id,))]
        if not review_created_ts:
            return {'corrected_after_review': False, 'log_count': len(logs)}
        corrected = False
        for lgrow in logs:
            if lgrow.get('action') in ('reversal', 'correct'):
                if str(lgrow.get('ts') or '') > str(review_created_ts):
                    corrected = True
                    break
        return {'corrected_after_review': corrected, 'log_count': len(logs)}
    finally:
        if owned:
            lg.close()


def save_magi_review_record(
    race_id,
    review_bundle,
    used_pre_race_snapshot,
    used_post_race_recalc,
    result_fetched_ts=None,
    store: Optional[audit_store.AuditStore] = None,
):
    """MAGI回顧の監査記録（audit_events.stage=magi_review）。"""
    ids = (review_bundle or {}).get('ids') or {}
    pre = (review_bundle or {}).get('pre_race_snapshot') or {}
    run_id = ids.get('analysis_run_id') or pre.get('analysis_run_id')
    created = datetime.now().isoformat(timespec='seconds')
    payload = {
        'race_id': str(race_id),
        'analysis_run_id': run_id,
        'recommendation_id': ids.get('recommendation_id'),
        'purchase_batch_id': ids.get('purchase_batch_id'),
        'pre_race_snapshot_status': pre.get('status', 'unavailable'),
        'used_pre_race_snapshot': bool(used_pre_race_snapshot),
        'used_post_race_recalculation': bool(used_post_race_recalc),
        'result_fetched_ts': result_fetched_ts,
        'review_created_ts': created,
    }
    out = ap.record_event(
        race_id, 'magi_review', payload=payload, status='ok',
        analysis_run_id=run_id, store=store)
    return out, created
