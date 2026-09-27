# -*- coding: utf-8 -*-
"""
フェーズA: 判断・推奨・購入の監査記録（追記専用）。

画面用 score_cache は従来どおり。ここは ledger.db 上の別テーブル群。
計算ロジックは呼ばず、呼び出し側が渡した payload を JSON で保存する。
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
import datetime

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(_BASE, 'data', 'ledger.db')

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS analysis_runs (
  analysis_run_id TEXT PRIMARY KEY,
  race_id TEXT NOT NULL,
  created_ts TEXT NOT NULL,
  input_hash TEXT,
  rule_version TEXT,
  settings_json TEXT,
  code_ref TEXT,
  cache_hint TEXT,
  meta_json TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  analysis_run_id TEXT,
  race_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  created_ts TEXT NOT NULL,
  payload_json TEXT,
  FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(analysis_run_id)
);

CREATE TABLE IF NOT EXISTS audit_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  analysis_run_id TEXT,
  race_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_ts TEXT NOT NULL,
  payload_json TEXT,
  FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs(analysis_run_id)
);

CREATE TABLE IF NOT EXISTS purchase_batches (
  purchase_batch_id TEXT PRIMARY KEY,
  analysis_run_id TEXT,
  race_id TEXT NOT NULL,
  created_ts TEXT NOT NULL,
  lines_json TEXT,
  recommended_ref_json TEXT,
  meta_json TEXT,
  record_status TEXT DEFAULT 'ok'
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_race
  ON analysis_runs(race_id, created_ts);
CREATE INDEX IF NOT EXISTS idx_audit_events_run
  ON audit_events(analysis_run_id, created_ts);
CREATE INDEX IF NOT EXISTS idx_audit_events_race
  ON audit_events(race_id, created_ts);
CREATE INDEX IF NOT EXISTS idx_purchase_batches_race
  ON purchase_batches(race_id, created_ts);
"""

_VALID_EVENT_STATUS = frozenset({'ok', 'skipped', 'failed', 'not_run'})

REQUIRED_AUDIT_TABLES = frozenset({
    'analysis_runs', 'audit_events', 'audit_snapshots', 'purchase_batches',
})
REQUIRED_PURCHASE_BATCH_COLUMNS = frozenset({
    'purchase_batch_id', 'race_id', 'purchase_operation_id', 'meta_json',
})


class AuditSchemaError(RuntimeError):
    """監査DBスキーマ migration / 検証失敗。"""

# purchase_batches.record_status（'ok' は step5 以前の committed 相当）
BATCH_COMMITTED = frozenset({'ok', 'committed'})
BATCH_PENDING = 'pending'
BATCH_FAILED = 'failed'
BATCH_COMMITTED_NEW = 'committed'


def is_batch_committed(record_status):
    return str(record_status or 'ok') in BATCH_COMMITTED


def _now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), default=str)


def _parse_meta_operation_id(meta_json):
    try:
        meta = json.loads(meta_json or '{}')
    except Exception:
        meta = {}
    op = str(meta.get('purchase_operation_id') or '').strip()
    return op or None


def _backfill_purchase_operation_ids(con):
    """meta_json.purchase_operation_id → 列へ。グローバル重複は失敗。"""
    prev_rf = con.row_factory
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT purchase_batch_id, race_id, meta_json, purchase_operation_id
           FROM purchase_batches""").fetchall()
    op_owner = {}
    conflicts = []
    updates = []
    for row in rows:
        bid = row['purchase_batch_id']
        rid = row['race_id']
        col = str(row['purchase_operation_id'] or '').strip()
        op = col or _parse_meta_operation_id(row['meta_json'])
        if not op:
            continue
        if op in op_owner:
            prev_bid, prev_rid = op_owner[op]
            conflicts.append((op, prev_bid, prev_rid, bid, rid))
        else:
            op_owner[op] = (bid, rid)
        if not col:
            updates.append((op, bid))
    if conflicts:
        sample = conflicts[0]
        raise AuditSchemaError(
            f'purchase_operation_id conflict op={sample[0]!r} '
            f'batches {sample[1]}/{sample[3]} races {sample[2]}/{sample[4]}')
    for op, bid in updates:
        con.execute(
            "UPDATE purchase_batches SET purchase_operation_id=? "
            "WHERE purchase_batch_id=? AND (purchase_operation_id IS NULL OR purchase_operation_id='')",
            (op, bid))
    con.row_factory = prev_rf


def ensure_schema(con):
    """監査テーブルを idempotent に作成。"""
    con.executescript(_AUDIT_DDL)
    try:
        con.execute(
            "ALTER TABLE purchase_batches ADD COLUMN purchase_operation_id TEXT")
    except sqlite3.OperationalError as e:
        if 'duplicate column' not in str(e).lower():
            raise AuditSchemaError(f'ALTER purchase_operation_id: {e}') from e
    _backfill_purchase_operation_ids(con)
    con.execute("DROP INDEX IF EXISTS idx_purchase_operation_id")
    con.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_operation_global
           ON purchase_batches(purchase_operation_id)
           WHERE purchase_operation_id IS NOT NULL AND purchase_operation_id != ''""")
    con.commit()


