# -*- coding: utf-8 -*-
"""購入 operation ID・実購入完全性・batch-only 分離・canonical 入力。"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core import audit_store
from core import money

PURCHASE_OPERATION_ID_MAX_LEN = 128

COMPLETION_SCOPE_BATCH_ONLY = 'batch_only'
COMPLETION_SCOPE_LEDGER_LINKED = 'ledger_linked'
RECORD_KIND_AUDIT_BATCH = 'audit_batch'
RECORD_KIND_ACTUAL_PURCHASE = 'actual_purchase'

GLOBAL_OP_INDEX_NAME = 'idx_purchase_operation_global'
EXPECTED_PARTIAL_WHERE_NORM = (
    "PURCHASE_OPERATION_ID IS NOT NULL AND PURCHASE_OPERATION_ID != ''"
)

PURCHASE_MODE_BATCH_ONLY = 'batch_only'
PURCHASE_MODE_LEDGER_LINKED = 'ledger_linked'

KNOWN_BET_TYPES = frozenset(money.BET_TYPE_RESULT_KEY.keys())
COMBO_LEN = {
    '単勝': 1, '複勝': 1,
    '馬連': 2, '馬単': 2, 'ワイド': 2, '枠連': 2,
    '3連複': 3, '3連単': 3,
}
WIN_PLACE_TYPES = frozenset({'単勝', '複勝'})

B4_META_KEYS = (
    'purchase_manifest',
    'purchase_manifest_hash',
    'completion_scope',
    'record_kind',
    'ledger_linked',
)


class PurchaseIntegrityError(RuntimeError):
    """購入 transaction 内 validator 失敗。"""


@dataclass(frozen=True)
class PurchaseRequestContext:
    race_id: str
    operation_id: str
    purchase_mode: str
    analysis_run_id: str
    recommendation_id: str
    purchase_fingerprint: Optional[str] = None


def normalize_purchase_operation_id(raw) -> Tuple[Optional[str], Optional[str]]:
    if raw is None:
        return None, 'operation_id_required'
    op = str(raw).strip()
    if not op:
        return None, 'operation_id_required'
    if len(op) > PURCHASE_OPERATION_ID_MAX_LEN:
        return None, 'operation_id_too_long'
    return op, None


def require_shared_connection(ledger, store, *, require_ledger=True) -> Optional[str]:
    if store is None:
        return 'audit_store_required'
    if require_ledger:
        if ledger is None or ledger.con is not store.con:
            return 'audit_connection_mismatch'
    elif ledger is not None and ledger.con is not store.con:
        return 'audit_connection_mismatch'
    return None


def _batch_meta(batch: dict) -> dict:
    try:
        return json.loads(batch.get('meta_json') or '{}')
    except Exception:
        return {}


def _strict_meta_bool(val) -> Optional[bool]:
    if val is True:
        return True
    if val is False:
        return False
    return None


def _horse_ok(n: int) -> bool:
    return 1 <= int(n) <= 18


_FW_DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')


def _parse_strict_stake(raw):
    """金額は正の整数だけ。float 切り捨て・bool・負数は拒否。"""
    if isinstance(raw, bool) or isinstance(raw, float):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        s = raw.strip().translate(_FW_DIGITS)
        if not s or not s.isdigit():
            return None
        n = int(s)
        return n if n > 0 else None
    return None


def _horse_from_token(part: str):
    s = str(part or '').strip().translate(_FW_DIGITS)
    if not s or not re.fullmatch(r'[0-9]+', s):
        return None
    n = int(s)
    if not _horse_ok(n):
        return None
    return n


def _strict_combo_numbers(kind: str, label):
    """馬番トークンだけを受ける。数字の拾い出し・object の str 化はしない。"""
    if not isinstance(label, str):
        return None, 'invalid_purchase_line'
    s = label.strip()
    if not s:
        return None, 'invalid_purchase_line'
    if '→' in s and '-' in s:
        return None, 'invalid_purchase_line'
    if '→' in s:
        parts = s.split('→')
    elif '-' in s:
        parts = s.split('-')
    else:
        parts = [s]
    if any(not str(p).strip() for p in parts):
        return None, 'invalid_purchase_line'
    nums = []
    for p in parts:
        n = _horse_from_token(p)
        if n is None:
            return None, 'invalid_purchase_line'
        nums.append(n)
    if len(nums) != len(set(nums)):
        return None, 'invalid_purchase_line'
    need = COMBO_LEN.get(kind)
    if need is not None and len(nums) != need:
        return None, 'invalid_combo_length'
    if kind in ('馬連', '3連複', 'ワイド', '枠連'):
        nums = sorted(nums)
    return nums, None


def combo_to_bamei(bet_type: str, combo: List[int]) -> str:
    btype = str(bet_type or '').strip()
    nums = [int(x) for x in combo]
    if btype in money.ORDERED_BET_TYPES:
        return '-'.join(str(x) for x in nums)
    if btype in ('馬連', '3連複', 'ワイド', '枠連'):
        return '-'.join(str(x) for x in sorted(nums))
    if len(nums) == 1:
        return str(nums[0])
    return '-'.join(str(x) for x in nums)


def _extract_raw_line_fields(ln: dict) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    if not isinstance(ln, dict):
        return None, None, None, 'purchase_line_not_object'
    kind_raw = ln.get('kind') if 'kind' in ln else None
    kjp_kind_raw = ln.get('券種') if '券種' in ln else None
    label_raw = ln.get('label') if 'label' in ln else None
    kjp_label_raw = ln.get('買い目') if '買い目' in ln else None
    for raw in (kind_raw, kjp_kind_raw, label_raw, kjp_label_raw):
        if raw is not None and not isinstance(raw, str):
            return None, None, None, 'invalid_purchase_line'
    has_kind = isinstance(kind_raw, str) and kind_raw.strip() != ''
    has_kjp_kind = isinstance(kjp_kind_raw, str) and kjp_kind_raw.strip() != ''
    has_label = isinstance(label_raw, str) and label_raw.strip() != ''
    has_kjp_label = isinstance(kjp_label_raw, str) and kjp_label_raw.strip() != ''
    if has_kind and has_kjp_kind and kind_raw.strip() != kjp_kind_raw.strip():
        return None, None, None, 'purchase_line_ambiguous_keys'
    if has_label and has_kjp_label and label_raw.strip() != kjp_label_raw.strip():
        return None, None, None, 'purchase_line_ambiguous_keys'
    kind = (kind_raw if has_kind else (kjp_kind_raw if has_kjp_kind else '')) or ''
    kind = kind.strip()
    label = label_raw if has_label else (kjp_label_raw if has_kjp_label else '')
    if label is None:
        label = ''
    stake_raw = ln.get('stake') if 'stake' in ln else None
    if stake_raw is None:
        return None, None, None, 'invalid_stake'
    return kind, label, stake_raw, None


def canonicalize_purchase_input(raw_lines) -> Tuple[Optional[List[dict]], Optional[str]]:
    """購入 API 入口で一度だけ正規化。以後 manifest / bets / lines はこれのみ使用。"""
    if not raw_lines:
        return None, 'no purchase lines with stake'
    out: List[dict] = []
    for ln in raw_lines:
        kind, label, stake_raw, key_err = _extract_raw_line_fields(ln)
        if key_err:
            return None, key_err
        if not kind:
            return None, 'unknown_bet_type'
        if kind not in KNOWN_BET_TYPES:
            return None, 'unknown_bet_type'
        stake = _parse_strict_stake(stake_raw)
        if stake is None:
            return None, 'invalid_stake'
        combo, combo_err = _strict_combo_numbers(kind, label)
        if combo_err:
            return None, combo_err
        bamei = combo_to_bamei(kind, combo)
        umaban = combo[0] if kind in WIN_PLACE_TYPES else None
        out.append({
            'bet_type': kind,
            'combo': combo,
            'stake': stake,
            'bamei': bamei,
            'umaban': umaban,
        })
    if not out:
        return None, 'no purchase lines with stake'
    out.sort(key=lambda x: (x['bet_type'], tuple(x['combo']), x['stake']))
    return out, None


def canonical_lines_to_storage_lines(canonical: List[dict]) -> List[dict]:
    return [
        {'kind': c['bet_type'], 'label': c['bamei'], 'stake': int(c['stake'])}
        for c in (canonical or [])
    ]


def manifest_from_canonical_lines(canonical: List[dict]) -> List[dict]:
    return canonicalize_manifest([
        {'bet_type': c['bet_type'], 'combo': list(c['combo']), 'stake': int(c['stake'])}
        for c in (canonical or [])
    ])


def build_purchase_manifest_from_lines(purchase_lines) -> List[dict]:
    canonical, err = canonicalize_purchase_input(purchase_lines)
    if err or not canonical:
        return []
    return manifest_from_canonical_lines(canonical)


def canonicalize_manifest(entries: List[dict]) -> List[dict]:
    out = []
    for e in entries or []:
        if e is None or not isinstance(e, dict):
            continue
        try:
            if isinstance(e.get('stake'), bool) or isinstance(e.get('stake'), float):
                continue
            stake = int(e.get('stake'))
        except (TypeError, ValueError, OverflowError):
            continue
        out.append({
            'bet_type': str(e.get('bet_type') or '').strip(),
            'combo': [int(x) for x in (e.get('combo') or [])],
            'stake': stake,
        })
    out.sort(key=lambda x: (x['bet_type'], tuple(x['combo']), x['stake']))
    return out


def purchase_manifest_hash(manifest: List[dict]) -> str:
    payload = json.dumps(
        canonicalize_manifest(manifest),
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _manifest_entry_key(entry: dict) -> Tuple:
    return (
        str(entry.get('bet_type') or '').strip(),
        tuple(int(x) for x in (entry.get('combo') or [])),
        int(entry.get('stake') or 0),
    )


def _safe_manifest_from_meta(raw) -> Tuple[Optional[List[dict]], Optional[str]]:
    if raw is None:
        return None, 'missing_purchase_manifest'
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None, 'manifest_not_list'
    if not isinstance(raw, list):
        return None, 'manifest_not_list'
    if not raw:
        return None, 'missing_purchase_manifest'
    if any(item is None for item in raw):
        return None, 'manifest_null_entry'
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            return None, 'manifest_entry_not_object'
        if 'bet_type' not in item or 'combo' not in item or 'stake' not in item:
            return None, 'manifest_missing_keys'
        try:
            if isinstance(item['stake'], bool) or isinstance(item['stake'], float):
                return None, 'manifest_invalid_stake'
            stake = int(item['stake'])
        except (TypeError, ValueError, OverflowError):
            return None, 'manifest_invalid_stake'
        if stake <= 0:
            return None, 'manifest_invalid_stake'
        btype = str(item.get('bet_type') or '').strip()
        if btype not in KNOWN_BET_TYPES:
            return None, 'manifest_unknown_bet_type'
        combo_raw = item.get('combo')
        if not isinstance(combo_raw, (list, tuple)):
            return None, 'manifest_invalid_combo'
        try:
            if any(isinstance(x, bool) or isinstance(x, float) for x in combo_raw):
                return None, 'manifest_invalid_combo'
            combo = [int(x) for x in combo_raw]
        except (TypeError, ValueError, OverflowError):
            return None, 'manifest_invalid_combo'
        need = COMBO_LEN.get(btype)
        if need is not None and len(combo) != need:
            return None, 'manifest_invalid_combo_length'
        if not all(_horse_ok(x) for x in combo):
            return None, 'manifest_invalid_horse'
        entries.append({'bet_type': btype, 'combo': combo, 'stake': stake})
    return canonicalize_manifest(entries), None


def _manifest_from_lines_json(batch: dict) -> Tuple[Optional[List[dict]], Optional[str]]:
    try:
        lines = json.loads(batch.get('lines_json') or '[]')
    except Exception:
        return None, 'lines_json_invalid'
    if not isinstance(lines, list):
        return None, 'lines_json_invalid'
    canonical, err = canonicalize_purchase_input(lines)
    if err:
        return None, f'lines_json_{err}'
    return manifest_from_canonical_lines(canonical or []), None


def _bet_to_manifest_entry(bet: dict) -> Optional[dict]:
    btype = str(bet.get('bet_type') or '').strip()
    label = str(bet.get('bamei') or bet.get('label') or '')
    try:
        st = int(bet.get('stake') or 0)
    except (TypeError, ValueError):
        st = 0
    if st <= 0:
        return None
    parsed = money.parse_bet_label(btype, label)
    if not parsed:
        return None
    return {
        'bet_type': btype,
        'combo': [int(x) for x in parsed],
        'stake': st,
    }


def _win_place_umaban_consistent(btype: str, combo: List[int], bet: dict) -> Optional[str]:
    if btype not in WIN_PLACE_TYPES:
        return None
    horse = int(combo[0])
    try:
        uma = int(bet.get('umaban') or 0)
    except (TypeError, ValueError):
        uma = 0
    label = str(bet.get('bamei') or '')
    parsed = money.parse_bet_label(btype, label)
    label_horse = int(parsed[0]) if parsed and len(parsed) == 1 else None
    if uma != horse:
        return 'umaban_mismatch'
    if label_horse is not None and label_horse != horse:
        return 'bamei_horse_mismatch'
    return None


def _batch_operation_id(batch: dict, meta: dict) -> str:
    op = batch.get('purchase_operation_id')
    if op is None or str(op).strip() == '':
        op = meta.get('purchase_operation_id')
    return str(op or '').strip()


def batch_matches_purchase_request(
    store: audit_store.AuditStore,
    batch_id: str,
    request: PurchaseRequestContext,
    *,
    match_operation_id: bool = True,
) -> Tuple[bool, Optional[str]]:
    batch = store.get_purchase_batch(batch_id)
    if not batch:
        return False, 'duplicate_context_mismatch'
    meta = _batch_meta(batch)
    if str(batch.get('race_id') or '').strip() != str(request.race_id or '').strip():
        return False, 'duplicate_context_mismatch'
    if match_operation_id and (
            _batch_operation_id(batch, meta) != str(request.operation_id or '').strip()):
        return False, 'duplicate_context_mismatch'
    if str(batch.get('analysis_run_id') or '').strip() != str(request.analysis_run_id or '').strip():
        return False, 'duplicate_context_mismatch'
    ref = {}
    try:
        ref = json.loads(batch.get('recommended_ref_json') or '{}')
    except Exception:
        ref = {}
    rec_id = str(ref.get('recommendation_id') or '').strip()
    if rec_id != str(request.recommendation_id or '').strip():
        return False, 'duplicate_context_mismatch'
    scope = str(meta.get('completion_scope') or '').strip()
    if request.purchase_mode == PURCHASE_MODE_LEDGER_LINKED:
        if scope != COMPLETION_SCOPE_LEDGER_LINKED:
            return False, 'duplicate_context_mismatch'
    elif request.purchase_mode == PURCHASE_MODE_BATCH_ONLY:
        if scope != COMPLETION_SCOPE_BATCH_ONLY:
            return False, 'duplicate_context_mismatch'
    if request.purchase_fingerprint:
        if str(meta.get('fingerprint') or '') != str(request.purchase_fingerprint):
            return False, 'duplicate_context_mismatch'
    return True, None


def validate_committed_actual_purchase(
    store: audit_store.AuditStore,
    ledger,
    batch_id: str,
    *,
    require_ledger: bool = True,
) -> Dict[str, Any]:
    try:
        return _validate_committed_actual_purchase_impl(
            store, ledger, batch_id, require_ledger=require_ledger)
    except OverflowError:
        return {
            'valid': False,
            'state': 'inconsistent',
            'reason': 'numeric_overflow',
            'details': {'purchase_batch_id': batch_id},
        }


def _validate_committed_actual_purchase_impl(
    store: audit_store.AuditStore,
    ledger,
    batch_id: str,
    *,
    require_ledger: bool = True,
) -> Dict[str, Any]:
    batch = store.get_purchase_batch(batch_id)
    if not batch:
        return {
            'valid': False,
            'state': 'failed',
            'reason': 'batch_not_found',
            'details': {'purchase_batch_id': batch_id},
        }
    stat = str(batch.get('record_status') or 'ok')
    meta = _batch_meta(batch)
    rid = str(batch.get('race_id') or '').strip()
    run_id = str(batch.get('analysis_run_id') or '').strip()
    ref = {}
    try:
        ref = json.loads(batch.get('recommended_ref_json') or '{}')
    except Exception:
        ref = {}
    rec_id = str(ref.get('recommendation_id') or '').strip()

    scope = str(meta.get('completion_scope') or '').strip()
    kind = str(meta.get('record_kind') or '').strip()
    ledger_linked = _strict_meta_bool(meta.get('ledger_linked'))

    base_details = {
        'purchase_batch_id': batch_id,
        'record_status': stat,
        'completion_scope': scope,
        'record_kind': kind,
        'ledger_linked': ledger_linked,
    }

    if stat == audit_store.BATCH_FAILED:
        return {'valid': False, 'state': 'failed', 'reason': 'batch_failed', 'details': base_details}
    if stat == audit_store.BATCH_PENDING:
        return {'valid': False, 'state': 'pending', 'reason': 'purchase_incomplete', 'details': base_details}
    if not audit_store.is_batch_committed(stat):
        return {'valid': False, 'state': 'failed', 'reason': 'batch_not_committed', 'details': base_details}

    if scope == COMPLETION_SCOPE_BATCH_ONLY or kind == RECORD_KIND_AUDIT_BATCH:
        return {
            'valid': False, 'state': 'batch_only',
            'reason': 'batch_only_not_actual_purchase', 'details': base_details,
        }

    b4_ok = all(k in meta for k in B4_META_KEYS)
    if not b4_ok:
        return {
            'valid': False, 'state': 'legacy_unverified',
            'reason': 'legacy_missing_b4_evidence', 'details': base_details,
        }

    if scope != COMPLETION_SCOPE_LEDGER_LINKED:
        return {'valid': False, 'state': 'inconsistent', 'reason': 'invalid_completion_scope', 'details': base_details}
    if kind != RECORD_KIND_ACTUAL_PURCHASE:
        return {'valid': False, 'state': 'inconsistent', 'reason': 'invalid_record_kind', 'details': base_details}
    if ledger_linked is not True:
        return {'valid': False, 'state': 'inconsistent', 'reason': 'invalid_ledger_linked', 'details': base_details}

    if ledger is None and require_ledger:
        return {'valid': False, 'state': 'inconsistent', 'reason': 'ledger_required', 'details': base_details}

    manifest, m_err = _safe_manifest_from_meta(meta.get('purchase_manifest'))
    if m_err:
        return {'valid': False, 'state': 'inconsistent', 'reason': m_err, 'details': base_details}

    lines_manifest, l_err = _manifest_from_lines_json(batch)
    if l_err:
        return {'valid': False, 'state': 'inconsistent', 'reason': l_err, 'details': base_details}

    if Counter(_manifest_entry_key(x) for x in (manifest or [])) != Counter(
            _manifest_entry_key(x) for x in (lines_manifest or [])):
        return {
            'valid': False, 'state': 'inconsistent',
            'reason': 'manifest_lines_mismatch', 'details': base_details,
        }

    stored_hash = str(meta.get('purchase_manifest_hash') or '').strip()
    if not stored_hash:
        return {'valid': False, 'state': 'inconsistent', 'reason': 'missing_manifest_hash', 'details': base_details}
    calc_hash = purchase_manifest_hash(manifest or [])
    if stored_hash != calc_hash:
        return {
            'valid': False, 'state': 'inconsistent', 'reason': 'manifest_hash_mismatch',
            'details': {**base_details, 'expected_hash': stored_hash, 'calc_hash': calc_hash},
        }

    sum_manifest = sum(int(x['stake']) for x in (manifest or []))
    try:
        if isinstance(meta.get('total_stake'), bool) or isinstance(meta.get('total_stake'), float):
            raise ValueError('non-int total')
        total_meta = int(meta.get('total_stake'))
    except (TypeError, ValueError, OverflowError):
        return {'valid': False, 'state': 'inconsistent', 'reason': 'invalid_total_stake', 'details': base_details}

    rows = ledger.con.execute(
        f"""SELECT * FROM bets WHERE purchase_batch_id=? AND {money.ACTUAL_PURCHASE_SQL}""",
        (batch_id, money.BET_PURPOSE_ACTUAL),
    ).fetchall()
    bets = [money.bet_row_dict(r) for r in rows]
    sum_bets = sum(int(b.get('stake') or 0) for b in bets)
    stake_details = {
        'sum_manifest': sum_manifest,
        'meta_total_stake': total_meta,
        'sum_actual_bets': sum_bets,
    }
    if not (sum_manifest == total_meta == sum_bets):
        return {
            'valid': False, 'state': 'inconsistent', 'reason': 'stake_totals_mismatch',
            'details': {**base_details, **stake_details},
        }
    if len(bets) != len(manifest or []):
        return {
            'valid': False, 'state': 'inconsistent', 'reason': 'bet_count_mismatch',
            'details': {**base_details, **stake_details, 'expected_count': len(manifest or []), 'actual_count': len(bets)},
        }

    exp_counter = Counter(_manifest_entry_key(e) for e in (manifest or []))
    act_entries = []
    field_errors = []
    for b in bets:
        if money.bet_row_effective_purpose(b) != money.BET_PURPOSE_ACTUAL:
            field_errors.append('non_actual_purpose_bet')
        if str(b.get('race_id') or '').strip() != rid:
            field_errors.append('race_id_mismatch')
        if str(b.get('analysis_run_id') or '').strip() != run_id:
            field_errors.append('analysis_run_id_mismatch')
        if str(b.get('recommendation_id') or '').strip() != rec_id:
            field_errors.append('recommendation_id_mismatch')
        if str(b.get('purchase_batch_id') or '').strip() != batch_id:
            field_errors.append('purchase_batch_id_mismatch')
        ent = _bet_to_manifest_entry(b)
        if not ent:
            field_errors.append('unparseable_bet_label')
        else:
            act_entries.append(ent)
            wp_err = _win_place_umaban_consistent(ent['bet_type'], ent['combo'], b)
            if wp_err:
                field_errors.append(wp_err)

    act_counter = Counter(_manifest_entry_key(e) for e in act_entries)
    if exp_counter != act_counter:
        return {
            'valid': False, 'state': 'inconsistent', 'reason': 'manifest_bets_mismatch',
            'details': {**base_details, **stake_details, 'field_errors': field_errors},
        }
    if field_errors:
        return {
            'valid': False, 'state': 'inconsistent', 'reason': field_errors[0],
            'details': {**base_details, **stake_details, 'field_errors': field_errors},
        }

    return {
        'valid': True,
        'state': 'committed_actual',
        'reason': None,
        'details': {**base_details, **stake_details, 'bet_count': len(bets)},
    }


def assert_api_success_implies_committed_actual(store, ledger, batch_id: str) -> None:
    val = validate_committed_actual_purchase(store, ledger, batch_id)
    if not val.get('valid') or val.get('state') != 'committed_actual':
        raise PurchaseIntegrityError(val.get('reason') or 'purchase_inconsistent')


def classify_purchase_batch_state(
    store: audit_store.AuditStore,
    ledger,
    batch_id: str,
) -> str:
    val = validate_committed_actual_purchase(store, ledger, batch_id)
    state = val.get('state') or 'failed'
    if state == 'committed_actual':
        return 'committed'
    return state


def duplicate_success_for_batch(
    store: audit_store.AuditStore,
    ledger,
    batch_id: str,
    *,
    purchase_mode: str = PURCHASE_MODE_LEDGER_LINKED,
    request: Optional[PurchaseRequestContext] = None,
    match_operation_id: bool = True,
) -> Tuple[bool, Optional[str]]:
    batch = store.get_purchase_batch(batch_id)
    meta = _batch_meta(batch) if batch else {}
    scope = str(meta.get('completion_scope') or '').strip()
    if purchase_mode == PURCHASE_MODE_LEDGER_LINKED:
        if scope == COMPLETION_SCOPE_BATCH_ONLY or meta.get('record_kind') == RECORD_KIND_AUDIT_BATCH:
            return False, 'operation_scope_conflict'
    val = validate_committed_actual_purchase(store, ledger, batch_id)
    state = val.get('state')
    if purchase_mode == PURCHASE_MODE_LEDGER_LINKED:
        if state == 'legacy_unverified':
            return False, 'purchase_inconsistent'
        if state == 'pending':
            return False, 'purchase_incomplete'
        if state == 'failed':
            return False, 'purchase_incomplete'
        if state == 'batch_only':
            return False, 'operation_scope_conflict'
        if state == 'inconsistent':
            return False, 'purchase_inconsistent'
        if state == 'committed_actual' and val.get('valid'):
            if request is None:
                return False, 'duplicate_context_mismatch'
            ok_ctx, ctx_err = batch_matches_purchase_request(
                store, batch_id, request, match_operation_id=match_operation_id)
            if not ok_ctx:
                return False, ctx_err or 'duplicate_context_mismatch'
            return True, None
        return False, 'purchase_inconsistent'
    if state == 'batch_only' and not val.get('valid'):
        batch = store.get_purchase_batch(batch_id)
        if batch and audit_store.is_batch_committed(str(batch.get('record_status') or '')):
            return True, None
    if state == 'committed_actual':
        return False, 'operation_scope_conflict'
    if state == 'pending':
        return False, 'purchase_incomplete'
    if state == 'inconsistent':
        return False, 'purchase_inconsistent'
    return False, 'purchase_incomplete'


def evaluate_operation_id_replay(
    store: audit_store.AuditStore,
    ledger,
    operation_id: str,
    race_id: str,
    *,
    purchase_mode: str = PURCHASE_MODE_LEDGER_LINKED,
    request: Optional[PurchaseRequestContext] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    row = store.find_purchase_batch_by_operation_id(operation_id)
    if not row:
        return None, None, None
    bid = row['purchase_batch_id']
    if str(row.get('race_id') or '') != str(race_id or '').strip():
        return bid, None, 'operation_id_race_conflict'
    ok, err = duplicate_success_for_batch(
        store, ledger, bid, purchase_mode=purchase_mode, request=request)
    if ok:
        return bid, 'duplicate_ok', None
    return bid, None, err or 'purchase_inconsistent'


def _normalize_index_where(clause: str) -> str:
    s = re.sub(r'\s+', ' ', str(clause or '').strip())
    s = s.replace('\n', ' ').replace('\r', ' ')
    s = s.upper()
    s = re.sub(r"!=\s*''", "!= ''", s)
    s = re.sub(r'!=\s*""', "!= ''", s)
    return s.strip()


def _extract_create_index_where(sql: str) -> Optional[str]:
    m = re.search(r'\bWHERE\b(.+?)(?:\)|;)?\s*$', sql or '', re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    clause = m.group(1).strip()
    if clause.endswith(')'):
        clause = clause[:-1].strip()
    return clause


def verify_purchase_operation_global_index_metadata(con) -> None:
    row = con.execute(
        """SELECT sql, tbl_name FROM sqlite_master
           WHERE type='index' AND name=?""",
        (GLOBAL_OP_INDEX_NAME,),
    ).fetchone()
    if not row or not row[0]:
        raise audit_store.AuditSchemaError(f'missing index {GLOBAL_OP_INDEX_NAME}')
    sql = str(row[0] or '')
    tbl_name = str(row[1] or '')
    if tbl_name != 'purchase_batches':
        raise audit_store.AuditSchemaError(
            f'{GLOBAL_OP_INDEX_NAME} on table {tbl_name!r}, expected purchase_batches')

    listed = con.execute("PRAGMA index_list('purchase_batches')").fetchall()
    idx_row = None
    for r in listed:
        name = r[1] if len(r) > 1 else r['name']
        if name == GLOBAL_OP_INDEX_NAME:
            idx_row = r
            break
    if idx_row is None:
        raise audit_store.AuditSchemaError(
            f'{GLOBAL_OP_INDEX_NAME} not in PRAGMA index_list(purchase_batches)')

    unique_flag = idx_row[2] if len(idx_row) > 2 else idx_row['unique']
    if not int(unique_flag or 0):
        raise audit_store.AuditSchemaError(f'{GLOBAL_OP_INDEX_NAME} must be UNIQUE')

    partial_flag = idx_row[4] if len(idx_row) > 4 else 0
    if not int(partial_flag or 0):
        raise audit_store.AuditSchemaError(
            f'{GLOBAL_OP_INDEX_NAME} must be a partial index')

    info = con.execute(f"PRAGMA index_xinfo('{GLOBAL_OP_INDEX_NAME}')").fetchall()
    key_cols = []
    for r in info:
        seq = r[0] if len(r) > 0 else None
        col_name = r[2] if len(r) > 2 else None
        coll = r[4] if len(r) > 4 else None
        key_flag = r[5] if len(r) > 5 else 1
        if seq is None or int(seq) < 0 or not col_name:
            continue
        if int(key_flag or 0) == 0:
            continue
        key_cols.append(str(col_name))
        coll_name = str(coll or 'BINARY').upper()
        if coll_name != 'BINARY':
            raise audit_store.AuditSchemaError(
                f'{GLOBAL_OP_INDEX_NAME} collation {coll_name} is not BINARY')
    if key_cols != ['purchase_operation_id']:
        raise audit_store.AuditSchemaError(
            f'{GLOBAL_OP_INDEX_NAME} key columns {key_cols!r} != [purchase_operation_id]')

    where_raw = _extract_create_index_where(sql)
    if not where_raw:
        raise audit_store.AuditSchemaError(f'{GLOBAL_OP_INDEX_NAME} missing WHERE clause')
    norm_where = _normalize_index_where(where_raw)
    if norm_where != EXPECTED_PARTIAL_WHERE_NORM:
        raise audit_store.AuditSchemaError(
            f'{GLOBAL_OP_INDEX_NAME} partial WHERE mismatch: {norm_where!r}')
    if 'NOCASE' in sql.upper():
        raise audit_store.AuditSchemaError(
            f'{GLOBAL_OP_INDEX_NAME} must not use COLLATE NOCASE')
