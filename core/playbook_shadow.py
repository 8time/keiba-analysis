# -*- coding: utf-8 -*-
"""Cゾーン 的中率重視 Shadow（3連複 Rank2-4-8）。

本番 playbook（2-3-6）には影響しない。毎レース計算し bets.json に別キーで保存する。
"""
from core import bettype_selector as _bts
from core import trio_engine as _te

SHADOW_BETS_KEY = 'playbook_shadow_c248'
SHADOW_ID = 'c_trio_hitrate_248'
SHADOW_MODE = 'hitrate'
SHADOW_FORMATION = '2-4-8'
SHADOW_SHAPE = (2, 4, 8)
SHADOW_BUDGET_YEN = 700
SHADOW_SPEC_VERSION = 'c248_v1'
SHADOW_MIN_RACES = 100
SHADOW_TARGET_RACES = 300
SHADOW_UI_LINE = 'C中庸｜的中率Shadow｜3連複 Rank2-4-8（本番では使いません）'


def applicable(production_rec):
    """Shadow 対象: C ゾーン & cross_n≥3 & 本番が 2-3-6 セル。"""
    rec = production_rec or {}
    if rec.get('zone') != 'C':
        return False
    if rec.get('selected_playbook') != _bts.PLAYBOOK_C_TRIO_236:
        return False
    try:
        if int(rec.get('cross_n') or 0) < _bts.CROSS_N_TRIO_THRESHOLD:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _trio_rows(combos, names):
    rows = []
    for c in combos:
        t = tuple(sorted(int(x) for x in c))
        rows.append({
            'combo': t,
            'kind': '3連複',
            'label': '-'.join(str(u) for u in t),
            'names': tuple(names.get(u, '') for u in t),
        })
    return rows


def build_shadow_rec(production_rec):
    """本番 rec から Shadow 2-4-8 を組む。本番 dict は変更しない。"""
    rec = production_rec or {}
    base = {
        'race_id': rec.get('race_id'),
        'zone': rec.get('zone'),
        'cross_n': rec.get('cross_n'),
        'shadow_id': SHADOW_ID,
        'shadow_mode': SHADOW_MODE,
        'shadow_spec_version': SHADOW_SPEC_VERSION,
        'formation': SHADOW_FORMATION,
        'budget_yen': SHADOW_BUDGET_YEN,
        'production_playbook': rec.get('selected_playbook'),
        'ui_line': SHADOW_UI_LINE,
        'rank_logic': 'ltr',
        'strategy': 'c_ltr_trio_248_shadow',
        'selected_bet_type': '3連複',
        'trio': [],
        'trifecta': [],
        'n_points': 0,
        'skip': True,
        'skip_reason': None,
        'skip_detail': None,
        'warning': None,
    }
    if not applicable(rec):
        base['skip_reason'] = 'not_applicable'
        base['skip_detail'] = 'C・cross_n≥3・本番2-3-6 以外'
        return base

    order = list(rec.get('ltr_order_top8') or [])
    names = {}
    for row in rec.get('trio') or []:
        if isinstance(row, dict) and row.get('combo'):
            for u in row['combo']:
                names[int(u)] = (row.get('names') or ['', '', ''])[0]
    if len(order) < 8:
        base['skip_reason'] = 'ltr_insufficient'
        base['skip_detail'] = 'ltr order %d < 8' % len(order)
        base['warning'] = 'Shadow 2-4-8: 能力順8頭分が足りません'
        return base

    a, b, c = SHADOW_SHAPE
    combos = _te.build_formation(order[:a], order[:b], order[:c])
    n = len(combos)
    if n == 0:
        base['skip_reason'] = 'no_tickets'
        return base

    base['trio'] = _trio_rows(combos, names)
    base['ltr_order_top8'] = order[:8]
    base['n_points'] = n
    base['stake_per_ticket'] = round(SHADOW_BUDGET_YEN / n, 2)
    base['investment'] = SHADOW_BUDGET_YEN
    base['skip'] = False
    base['partners_logic'] = 'ltr_nested_2_4_8_shadow'
    return base


def snapshot_payload(shadow_rec):
    shadow_rec = shadow_rec or {}
    return {
        'bets': {'trio': shadow_rec.get('trio') or [], 'trifecta': []},
        'axis': (shadow_rec.get('ltr_order_top8') or [])[:2],
        'meta': {
            'race_id': shadow_rec.get('race_id'),
            'zone': shadow_rec.get('zone'),
            'shadow_id': shadow_rec.get('shadow_id'),
            'shadow_mode': shadow_rec.get('shadow_mode'),
            'shadow_spec_version': shadow_rec.get('shadow_spec_version'),
            'formation': shadow_rec.get('formation'),
            'budget_yen': shadow_rec.get('budget_yen'),
            'production_playbook': shadow_rec.get('production_playbook'),
            'n_points': shadow_rec.get('n_points'),
            'stake_per_ticket': shadow_rec.get('stake_per_ticket'),
            'ui_line': shadow_rec.get('ui_line'),
            'skip': shadow_rec.get('skip'),
            'skip_reason': shadow_rec.get('skip_reason'),
            'warning': shadow_rec.get('warning'),
            'cross_n': shadow_rec.get('cross_n'),
        },
        'warning': shadow_rec.get('warning'),
    }


def persist(race_id, production_rec):
    """Shadow を bets.json に保存。本番 playbook は触らない。"""
    if not race_id:
        return None
    from core import newspaper as np
    shadow = build_shadow_rec(production_rec)
    if not shadow:
        return None
    extra = {
        'zone': shadow.get('zone'),
        'shadow_id': shadow.get('shadow_id'),
        'shadow_mode': shadow.get('shadow_mode'),
        'shadow_spec_version': shadow.get('shadow_spec_version'),
        'formation': shadow.get('formation'),
        'budget_yen': shadow.get('budget_yen'),
        'stake_per_ticket': shadow.get('stake_per_ticket'),
        'production_playbook': shadow.get('production_playbook'),
        'cross_n': shadow.get('cross_n'),
        'ui_line': shadow.get('ui_line'),
        'skip': shadow.get('skip'),
        'skip_reason': shadow.get('skip_reason'),
        'ticket_type': '3連複',
        'ticket_count': int(shadow.get('n_points') or 0),
        'investment': int(shadow.get('investment') or 0) if not shadow.get('skip') else 0,
        'strategy': shadow.get('strategy'),
    }
    prev = None
    try:
        prev = np.load_bets(race_id)
    except Exception:
        prev = None
    np.write_bets_snapshot(race_id, SHADOW_BETS_KEY, snapshot_payload(shadow), extra=extra)
    try:
        from core import playbook_ledger as plg
        plg.preserve_shadow_outcome_if_same(race_id, shadow, prev)
    except Exception:
        pass
    return shadow