def _verify_purchase_operation_global_index(con):
    from core import audit_purchase as apur
    apur.verify_purchase_operation_global_index_metadata(con)


def verify_audit_schema(con):
    """必須テーブル・列・index の存在確認。"""
    tables = {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    missing = REQUIRED_AUDIT_TABLES - tables
    if missing:
        raise AuditSchemaError(f'missing audit tables: {sorted(missing)}')
    cols = {
        r[1] for r in con.execute("PRAGMA table_info(purchase_batches)").fetchall()
    }
    missing_cols = REQUIRED_PURCHASE_BATCH_COLUMNS - cols
    if missing_cols:
        raise AuditSchemaError(f'missing purchase_batches columns: {sorted(missing_cols)}')
    _verify_purchase_operation_global_index(con)


class AuditStore:
    """ledger.db 共有接続または独立接続で監査記録を追記する。"""

    def __init__(self, con=None, db=DEFAULT_DB):
        self._owned = con is None
        if con is not None:
            self.con = con
        else:
            os.makedirs(os.path.dirname(db), exist_ok=True)
            self.con = sqlite3.connect(db)
            self.con.row_factory = sqlite3.Row
        ensure_schema(self.con)

    def create_analysis_run(
        self,
        race_id,
        input_hash=None,
        rule_version=None,
        settings=None,
        code_ref=None,
        cache_hint=None,
        meta=None,
        analysis_run_id=None,
    ):
        """新しい analysis_run_id を発行して保存。"""
        rid = str(race_id or '').strip()
        if not rid:
            raise ValueError('race_id required')
        run_id = (analysis_run_id or uuid.uuid4().hex)
        ts = _now_iso()
        self.con.execute(
            """INSERT INTO analysis_runs(
                 analysis_run_id, race_id, created_ts, input_hash, rule_version,
                 settings_json, code_ref, cache_hint, meta_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id, rid, ts, input_hash, rule_version,
                _json_dumps(settings) if settings is not None else None,
                code_ref,
                cache_hint,
                _json_dumps(meta) if meta is not None else None,
            ),
        )
        self.con.commit()
        return run_id

    def append_event(
        self,
        analysis_run_id,
        race_id,
        stage,
        payload=None,
        status='ok',
    ):
        """工程イベントを追記。status: ok / skipped / failed / not_run"""
        rid = str(race_id or '').strip()
        stg = str(stage or '').strip()
        if not rid or not stg:
            raise ValueError('race_id and stage required')
        stat = str(status or 'ok').strip()
        if stat not in _VALID_EVENT_STATUS:
            stat = 'ok'
        event_id = uuid.uuid4().hex
        ts = _now_iso()
        self.con.execute(
            """INSERT INTO audit_events(
                 event_id, analysis_run_id, race_id, stage, status, created_ts, payload_json)
               VALUES(?,?,?,?,?,?,?)""",
            (
                event_id, analysis_run_id, rid, stg, stat, ts,
                _json_dumps(payload) if payload is not None else None,
            ),
        )
        self.con.commit()
        return event_id

    def append_snapshot(self, analysis_run_id, race_id, kind, payload):
        """事前スナップショットを追記。"""
        rid = str(race_id or '').strip()
        k = str(kind or '').strip()
        if not rid or not k:
            raise ValueError('race_id and kind required')
        snapshot_id = uuid.uuid4().hex
        ts = _now_iso()
        self.con.execute(
            """INSERT INTO audit_snapshots(
                 snapshot_id, analysis_run_id, race_id, kind, created_ts, payload_json)
               VALUES(?,?,?,?,?,?)""",
            (snapshot_id, analysis_run_id, rid, k, ts, _json_dumps(payload)),
        )
        self.con.commit()
        return snapshot_id

    def get_analysis_run(self, analysis_run_id):
        row = self.con.execute(
            "SELECT * FROM analysis_runs WHERE analysis_run_id=?",
            (analysis_run_id,)).fetchone()
        return dict(row) if row else None

    def find_purchase_batch_by_operation_id(self, operation_id):
        op = str(operation_id or '').strip()
        if not op:
            return None
        row = self.con.execute(
            """SELECT purchase_batch_id, race_id FROM purchase_batches
               WHERE purchase_operation_id=?""",
            (op,)).fetchone()
        return dict(row) if row else None

    def find_purchase_by_operation_id(self, race_id, operation_id):
        row = self.find_purchase_batch_by_operation_id(operation_id)
        if not row:
            return None
        rid = str(race_id or '').strip()
        if rid and str(row.get('race_id') or '') != rid:
            return None
        return row['purchase_batch_id']

    def create_purchase_batch(
        self,
        race_id,
        lines,
        analysis_run_id=None,
        recommended_ref=None,
        meta=None,
        record_status='ok',
        purchase_operation_id=None,
        _commit=True,
    ):
        """購入確定1回分を追記（bets テーブルとは別。step5 で関連付け）。"""
        rid = str(race_id or '').strip()
        if not rid:
            raise ValueError('race_id required')
        batch_id = uuid.uuid4().hex
        ts = _now_iso()
        stat = str(record_status or 'ok')
        op_id = str(purchase_operation_id or '').strip() or None
        self.con.execute(
            """INSERT INTO purchase_batches(
                 purchase_batch_id, analysis_run_id, race_id, created_ts,
                 lines_json, recommended_ref_json, meta_json, record_status,
                 purchase_operation_id)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                batch_id, analysis_run_id, rid, ts,
                _json_dumps(lines) if lines is not None else None,
                _json_dumps(recommended_ref) if recommended_ref is not None else None,
                _json_dumps(meta) if meta is not None else None,
                stat,
                op_id,
            ),
        )
        if _commit:
            self.con.commit()
        return batch_id

    def get_purchase_batch(self, purchase_batch_id):
        row = self.con.execute(
            "SELECT * FROM purchase_batches WHERE purchase_batch_id=?",
            (purchase_batch_id,)).fetchone()
        return dict(row) if row else None

    def set_purchase_batch_status(self, purchase_batch_id, record_status, _commit=True):
        self.con.execute(
            "UPDATE purchase_batches SET record_status=? WHERE purchase_batch_id=?",
            (str(record_status), purchase_batch_id))
        if _commit:
            self.con.commit()

    def list_analysis_runs(self, race_id, limit=50):
        rid = str(race_id or '').strip()
        rows = self.con.execute(
            """SELECT * FROM analysis_runs WHERE race_id=?
               ORDER BY created_ts DESC LIMIT ?""",
            (rid, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_events(self, analysis_run_id):
        rows = self.con.execute(
            """SELECT * FROM audit_events WHERE analysis_run_id=?
               ORDER BY created_ts ASC""",
            (analysis_run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_event(self, event_id):
        row = self.con.execute(
            "SELECT * FROM audit_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_recommendations(self, analysis_run_id):
        rows = self.con.execute(
            """SELECT * FROM audit_events
               WHERE analysis_run_id=? AND stage='recommendation'
               ORDER BY created_ts ASC""",
            (analysis_run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_purchase_by_fingerprint(
        self, race_id, fingerprint, committed_only=True, within_seconds=None,
    ):
        rid = str(race_id or '').strip()
        if not rid or not fingerprint:
            return None
        rows = self.con.execute(
            """SELECT purchase_batch_id, meta_json, record_status, created_ts
               FROM purchase_batches
               WHERE race_id=?
                 AND json_extract(meta_json, '$.fingerprint') = ?
               ORDER BY created_ts DESC""",
            (rid, str(fingerprint)),
        ).fetchall()
        now = datetime.datetime.now()
        for row in rows:
            if committed_only and not is_batch_committed(row['record_status']):
                continue
            try:
                meta = json.loads(row['meta_json'] or '{}')
            except Exception:
                meta = {}
            if meta.get('fingerprint') != fingerprint:
                continue
            if within_seconds is not None:
                try:
                    created = datetime.datetime.fromisoformat(row['created_ts'])
                    if (now - created).total_seconds() > float(within_seconds):
                        continue
                except Exception:
                    pass
            return row['purchase_batch_id']
        return None

    def iter_purchase_batches(self, race_id, *, committed_only=False, page_size=50):
        """created_ts DESC でページング（MAGI / 集計の limit 欠落防止）。"""
        rid = str(race_id or '').strip()
        offset = 0
        page = max(1, int(page_size))
        while True:
            rows = self.con.execute(
                """SELECT * FROM purchase_batches WHERE race_id=?
                   ORDER BY created_ts DESC LIMIT ? OFFSET ?""",
                (rid, page, offset),
            ).fetchall()
            if not rows:
                return
            for r in rows:
                d = dict(r)
                if committed_only and not is_batch_committed(d.get('record_status')):
                    continue
                yield d
            if len(rows) < page:
                return
            offset += page

    def list_purchase_batches(self, race_id, limit=30, committed_only=False):
        rid = str(race_id or '').strip()
        rows = self.con.execute(
            """SELECT * FROM purchase_batches WHERE race_id=?
               ORDER BY created_ts DESC LIMIT ?""",
            (rid, int(limit)),
        ).fetchall()
        out = [dict(r) for r in rows]
        if committed_only:
            out = [r for r in out if is_batch_committed(r.get('record_status'))]
        return out

    def close(self):
        if self._owned:
            try:
                self.con.close()
            except Exception:
                pass
