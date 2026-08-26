# -*- coding: utf-8 -*-
"""プレイブック実券の記録と、確定後だけの成績付け。

買い方（D/C/B-A の券の組み方）はここでも変えない。
生成時点では着順・確定オッズ・払戻を見ない。
的中・払戻・回収率は settle() が確定結果を受け取ったあとだけ付ける。
"""
import os
import json
import glob
import time

UNIT_YEN = 100

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NP_DIR = os.path.join(_ROOT, 'data', 'newspaper')
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')


def generation_fields(rec):
    """買い目が決まった時点で分かることだけ。着順・払戻は入れない。"""
    rec = rec or {}
    zone = rec.get('zone')
    if zone == 'D':
        kind = '3連複'
    elif zone == 'C':
        kind = '3連単'
    else:
        kind = None
    n = int(rec.get('n_points') or 0)
    if n < 0:
        n = 0
    return {
        'ticket_type': kind,
        'ticket_count': n,
        'investment': n * UNIT_YEN,
    }


def tickets_as_tuples(rows, ordered):
    out = []
    for r in rows or []:
        c = r.get('combo') if isinstance(r, dict) else r
        if not c:
            continue
        t = tuple(int(x) for x in c)
        out.append(t if ordered else tuple(sorted(t)))
    return out


def tickets_from_rec(rec):
    rec = rec or {}
    zone = rec.get('zone')
    if zone == 'D':
        return '3連複', tickets_as_tuples(rec.get('trio'), ordered=False)
    if zone == 'C':
        return '3連単', tickets_as_tuples(rec.get('trifecta'), ordered=True)
    return None, []


def race_date_of(race_id, view_meta=None):
    """開催日。race_id 先頭8桁または view の日付。結果ではない。"""
    meta = view_meta or {}
    d = str(meta.get('date') or meta.get('race_date') or '')
    digits = ''.join(ch for ch in d if ch.isdigit())
    if len(digits) >= 8:
        return '%s-%s-%s' % (digits[:4], digits[4:6], digits[6:8])
    rid = ''.join(ch for ch in str(race_id or '') if ch.isdigit())
    if len(rid) >= 8:
        return '%s-%s-%s' % (rid[:4], rid[4:6], rid[6:8])
    return None


def _parse_combo(raw, ordered):
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        nums = [int(x) for x in raw]
    else:
        s = str(raw).replace('-', '').replace(' ', '')
        if s.isdigit() and len(s) >= 6 and len(s) % 2 == 0:
            nums = [int(s[i:i + 2]) for i in range(0, len(s), 2)]
        else:
            return None
    if len(nums) != 3:
        return None
    t = tuple(nums)
    return t if ordered else tuple(sorted(t))


def score_tickets(tickets, ordered, winners):
    """確定配当だけを見て的中・払戻を付ける。tickets は生成済みの組。"""
    bought = []
    for c in tickets or []:
        parsed = c if (isinstance(c, tuple) and len(c) == 3) else _parse_combo(c, ordered)
        if parsed is None:
            continue
        bought.append(parsed if ordered else tuple(sorted(parsed)))
    hit_set = set()
    payout = 0
    actual = []
    for w in winners or []:
        combo = _parse_combo(w.get('combo'), ordered)
        if combo is None:
            continue
        try:
            yen = int(round(float(w.get('payout') or 0)))
        except (TypeError, ValueError):
            yen = 0
        actual.append({'combo': list(combo), 'payout': yen})
        if combo in bought:
            hit_set.add(combo)
            payout += yen
    n = len(bought)
    invest = n * UNIT_YEN
    hit = bool(hit_set)
    roi = round(100.0 * payout / invest, 1) if invest else None
    return {
        'actual_result': actual,
        'hit': hit,
        'hit_count': len(hit_set),
        'payout': payout,
        'investment': invest,
        'roi': roi,
        'ticket_count': n,
    }


