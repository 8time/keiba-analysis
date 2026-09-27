# -*- coding: utf-8 -*-
"""購入 batch に固定された snapshot_event_ids からのみ pre-race を復元。"""
from __future__ import annotations

import json
from typing import Any, Optional

from core import audit_store

SNAPSHOT_NOT_RUN = 'NOT_RUN_AT_PURCHASE'

STAGE_PAYLOAD_KEYS = (
    'scanner', 'scanner_display', 'elim', 'sra', 'anabaka_hunter', 'recommendation',
)


def _parse(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or '{}')
    except Exception:
        return {}


def event_payload(store: audit_store.AuditStore, event_id: Optional[str]) -> dict:
    if not event_id or event_id == SNAPSHOT_NOT_RUN:
        return {}
    ev = store.get_event(event_id)
    if not ev:
        return {}
    return _parse(ev.get('payload_json'))


def resolve_snapshot_payloads(
    snapshot_event_ids: dict,
    store: audit_store.AuditStore,
) -> dict:
    """event_id → payload。NOT_RUN は空 dict。ID と payload は同一 event 由来。"""
    snap = snapshot_event_ids or {}
    out = {}
    for stage in ('scanner', 'scanner_display'):
        eid = snap.get(stage)
        if eid == SNAPSHOT_NOT_RUN:
            out[f'{stage}_payload'] = {}
            out[f'{stage}_event_id'] = SNAPSHOT_NOT_RUN
        elif eid:
            out[f'{stage}_payload'] = event_payload(store, eid)
            out[f'{stage}_event_id'] = eid
        else:
            out[f'{stage}_payload'] = {}
            out[f'{stage}_event_id'] = None
    for stage in ('elim', 'sra', 'anabaka_hunter', 'recommendation'):
        eid = snap.get(stage)
        if eid == SNAPSHOT_NOT_RUN:
            out[f'{stage}_payload'] = {}
            out[f'{stage}_event_id'] = SNAPSHOT_NOT_RUN
        elif eid:
            out[f'{stage}_payload'] = event_payload(store, eid)
            out[f'{stage}_event_id'] = eid
        else:
            out[f'{stage}_payload'] = {}
            out[f'{stage}_event_id'] = None
    rec_id = snap.get('recommendation')
    if rec_id == SNAPSHOT_NOT_RUN:
        out['recommendation_id'] = SNAPSHOT_NOT_RUN
        out['recommendation_payload'] = {}
    elif rec_id:
        out['recommendation_id'] = rec_id
        out['recommendation_payload'] = event_payload(store, rec_id)
    ah = out.get('anabaka_hunter_payload')
    if ah is not None:
        out['hunter_payload'] = ah
    return out
