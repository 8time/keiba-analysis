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

from core.bayes_stats import wilson_interval

UNIT_YEN = 100

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NP_DIR = os.path.join(_ROOT, 'data', 'newspaper')
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')


def _ticket_type_of(rec):
    """生成時点の券種。セレクター優先、なければ zone 互換。"""
    rec = rec or {}
    tt = rec.get('selected_bet_type')
    if tt:
        return tt
    zone = rec.get('zone')
    if zone == 'D':
        return '3連複'
    if zone == 'C':
        return '3連単'
    return None


def generation_fields(rec):
    """買い目が決まった時点で分かることだけ。着順・払戻は入れない。"""
    rec = rec or {}
    kind = _ticket_type_of(rec)
    n = int(rec.get('n_points') or 0)
    if n < 0:
        n = 0
    out = {
        'ticket_type': kind,
        'ticket_count': n,
        'investment': n * UNIT_YEN,
        'recommended_bet_type': rec.get('selected_bet_type'),
        'recommended_playbook': rec.get('selected_playbook'),
        'selector_rule_version': rec.get('selector_rule_version'),
        'cross_n': rec.get('cross_n'),
        'selection_reason': rec.get('selection_reason'),
    }
    return out


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
    kind = _ticket_type_of(rec)
    if kind == '3連複':
        return '3連複', tickets_as_tuples(rec.get('trio'), ordered=False)
    if kind == '3連単':
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
    kind = extra.get('ticket_type') or meta.get('selected_bet_type')
    if not kind:
        if zone == 'D':
            kind = '3連複'
        elif zone == 'C':
            kind = '3連単'
    bets = res.get('bets') or {}
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
    try:
        settle_shadow(race_id, official=official, fetch_remote=fetch_remote)
    except Exception:
        pass
    return outcome


def _shadow_blob(data):
    from core.playbook_shadow import SHADOW_BETS_KEY
    return (data or {}).get(SHADOW_BETS_KEY) or {}


def _tickets_from_shadow_blob(sh):
    res = (sh or {}).get('result') or {}
    bets = res.get('bets') or {}
    rows = bets.get('trio') or []
    return tickets_as_tuples(rows, ordered=False)


def _patch_shadow_outcome(race_id, outcome):
    from core.newspaper import _bets_path
    from core.playbook_shadow import SHADOW_BETS_KEY
    p = _bets_path(race_id)
    if not os.path.exists(p):
        return
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        sh = data.get(SHADOW_BETS_KEY)
        if not isinstance(sh, dict):
            return
        sh['outcome'] = outcome
        data[SHADOW_BETS_KEY] = sh
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def score_shadow_tickets(tickets, winners, budget_yen):
    """Shadow 用: 予算固定・均等配分 stake。"""
    n = len(tickets or [])
    if n <= 0:
        return {
            'actual_result': [], 'hit': False, 'hit_count': 0,
            'payout': 0, 'investment': 0, 'roi': None, 'ticket_count': 0,
        }
    stake = float(budget_yen) / n
    invest = int(round(budget_yen))
    hit_set = set()
    payout = 0
    actual = []
    bought = [tuple(sorted(int(x) for x in c)) for c in tickets]
    for w in winners or []:
        combo = _parse_combo(w.get('combo'), ordered=False)
        if combo is None:
            continue
        try:
            yen = int(round(float(w.get('payout') or 0)))
        except (TypeError, ValueError):
            yen = 0
        actual.append({'combo': list(combo), 'payout': yen})
        if combo in bought:
            hit_set.add(combo)
            payout += int(round(yen * (stake / UNIT_YEN)))
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
        'stake_per_ticket': round(stake, 2),
    }


def preserve_shadow_outcome_if_same(race_id, shadow_rec, prev_blob):
    from core.playbook_shadow import SHADOW_BETS_KEY
    prev = _shadow_blob(prev_blob)
    old_out = prev.get('outcome')
    if not old_out:
        return
    new_tk = tickets_as_tuples((shadow_rec or {}).get('trio'), ordered=False)
    old_tk = _tickets_from_shadow_blob(prev)
    if set(new_tk) == set(old_tk):
        _patch_shadow_outcome(race_id, old_out)