def _payouts_from_jv(race_id, bet_label):
    """ローカル jravan.db。生成経路からは呼ばない。"""
    rid = str(race_id or '')
    if not rid or not os.path.exists(_JV_DB):
        return []
    try:
        import sqlite3
        con = sqlite3.connect('file:%s?mode=ro' % _JV_DB, uri=True)
        rows = con.execute(
            "SELECT combo, payout FROM payouts "
            "WHERE bet_type=? AND (race_id=? OR race_key=?)",
            (bet_label, rid, rid)).fetchall()
        con.close()
    except Exception:
        return []
    ordered = bet_label == '3連単'
    out = []
    for combo, pay in rows:
        c = _parse_combo(combo, ordered)
        if c is None:
            continue
        try:
            yen = int(pay)
        except (TypeError, ValueError):
            continue
        out.append({'combo': c, 'payout': yen})
    return out


def _payouts_from_scraper(race_id, ticket_type):
    """確定後専用。result.html の当選組だけ。生成経路からは呼ばない。"""
    from core import scraper as sc
    key = 'trio' if ticket_type == '3連複' else 'trifecta'
    ordered = ticket_type == '3連単'
    raw = sc.fetch_race_payouts(race_id) or {}
    out = []
    for row in raw.get(key) or []:
        c = _parse_combo(row.get('combo'), ordered)
        if c is None:
            continue
        odds = row.get('odds')
        try:
            yen = int(round(float(odds) * UNIT_YEN)) if odds is not None else 0
        except (TypeError, ValueError):
            yen = 0
        out.append({'combo': c, 'payout': yen})
    return out


def official_winners(race_id, ticket_type, official=None, fetch_remote=False):
    """確定結果の当選組。official があればネットしない。"""
    if official is not None:
        if isinstance(official, dict) and 'winners' in official:
            return list(official.get('winners') or [])
        if isinstance(official, list):
            return list(official)
        return []
    if not ticket_type:
        return []
    local = _payouts_from_jv(race_id, ticket_type)
    if local:
        return local
    if fetch_remote:
        return _payouts_from_scraper(race_id, ticket_type)
    return []


def _patch_outcome(race_id, outcome):
    from core.newspaper import _bets_path, _view_path
    for p in (_bets_path(race_id), _view_path(race_id)):
        if not os.path.exists(p):
            continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            pb = data.get('playbook')
            if not isinstance(pb, dict):
                continue
            pb['outcome'] = outcome
            data['playbook'] = pb
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception:
            continue


def _tickets_from_blob(pb):
    extra = (pb or {}).get('extra') or {}
    res = (pb or {}).get('result') or {}
    meta = res.get('meta') or extra
    zone = extra.get('zone') or meta.get('zone')
    bets = res.get('bets') or {}
    kind = extra.get('ticket_type')
    if not kind:
        if zone == 'D':
            kind = '3連複'
        elif zone == 'C':
            kind = '3連単'
    ordered = kind == '3連単'
    rows = (bets.get('trifecta') if ordered else bets.get('trio')) or []
    return kind, tickets_as_tuples(rows, ordered)


def preserve_outcome_if_same(race_id, rec, prev_blob):
    """同じ券を再保存したときだけ、既に付けた確定成績を残す。"""
    prev = (prev_blob or {}).get('playbook') or {}
    old_out = prev.get('outcome')
    if not old_out:
        return
    old_kind, old_tk = _tickets_from_blob(prev)
    new_kind, new_tk = tickets_from_rec(rec)
    if old_kind == new_kind and set(old_tk) == set(new_tk):
        _patch_outcome(race_id, old_out)


def settle(race_id, official=None, fetch_remote=False):
    """確定結果が入ってから的中・払戻を付ける。買い目は作り直さない。"""
    from core.newspaper import load_bets
    data = load_bets(race_id) or {}
    pb = data.get('playbook') or {}
    if not pb:
        return None
    extra = pb.get('extra') or {}
    kind, tickets = _tickets_from_blob(pb)
    if extra.get('skip') or extra.get('zone') == 'BA' or not kind:
        outcome = {
            'settled_at': time.time(),
            'source': 'skip',
            'actual_result': [],
            'hit': False,
            'payout': 0,
            'investment': 0,
            'roi': None,
            'ticket_count': 0,
        }
        _patch_outcome(race_id, outcome)
        return outcome
    winners = official_winners(race_id, kind, official=official,
                               fetch_remote=fetch_remote)
    if not winners and official is None and not fetch_remote:
        return None
    ordered = kind == '3連単'
    scored = score_tickets(tickets, ordered, winners)
    src = 'official' if official is not None else ('remote' if fetch_remote else 'jv')
    outcome = {
        'settled_at': time.time(),
        'source': src,
        'ticket_type': kind,
        **scored,
    }
    _patch_outcome(race_id, outcome)
    return outcome


