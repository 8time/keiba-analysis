# -*- coding: utf-8 -*-
"""Forward research collector. Shadow only. Does not submit bets or touch production strategy."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from research.forward.snapshot import append_result, capture_decision

FORWARD_V1 = 'FORWARD_V1'
PRIMARY_TARGET_MINUTES = 15
PRIMARY_MIN_MINUTES = 5
MAX_RESULT_RETRIES = 5
PAYOUT_CONFIDENCE = {
    '単勝': 'VERIFIED',
    '複勝': 'PARTIAL',
    '馬連': 'PARTIAL',
    'ワイド': 'PARTIAL',
    '3連複': 'PARTIAL',
    '3連単': 'PARTIAL',
}
LIVE_FEATURES = {
    'decision_time_odds': 'LIVE_AVAILABLE',
    'decision_time_popularity': 'LIVE_AVAILABLE',
    'PastRuns': 'LIVE_AVAILABLE',
    'BattleScore': 'LIVE_AVAILABLE',
    'Projected Score': 'LIVE_AVAILABLE',
    'ScoringSignal': 'LIVE_DERIVABLE',
    'vh_score': 'LIVE_AVAILABLE',
    'ltr_score': 'LIVE_AVAILABLE',
    'elim_keep': 'LIVE_DERIVABLE',
    'ability_score': 'NOT_AVAILABLE',
    'h7_fig': 'NOT_AVAILABLE',
    'spurt_mean3': 'NOT_AVAILABLE',
    'prior_top3_rate': 'NOT_AVAILABLE',
    'jockey_jyo_win': 'NOT_AVAILABLE',
    'trainer_jyo_t3': 'NOT_AVAILABLE',
    'elim_n': 'UNCERTAIN',
}
BANNED_DECISION = {'finish', 'chakujun', 'payout', 'payouts', 'won', 'final_odds'}
TRANSITIONS = {
    None: {'OBSERVED'},
    'OBSERVED': {'DECISION_CAPTURED', 'FAILED_RETRYABLE', 'INVALID'},
    'DECISION_CAPTURED': {'SHADOW_CREATED', 'FAILED_RETRYABLE', 'INVALID'},
    'SHADOW_CREATED': {'RESULT_CAPTURED', 'FAILED_RETRYABLE'},
    'RESULT_CAPTURED': {'SETTLED', 'FAILED_RETRYABLE'},
    'SETTLED': {'EVALUATED'},
    'FAILED_RETRYABLE': {'OBSERVED', 'DECISION_CAPTURED', 'SHADOW_CREATED', 'RESULT_CAPTURED', 'INVALID'},
    'INVALID': set(),
    'EVALUATED': set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _eid(*parts) -> str:
    raw = '|'.join(str(p) for p in parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]


def code_hash() -> str:
        path = os.path.abspath(__file__)
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]


class ForwardStore:
    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)
        self.db_path = os.path.join(directory, 'forward.db')
        self.raw_path = os.path.join(directory, 'raw_events.jsonl')
        self.odds_path = os.path.join(directory, 'odds_snapshots.jsonl')
        self._init_db()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self):
        with self._connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS races (
                race_id TEXT PRIMARY KEY, state TEXT, version TEXT,
                retry_count INTEGER DEFAULT 0, last_error TEXT, updated_at TEXT)''')
            con.execute('''CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, race_id TEXT, stage TEXT, created_at TEXT)''')

    def state(self, race_id: str):
        with self._connect() as con:
            row = con.execute('SELECT state, retry_count, last_error FROM races WHERE race_id=?', (race_id,)).fetchone()
        return None if row is None else {'state': row[0], 'retry_count': row[1], 'last_error': row[2]}

    def _set_state(self, race_id: str, state: str, error: str | None = None, bump_retry: bool = False):
        cur = self.state(race_id)
        prev = None if cur is None else cur['state']
        if state not in TRANSITIONS.get(prev, set()) and not (prev == state):
            raise ValueError(f'illegal transition {prev} -> {state}')
        retries = 0 if cur is None else cur['retry_count']
        if bump_retry:
            retries += 1
        with self._connect() as con:
            con.execute('''INSERT INTO races (race_id, state, version, retry_count, last_error, updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(race_id) DO UPDATE SET
                  state=excluded.state, version=excluded.version,
                  retry_count=excluded.retry_count, last_error=excluded.last_error,
                  updated_at=excluded.updated_at''',
                (race_id, state, FORWARD_V1, retries, error, _now()))

    def append_event(self, race_id: str, stage: str, payload: dict, identity: str) -> bool:
        event_id = _eid(FORWARD_V1, race_id, stage, identity)
        with self._connect() as con:
            seen = con.execute('SELECT 1 FROM events WHERE event_id=?', (event_id,)).fetchone()
        if seen:
            return False
        if payload.get('purchased') is True or payload.get('submit_bet') or payload.get('real_purchase_id'):
            raise RuntimeError('shadow collector cannot record a real purchase')
        row = {'event_id': event_id, 'race_id': race_id, 'stage': stage, 'schema': FORWARD_V1,
               'created_at': _now(), 'code_hash': code_hash(), **payload}
        with open(self.raw_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        with self._connect() as con:
            con.execute('INSERT INTO events (event_id, race_id, stage, created_at) VALUES (?,?,?,?)',
                        (event_id, race_id, stage, row['created_at']))
        return True

    def observe(self, race_id: str, meta: dict):
        if self.state(race_id) is None:
            self._set_state(race_id, 'OBSERVED')
        self.append_event(race_id, 'OBSERVED', {'meta': meta, 'SHADOW_ONLY': True}, 'observe')

    def add_odds_snapshot(self, race_id: str, snapshot: dict) -> bool:
        for key in ('timestamp', 'minutes_to_post', 'horses'):
            if key not in snapshot:
                raise ValueError(f'odds snapshot missing {key}')
        if any(h.get('final_odds') not in (None, '') for h in snapshot['horses']):
            raise ValueError('odds snapshot cannot contain final_odds')
        identity = snapshot['timestamp']
        wrote = self.append_event(race_id, 'ODDS_SNAPSHOT', snapshot, identity)
        if wrote:
            with open(self.odds_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'race_id': race_id, **snapshot}, ensure_ascii=False, default=str) + '\n')
        return wrote

    def snapshots(self, race_id: str) -> list:
        if not os.path.exists(self.odds_path):
            return []
        rows = []
        with open(self.odds_path, encoding='utf-8') as f:
            for line in f:
                row = json.loads(line)
                if row.get('race_id') == race_id:
                    rows.append(row)
        return rows

    def choose_primary(self, race_id: str) -> dict:
        """Closest snapshot to T-15 among those at least 5 minutes before post. Not fit on history."""
        eligible = [s for s in self.snapshots(race_id) if s.get('minutes_to_post') is not None and s['minutes_to_post'] >= PRIMARY_MIN_MINUTES]
        if not eligible:
            late = self.snapshots(race_id)
            if not late:
                raise ValueError('no odds snapshot')
            chosen = max(late, key=lambda s: s['timestamp'])
            chosen = dict(chosen)
            chosen['quality_flags'] = ['LATE_SNAPSHOT']
            return chosen
        return min(eligible, key=lambda s: abs(s['minutes_to_post'] - PRIMARY_TARGET_MINUTES))

    def capture_primary(self, race_id: str, decision: dict):
        self._reject_lookahead(decision)
        horses = []
        for h in decision.get('horses') or []:
            raw_missing = h.get('decision_time_odds') is None
            horses.append({
                **h,
                'decision_time_odds': None if raw_missing else h.get('decision_time_odds'),
                'raw_missing_odds': raw_missing,
                'final_odds': None,
            })
        payload = {
            **decision,
            'horses': horses,
            'SHADOW_ONLY': True,
            'purchased': False,
            'primary_rule': f'closest_to_T-{PRIMARY_TARGET_MINUTES}_among_T_minus_at_least_{PRIMARY_MIN_MINUTES}',
            'schema': FORWARD_V1,
            'code_hash': code_hash(),
        }
        capture_decision(payload, directory=self.directory)
        cur = self.state(race_id)
        if cur is None:
            self._set_state(race_id, 'OBSERVED')
        if self.state(race_id)['state'] == 'OBSERVED':
            self._set_state(race_id, 'DECISION_CAPTURED')
        self.append_event(race_id, 'DECISION_CAPTURED', {'race_id': race_id, 'flags': decision.get('quality_flags') or []}, 'primary')

    def capture_shadow(self, race_id: str, shadow: dict):
        if shadow.get('purchased') is True:
            raise RuntimeError('shadow record cannot be purchased')
        shadow = {**shadow, 'SHADOW_ONLY': True, 'purchased': False, 'real_money': 0}
        capture_decision({'race_id': race_id, 'purpose': 'shadow_observation', **shadow}, directory=self.directory)
        if self.state(race_id)['state'] == 'DECISION_CAPTURED':
            self._set_state(race_id, 'SHADOW_CREATED')
        self.append_event(race_id, 'SHADOW_CREATED', {'bet_type': shadow.get('bet_type'), 'skip_reason': shadow.get('skip_reason')}, 'shadow')

    def capture_result(self, race_id: str, result: dict):
        append_result(race_id, race_id, result.get('finish'), result.get('payouts'),
                      directory=self.directory, final_odds=result.get('final_odds'),
                      refund_status=result.get('refund_status'))
        cur = self.state(race_id)['state']
        if cur == 'FAILED_RETRYABLE':
            self._set_state(race_id, 'SHADOW_CREATED')
            cur = 'SHADOW_CREATED'
        if cur == 'SHADOW_CREATED':
            self._set_state(race_id, 'RESULT_CAPTURED')
        self.append_event(race_id, 'RESULT_CAPTURED', {'race_id': race_id}, result.get('result_id') or 'official')
        self._settle_and_evaluate(race_id, result)

    def mark_retry(self, race_id: str, error: str):
        cur = self.state(race_id)
        if cur and cur['retry_count'] + 1 > MAX_RESULT_RETRIES:
            self._set_state(race_id, 'INVALID', error=error)
            return
        self._set_state(race_id, 'FAILED_RETRYABLE', error=error, bump_retry=True)

    def resume_waiting(self) -> list:
        with self._connect() as con:
            rows = con.execute(
                "SELECT race_id, state, retry_count FROM races WHERE state IN ('OBSERVED','DECISION_CAPTURED','SHADOW_CREATED','FAILED_RETRYABLE')"
            ).fetchall()
        return [{'race_id': r[0], 'state': r[1], 'retry_count': r[2]} for r in rows]

    def summary(self) -> dict:
        with self._connect() as con:
            rows = con.execute('SELECT state, COUNT(*) FROM races GROUP BY state').fetchall()
        counts = {r[0]: r[1] for r in rows}
        return {
            'schema': FORWARD_V1,
            'races': counts,
            'n_races': sum(counts.values()),
            'n_completed': counts.get('EVALUATED', 0),
            'n_waiting': sum(counts.get(s, 0) for s in ('OBSERVED', 'DECISION_CAPTURED', 'SHADOW_CREATED', 'FAILED_RETRYABLE')),
            'real_purchase': 0,
        }

    def _settle_and_evaluate(self, race_id: str, result: dict):
        stake = 0
        profit = None
        confidence = 'UNVERIFIED'
        bet = result.get('shadow_bet_type')
        if bet:
            confidence = PAYOUT_CONFIDENCE.get(bet, 'UNVERIFIED')
        if bet == '単勝' and confidence == 'VERIFIED':
            stake = 100
            odds = None
            finish = result.get('finish') or []
            winner = str(finish[0]) if finish else None
            finals = result.get('final_odds') or {}
            if winner and str(winner) in {str(k) for k in finals}:
                odds = finals.get(winner) or finals.get(str(winner))
            hit = result.get('shadow_selection') == winner
            payout = (float(odds) * stake) if hit and odds else 0
            profit = payout - stake
        settlement = {
            'race_id': race_id, 'confidence': confidence, 'stake': stake, 'profit': profit,
            'real_money': 0, 'official_roi': profit is not None,
        }
        self.append_event(race_id, 'SETTLED', settlement, 'settlement')
        if self.state(race_id)['state'] == 'RESULT_CAPTURED':
            self._set_state(race_id, 'SETTLED')
        evaluation = {'race_id': race_id, 'rank_metrics': result.get('rank_metrics'), 'odds_move': result.get('odds_move')}
        self.append_event(race_id, 'EVALUATED', evaluation, 'evaluation')
        if self.state(race_id)['state'] == 'SETTLED':
            self._set_state(race_id, 'EVALUATED')

    def _reject_lookahead(self, decision: dict):
        bad = BANNED_DECISION & set(decision)
        if bad:
            raise ValueError(f'decision rejected: {sorted(bad)}')
        for h in decision.get('horses') or []:
            if h.get('final_odds') not in (None, ''):
                raise ValueError('final_odds rejected on decision')
            if 'chakujun' in h or 'finish' in h:
                raise ValueError('finish rejected on decision horse')


def odds_move(decision_odds, final_odds):
    if decision_odds in (None, 0) or final_odds in (None, 0):
        return {'status': 'MISSING'}
    d, f = float(decision_odds), float(final_odds)
    return {
        'decision_time_odds': d,
        'final_odds': f,
        'absolute_move': f - d,
        'relative_move': (f - d) / d,
        'implied_probability_move': (1 / f) - (1 / d),
    }


def rank_of(scores: dict, higher_better=True) -> dict:
    items = [(k, v) for k, v in scores.items() if v is not None]
    items.sort(key=lambda kv: kv[1], reverse=higher_better)
    return {k: i + 1 for i, (k, _) in enumerate(items)}


def run_synthetic(directory: str) -> dict:
    store = ForwardStore(directory)
    race = 'synthetic-forward-1'
    store.observe(race, {'source': 'synthetic'})
    horses_t60 = [{'umaban': 1, 'decision_time_odds': 4.0, 'popularity': 2, 'final_odds': None},
                  {'umaban': 2, 'decision_time_odds': 3.0, 'popularity': 1, 'final_odds': None}]
    horses_t15 = [{'umaban': 1, 'decision_time_odds': 3.5, 'popularity': 1, 'final_odds': None},
                  {'umaban': 2, 'decision_time_odds': 3.2, 'popularity': 2, 'final_odds': None}]
    store.add_odds_snapshot(race, {'timestamp': '2026-09-22T00:00:00+00:00', 'minutes_to_post': 60, 'source': 'synthetic', 'horses': horses_t60})
    store.add_odds_snapshot(race, {'timestamp': '2026-09-22T00:45:00+00:00', 'minutes_to_post': 15, 'source': 'synthetic', 'horses': horses_t15})
    store.add_odds_snapshot(race, {'timestamp': '2026-09-22T00:45:00+00:00', 'minutes_to_post': 15, 'source': 'synthetic', 'horses': horses_t15})
    primary = store.choose_primary(race)
    assert primary['minutes_to_post'] == 15
    influence = {1: 0.4, 2: 0.2}
    pop = {1: 1, 2: 2}
    store.capture_primary(race, {
        'race_id': race,
        'minutes_to_post': primary['minutes_to_post'],
        'horses': [{
            'umaban': 1,
            'decision_time_odds': 3.5,
            'popularity': 1,
            'influence_independent_score': influence[1],
            'influence_independent_rank': rank_of(influence)[1],
            'popularity_rank': pop[1],
            'influence_vs_market_delta': pop[1] - rank_of(influence)[1],
            'vh_score': None,
            'raw_missing_note': 'missing stays null',
        }, {
            'umaban': 2,
            'decision_time_odds': 3.2,
            'popularity': 2,
            'influence_independent_score': influence[2],
            'influence_independent_rank': rank_of(influence)[2],
            'popularity_rank': pop[2],
        }],
        'weights_hash': 'synthetic',
        'rule_version': FORWARD_V1,
    })
    store.capture_shadow(race, {
        'bet_type': '単勝', 'tickets': [{'umaban': 1}], 'skip_reason': None, 'zone': 'D', 'gate': None,
        'horses': [{'umaban': 1, 'decision_time_odds': 3.5, 'final_odds': None}],
    })
    move = odds_move(3.5, 3.1)
    store.capture_result(race, {
        'finish': [1, 2],
        'payouts': {'単勝': [{'umaban': 1, 'yen_per_100': 310}]},
        'final_odds': {'1': 3.1, '2': 3.4},
        'refund_status': None,
        'shadow_bet_type': '単勝',
        'shadow_selection': 1,
        'odds_move': {'1': move},
        'rank_metrics': {'note': 'forward_only'},
        'result_id': 'synthetic-official',
    })
    return store.summary()