def settle_shadow(race_id, official=None, fetch_remote=False):
    """Shadow 2-4-8 の確定成績。本番 playbook とは独立。"""
    from core.newspaper import load_bets
    from core.playbook_shadow import SHADOW_BETS_KEY, SHADOW_BUDGET_YEN
    data = load_bets(race_id) or {}
    sh = _shadow_blob(data)
    if not sh:
        return None
    extra = sh.get('extra') or {}
    if extra.get('skip'):
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
        _patch_shadow_outcome(race_id, outcome)
        return outcome
    tickets = _tickets_from_shadow_blob(sh)
    if not tickets:
        return None
    budget = int(extra.get('budget_yen') or extra.get('investment') or SHADOW_BUDGET_YEN)
    winners = official_winners(race_id, '3連複', official=official,
                                 fetch_remote=fetch_remote)
    if not winners and official is None and not fetch_remote:
        return None
    scored = score_shadow_tickets(tickets, winners, budget)
    src = 'official' if official is not None else ('remote' if fetch_remote else 'jv')
    outcome = {
        'settled_at': time.time(),
        'source': src,
        'ticket_type': '3連複',
        **scored,
    }
    _patch_shadow_outcome(race_id, outcome)
    return outcome


def shadow_entry_from_blob(race_id, data, view_meta=None):
    from core.playbook_shadow import SHADOW_BETS_KEY
    sh = (data or {}).get(SHADOW_BETS_KEY) or {}
    if not sh:
        return None
    extra = sh.get('extra') or {}
    res = sh.get('result') or {}
    meta = res.get('meta') or {}
    tickets = _tickets_from_shadow_blob(sh)
    n = int(extra.get('ticket_count', len(tickets)) or 0)
    invest = int(extra.get('investment', 0) or 0)
    oc = sh.get('outcome')
    row = {
        'race_id': str(race_id),
        'race_date': race_date_of(race_id, view_meta),
        'zone': extra.get('zone') or meta.get('zone'),
        'formation': extra.get('formation') or meta.get('formation'),
        'shadow_id': extra.get('shadow_id') or meta.get('shadow_id'),
        'ui_line': extra.get('ui_line') or meta.get('ui_line'),
        'skip': bool(extra.get('skip')),
        'ticket_type': '3連複',
        'tickets': [list(t) for t in tickets],
        'ticket_count': n,
        'investment': invest,
        'budget_yen': int(extra.get('budget_yen') or meta.get('budget_yen') or 0),
        'settled': bool(oc),
        'hit': (oc or {}).get('hit'),
        'payout': (oc or {}).get('payout'),
        'roi': (oc or {}).get('roi'),
        'cross_n': extra.get('cross_n') or meta.get('cross_n'),
        'recorded_ts': sh.get('ts'),
    }
    if oc:
        row['investment'] = int(oc.get('investment', row['investment']) or 0)
        row['ticket_count'] = int(oc.get('ticket_count', row['ticket_count']) or 0)
    return row


def list_shadow_entries():
    from core.newspaper import load_bets, load_view, _view_path
    from core.playbook_shadow import SHADOW_BETS_KEY
    out = []
    for p in glob.glob(os.path.join(_NP_DIR, '*.bets.json')):
        rid = os.path.basename(p).split('.')[0]
        try:
            data = load_bets(rid) or {}
        except Exception:
            continue
        if SHADOW_BETS_KEY not in data:
            continue
        meta = None
        try:
            vp = _view_path(rid)
            v = load_view(rid) if os.path.exists(vp) else None
            meta = (v or {}).get('meta')
        except Exception:
            meta = None
        row = shadow_entry_from_blob(rid, data, meta)
        if row:
            out.append(row)
    out.sort(key=lambda r: (r.get('race_date') or '', r.get('race_id') or ''), reverse=True)
    return out


