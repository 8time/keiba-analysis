"""Immutable, observation-only prediction snapshots.

This module never recalculates a racing score. Unknown source times remain unknown.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'data' / 'prediction_time_machine.db'
JST = ZoneInfo('Asia/Tokyo')
SCHEMA_VERSION = 1
START_MARKER = 'TIME_MACHINE_V1_START'
MARKET_NAMES = {'Odds', 'Popularity', 'ShowMin', 'ShowMax', 'WinOdds', 'Ninki'}
SOURCES = {'JV', 'NETKEIBA', 'LIVE', 'CACHE', 'IMPUTED', 'DERIVED', 'UNKNOWN'}
REQUIRED_COMPONENTS = ('pace', 'battle_score', 'sra_projected_score',
                       'vh', 'hunter', 'goal', 'recommendation')
TRACKED_STAGES = ('position_score_map',) + REQUIRED_COMPONENTS + ('elim',)
# UNSPECIFIED keeps the strict set. Narrower profiles do not call absent UI stages missing.
WORKFLOW_REQUIRED = {
    'UNSPECIFIED': ('position_score_map',) + REQUIRED_COMPONENTS,
    'SRA_CORE': ('position_score_map', 'battle_score', 'sra_projected_score'),
    'MAIN_PAGE': ('position_score_map', 'battle_score', 'sra_projected_score',
                  'pace', 'goal', 'vh', 'recommendation'),
    'FULL_PREDICTION': ('position_score_map',) + REQUIRED_COMPONENTS + ('elim',),
}
STAGE_CODES = {
    'position_score_map': 'POSITION',
    'pace': 'PACE',
    'battle_score': 'BATTLE',
    'sra_projected_score': 'SRA',
    'vh': 'VH',
    'hunter': 'HUNTER',
    'goal': 'GOAL',
    'elim': 'ELIM',
    'recommendation': 'RECOMMENDATION',
}
UI_STAGE_TRIGGERS = {
    'position_score_map': 'SRA分析の計算中に常に実行',
    'battle_score': 'SRA分析の計算中に常に実行',
    'sra_projected_score': 'SRA分析の計算中に常に実行',
    'pace': 'メイン画面の展開マップ描画時（折りたたみでもスクリプトは実行される）',
    'goal': 'メイン画面の展開マップ描画時',
    'vh': 'メイン画面の統合ビュー描画時',
    'recommendation': 'メイン画面の統合ビューで買い目を組んだとき',
    'hunter': '穴馬ハンター画面を開いたとき',
    'elim': '「強適消去エンジンを実行」ボタンを押したとき',
    'stage1': '本番画面では実行されない',
}
CAPTURE_ORIGINS = {'production', 'fixture', 'test', 'manual', 'unspecified'}
CACHE_PROVENANCE_DIR = ROOT / 'data' / 'cache_provenance'
# Research Stage 1 probability is not produced by the live prediction path.
NOT_ON_PRODUCTION_PATH = ('stage1_probability',)
CRITICAL_INPUTS = {
    'Odds', 'Popularity', 'ShowMin', 'ShowMax', 'WinOdds', 'Ninki',
    'PastRuns', 'Jockey', 'Futan', '斤量', 'Weight', '馬体重',
    'CurrentSurface', 'CurrentDistance', 'Baba', 'Condition',
}
DERIVED_FROM = {
    'BattleScore': ['PastRuns', 'OguraIndex', 'AvgAgari', 'AvgPosition'],
    'Projected Score': ['BattleScore', 'Strength (X)', 'Suitability (Y)'],
    'AvgPosition': ['PastRuns'],
    'AvgAgari': ['PastRuns'],
    'OguraIndex': ['PastRuns'],
    'SpeedIndex': ['PastRuns'],
    'Suitability (Y)': ['raw_input'],
    'Strength (X)': ['raw_input'],
    'NIndex': ['raw_input'],
    'LTR': ['raw_input'],
    'DeployScore': ['position_score', 'pace_profile'],
}
BATTLE_COMPONENT_FIELDS = (
    'OguraIndex', 'SpeedIndex', 'ScoreBaseOgura', 'ScoreMakuri',
    'AvgAgari', 'AvgPosition', 'AgariRank', 'AgariTrust',
)
# Board prices can certify a pre-race snapshot. Forecasts and result pages cannot.
BOARD_ODDS_KINDS = {'win_odds_endpoint', 'realtime_api', 'html_table'}
NON_BOARD_ODDS_KINDS = {'expected', 'result'}


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def now_jst():
    return dt.datetime.now(JST).isoformat(timespec='seconds')


def _time(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(JST)
    except (TypeError, ValueError):
        return None


def _safe(value):
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_safe(v) for v in value),
                      key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True,
                                               default=str))
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if hasattr(value, 'item'):
        try:
            return _safe(value.item())
        except (ValueError, TypeError):
            pass
    if hasattr(value, 'tolist'):
        try:
            return _safe(value.tolist())
        except (ValueError, TypeError):
            pass
    try:
        import pandas as pd
        if pd.isna(value) is True:
            return None
    except (ImportError, TypeError, ValueError):
        pass
    return str(value)


def canonical(value):
    return json.dumps(_safe(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _file_hash(paths):
    h = hashlib.sha256()
    for path in sorted(paths, key=str):
        if path.is_file():
            h.update(str(path.relative_to(ROOT)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def versions():
    """Source-content hash detects dirty and untracked Python code too."""
    files = [ROOT / 'app.py', *sorted((ROOT / 'core').glob('*.py'))]
    source_hash = _file_hash(files)
    model_files = [ROOT / 'core' / name for name in (
        'calculator.py', 'pace_map.py', 'value_hunter.py', 'elim_engine.py',
        'ltr_ranker.py', 'playbook_tickets.py')]
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                capture_output=True, text=True, timeout=5).stdout.strip() or None
        dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        commit, dirty = None, None
    return {'git_commit': commit, 'git_dirty': dirty, 'source_tree_hash': source_hash,
            'model_version': _file_hash(model_files), 'config_hash': _file_hash(
                [p for p in (ROOT / 'config').rglob('*.json')] if (ROOT / 'config').exists() else [])}


def _sqlite_content_hint(path):
    """Schema hash and latest race key. mtime alone does not prove identical bytes."""
    hint = {'identity_strength': 'weak_file_metadata_only',
            'mtime_is_content_proof': False}
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error as exc:
        hint['fingerprint_error'] = type(exc).__name__
        return hint
    try:
        schema_rows = con.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY sql").fetchall()
        schema = '\n'.join(row[0] for row in schema_rows if row[0])
        hint['schema_fingerprint'] = hashlib.sha256(schema.encode('utf-8')).hexdigest()
        hint['user_version'] = con.execute('PRAGMA user_version').fetchone()[0]
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if 'races' in tables:
            hint['latest_race_key'] = con.execute(
                'SELECT MAX(race_key) FROM races').fetchone()[0]
            hint['identity_strength'] = 'schema_hash_and_latest_race_key'
            hint['coverage_note'] = (
                'latest_race_key は収録の先端だけを示す。'
                '途中行の改変は size と mtime が変わらなければ検出できない。')
        elif hint['schema_fingerprint']:
            hint['identity_strength'] = 'schema_hash_only'
    except sqlite3.Error as exc:
        hint['fingerprint_error'] = type(exc).__name__
    finally:
        con.close()
    return hint


def data_versions():
    """File identity hints; copied input rows remain the actual replay evidence."""
    result = {}
    for label, name in [('jv', 'jravan.db'), ('odds_history', 'odds_history.db')]:
        path = ROOT / 'data' / name
        if path.exists():
            stat = path.stat()
            result[label] = {'path': str(path),
                             'size_bytes': stat.st_size,
                             'file_modified_at': dt.datetime.fromtimestamp(
                                 stat.st_mtime, JST).isoformat(),
                             'identity_strength': 'weak_file_metadata_only',
                             'mtime_is_content_proof': False}
            if name.endswith('.db'):
                result[label].update(_sqlite_content_hint(path))
        else:
            result[label] = {'state': 'MISSING', 'path': str(path)}
    return result


def connect(db_path=DEFAULT_DB):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, factory=_ClosingConnection)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
      CREATE TABLE IF NOT EXISTS prediction_snapshots (
        snapshot_id TEXT PRIMARY KEY, race_id TEXT NOT NULL,
        snapshot_created_at TEXT NOT NULL, scheduled_start_at TEXT,
        quality TEXT NOT NULL, fingerprint TEXT NOT NULL,
        schema_version INTEGER NOT NULL, body_json TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_ptm_race_time
        ON prediction_snapshots(race_id,snapshot_created_at);
      CREATE TRIGGER IF NOT EXISTS ptm_no_update BEFORE UPDATE ON prediction_snapshots
        BEGIN SELECT RAISE(ABORT,'immutable_snapshot'); END;
      CREATE TRIGGER IF NOT EXISTS ptm_no_delete BEFORE DELETE ON prediction_snapshots
        BEGIN SELECT RAISE(ABORT,'immutable_snapshot'); END;
      CREATE TABLE IF NOT EXISTS prediction_outcomes (
        outcome_id TEXT PRIMARY KEY, race_id TEXT NOT NULL,
        observed_at TEXT NOT NULL, body_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS prediction_observations (
        event_id TEXT PRIMARY KEY, race_id TEXT NOT NULL,
        analysis_run_id TEXT, stage TEXT NOT NULL,
        observed_at TEXT NOT NULL, payload_json TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_ptm_observation_race
        ON prediction_observations(race_id,observed_at);
      CREATE TRIGGER IF NOT EXISTS ptm_observation_no_update BEFORE UPDATE ON prediction_observations
        BEGIN SELECT RAISE(ABORT,'immutable_observation'); END;
      CREATE TRIGGER IF NOT EXISTS ptm_observation_no_delete BEFORE DELETE ON prediction_observations
        BEGIN SELECT RAISE(ABORT,'immutable_observation'); END;
      CREATE TABLE IF NOT EXISTS prediction_tm_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
      );
    ''')
    return con


def read_connection(db_path=DEFAULT_DB):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                          factory=_ClosingConnection)
    con.row_factory = sqlite3.Row
    return con


def temporal_status(scheduled_start_at, source_fetched_at, snapshot_created_at):
    start, fetched, made = map(_time, (scheduled_start_at, source_fetched_at,
                                      snapshot_created_at))
    if fetched and made and fetched > made:
        return 'FUTURE_SOURCE'
    if start and ((fetched and fetched >= start) or (made and made >= start)):
        return 'POST_RACE'
    if not start or not fetched or not made:
        return 'UNKNOWN_TIME'
    return 'PRE_RACE'


def _walk_provenance(provenance):
    if isinstance(provenance, dict):
        if 'source' in provenance or 'fetched_at' in provenance:
            yield provenance
        for value in provenance.values():
            yield from _walk_provenance(value)
    elif isinstance(provenance, list):
        for value in provenance:
            yield from _walk_provenance(value)


def _provenance_time(node):
    """Derived values use the observation time, never a guessed source fetch."""
    if node.get('source') == 'DERIVED':
        return node.get('derived_at')
    return node.get('fetched_at')


def _provenance_ok(node):
    source = node.get('source')
    if source == 'DERIVED':
        return bool(node.get('derived_from')) and bool(node.get('derived_at'))
    if source == 'IMPUTED':
        return True
    if node.get('is_missing') and node.get('field') not in CRITICAL_INPUTS:
        return True
    return (source in SOURCES - {'UNKNOWN'} and node.get('fetched_at') is not None
            and not node.get('is_missing'))


def _odds_kinds(body):
    kinds = set()
    for row in body.get('odds_observations') or []:
        for key in ('odds_value_kind', 'popularity_value_kind'):
            if row.get(key):
                kinds.add(row.get(key))
    return kinds


def completeness(body):
    """Recompute flags from evidence; caller-supplied flags are never trusted."""
    provenance = list(_walk_provenance(body.get('provenance', {})))
    predictions = body.get('predictions') or {}
    versions_ = body.get('versions') or {}
    start = body.get('race', {}).get('scheduled_start_at')
    made = body.get('snapshot_created_at')
    statuses = [temporal_status(start, _provenance_time(p), made) for p in provenance]
    for odds in body.get('odds_observations', []):
        for key in ('odds_fetched_at', 'popularity_fetched_at'):
            statuses.append(temporal_status(start, odds.get(key), made))
    odds_rows = body.get('odds_observations') or []
    flags = {
        'PRE_RACE_TIME_VERIFIED': bool(_time(start) and _time(made) and
                                       _time(made) < _time(start)),
        'ODDS_TIME_VERIFIED': bool(odds_rows) and all(
            _time(x.get('odds_fetched_at')) is not None and
            _time(x.get('popularity_fetched_at')) is not None and
            x.get('odds_source') not in (None, 'UNKNOWN') and
            x.get('popularity_source') not in (None, 'UNKNOWN') and
            x.get('odds_value_kind') not in NON_BOARD_ODDS_KINDS and
            x.get('popularity_value_kind') not in NON_BOARD_ODDS_KINDS and
            isinstance(x.get('odds'), (int, float)) and x['odds'] > 0 and
            isinstance(x.get('popularity'), int) and 0 < x['popularity'] < 99
            for x in odds_rows),
        'RAW_INPUT_COMPLETE': body.get('raw_input') is not None,
        'PROVENANCE_COMPLETE': bool(provenance) and all(
            _provenance_ok(p) for p in provenance),
        'CODE_VERSION_CAPTURED': bool(versions_.get('source_tree_hash')),
        'MODEL_VERSION_CAPTURED': bool(versions_.get('model_version')),
    }
    profile = _workflow_profile(body)
    required = set(WORKFLOW_REQUIRED.get(profile, WORKFLOW_REQUIRED['UNSPECIFIED']))
    for component in TRACKED_STAGES:
        flags[STAGE_CODES[component] + '_CAPTURED'] = (
            _stage_status(body, component) == 'CAPTURED')
    flags['STAGE1_CAPTURED'] = predictions.get('stage1') is not None
    flags['POSITION_STAGE_CAPTURED'] = flags['POSITION_CAPTURED']
    flags['IMPUTED_PRESENT'] = any(bool(p.get('is_imputed')) for p in provenance)
    flags['SOURCE_TIME_STATES'] = statuses
    flags['MIXED_SOURCE_WARNING'] = any(
        w.get('code') == 'MIXED_UNIT_SOURCE'
        for w in (body.get('data_quality_warnings') or []))
    data_flags = ('PRE_RACE_TIME_VERIFIED', 'ODDS_TIME_VERIFIED', 'RAW_INPUT_COMPLETE',
                  'PROVENANCE_COMPLETE', 'CODE_VERSION_CAPTURED', 'MODEL_VERSION_CAPTURED')
    missing = [name for name in data_flags if flags[name] is False]
    for component in sorted(required):
        if _stage_status(body, component) != 'CAPTURED':
            missing.append(STAGE_CODES[component] + '_CAPTURED')
    flags['MISSING_REQUIREMENTS'] = sorted(set(missing))
    return flags


def _workflow_profile(body):
    profile = body.get('workflow_profile') or 'UNSPECIFIED'
    if profile not in WORKFLOW_REQUIRED:
        return 'UNSPECIFIED'
    return profile


def _stage_status(body, component):
    """A stored value is CAPTURED. An explicit skip stays NOT_EXECUTED or NOT_APPLICABLE."""
    predictions = body.get('predictions') or {}
    if predictions.get(component) is not None:
        return 'CAPTURED'
    declared = (body.get('stage_execution') or {}).get(component)
    if declared in {'NOT_EXECUTED', 'NOT_APPLICABLE', 'MISSING', 'FAILED'}:
        return declared
    return 'MISSING'


def green_blockers(body):
    """Reason codes for this workflow. Caller text is not trusted."""
    flags = completeness(body)
    blockers = []
    details = {}
    if 'result' in _odds_kinds(body):
        blockers.append('RESULT_ODDS')
    kinds = _odds_kinds(body)
    if 'expected' in kinds:
        blockers.append('ODDS_NOT_BOARD')
    if not flags['ODDS_TIME_VERIFIED'] and 'ODDS_NOT_BOARD' not in blockers and 'RESULT_ODDS' not in blockers:
        blockers.append('ODDS_TIME_UNKNOWN')
    if not flags['PRE_RACE_TIME_VERIFIED']:
        start = _time((body.get('race') or {}).get('scheduled_start_at'))
        made = _time(body.get('snapshot_created_at'))
        if start and made and made >= start:
            blockers.append('POST_RACE_SNAPSHOT')
        else:
            blockers.append('SCHEDULED_START_UNKNOWN')
    if 'POST_RACE' in flags['SOURCE_TIME_STATES']:
        blockers.append('POST_RACE_SOURCE')
    if 'FUTURE_SOURCE' in flags['SOURCE_TIME_STATES']:
        blockers.append('FUTURE_SOURCE')
    if 'UNKNOWN_TIME' in flags['SOURCE_TIME_STATES'] or not flags['SOURCE_TIME_STATES']:
        blockers.append('UNKNOWN_TIME')
    if not flags['RAW_INPUT_COMPLETE']:
        blockers.append('RAW_INPUT_MISSING')
    if not flags['CODE_VERSION_CAPTURED']:
        blockers.append('CODE_VERSION_MISSING')
    if not flags['MODEL_VERSION_CAPTURED']:
        blockers.append('MODEL_VERSION_MISSING')
    if flags['MIXED_SOURCE_WARNING']:
        blockers.append('MIXED_LIVE_JV')
    unknown_fields = {}
    missing_critical = {}
    cache_unknown = 0
    imputed_position = 0
    imputed_other = 0
    for node in _walk_provenance(body.get('provenance') or {}):
        source = node.get('source')
        field = node.get('field') or 'UNNAMED'
        if source == 'CACHE' and not node.get('fetched_at'):
            cache_unknown += 1
        if node.get('is_imputed') or source == 'IMPUTED':
            if field == 'PastRuns' or node.get('passing_quality') == 'Imputed' or node.get('agari_quality') == 'Imputed':
                imputed_position += 1
            else:
                imputed_other += 1
        if _provenance_ok(node):
            continue
        if node.get('is_missing') and field in CRITICAL_INPUTS:
            missing_critical[field] = missing_critical.get(field, 0) + 1
        elif source in (None, 'UNKNOWN'):
            unknown_fields[field] = unknown_fields.get(field, 0) + 1
        else:
            unknown_fields[field] = unknown_fields.get(field, 0) + 1
    if cache_unknown:
        blockers.append('CACHE_SOURCE_TIME_UNKNOWN')
        details['CACHE_SOURCE_TIME_UNKNOWN'] = cache_unknown
    if imputed_position:
        blockers.append('IMPUTED_POSITION')
        details['IMPUTED_POSITION'] = imputed_position
    if imputed_other:
        blockers.append('IMPUTED_PRESENT')
        details['IMPUTED_PRESENT'] = imputed_other
    if unknown_fields:
        blockers.append('PROVENANCE_UNKNOWN')
        details['PROVENANCE_UNKNOWN'] = unknown_fields
    if missing_critical:
        blockers.append('CRITICAL_INPUT_MISSING')
        details['CRITICAL_INPUT_MISSING'] = missing_critical
    if not flags['PROVENANCE_COMPLETE'] and 'PROVENANCE_UNKNOWN' not in blockers and 'CRITICAL_INPUT_MISSING' not in blockers and 'IMPUTED_POSITION' not in blockers:
        blockers.append('PROVENANCE_INCOMPLETE')
    profile = _workflow_profile(body)
    for component in WORKFLOW_REQUIRED[profile]:
        status = _stage_status(body, component)
        if status != 'CAPTURED':
            blockers.append(f'{status}_{STAGE_CODES[component]}')
    # Stable, unique, RED-relevant codes first.
    order = []
    for code in blockers:
        if code not in order:
            order.append(code)
    return order, details


def assess_quality(body):
    flags = completeness(body)
    statuses = flags['SOURCE_TIME_STATES']
    blockers, _details = green_blockers(body)
    red = {'RESULT_ODDS', 'POST_RACE_SNAPSHOT', 'POST_RACE_SOURCE', 'FUTURE_SOURCE'}
    if any(code in red for code in blockers):
        return 'RED', statuses
    if blockers:
        return 'YELLOW', statuses
    return 'GREEN', statuses


def save_snapshot(body, db_path=DEFAULT_DB):
    """Atomic INSERT; duplicate IDs fail, no update or replacement is possible."""
    body = _safe(body)
    if any(k in body for k in ('outcome', 'actual_result', 'payout', 'finish_position')):
        raise ValueError('outcome data belongs in prediction_outcomes')
    rid = str(body.get('race', {}).get('race_id') or '')
    if not rid:
        raise ValueError('race_id required')
    body.setdefault('snapshot_id', str(uuid.uuid4()))
    body.setdefault('snapshot_created_at', now_jst())
    body.setdefault('prediction_created_at', body['snapshot_created_at'])
    body['timezone'] = 'Asia/Tokyo'
    body['schema_version'] = SCHEMA_VERSION
    body.setdefault('versions', versions())
    blockers, blocker_details = green_blockers(body)
    quality, statuses = assess_quality(body)
    body['data_quality'] = {'status': quality, 'source_time_states': statuses,
                            'blockers': blockers, 'blocker_details': blocker_details,
                            'workflow_profile': _workflow_profile(body),
                            'capture_origin': body.get('capture_origin') or 'unspecified',
                            'stage_execution': {key: _stage_status(body, key)
                                                for key in TRACKED_STAGES},
                            'completeness': completeness(body)}
    body['fingerprint'] = digest({k: v for k, v in body.items() if k != 'fingerprint'})
    with connect(db_path) as con:
        con.execute('INSERT OR IGNORE INTO prediction_tm_meta(key,value) VALUES (?,?)',
                    (START_MARKER, now_jst()))
        con.execute('''INSERT INTO prediction_snapshots VALUES(?,?,?,?,?,?,?,?)''',
                    (body['snapshot_id'], rid, body['snapshot_created_at'],
                     body['race'].get('scheduled_start_at'), quality,
                     body['fingerprint'], SCHEMA_VERSION, canonical(body)))
    return body['snapshot_id']


def replay(snapshot_id, db_path=DEFAULT_DB):
    with read_connection(db_path) as con:
        row = con.execute('SELECT body_json,fingerprint FROM prediction_snapshots WHERE snapshot_id=?',
                          (snapshot_id,)).fetchone()
    if not row:
        raise KeyError(snapshot_id)
    body = json.loads(row['body_json'])
    expected = digest({k: v for k, v in body.items() if k != 'fingerprint'})
    if expected != row['fingerprint'] or expected != body.get('fingerprint'):
        raise ValueError('snapshot fingerprint mismatch')
    return body


def explain_horse(snapshot_id, horse_number, db_path=DEFAULT_DB):
    body = replay(snapshot_id, db_path)
    number = str(horse_number)
    row = next((x for x in body.get('horses') or []
                if str(x.get('Umaban')) == number), None)
    provenance = next((x.get('values') for x in body.get('provenance') or []
                       if str(x.get('umaban')) == number), None)
    goal = (body.get('predictions') or {}).get('goal') or {}
    decomposition = goal.get('decomposition') or {}
    return {'snapshot_id': snapshot_id, 'race_id': body['race']['race_id'],
            'horse_number': number, 'snapshot_quality': body['data_quality'],
            'input_and_features': row, 'provenance': provenance,
            'goal_contributions': (decomposition.get('contributions') or {}).get(number),
            'goal_signal_sources': (decomposition.get('source_by_horse') or {}).get(number),
            'missing_outputs': body.get('missing_outputs', [])}


def save_outcome(race_id, outcome, db_path=DEFAULT_DB):
    payload = _safe(outcome)
    with connect(db_path) as con:
        con.execute('INSERT INTO prediction_outcomes VALUES(?,?,?,?)',
                    (str(uuid.uuid4()), str(race_id), now_jst(), canonical(payload)))


def observe_stage(event_id, race_id, analysis_run_id, stage, payload, db_path=DEFAULT_DB):
    """A copied audit event is immutable evidence, not a computed prediction."""
    with connect(db_path) as con:
        con.execute('''INSERT INTO prediction_observations VALUES(?,?,?,?,?,?)''',
                    (str(event_id), str(race_id), analysis_run_id, str(stage),
                     now_jst(), canonical(payload)))


def record_component(race_id, stage, inputs, outputs, *, analysis_run_id=None,
                     provenance=None, db_path=DEFAULT_DB):
    """One observation at the actual calculation site; caller handles failures."""
    if analysis_run_id is None and db_path == DEFAULT_DB:
        try:
            from core import audit_pipeline
            analysis_run_id = audit_pipeline.current_run_id(race_id)
        except Exception:
            pass
    event_id = str(uuid.uuid4())
    observe_stage(event_id, race_id, analysis_run_id, stage,
                  {'recorded_at': now_jst(), 'inputs': _safe(inputs),
                   'outputs': _safe(outputs), 'provenance': _safe(provenance),
                   'versions': versions()}, db_path)
    return event_id


def replay_race(race_id, cutoff=None, db_path=DEFAULT_DB):
    """Show exact stored snapshots and stage events available by cutoff."""
    cut = _time(cutoff) if cutoff else None
    if cutoff and cut is None:
        raise ValueError('timezone-aware cutoff required')
    with read_connection(db_path) as con:
        snapshots = con.execute(
            'SELECT snapshot_id,snapshot_created_at FROM prediction_snapshots WHERE race_id=? '
            'ORDER BY snapshot_created_at,snapshot_id', (str(race_id),)).fetchall()
        events = con.execute(
            'SELECT * FROM prediction_observations WHERE race_id=? '
            'ORDER BY observed_at,event_id', (str(race_id),)).fetchall()
    return {
        'snapshots': [replay(r['snapshot_id'], db_path) for r in snapshots
                      if cut is None or _time(r['snapshot_created_at']) <= cut],
        'observations': [{'event_id': r['event_id'], 'analysis_run_id': r['analysis_run_id'],
                          'stage': r['stage'], 'observed_at': r['observed_at'],
                          'payload': json.loads(r['payload_json'])}
                         for r in events if cut is None or _time(r['observed_at']) <= cut],
    }


def find_sra_base_snapshot(race_id, analysis_run_id, db_path=DEFAULT_DB):
    """Return capture_sra body for this run, or None (never cross-run lookup)."""
    path = Path(db_path)
    if not path.is_file():
        return None
    with read_connection(path) as con:
        rows = con.execute(
            'SELECT body_json FROM prediction_snapshots WHERE race_id=? '
            'ORDER BY snapshot_created_at DESC,snapshot_id DESC', (str(race_id),)).fetchall()
    for row in rows:
        body = json.loads(row['body_json'])
        if (body.get('analysis_run_id') == str(analysis_run_id)
                and body.get('capture_scope') == 'SRA dataframe and audit event only'):
            return body
    return None


def finalize_run_snapshot_if_base(race_id, analysis_run_id, db_path=DEFAULT_DB):
    """Assemble snapshot when SRA base exists; otherwise skip (observations may still be saved)."""
    if not analysis_run_id:
        return {'ok': False, 'skipped': True, 'reason': 'no_analysis_run_id'}
    if find_sra_base_snapshot(race_id, analysis_run_id, db_path) is None:
        return {'ok': False, 'skipped': True, 'reason': 'no_sra_snapshot_for_analysis_run'}
    sid = finalize_run_snapshot(race_id, analysis_run_id, db_path)
    return {'ok': True, 'skipped': False, 'snapshot_id': sid}


def finalize_run_snapshot(race_id, analysis_run_id, db_path=DEFAULT_DB):
    """Create a new immutable snapshot from recorded values of one analysis run.

    This reads only observations already committed. It never recalculates a score.
    """
    with read_connection(db_path) as con:
        events = con.execute(
            'SELECT stage,payload_json FROM prediction_observations WHERE race_id=? '
            'AND analysis_run_id=? ORDER BY observed_at,event_id',
            (str(race_id), str(analysis_run_id))).fetchall()
    base = find_sra_base_snapshot(race_id, analysis_run_id, db_path)
    if base is None:
        raise ValueError('no SRA snapshot for analysis run')
    base = json.loads(json.dumps(base))
    predictions = dict(base.get('predictions') or {})
    warnings = list(base.get('data_quality_warnings') or [])
    for row in events:
        stage = row['stage']
        event = json.loads(row['payload_json'])
        outputs = _event_outputs(event)
        if stage == 'position_stage':
            predictions['position_score_map'] = (outputs or {}).get('position_score_map')
            predictions['position_stage'] = outputs
        elif stage == 'pace_4corner':
            predictions['pace'] = outputs
            pos4 = (outputs or {}).get('pos4') if isinstance(outputs, dict) else None
            if isinstance(pos4, dict) and pos4:
                order = sorted(pos4, key=lambda u: (pos4[u], str(u)))
                predictions['predicted_4c_rank'] = {
                    str(u): i + 1 for i, u in enumerate(order)}
                predictions['predicted_4c_position'] = {
                    str(k): v for k, v in pos4.items()}
                predictions['predicted_4c_rank_method'] = 'stable_sort_of_saved_pos4'
            else:
                predictions['predicted_4c_rank'] = None
        elif stage == 'pace_map_goal':
            predictions['goal'] = outputs
            warnings.extend(_mixed_source_warnings(outputs))
        elif stage == 'vh_edge_sets':
            predictions['vh'] = outputs
        elif stage == 'anabaka_hunter_full':
            predictions['hunter'] = outputs
        elif stage == 'anabaka_hunter' and predictions.get('hunter') is None:
            predictions['hunter'] = outputs
        elif stage == 'recommendation':
            predictions['recommendation'] = outputs
        elif stage == 'elim':
            predictions['elim'] = outputs
    base.pop('fingerprint', None)
    base.pop('data_quality', None)
    base['snapshot_id'] = str(uuid.uuid4())
    base['snapshot_created_at'] = now_jst()
    base['prediction_created_at'] = base['snapshot_created_at']
    base['predictions'] = predictions
    base['data_quality_warnings'] = warnings
    execution = dict(base.get('stage_execution') or {})
    for key in TRACKED_STAGES:
        if predictions.get(key) is not None:
            execution[key] = 'CAPTURED'
        elif execution.get(key) not in {'NOT_EXECUTED', 'NOT_APPLICABLE', 'FAILED', 'MISSING'}:
            execution[key] = 'NOT_EXECUTED'
    execution['stage1'] = 'NOT_APPLICABLE'
    base['stage_execution'] = execution
    profile = _workflow_profile(base)
    if profile == 'SRA_CORE' and all(execution.get(key) == 'CAPTURED'
                                     for key in WORKFLOW_REQUIRED['MAIN_PAGE']):
        profile = 'MAIN_PAGE'
        base['workflow_profile'] = profile
    base['capture_scope'] = 'assembled recorded run; missing values remain missing'
    base['missing_outputs'] = [key for key in WORKFLOW_REQUIRED[profile]
                               if execution.get(key) != 'CAPTURED']
    base['not_on_production_path'] = list(NOT_ON_PRODUCTION_PATH)
    return save_snapshot(base, db_path)


def _event_outputs(event):
    """Prefer calculation outputs. Audit mirrors wrap them under payload."""
    if isinstance(event, dict) and 'outputs' in event:
        return event.get('outputs')
    payload = event.get('payload') if isinstance(event, dict) else None
    if isinstance(payload, dict) and 'status' in payload and 'payload' in payload:
        return payload.get('payload')
    return payload


def _mixed_source_warnings(goal_outputs):
    sources = ((goal_outputs or {}).get('decomposition') or {}).get('source_by_horse') or {}
    by_field = {}
    for fields in sources.values():
        if not isinstance(fields, dict):
            continue
        for field, src in fields.items():
            by_field.setdefault(field, set()).add(src)
    warnings = []
    for field, kinds in sorted(by_field.items()):
        if 'LIVE' in kinds and 'JV' in kinds:
            warnings.append({
                'code': 'MIXED_UNIT_SOURCE',
                'field': field,
                'sources': sorted(kinds),
                'detail': '同一特徴にLIVEとJVが馬ごとに混在している。尺度が違う可能性がある',
            })
    return warnings


def _eligible(body, cutoff, minutes_before_start, quality='GREEN'):
    cut, made = _time(cutoff), _time(body.get('snapshot_created_at'))
    start = _time(body.get('race', {}).get('scheduled_start_at'))
    if not cut or not made or not start or made > cut:
        return False
    if made > start - dt.timedelta(minutes=minutes_before_start):
        return False
    source_cutoff = min(cut, start - dt.timedelta(minutes=minutes_before_start))
    current_quality = assess_quality(body)[0]
    if body.get('data_quality', {}).get('status') != current_quality:
        return False
    if current_quality != quality:
        return False
    for item in _walk_provenance(body.get('provenance', {})):
        if item.get('source') == 'DERIVED':
            derived_at = _time(item.get('derived_at'))
            if quality == 'GREEN' and derived_at is None:
                return False
            if derived_at and (derived_at > source_cutoff or derived_at >= start):
                return False
            continue
        if item.get('source') == 'IMPUTED' and quality == 'GREEN':
            return False
        fetched = _time(item.get('fetched_at'))
        if (quality == 'GREEN' and not fetched) or (fetched and
                (fetched > source_cutoff or fetched >= start)):
            return False
    for odds in body.get('odds_observations', []):
        for key in ('odds_fetched_at', 'popularity_fetched_at'):
            fetched = _time(odds.get(key))
            if (quality == 'GREEN' and not fetched) or (fetched and
                    (fetched > source_cutoff or fetched >= start)):
                return False
    return True


def research_dataset(cutoff, minutes_before_start=0, db_path=DEFAULT_DB,
                     *, quality='GREEN', date_from=None, date_to=None,
                     production_only=False, workflow=None):
    """One last fully time-certified snapshot per race; outcomes stay separate."""
    if minutes_before_start < 0:
        raise ValueError('minutes_before_start must be nonnegative')
    if quality not in {'GREEN', 'YELLOW', 'RED'}:
        raise ValueError('invalid quality')
    with read_connection(db_path) as con:
        rows = con.execute('SELECT snapshot_id,body_json FROM prediction_snapshots').fetchall()
        outcomes = con.execute('SELECT race_id,body_json FROM prediction_outcomes ORDER BY observed_at').fetchall()
    by_race = {}
    for row in rows:
        body = json.loads(row['body_json'])
        if digest({k: v for k, v in body.items() if k != 'fingerprint'}) != body.get('fingerprint'):
            raise ValueError(f"snapshot fingerprint mismatch: {row['snapshot_id']}")
        race_date = str(body.get('race', {}).get('race_date') or '').replace('-', '')
        if date_from and (not race_date or race_date < date_from.replace('-', '')):
            continue
        if date_to and (not race_date or race_date > date_to.replace('-', '')):
            continue
        origin = body.get('capture_origin') or body.get('data_quality', {}).get('capture_origin')
        if production_only and origin != 'production':
            continue
        if workflow and _workflow_profile(body) != workflow:
            continue
        if _eligible(body, cutoff, minutes_before_start, quality):
            rid = body['race']['race_id']
            if rid not in by_race or body['snapshot_created_at'] > by_race[rid]['snapshot_created_at']:
                by_race[rid] = body
    outcome_map = {r['race_id']: json.loads(r['body_json']) for r in outcomes}
    return [{'prediction': body, 'outcome': outcome_map.get(rid)}
            for rid, body in sorted(by_race.items())]


def _market_origin(events, column, umaban, value):
    matches = []
    for event in events or []:
        if event.get('field') != column:
            continue
        values = event.get('values') or {}
        keys = (str(umaban), str(umaban).zfill(2))
        candidate = next((values[k] for k in keys if k in values), None)
        if candidate is not None and canonical(candidate) == canonical(value):
            matches.append(event)
    return max(matches, key=lambda e: e.get('fetched_at') or '') if matches else None


def _enrichment_origin(events, column, umaban, value):
    matches = []
    for event in events or []:
        values = event.get('values') or {}
        keys = (str(umaban), str(umaban).zfill(2))
        entry = next((values[k] for k in keys if k in values), None)
        if isinstance(entry, dict) and column in entry and canonical(entry[column]) == canonical(value):
            matches.append(event)
    return max(matches, key=lambda e: e.get('fetched_at') or '') if matches else None


def _missing_value(column, value):
    if value is None or value == '' or value == '-':
        return True
    if column in {'Odds', 'ShowMin', 'ShowMax'}:
        try:
            return float(value) <= 0
        except (TypeError, ValueError):
            return True
    if column in {'Popularity', 'Ninki'}:
        try:
            return int(value) >= 99 or int(value) <= 0
        except (TypeError, ValueError):
            return True
    return False


def _cell_provenance(column, value, raw_value, acquisition, market_event=None,
                     enrichment_event=None, *, observed_at=None, in_raw=True):
    # The composite scraper does not expose per-field upstream fetch times.
    # Even when its returned dataframe is captured, calling it NETKEIBA for
    # every field would falsely certify merged LAB/JV/CACHE values.
    source = 'UNKNOWN'
    fetched_at = None
    value_kind = None
    derived_at = None
    derived_from = []
    if (column not in MARKET_NAMES and in_raw and raw_value is not None and
            canonical(value) == canonical(raw_value)):
        source = acquisition.get('source') or 'UNKNOWN'
        fetched_at = acquisition.get('fetched_at')
    if market_event is not None:
        source = market_event.get('source') or 'UNKNOWN'
        fetched_at = market_event.get('fetched_at')
        value_kind = market_event.get('value_kind')
    if source == 'UNKNOWN' and enrichment_event is not None:
        source = enrichment_event.get('source') or 'UNKNOWN'
        fetched_at = enrichment_event.get('fetched_at')
    if column in DERIVED_FROM or (not in_raw and column not in MARKET_NAMES):
        source = 'DERIVED'
        fetched_at = None
        value_kind = None
        derived_at = observed_at
        derived_from = list(DERIVED_FROM.get(column) or ['absent_from_raw_input'])
    return {'field': column, 'source': source, 'fetched_at': fetched_at,
            'as_of': None, 'source_record_id': None,
            'is_missing': _missing_value(column, value),
            'is_imputed': False, 'transform': None,
            'value_kind': value_kind,
            'derived_at': derived_at,
            'derived_at_semantics': 'observed_no_later_than' if derived_at else None,
            'derived_from': derived_from}


def capture_sra(race_id, raw_df, scored_df, metadata=None, *, source_fetched_at=None,
                prediction_created_at=None, audit_payload=None,
                analysis_run_id=None, enrichment_events=None, db_path=DEFAULT_DB,
                capture_origin='unspecified', workflow_profile='SRA_CORE'):
    """Capture actual dataframe values, never infer missing model outputs."""
    import pandas as pd
    meta = _safe(metadata or {})
    date = str(meta.get('date_val') or '')
    post = meta.get('post_time')
    start = None
    if len(date) == 8 and str(post or '').count(':') == 1:
        start = f'{date[:4]}-{date[4:6]}-{date[6:8]}T{post}:00+09:00'
    made = now_jst()
    raw = _safe(raw_df.to_dict('records')) if raw_df is not None else None
    scored = _safe(scored_df.to_dict('records')) if scored_df is not None else None
    acquisition = _safe(getattr(raw_df, 'attrs', {}).get('_ptm_acquisition', {})) if raw_df is not None else {}
    market_events = _safe(getattr(raw_df, 'attrs', {}).get('_ptm_market_events', [])) if raw_df is not None else []
    enrichment_events = _safe(enrichment_events or [])
    raw_by_umaban = {str(row.get('Umaban')): row for row in (raw or [])}
    provenance = []
    for row in (scored or []):
        cells = {}
        original = raw_by_umaban.get(str(row.get('Umaban')), {})
        for key, value in row.items():
            market_event = (_market_origin(market_events, key, row.get('Umaban'), value)
                            if key in MARKET_NAMES else None)
            enrichment_event = _enrichment_origin(
                enrichment_events, key, row.get('Umaban'), value)
            cells[key] = _cell_provenance(
                key, value, original.get(key), acquisition, market_event,
                enrichment_event, observed_at=made, in_raw=key in original)
            if key == 'PastRuns' and isinstance(value, list):
                cells[key]['items'] = [
                    {'source': (acquisition.get('source') or 'UNKNOWN')
                     if not (run.get('PassingType') == 'Imputed' or
                             run.get('AgariType') == 'Imputed') else 'IMPUTED',
                     'fetched_at': acquisition.get('fetched_at'),
                     'as_of': run.get('Date'),
                     'source_record_id': run.get('RaceId'),
                     'is_imputed': (run.get('PassingType') == 'Imputed' or
                                    run.get('AgariType') == 'Imputed'),
                     'passing_quality': run.get('PassingType') or 'UNKNOWN',
                     'agari_quality': run.get('AgariType') or 'UNKNOWN'}
                    for run in value if isinstance(run, dict)]
                if any(x['is_imputed'] for x in cells[key]['items']):
                    cells[key]['is_imputed'] = True
                    cells[key]['source'] = 'IMPUTED'
        provenance.append({'umaban': row.get('Umaban'), 'values': cells})
    market = [{k: row.get(k) for k in MARKET_NAMES if k in row} for row in (scored or [])]
    nonmarket = [{k: v for k, v in row.items() if k not in MARKET_NAMES}
                 for row in (scored or [])]
    identities = [{'horse_id': row.get('HorseID') or row.get('horse_id'),
                   'horse_name': row.get('Name'), 'horse_number': row.get('Umaban'),
                   'frame_number': row.get('Waku') or row.get('Wakuban')}
                  for row in (scored or [])]
    odds_observations = []
    for row in (scored or []):
        origin = _market_origin(market_events, 'Odds', row.get('Umaban'), row.get('Odds'))
        pop_origin = _market_origin(market_events, 'Popularity', row.get('Umaban'),
                                    row.get('Popularity'))
        odds_observations.append({'horse_number': row.get('Umaban'),
                                  'odds': row.get('Odds'),
                                  'popularity': row.get('Popularity'),
                                  'odds_fetched_at': origin.get('fetched_at') if origin else None,
                                  'odds_source': origin.get('source') if origin else 'UNKNOWN',
                                  'odds_value_kind': origin.get('value_kind') if origin else None,
                                  'popularity_fetched_at': (pop_origin.get('fetched_at')
                                                            if pop_origin else None),
                                  'popularity_source': (pop_origin.get('source')
                                                        if pop_origin else 'UNKNOWN'),
                                  'popularity_value_kind': (pop_origin.get('value_kind')
                                                            if pop_origin else None),
                                  'race_start_at': start})
    battle = [{'umaban': row.get('Umaban'), 'value': row.get('BattleScore'),
               'market_derived': False,
               'components': {name: row.get(name) for name in BATTLE_COMPONENT_FIELDS
                              if name in row}}
              for row in (scored or []) if 'BattleScore' in row]
    sra = [{'umaban': row.get('Umaban'), 'value': row.get('Projected Score')}
           for row in (scored or []) if 'Projected Score' in row]
    body = {'race': {'race_id': str(race_id), 'venue': meta.get('venue'),
                     'race_date': date or None, 'race_number': str(race_id)[-2:],
                     'distance': (scored or [{}])[0].get('CurrentDistance'),
                     'surface': (scored or [{}])[0].get('CurrentSurface'),
                     'course': meta.get('course'), 'scheduled_start_at': start},
            'snapshot_created_at': made,
            'analysis_run_id': analysis_run_id,
            'cross_refs': {
                'forward_collector': {
                    'race_id': str(race_id),
                    'analysis_run_id': analysis_run_id,
                    'join_file': 'data/research/forward/ptm_links.jsonl',
                },
            },
            'prediction_created_at': prediction_created_at or made,
            'composite_fetch_completed_at': source_fetched_at,
            'composite_fetch_time_is_source_proof': False,
            'raw_acquisition': acquisition,
            'market_acquisition_events': market_events,
            'enrichment_acquisition_events': enrichment_events,
            'raw_input': raw, 'horses': scored, 'horse_identity': identities,
            'odds_observations': odds_observations,
            'market_features': market,
            'non_market_features': nonmarket,
            'provenance': provenance,
            'data_versions': data_versions(),
            'market_lineage': {'direct': sorted(MARKET_NAMES),
                               'mixed_score_inputs': ['goal', 'VH', 'LTR'],
                               'unresolved': ['SRA user-adjusted score']},
            'predictions': {'sra_audit_event': _safe(audit_payload),
                            'battle_score': battle or None,
                            'sra_projected_score': sra or None,
                            'stage1': None, 'position_score_map': None,
                            'pace': None, 'vh': None,
                            'hunter': None, 'goal': None, 'recommendation': None,
                            'elim': None},
            'stage_execution': {
                'position_score_map': 'NOT_EXECUTED',
                'battle_score': 'CAPTURED' if battle else 'MISSING',
                'sra_projected_score': 'CAPTURED' if sra else 'MISSING',
                'pace': 'NOT_EXECUTED', 'goal': 'NOT_EXECUTED', 'vh': 'NOT_EXECUTED',
                'hunter': 'NOT_EXECUTED', 'elim': 'NOT_EXECUTED',
                'recommendation': 'NOT_EXECUTED', 'stage1': 'NOT_APPLICABLE'},
            'stage1_status': 'not_generated_on_production_path',
            'workflow_profile': workflow_profile if workflow_profile in WORKFLOW_REQUIRED else 'SRA_CORE',
            'capture_origin': capture_origin if capture_origin in CAPTURE_ORIGINS else 'unspecified',
            'ui_stage_triggers': UI_STAGE_TRIGGERS,
            'evidence_class': 'production_capture',
            'data_quality_warnings': [],
            'capture_scope': 'SRA dataframe and audit event only',
            'missing_outputs': ['position_score_map'],
            'not_on_production_path': list(NOT_ON_PRODUCTION_PATH),
            'metadata': meta}
    sid = save_snapshot(body, db_path)
    restored = replay(sid, db_path)
    if restored['horses'] != scored or restored['predictions']['sra_audit_event'] != _safe(audit_payload):
        raise ValueError('snapshot immediate replay mismatch')
    return sid


def data_freshness(body):
    """Latest proven source time. Derived observation times are reported apart."""
    start = _time((body.get('race') or {}).get('scheduled_start_at'))
    fetched = []
    derived = []
    unverified = 0
    for item in _walk_provenance(body.get('provenance') or {}):
        if item.get('source') == 'DERIVED':
            stamped = _time(item.get('derived_at'))
            if stamped:
                derived.append(stamped)
            else:
                unverified += 1
            continue
        stamped = _time(item.get('fetched_at'))
        if stamped:
            fetched.append(stamped)
        elif item.get('source') != 'IMPUTED':
            unverified += 1
    latest = max(fetched) if fetched else None
    earliest = min(fetched) if fetched else None
    minutes = None
    if start and latest:
        minutes = (start - latest).total_seconds() / 60
    return {
        'earliest_source_fetched_at': earliest.isoformat() if earliest else None,
        'latest_source_fetched_at': latest.isoformat() if latest else None,
        'latest_derived_observed_at': max(derived).isoformat() if derived else None,
        'minutes_before_start_at_latest_source': minutes,
        'unverified_source_count': unverified,
    }


def summarize_snapshot(body):
    """Replay view. Missing stages stay null instead of being recalculated."""
    preds = body.get('predictions') or {}
    quality = body.get('data_quality') or {}
    flags = quality.get('completeness') or {}
    goal = preds.get('goal') if isinstance(preds.get('goal'), dict) else {}
    return {
        'race': body.get('race'),
        'snapshot_id': body.get('snapshot_id'),
        'snapshot_created_at': body.get('snapshot_created_at'),
        'prediction_created_at': body.get('prediction_created_at'),
        'scheduled_start_at': (body.get('race') or {}).get('scheduled_start_at'),
        'quality': quality.get('status'),
        'blockers': quality.get('blockers') or [],
        'workflow_profile': body.get('workflow_profile') or quality.get('workflow_profile'),
        'capture_origin': body.get('capture_origin') or quality.get('capture_origin') or 'unspecified',
        'stage_execution': quality.get('stage_execution') or body.get('stage_execution') or {},
        'evidence_class': body.get('evidence_class') or 'unspecified',
        'data_freshness': data_freshness(body),
        'stage1': preds.get('stage1'),
        'stage1_status': body.get('stage1_status'),
        'position_score_map': preds.get('position_score_map'),
        'predicted_4c_rank': preds.get('predicted_4c_rank'),
        'predicted_4c_position': preds.get('predicted_4c_position'),
        'pace': preds.get('pace'),
        'battle_score': preds.get('battle_score'),
        'sra': preds.get('sra_projected_score'),
        'vh': preds.get('vh'),
        'hunter': preds.get('hunter'),
        'goal': preds.get('goal'),
        'goal_order': goal.get('order') if isinstance(goal, dict) else None,
        'elim': preds.get('elim'),
        'recommendation': preds.get('recommendation'),
        'missing_outputs': body.get('missing_outputs'),
        'not_on_production_path': body.get('not_on_production_path'),
        'data_quality_warnings': body.get('data_quality_warnings') or [],
        'completeness_missing': flags.get('MISSING_REQUIREMENTS'),
        'code_version': (body.get('versions') or {}).get('source_tree_hash'),
        'model_version': (body.get('versions') or {}).get('model_version'),
        'jv_identity': (body.get('data_versions') or {}).get('jv'),
        'provenance': body.get('provenance'),
    }


def remember_cache_source(race_id, source, source_fetched_at, directory=None):
    """Store the original fetch time beside a new cache write. Never invent one."""
    folder = Path(directory) if directory else CACHE_PROVENANCE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    payload = {'race_id': str(race_id), 'source': source or 'UNKNOWN',
               'source_fetched_at': source_fetched_at,
               'cached_at': now_jst(),
               'note': 'cached_at はファイルへ書いた時刻であり、元データの取得時刻ではない'}
    (folder / f'{race_id}.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def recall_cache_source(race_id, directory=None):
    """Return the stored source time, or None when this cache predates the sidecar."""
    folder = Path(directory) if directory else CACHE_PROVENANCE_DIR
    path = folder / f'{race_id}.json'
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not payload.get('source_fetched_at'):
        payload['source_fetched_at'] = None
    return payload


def readiness_check(db_path=DEFAULT_DB):
    """Audit-recorder readiness. This does not run or change a prediction."""
    checks = {}
    sample = now_jst()
    checks['clock_timezone'] = {
        'ok': _time(sample) is not None and _time(sample).tzinfo is not None,
        'sample': sample}
    try:
        probe = Path(db_path)
        probe.parent.mkdir(parents=True, exist_ok=True)
        test_file = probe.parent / '.ptm_write_probe'
        test_file.write_text('ok', encoding='utf-8')
        test_file.unlink()
        checks['recorder_writable'] = {'ok': True, 'path': str(probe)}
    except OSError as exc:
        checks['recorder_writable'] = {'ok': False, 'error': str(exc)}
    try:
        CACHE_PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
        checks['cache_provenance_writable'] = {'ok': True, 'path': str(CACHE_PROVENANCE_DIR)}
    except OSError as exc:
        checks['cache_provenance_writable'] = {'ok': False, 'error': str(exc)}
    version = versions()
    checks['code_version'] = {'ok': bool(version.get('source_tree_hash')),
                              'source_tree_hash': version.get('source_tree_hash')}
    checks['model_version'] = {'ok': bool(version.get('model_version')),
                               'model_version': version.get('model_version')}
    data = data_versions()
    checks['jv_fingerprint'] = {'ok': data.get('jv', {}).get('state') != 'MISSING',
                                'identity': data.get('jv')}
    checks['source_hooks'] = {'ok': True, 'stages': UI_STAGE_TRIGGERS}
    required = ('clock_timezone', 'recorder_writable', 'cache_provenance_writable',
                'code_version', 'model_version', 'source_hooks')
    return {'ready': all(checks[name]['ok'] for name in required), 'checks': checks}


def snapshot_blocker_report(body):
    """Per-snapshot GREEN diagnosis (no quality relaxation)."""
    quality = (body.get('data_quality') or {})
    blockers = quality.get('blockers') or []
    details = quality.get('blocker_details') or {}
    fixable = {
        'NOT_EXECUTED_POSITION': 'position_stage を同一 analysis_run_id で記録し finalize',
        'CACHE_SOURCE_TIME_UNKNOWN': '新規キャッシュ保存時に source_fetched_at sidecar',
        'CRITICAL_INPUT_MISSING': 'スクレイプ欠損（騎手等）— HTML/取得経路',
        'IMPUTED_POSITION': 'Imputed 過去走を減らすか研究対象外',
        'POST_RACE_SNAPSHOT': '発走前に SRA/推奨/finalize を実行',
        'UNKNOWN_TIME': '受領地点 fetched_at または sidecar 復元',
        'MIXED_LIVE_JV': '単一ソースに揃える（予測式は変更しない）',
    }
    return {
        'snapshot_id': body.get('snapshot_id'),
        'quality': quality.get('status'),
        'capture_origin': body.get('capture_origin'),
        'workflow_profile': body.get('workflow_profile'),
        'capture_scope': body.get('capture_scope'),
        'snapshot_created_at': body.get('snapshot_created_at'),
        'scheduled_start_at': (body.get('race') or {}).get('scheduled_start_at'),
        'blockers': blockers,
        'blocker_details': details,
        'fixable_hints': {code: fixable.get(code) for code in blockers if code in fixable},
    }


def blocker_census(db_path=DEFAULT_DB, *, capture_origin=None):
    """Count YELLOW/RED snapshots by blocker. Do not invent a rate from a tiny set."""
    path = Path(db_path)
    if not path.is_file():
        return {'snapshots': 0, 'green': 0, 'non_green': 0, 'counts': {},
                'entries': [], 'note': '件数不足。prediction snapshot がまだない'}
    with read_connection(path) as con:
        rows = con.execute(
            'SELECT snapshot_id,body_json FROM prediction_snapshots ORDER BY snapshot_created_at'
        ).fetchall()
    counts = {}
    seen = 0
    green = 0
    entries = []
    fixture_green = 0
    production_green = 0
    for row in rows:
        body = json.loads(row['body_json'])
        body.setdefault('snapshot_id', row['snapshot_id'])
        origin = body.get('capture_origin') or (body.get('data_quality') or {}).get('capture_origin')
        if capture_origin and origin != capture_origin:
            continue
        seen += 1
        quality = (body.get('data_quality') or {}).get('status')
        if quality == 'GREEN':
            green += 1
            if origin == 'production':
                production_green += 1
            elif origin == 'fixture':
                fixture_green += 1
        rep = snapshot_blocker_report(body)
        entries.append(rep)
        if quality == 'GREEN':
            continue
        for code in rep['blockers']:
            counts[code] = counts.get(code, 0) + 1
    non_green = seen - green
    note = None
    if non_green < 5:
        note = '件数不足。割合にはしない'
    return {
        'snapshots': seen, 'green': green, 'non_green': non_green,
        'production_green': production_green, 'fixture_green': fixture_green,
        'counts': counts, 'entries': entries, 'note': note,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prediction Time Machine exact snapshot replay')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest='command', required=True)
    rep = sub.add_parser('replay')
    rep.add_argument('--snapshot-id', required=True)
    exp = sub.add_parser('explain')
    exp.add_argument('--snapshot-id', required=True)
    exp.add_argument('--umaban', required=True)
    race = sub.add_parser('race')
    race.add_argument('--race-id', required=True)
    race.add_argument('--cutoff')
    data = sub.add_parser('dataset')
    data.add_argument('--cutoff', required=True)
    data.add_argument('--minutes-before-start', type=int, default=0)
    data.add_argument('--quality', choices=('GREEN', 'YELLOW', 'RED'), default='GREEN')
    data.add_argument('--from-date')
    data.add_argument('--to-date')
    data.add_argument('--production-only', action='store_true')
    data.add_argument('--workflow', choices=tuple(WORKFLOW_REQUIRED))
    sub.add_parser('readiness')
    census = sub.add_parser('blockers')
    census.add_argument('--origin')
    args = parser.parse_args(argv)
    if args.command == 'replay':
        body = replay(args.snapshot_id, args.db)
        print(json.dumps({'summary': summarize_snapshot(body), 'snapshot': body},
                         ensure_ascii=False, indent=2))
    elif args.command == 'explain':
        print(json.dumps(explain_horse(args.snapshot_id, args.umaban, args.db),
                         ensure_ascii=False, indent=2))
    elif args.command == 'race':
        print(json.dumps(replay_race(args.race_id, args.cutoff, args.db),
                         ensure_ascii=False, indent=2))
    elif args.command == 'readiness':
        print(json.dumps(readiness_check(args.db), ensure_ascii=False, indent=2))
    elif args.command == 'blockers':
        print(json.dumps(blocker_census(args.db, capture_origin=args.origin),
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(research_dataset(args.cutoff, args.minutes_before_start,
                                          args.db, quality=args.quality,
                                          date_from=args.from_date,
                                          date_to=args.to_date,
                                          production_only=args.production_only,
                                          workflow=args.workflow),
                         ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
