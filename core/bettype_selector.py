# -*- coding: utf-8 -*-
"""第1段階: 券種選択 / 第2段階: 既存playbook選択（bet_selector_v1）。

研究で確定したルールのみ。NNV・馬連・馬単は live セレクターに含めない。
"""
from __future__ import annotations

SELECTOR_RULE_VERSION = 'bet_selector_v1'
CROSS_N_TRIO_THRESHOLD = 3

# 券種（第1段階）
BET_TRIO = '3連複'
BET_TRIFECTA = '3連単'
BET_SKIP = None

# 診断ラベル（券の形そのものではない。旧UIの型目安）
# N=人気 / R=能力(Rank) / V=穴(VH)
DIAG_NNV = 'NNV'
DIAG_RRV = 'RRV'
DIAG_RRR = 'RRR'
DIAG_PLAIN = {
    DIAG_NNV: '人気＋穴',
    DIAG_RRV: '能力＋穴',
    DIAG_RRR: '能力のみ',
}

# 既存 playbook 識別子（第2段階）
PLAYBOOK_D_TRIO_2 = 'd_ninki_trio_2'
PLAYBOOK_C_TRIO_236 = 'c_ltr_trio_236'
PLAYBOOK_C_TRIFECTA_247 = 'c_ltr_trifecta_247'
PLAYBOOK_BA_SKIP = 'ba_skip'


def compute_cross_n(proj_scores, vh_scores, horses=None):
    """Rank上位4 ∩ VH上位4（consensus_view.compute_cross_n と同一定義）。

    proj_scores: {umaban: float} Projected Score（素点）。高いほど Rank 上位。
    vh_scores: {umaban: float} VH スコア。高いほど VH 上位。
    horses: 省略可。proj/vh に無い出走馬を rows に含める場合に使用。
    """
    from core import consensus_view as _cv
    proj_scores = proj_scores or {}
    vh_scores = vh_scores or {}
    if horses:
        umabans = [int(h['umaban']) for h in horses if h.get('umaban') is not None]
    else:
        umabans = list(set(proj_scores) | set(vh_scores))
    rows = []
    for u in umabans:
        if u not in proj_scores:
            continue
        rows.append({'umaban': u, 'proj': float(proj_scores[u])})
    if len(rows) < 4 or len(vh_scores) < 4:
        return 0
    return _cv.compute_cross_n(rows, vh_scores)


def select_bet_type(zone, cross_n):
    """第1段階: このレースで何券種を使うか。"""
    zone = str(zone or '')
    try:
        cross_n = int(cross_n)
    except (TypeError, ValueError):
        cross_n = 0
    if zone == 'BA':
        return BET_SKIP
    if zone == 'D':
        return BET_TRIO
    if zone == 'C':
        if cross_n >= CROSS_N_TRIO_THRESHOLD:
            return BET_TRIO
        return BET_TRIFECTA
    return BET_SKIP


def select_playbook(bet_type, zone, cross_n):
    """第2段階: 選ばれた券種を既存 playbook のどれで実行するか。"""
    zone = str(zone or '')
    bet_type = bet_type if bet_type is not None else select_bet_type(zone, cross_n)
    if zone == 'BA' or bet_type is BET_SKIP:
        return PLAYBOOK_BA_SKIP
    if zone == 'D':
        return PLAYBOOK_D_TRIO_2
    if zone == 'C':
        if bet_type == BET_TRIO:
            return PLAYBOOK_C_TRIO_236
        return PLAYBOOK_C_TRIFECTA_247
    return PLAYBOOK_BA_SKIP


def _zone_code(zone):
    z = str(zone or '').strip()
    if z in ('D', 'D鉄板') or z.startswith('D'):
        return 'D'
    if z in ('C', 'C中庸') or z.startswith('C'):
        return 'C'
    if z in ('BA', 'B', 'A', '荒れ', '荒れゾーン') or z.startswith('B') or z.startswith('A'):
        return 'BA'
    return z


def diag_family(zone, cross_n):
    """エンジン内部の判定パターン。買い目フォーメーションそのものではない。

    戻り値: {'code': 'NNV'|'RRV'|'RRR'|None, 'plain': 日本語, 'verdict': 判定文}
    """
    z = _zone_code(zone)
    try:
        n = int(cross_n)
    except (TypeError, ValueError):
        n = 0
    if z == 'D':
        code = DIAG_NNV
        verdict = '鉄板なので3連複を優先'
    elif z == 'C' and n >= CROSS_N_TRIO_THRESHOLD:
        code = DIAG_RRV
        verdict = 'クロスが多いので3連単ではなく3連複を優先'
    elif z == 'C':
        code = DIAG_RRR
        verdict = 'クロスが少ないので3連単を優先'
    else:
        return {'code': None, 'plain': '見送り', 'verdict': '荒れ見込みなので見送り'}
    return {'code': code, 'plain': DIAG_PLAIN[code], 'verdict': verdict}


