# -*- coding: utf-8 -*-
"""検証済み買い方（buying_playbook_2026-08）をライブ買い目へ写す。

新しい特徴量・スコア・しきい値は作らない。ゾーン境界は formation_stats.ZONE_BOUNDS
（D:0≤v<50 / C:50≤v<70 / B/A:v≥70）をそのまま使う。

役割の分離:
  妙味度     → ゾーン判定のみ
  人気順位   → D で 人気1・2を軸、人気3・4を相手（holdout と同じ。◎〇印は券に使わない）
  LTR Rank   → C の 3連単 Rank2-4-7 のみ（高いほど強い。◎〇は組み込まない）
  Projected Score はここでは使わない
"""
from core import formation_stats as _fs
from core import trio_engine as _te

# UI 見出しは仕様どおり。plain_caption が略語の言い換え。
_ADVICE = {
    'D': {
        'ui_line': 'D鉄板｜人気型｜3連複2点',
        'plain_caption': (
            '堅いレースです。検証どおり人気1番と2番を軸に、人気3番と4番を相手にした'
            '3連複2点だけがデフォルトです。印が人気1・2からずれていても、券は人気1〜4で組みます。'
            '能力順（検証AI）は使いません。'
        ),
        'strategy': 'd_ninki_trio_2',
        'rank_logic': 'popularity',
    },
    'C': {
        'ui_line': 'C中庸｜Rank型｜検証済みフォーメーション',
        'plain_caption': (
            '市場が迷いやすいレースです。デフォルトは能力の高い順（検証AI＝LTR）の'
            '3連単2-4-7（1着=上位2頭／2着=上位4頭／3着=上位7頭）の30点だけです。'
            '印や予測スコアは使いません。'
        ),
        'strategy': 'c_ltr_trifecta_247',
        'rank_logic': 'ltr',
    },
    'BA': {
        'ui_line': '荒れゾーン｜見送り',
        'plain_caption': (
            '荒れる見込みのレースです。デフォルトでは買い目を出しません。'
            '点数を増やして当てにいく運用は検証で回収が悪くなっています。'
        ),
        'strategy': 'ba_skip',
        'rank_logic': 'skip',
    },
}


def advise(vscore):
    """馬が揃う前でも出せるゾーン判定（SRAの保存ブロック直下の推奨買い方用）。"""
    code = _fs.zone_code(vscore)
    a = dict(_ADVICE[code])
    a['zone'] = code
    a['zone_label'] = _fs.ZONE_SHORT.get(_fs.zone_of(vscore), _fs.zone_of(vscore))
    a['vscore'] = None if vscore is None else float(vscore)
    a['skip'] = code == 'BA'
    return a


def _pop_order(horses):
    scored = []
    rest = []
    for h in horses:
        u = h.get('umaban')
        if u is None:
            continue
        p = h.get('pop')
        try:
            p = int(p)
        except (TypeError, ValueError):
            rest.append(int(u))
            continue
        if p <= 0 or p >= 99:
            rest.append(int(u))
            continue
        scored.append((p, int(u)))
    scored.sort()
    return [u for _p, u in scored] + rest


def _ltr_order(horses, ltr_scores):
    """LTR はライブ推論で高いほど強い（LambdaRank）。holdout の ability_score とは符号が逆。"""
    ltr_scores = ltr_scores or {}
    ranked, missing = [], []
    for h in horses:
        u = h.get('umaban')
        if u is None:
            continue
        u = int(u)
        s = ltr_scores.get(u)
        if s is None:
            missing.append(u)
            continue
        try:
            ranked.append((float(s), u))
        except (TypeError, ValueError):
            missing.append(u)
    ranked.sort(key=lambda x: -x[0])
    return [u for _s, u in ranked], missing


def _umaban_at_pop(horses, ninki):
    """人気順位 ninki の馬番。holdout は ninki==1/2/3/4 を直接引いている。"""
    want = int(ninki)
    for h in horses:
        try:
            if int(h.get('pop')) == want:
                return int(h['umaban'])
        except (TypeError, ValueError):
            continue
    return None


def _resolve_axis(horses, axis_marks):
    """表示用。券のD軸には使わない（holdout の軸は常に人気1・2）。"""
    pop = _pop_order(horses)
    marks = axis_marks or {}
    by_mark = {'◎': [], '〇': [], '▲': []}
    for u, mk in marks.items():
        try:
            uu = int(u)
        except (TypeError, ValueError):
            continue
        m = str(mk or '')[:1]
        if m in by_mark:
            by_mark[m].append(uu)
    axis = []
    for mk in ('◎', '〇'):
        for u in by_mark[mk]:
            if u not in axis:
                axis.append(u)
            if len(axis) >= 2:
                return axis[:2]
    for u in pop:
        if u not in axis:
            axis.append(u)
        if len(axis) >= 2:
            break
    return axis[:2]


def _name_map(horses):
    out = {}
    for h in horses:
        try:
            out[int(h['umaban'])] = str(h.get('name') or '')
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _trio_rows(combos, names):
    rows = []
    for c in combos:
        t = tuple(sorted(int(x) for x in c))
        rows.append({
            'combo': t,
            'kind': '3連複',
            'label': '-'.join(f'{u}' for u in t),
            'names': tuple(names.get(u, '') for u in t),
        })
    return rows