def summarize_shadow_vs_production(shadow_entries=None, production_entries=None):
    """Shadow 2-4-8 と同レースの本番 2-3-6 を比較。"""
    from core.playbook_shadow import SHADOW_MIN_RACES, SHADOW_TARGET_RACES
    shadow_entries = list(shadow_entries if shadow_entries is not None else list_shadow_entries())
    production_entries = list(
        production_entries if production_entries is not None
        else list_entries())
    prod_by_id = {r['race_id']: r for r in production_entries
                  if r.get('zone') == 'C' and not r.get('skip')}
    active = [s for s in shadow_entries if not s.get('skip')]
    settled = [s for s in active if s.get('settled')]
    paired_prod = []
    for s in settled:
        p = prod_by_id.get(s['race_id'])
        if p and p.get('settled'):
            paired_prod.append(p)
    sh_stats = _zone_stats(settled) if settled else _zone_stats([])
    pr_stats = _zone_stats(paired_prod) if paired_prod else _zone_stats([])
    n_settled = len(settled)
    ready = n_settled >= SHADOW_MIN_RACES
    return {
        'shadow': sh_stats,
        'production_paired': pr_stats,
        'n_shadow_total': len(shadow_entries),
        'n_shadow_active': len(active),
        'n_shadow_settled': n_settled,
        'n_paired_settled': len(paired_prod),
        'min_races': SHADOW_MIN_RACES,
        'target_races': SHADOW_TARGET_RACES,
        'evaluation_ready': ready,
        'progress_pct': round(100.0 * n_settled / SHADOW_TARGET_RACES, 1) if SHADOW_TARGET_RACES else 0,
    }


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
        'skip_reason': extra.get('skip_reason'),
        'degraded': bool(extra.get('degraded')),
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


def _max_losing_streak(rows):
    ordered = sorted(
        [r for r in rows if r.get('settled')],
        key=lambda r: (r.get('race_date') or '', r.get('race_id') or ''))
    m = c = 0
    for r in ordered:
        if r.get('hit'):
            c = 0
        else:
            c += 1
            m = max(m, c)
    return m


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
    lo, hi = wilson_interval(hits, ns) if ns else (None, None)
    return {
        'n_races': n,
        'n_settled': ns,
        'n_tickets': ticks,
        'n_hit': hits,
        'hit_rate': hit_rate,
        'investment': invest,
        'payout': pay,
        'roi': roi,
        'loss_per_100': round(100.0 - roi, 1) if roi is not None else None,
        'cost_per_hit': round(invest / hits, 1) if hits else None,
        'hit_rate_lo': round(lo * 100, 1) if lo is not None else None,
        'hit_rate_hi': round(hi * 100, 1) if hi is not None else None,
        'max_losing_streak': _max_losing_streak(rows),
        'avg_investment': round(invest / ns, 1) if ns else None,
    }


def summarize(entries=None):
    entries = list(entries if entries is not None else list_entries())
    d = [r for r in entries if r.get('zone') == 'D']
    c = [r for r in entries if r.get('zone') == 'C']
    ba = [r for r in entries if r.get('zone') == 'BA' or r.get('skip')]
    bought = [r for r in entries if r.get('zone') in ('D', 'C') and not r.get('skip')]
    skipped = [r for r in entries if r.get('skip') or r.get('zone') == 'BA']
    skips_by_reason = {}
    for r in entries:
        reason = r.get('skip_reason')
        if reason:
            skips_by_reason[reason] = skips_by_reason.get(reason, 0) + 1
    total_dc = len(bought) + len(skipped)
    purchase_rate = round(100.0 * len(bought) / total_dc, 1) if total_dc else None
    degraded_n = sum(1 for r in entries if r.get('degraded'))
    return {
        'D': _zone_stats(d),
        'C': _zone_stats(c),
        'BA': _zone_stats(ba),
        'ALL': _zone_stats(bought),
        'skips_by_reason': skips_by_reason,
        'degraded_n': degraded_n,
        'purchase_rate': purchase_rate,
    }