def entry_from_blob(race_id, data, view_meta=None):
    pb = (data or {}).get('playbook') or {}
    if not pb:
        return None
    extra = pb.get('extra') or {}
    res = pb.get('result') or {}
    meta = res.get('meta') or {}
    zone = extra.get('zone') or meta.get('zone')
    kind, tickets = _tickets_from_blob(pb)
    n = int(extra.get('ticket_count', len(tickets)) or 0)
    invest = int(extra.get('investment', n * UNIT_YEN) or 0)
    oc = pb.get('outcome')
    row = {
        'race_id': str(race_id),
        'race_date': race_date_of(race_id, view_meta),
        'zone': zone,
        'strategy': extra.get('strategy') or meta.get('strategy'),
        'ui_line': extra.get('ui_line') or meta.get('ui_line'),
        'skip': bool(extra.get('skip') or zone == 'BA'),
        'ticket_type': extra.get('ticket_type') or kind,
        'tickets': [list(t) for t in tickets],
        'ticket_count': n,
        'investment': invest,
        'settled': bool(oc),
        'actual_result': (oc or {}).get('actual_result'),
        'hit': (oc or {}).get('hit'),
        'payout': (oc or {}).get('payout'),
        'roi': (oc or {}).get('roi'),
    }
    if oc:
        row['investment'] = int(oc.get('investment', row['investment']) or 0)
        row['ticket_count'] = int(oc.get('ticket_count', row['ticket_count']) or 0)
    return row


def list_entries():
    """playbook キーを持つ bets.json だけ。手動 trio/trifecta エンジンは見ない。"""
    from core.newspaper import load_bets, load_view, _view_path
    out = []
    for p in glob.glob(os.path.join(_NP_DIR, '*.bets.json')):
        rid = os.path.basename(p).split('.')[0]
        try:
            data = load_bets(rid) or {}
        except Exception:
            continue
        if 'playbook' not in data:
            continue
        meta = None
        try:
            vp = _view_path(rid)
            v = load_view(rid) if os.path.exists(vp) else None
            meta = (v or {}).get('meta')
        except Exception:
            meta = None
        row = entry_from_blob(rid, data, meta)
        if row:
            out.append(row)
    out.sort(key=lambda r: (r.get('race_date') or '', r.get('race_id') or ''),
             reverse=True)
    return out


def _zone_stats(rows):
    n = len(rows)
    ticks = sum(int(r.get('ticket_count') or 0) for r in rows)
    settled = [r for r in rows if r.get('settled')]
    ns = len(settled)
    invest = sum(int(r.get('investment') or 0) for r in settled)
    pay = sum(int(r.get('payout') or 0) for r in settled)
    hits = sum(1 for r in settled if r.get('hit'))
    hit_rate = round(100.0 * hits / ns, 1) if ns else None
    roi = round(100.0 * pay / invest, 1) if invest else None
    return {
        'n_races': n,
        'n_settled': ns,
        'n_tickets': ticks,
        'n_hit': hits,
        'hit_rate': hit_rate,
        'investment': invest,
        'payout': pay,
        'roi': roi,
    }


def summarize(entries=None):
    entries = list(entries if entries is not None else list_entries())
    d = [r for r in entries if r.get('zone') == 'D']
    c = [r for r in entries if r.get('zone') == 'C']
    ba = [r for r in entries if r.get('zone') == 'BA' or r.get('skip')]
    bought = [r for r in entries if r.get('zone') in ('D', 'C')]
    return {
        'D': _zone_stats(d),
        'C': _zone_stats(c),
        'BA': _zone_stats(ba),
        'ALL': _zone_stats(bought),
    }