def _trifecta_rows(combos, names):
    rows = []
    for c in combos:
        t = tuple(int(x) for x in c)
        rows.append({
            'combo': t,
            'kind': '3連単',
            'label': '→'.join(f'{u}' for u in t),
            'names': tuple(names.get(u, '') for u in t),
        })
    return rows


def build_tickets(race_id, vscore, horses, axis_marks=None, ltr_scores=None):
    """ゾーンに応じたデフォルト買い目。Projected Score は引数に取らない。

    horses: [{'umaban':int,'name':str,'pop':int|None}, ...]
    axis_marks: {umaban: '◎'|'〇'|'▲'}
    ltr_scores: {umaban: float} 高いほど強い。C で必須。
    """
    adv = advise(vscore)
    horses = [h for h in (horses or []) if h.get('umaban') is not None]
    names = _name_map(horses)
    axis = _resolve_axis(horses, axis_marks) if horses else []
    rec = {
        'race_id': str(race_id or ''),
        'zone': adv['zone'],
        'zone_label': adv['zone_label'],
        'vscore': adv['vscore'],
        'strategy': adv['strategy'],
        'rank_logic': adv['rank_logic'],
        'ui_line': adv['ui_line'],
        'plain_caption': adv['plain_caption'],
        'axis': axis,
        'axis_marks': {int(k): str(v) for k, v in (axis_marks or {}).items()
                       if str(v or '')[:1] in ('◎', '〇', '▲')},
        'trio': [],
        'trifecta': [],
        'n_points': 0,
        'skip': adv['skip'],
        'warning': None,
    }
    if not horses:
        rec['warning'] = '出走表がありません'
        rec['skip'] = True
        return rec

    if adv['zone'] == 'BA':
        rec['axis'] = axis
        rec['warning'] = None
        return rec

    if adv['zone'] == 'D':
        # holdout (rank_vs_ninki_legs.py): ◎=ninki1 / 〇=ninki2 を全券固定し、
        # 3頭目は ninki3 と ninki4（=軸を除いた人気上位2頭。軸が1・2のとき同一）。
        a = _umaban_at_pop(horses, 1)
        b = _umaban_at_pop(horses, 2)
        p3 = _umaban_at_pop(horses, 3)
        p4 = _umaban_at_pop(horses, 4)
        rec['axis'] = [u for u in (a, b) if u is not None]
        rec['partners'] = [u for u in (p3, p4) if u is not None]
        rec['partners_logic'] = 'ninki_3_4'
        if None in (a, b, p3, p4) or len({a, b, p3, p4}) < 4:
            rec['warning'] = '人気1〜4番が揃わないため D の2点を出せません'
            rec['skip'] = True
            return rec
        rec['trio'] = _trio_rows(
            [tuple(sorted((a, b, p3))), tuple(sorted((a, b, p4)))], names)
        rec['n_points'] = 2
        return rec

    # C: holdout (c_zone_rank_holdout.tri_shape / vscore_zone_formation.trifecta_tickets)
    # は LTR 上位の集合カーテシアン 2-4-7 のみ。◎〇は使わない。3連複の追加点も無い。
    order, missing = _ltr_order(horses, ltr_scores)
    rec['axis'] = order[:2]
    if len(order) < 7:
        rec['warning'] = (
            '能力順（検証AI）が7頭分取れないため C の推奨買い目を出せません'
            '（予測スコアでは代用しません）'
        )
        rec['skip'] = True
        rec['ltr_missing'] = missing
        return rec
    want = {(x, y, z)
            for x in order[:2] for y in order[:4] for z in order[:7]
            if len({x, y, z}) == 3}
    tri_combos = _te.build_trifecta_formation(order[:2], order[:4], order[:7])
    rec['trifecta'] = _trifecta_rows(tri_combos, names)
    rec['ltr_order_top7'] = order[:7]
    rec['n_points'] = len(rec['trifecta'])
    rec['partners_logic'] = 'ltr_nested_2_4_7'
    rec['skip'] = False
    if set(tri_combos) != want:
        rec['warning'] = '3連単2-4-7の集合がholdout定義と一致しません'
    return rec


def snapshot_payload(rec):
    """newspaper.write_bets_snapshot 用。"""
    rec = rec or {}
    return {
        'bets': {
            'trio': rec.get('trio') or [],
            'trifecta': rec.get('trifecta') or [],
        },
        'axis': rec.get('axis') or [],
        'meta': {
            'race_id': rec.get('race_id'),
            'zone': rec.get('zone'),
            'strategy': rec.get('strategy'),
            'rank_logic': rec.get('rank_logic'),
            'n_points': rec.get('n_points'),
            'ui_line': rec.get('ui_line'),
            'skip': rec.get('skip'),
            'warning': rec.get('warning'),
            'ltr_order_top7': rec.get('ltr_order_top7'),
            'partners': rec.get('partners'),
            'partners_logic': rec.get('partners_logic'),
        },
        'warning': rec.get('warning'),
    }
