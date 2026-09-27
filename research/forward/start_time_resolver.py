# -*- coding: utf-8 -*-
"""Read scheduled post times from existing netkeiba HTML. Never infer from race number."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

_ITEM = re.compile(
    r'race_id=(\d{12}).{0,4000}?RaceList_Itemtime">\s*(\d{1,2}:\d{2})',
    re.S,
)
_RACE_DATA = re.compile(
    r'race_id=(\d{12}).{0,4000}?class="RaceData">.{0,160}?(\d{1,2}:\d{2})',
    re.S,
)
_HASSO = re.compile(r'(\d{1,2}:\d{2})\s*発走')
_KAISAI_DATE = re.compile(r'kaisai_date=(\d{8})')


def page_dates(html: str) -> list[str]:
    return list(dict.fromkeys(_KAISAI_DATE.findall(html or '')))


def parse_list_start_times(html: str, requested_date: str) -> dict:
    """Map race_id -> record. Reject the page when it does not name requested_date."""
    dates = page_dates(html)
    if html and dates and requested_date not in dates:
        return {'_page': {'flags': ['STALE_RACE_LIST'], 'dates': dates}}
    if html and not dates and 'RaceList_Itemtime' not in html:
        return {'_page': {'flags': ['NO_JRA_MEETING']}}
    out = {}
    if dates and requested_date not in dates:
        return out
    for race_id, clock in _ITEM.findall(html or ''):
        if race_id in out:
            continue
        out[race_id] = {
            'scheduled_start_time': clock,
            'timezone': 'Asia/Tokyo',
            'source': 'race_list_sub.RaceList_Itemtime',
            'confidence': 'SOURCE_PARSED',
            'flags': [],
        }
    for race_id, clock in _RACE_DATA.findall(html or ''):
        out.setdefault(race_id, {
            'scheduled_start_time': clock,
            'timezone': 'Asia/Tokyo',
            'source': 'race_list_sub.RaceData',
            'confidence': 'SOURCE_PARSED',
            'flags': [],
        })
    return out


def parse_detail_start_time(html: str) -> str | None:
    match = _HASSO.search(html or '')
    return match.group(1) if match else None


def resolve_start_time(race_id: str, requested_date: str, race_metadata: dict | None = None,
                       list_html: str | None = None, detail_html: str | None = None,
                       now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)
    meta = race_metadata or {}
    flags = []
    listed = parse_list_start_times(list_html or '', requested_date)
    page = listed.get('_page') or {}
    flags.extend(page.get('flags') or [])
    hit = listed.get(str(race_id))
    clock = None
    source = None
    confidence = 'UNKNOWN'
    if hit:
        clock = hit['scheduled_start_time']
        source = hit['source']
        confidence = hit['confidence']
    elif detail_html:
        clock = parse_detail_start_time(detail_html)
        if clock:
            source = 'shutuba.RaceData01'
            confidence = 'SOURCE_PARSED'
            flags.append('DETAIL_FALLBACK')
    elif meta.get('post_time'):
        clock = meta['post_time']
        source = meta.get('start_time_source') or 'metadata'
        confidence = 'SOURCE_EXACT'
    if clock is None:
        flags.append('START_TIME_MISSING')
    return {
        'race_id': str(race_id),
        'requested_date': requested_date,
        'scheduled_start_time': clock,
        'timezone': 'Asia/Tokyo',
        'source': source,
        'confidence': confidence,
        'retrieved_at': now.astimezone(JST).isoformat(),
        'validation_flags': flags,
    }


def to_jst(requested_date: str, clock: str) -> datetime | None:
    if not clock or not requested_date:
        return None
    day = datetime.strptime(requested_date, '%Y%m%d').replace(tzinfo=JST)
    hour, minute = clock.split(':', 1)
    return day.replace(hour=int(hour), minute=int(minute[:2]), second=0, microsecond=0)
