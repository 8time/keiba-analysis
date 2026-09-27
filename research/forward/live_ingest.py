# -*- coding: utf-8 -*-
"""Discover today's races and record pre-race snapshots. Does not buy tickets."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from research.forward.automation import FORWARD_V1, ForwardStore

JST = timezone(timedelta(hours=9))
SNAPSHOT_TARGETS = (60, 30, 15, 5)
LIVE_VERSION = 'LIVE_INGEST_V1'
FEATURE_KEYS = (
    'PastRuns', 'BattleScore', 'ScoringSignal', 'Projected Score', 'vh_score', 'ltr_score',
    'influence_independent_score', 'ability_score', 'h7_fig', 'spurt_mean3', 'prior_top3_rate',
    'jockey_jyo_win', 'trainer_jyo_t3', 'elim_n', 'elim_keep', 'gate', 'zone', 'cross_n',
)


def _id_is_not_another_day(race_id: str, today_yyyymmdd: str) -> bool:
    head = race_id[:8]
    if len(head) < 8 or not head.isdigit():
        return True
    month, day = int(head[4:6]), int(head[6:8])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return True
    return head == today_yyyymmdd


def parse_race_list_times(html: str) -> dict:
    """Best-effort map of race_id to HH:MM from a race-list page. Empty if not present."""
    import re
    found = {}
    if not html:
        return found
    for match in re.finditer(r'race_id=(\d{12})', html):
        window = html[match.start():match.start() + 500]
        clock = re.search(r'(\d{1,2}:\d{2})', window)
        if clock and match.group(1) not in found:
            found[match.group(1)] = clock.group(1)
    return found


def parse_post_time(text: str, day: datetime) -> datetime | None:
    if not text or ':' not in text:
        return None
    hh, mm = text.strip().split(':', 1)
    try:
        return day.replace(hour=int(hh), minute=int(mm[:2]), second=0, microsecond=0, tzinfo=JST)
    except ValueError:
        return None


class MemorySource:
    """Test double. Production source is NetkeibaSource."""

    def __init__(self, races=None, odds=None, results=None):
        self.races = races or []
        self.odds = odds or {}
        self.results = results or {}
        self.calls = 0

    def discover(self, day: datetime):
        self.calls += 1
        return list(self.races)

    def odds_for(self, race_id: str):
        self.calls += 1
        return self.odds.get(race_id)

    def result_for(self, race_id: str):
        self.calls += 1
        return self.results.get(race_id)


class NetkeibaSource:
    """Uses core.scraper only. Missing fields stay missing."""

    def discover(self, day: datetime):
        from core.scraper import fetch_robust_html
        from research.forward.start_time_resolver import parse_list_start_times, to_jst
        date_str = day.astimezone(JST).strftime('%Y%m%d')
        pages = []
        for url in (
            f'https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}',
            f'https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}',
        ):
            pages.append(fetch_robust_html(url) or '')
        parsed = {}
        for html in pages:
            parsed.update({k: v for k, v in parse_list_start_times(html, date_str).items() if k != '_page'})
        rows = [{'race_id': rid, 'post_time': rec['scheduled_start_time'], 'start_time_source': rec['source'],
                 'confidence': rec['confidence']} for rid, rec in parsed.items()]
        out = []
        for row in rows:
            post = to_jst(date_str, row.get('post_time') or '') or parse_post_time(row.get('post_time') or '', day.astimezone(JST))
            out.append({
                'race_id': str(row.get('race_id')),
                'venue': row.get('venue'),
                'race_num': row.get('race_num'),
                'race_name': row.get('race_name'),
                'post_at': post.isoformat() if post else None,
                'source': row.get('start_time_source') or 'race_list_sub.RaceList_Itemtime',
                'confidence': row.get('confidence'),
            })
        return out

    def odds_for(self, race_id: str):
        from core.scraper import fetch_realtime_odds_api
        raw = fetch_realtime_odds_api(race_id) or {}
        horses = []
        for key, val in raw.items():
            try:
                umaban = int(key)
            except (TypeError, ValueError):
                continue
            odds = val.get('Odds', val.get('odds')) if isinstance(val, dict) else None
            pop = val.get('Ninki', val.get('popularity')) if isinstance(val, dict) else None
            if odds in (None, '', 0, 0.0):
                odds = None
            horses.append({
                'umaban': umaban,
                'decision_time_odds': odds,
                'popularity': pop,
                'final_odds': None,
            })
        return horses

    def result_for(self, race_id: str):
        from core.scraper import fetch_race_result
        try:
            finish = fetch_race_result(race_id)
        except Exception:
            return None
        if not finish:
            return None
        return {'finish': list(finish), 'source': 'core.scraper.fetch_race_result', 'payouts': {}, 'final_odds': None}


def _ensure_table(store: ForwardStore):
    with store._connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS live_races (
            race_id TEXT PRIMARY KEY,
            post_at TEXT,
            discovered_at TEXT,
            flags TEXT,
            targets_done TEXT,
            shadow_done INTEGER DEFAULT 0,
            result_done INTEGER DEFAULT 0)''')


def _load(store, race_id):
    _ensure_table(store)
    with store._connect() as con:
        row = con.execute('SELECT post_at, flags, targets_done, shadow_done, result_done, discovered_at FROM live_races WHERE race_id=?', (race_id,)).fetchone()
    if not row:
        return None
    return {
        'post_at': row[0], 'flags': json.loads(row[1] or '[]'),
        'targets_done': json.loads(row[2] or '[]'),
        'shadow_done': row[3], 'result_done': row[4],
        'discovered_at': row[5],
    }


def _save(store, race_id, rec):
    _ensure_table(store)
    with store._connect() as con:
        con.execute('''INSERT INTO live_races (race_id, post_at, discovered_at, flags, targets_done, shadow_done, result_done)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(race_id) DO UPDATE SET
              post_at=excluded.post_at, flags=excluded.flags, targets_done=excluded.targets_done,
              shadow_done=excluded.shadow_done, result_done=excluded.result_done''',
            (race_id, rec.get('post_at'), rec.get('discovered_at'), json.dumps(rec.get('flags') or []),
             json.dumps(rec.get('targets_done') or []), int(rec.get('shadow_done') or 0), int(rec.get('result_done') or 0)))


def _blank_features():
    return {key: None for key in FEATURE_KEYS}


def tick(store: ForwardStore, source, now: datetime, dry_run: bool = False) -> dict:
    """One pass. `now` must be timezone-aware. Past dates are ignored."""
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(JST)
    today = now.date()
    actions = []
    for race in source.discover(now):
        race_id = str(race.get('race_id') or '')
        if not race_id:
            continue
        post = None
        if race.get('post_at'):
            post = datetime.fromisoformat(race['post_at'])
            if post.tzinfo is None:
                post = post.replace(tzinfo=JST)
        if post and post.astimezone(JST).date() != today:
            actions.append({'race_id': race_id, 'skipped': 'not_today'})
            continue
        rec = _load(store, race_id) or {
            'post_at': None, 'flags': [], 'targets_done': [], 'shadow_done': 0, 'result_done': 0,
            'discovered_at': now.isoformat(),
        }
        if rec.get('post_at') and post and rec['post_at'] != post.isoformat():
            if 'START_TIME_CHANGED' not in rec['flags']:
                rec['flags'].append('START_TIME_CHANGED')
        if post:
            rec['post_at'] = post.isoformat()
        if store.state(race_id) is None:
            store.observe(race_id, {'live': LIVE_VERSION, 'venue': race.get('venue'), 'dry_run': dry_run})
        if post is None:
            if 'START_TIME_MISSING' not in rec['flags']:
                rec['flags'].append('START_TIME_MISSING')
            _save(store, race_id, rec)
            actions.append({'race_id': race_id, 'skipped': 'no_post_time'})
            continue
        minutes = (post - now).total_seconds() / 60.0
        if rec['discovered_at'] and minutes < 5 and not rec['targets_done'] and not rec['shadow_done']:
            if 'LATE_DISCOVERY' not in rec['flags']:
                rec['flags'].append('LATE_DISCOVERY')
                store.append_event(race_id, 'LATE_DISCOVERY', {'minutes_to_post': minutes, 'SHADOW_ONLY': True, 'purchased': False}, 'late')
            _save(store, race_id, rec)
            actions.append({'race_id': race_id, 'skipped': 'late_discovery'})
            continue
        for target in SNAPSHOT_TARGETS:
            if target in rec['targets_done']:
                continue
            if abs(minutes - target) <= 3:
                horses = source.odds_for(race_id) or []
                if not horses:
                    flag = 'ODDS_MISSING'
                    if flag not in rec['flags']:
                        rec['flags'].append(flag)
                    horses = [{'umaban': None, 'decision_time_odds': None, 'popularity': None, 'final_odds': None}]
                store.add_odds_snapshot(race_id, {
                    'timestamp': now.isoformat(),
                    'minutes_to_post': round(minutes, 2),
                    'target': target,
                    'source': 'live_odds',
                    'horses': horses,
                })
                rec['targets_done'].append(target)
                actions.append({'race_id': race_id, 'snapshot': target})
        if (not rec['shadow_done']) and any(t <= 15 for t in rec['targets_done']):
            primary = store.choose_primary(race_id)
            features = _blank_features()
            horses = []
            for h in primary.get('horses') or []:
                row = {**h, **{k: h.get(k) for k in FEATURE_KEYS}}
                for key in FEATURE_KEYS:
                    if row.get(key) in (None, ''):
                        row[key] = None
                horses.append(row)
            if any(h.get('decision_time_odds') is None for h in horses):
                if 'ODDS_MISSING' not in rec['flags']:
                    rec['flags'].append('ODDS_MISSING')
            store.capture_primary(race_id, {
                'race_id': race_id,
                'minutes_to_post': primary.get('minutes_to_post'),
                'horses': horses,
                'quality_flags': rec['flags'],
                'schema': FORWARD_V1,
                'live_version': LIVE_VERSION,
            })
            tickets = None
            skip = 'FEATURE_MISSING'
            try:
                from core.playbook_tickets import build_tickets
                built = build_tickets(race_id, None, [
                    {'umaban': h.get('umaban'), 'name': h.get('name'), 'pop': h.get('popularity')}
                    for h in horses if h.get('umaban') is not None
                ])
                tickets = built.get('tickets')
                skip = built.get('skip_reason')
                features['zone'] = built.get('zone')
            except Exception as exc:
                skip = f'playbook_unavailable:{type(exc).__name__}'
            store.capture_shadow(race_id, {
                'bet_type': None,
                'tickets': tickets,
                'skip_reason': skip,
                'zone': features.get('zone'),
                'gate': None,
                'horses': horses,
                'features': features,
                'SHADOW_ONLY': True,
                'purchased': False,
                'real_money': 0,
            })
            rec['shadow_done'] = 1
            actions.append({'race_id': race_id, 'shadow': True})
        if rec['shadow_done'] and not rec['result_done'] and minutes < -15:
            result = source.result_for(race_id)
            if result and result.get('finish'):
                moves = {}
                for snap in store.snapshots(race_id):
                    for h in snap.get('horses') or []:
                        um = h.get('umaban')
                        if um is None:
                            continue
                        moves.setdefault(str(um), {})[f"T-{snap.get('target')}"] = h.get('decision_time_odds')
                store.capture_result(race_id, {
                    'finish': result.get('finish'),
                    'payouts': result.get('payouts') or {},
                    'final_odds': result.get('final_odds'),
                    'refund_status': result.get('refund_status'),
                    'shadow_bet_type': None,
                    'odds_move': moves,
                    'rank_metrics': {'forward_only': True},
                    'result_id': result.get('source') or 'live_result',
                })
                rec['result_done'] = 1
                actions.append({'race_id': race_id, 'evaluated': True})
            else:
                if 'RESULT_MISSING' not in rec['flags']:
                    rec['flags'].append('RESULT_MISSING')
        _save(store, race_id, rec)
    return {'now': now.isoformat(), 'actions': actions, 'version': LIVE_VERSION}


def status_view(store: ForwardStore, now: datetime) -> dict:
    _ensure_table(store)
    with store._connect() as con:
        rows = con.execute('SELECT race_id, post_at, flags, targets_done, shadow_done, result_done FROM live_races').fetchall()
    races = []
    for row in rows:
        races.append({
            'race_id': row[0], 'post_at': row[1], 'flags': json.loads(row[2] or '[]'),
            'targets_done': json.loads(row[3] or '[]'), 'shadow_done': bool(row[4]), 'result_done': bool(row[5]),
        })
    base = store.summary()
    return {
        'collector': LIVE_VERSION,
        'schema': FORWARD_V1,
        'today': now.astimezone(JST).date().isoformat(),
        'races': races,
        'summary': base,
        'purchase_path': False,
    }