def selection_reason(zone, cross_n, bet_type=None, playbook=None):
    """ログ用の短い理由文字列。"""
    zone = str(zone or '')
    try:
        cross_n = int(cross_n)
    except (TypeError, ValueError):
        cross_n = 0
    bet_type = bet_type if bet_type is not None else select_bet_type(zone, cross_n)
    playbook = playbook if playbook is not None else select_playbook(bet_type, zone, cross_n)
    if zone == 'D':
        return 'D → 3連複'
    if zone == 'BA':
        return 'BA → 見送り'
    if zone == 'C' and cross_n >= CROSS_N_TRIO_THRESHOLD:
        return 'C + cross_n >= 3 → 3連複'
    if zone == 'C':
        return 'C + cross_n < 3 → 3連単 RRR'
    return '見送り'


def select(zone, cross_n):
    """券種 + playbook + メタをまとめて返す。"""
    try:
        cross_n = int(cross_n)
    except (TypeError, ValueError):
        cross_n = 0
    bet_type = select_bet_type(zone, cross_n)
    playbook = select_playbook(bet_type, zone, cross_n)
    skip = zone == 'BA' or bet_type is BET_SKIP
    diag = diag_family(zone, cross_n)
    return {
        'zone': zone,
        'cross_n': cross_n,
        'selected_bet_type': bet_type,
        'selected_playbook': playbook,
        'selector_rule_version': SELECTOR_RULE_VERSION,
        'selection_reason': selection_reason(zone, cross_n, bet_type, playbook),
        'skip': skip,
        'diag_family': diag.get('code'),
        'diag_plain': diag.get('plain'),
        'diag_verdict': diag.get('verdict'),
    }


# playbook → 表示名（UI専用。ui_line と語彙を揃える）
PLAYBOOK_PLAIN = {
    PLAYBOOK_D_TRIO_2: '3連複 2点（人気1・2番を軸、人気3・4番を相手）',
    PLAYBOOK_C_TRIO_236: '3連複 Rank2-3-6（能力順）',
    PLAYBOOK_C_TRIFECTA_247: '3連単 Rank2-4-7（能力順・30点）',
    PLAYBOOK_BA_SKIP: '見送り',
}


def decision_chain(zone, cross_n, cross_n_source='given'):
    """Rule B の判定の道筋をUI表示用に返す（表示専用）。

    計算・閾値・買い目生成は一切行わず、既存 select() の結果を
    平易な日本語の手順に翻訳するだけ。

    cross_n_source: build_tickets の rec['cross_n_source']
      ('given'|'computed'|'unavailable')。unavailable のとき C は
      0頭扱い（安全側）であることを明示する。

    戻り値: {'playbook', 'bet_type', 'plain', 'steps': [str, ...],
             'applied': bool, 'skip': bool}
    """
    z = _zone_code(zone)
    try:
        n = int(cross_n)
    except (TypeError, ValueError):
        n = 0
    sel = select(z, n)
    pb = sel['selected_playbook']
    zone_plain = {
        'D': 'D鉄板（堅いレース）',
        'C': 'C中庸（市場が迷いやすいレース）',
        'BA': '荒れ（荒れる見込みのレース）',
    }.get(z, str(zone))
    steps = [f'ゾーン: {zone_plain}']
    if z == 'C':
        if cross_n_source == 'unavailable':
            steps.append('共通馬チェック: データ不足のため0頭扱い（安全側）')
        else:
            steps.append(
                f'共通馬チェック: 実力上位4頭と穴候補（VH）上位4頭の共通馬 {n}頭'
                + ('（3頭以上）' if n >= CROSS_N_TRIO_THRESHOLD else '（3頭未満）'))
    if pb == PLAYBOOK_BA_SKIP:
        steps.append('Rule B: 荒れゾーンは対象外 → 見送り'
                     '（馬連・ワイド救済もholdout検証で却下済み）')
        applied = False
    else:
        steps.append(f'Rule B: 適用 → {PLAYBOOK_PLAIN.get(pb, str(pb))}')
        applied = True
    return {
        'playbook': pb,
        'bet_type': sel['selected_bet_type'],
        'plain': PLAYBOOK_PLAIN.get(pb, str(pb)),
        'steps': steps,
        'applied': applied,
        'skip': sel['skip'],
    }
