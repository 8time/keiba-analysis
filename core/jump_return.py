# -*- coding: utf-8 -*-
"""障害帰りの表示判定 — 表示専用。

俗説: 前走が障害、今回が平地（芝またはダート）だと穴で激走することがある。
穴馬ハンターの判断材料として緑の色文字を出すだけ。
vh_score / combo / 材料数 / 推奨買い方 / 予測スコアには一切足さない。
統計上の勝率が高いわけではない（見る印）。
"""
import html as _html

LABEL_COLOR = '#2e7d32'
MEMO_COLOR = '#555555'
LABEL = '障害帰り'


def _surf_text(s):
    return str(s or '').strip()


def is_jump_surface(s):
    t = _surf_text(s)
    if not t:
        return False
    return ('障' in t) or ('障害' in t)


def is_flat_surface(s):
    t = _surf_text(s)
    if not t or is_jump_surface(t):
        return False
    return ('芝' in t) or ('ダ' in t)


def reach(prev_surface, current_surface, prev_distance=None, current_distance=None):
    """前走が障害・今回が芝/ダートなら候補。

    戻り: None（データ不足）/ dict（該当）/ False（条件外れ）。
    """
    prev = _surf_text(prev_surface)
    cur = _surf_text(current_surface)
    if not prev or not cur:
        return None
    if not is_jump_surface(prev):
        return False
    if not is_flat_surface(cur):
        return False
    info = {
        'prev_surface': prev,
        'current_surface': cur,
    }
    try:
        pd = int(float(prev_distance)) if prev_distance not in (None, '') else None
        if pd and pd > 0:
            info['prev_distance'] = pd
    except (TypeError, ValueError):
        pass
    try:
        cd = int(float(current_distance)) if current_distance not in (None, '') else None
        if cd and cd > 0:
            info['current_distance'] = cd
    except (TypeError, ValueError):
        pass
    return info


def label_html(info):
    """穴馬ハンター用の緑文字。info が dict のときだけ返す。"""
    if not isinstance(info, dict):
        return ''
    prev = info.get('prev_surface') or '障害'
    cur = info.get('current_surface') or '平地'
    pd = info.get('prev_distance')
    cd = info.get('current_distance')
    if pd and cd:
        detail = f'前走{prev}{pd}m→今回{cur}{cd}m'
    else:
        detail = f'前走{prev}→今回{cur}'
    return (
        f'<span style="color:{LABEL_COLOR};font-weight:bold;">{LABEL}</span>'
        f'<span style="color:{LABEL_COLOR};">（{_html.escape(detail)}）</span>'
    )


def block_html(info):
    """緑の候補行。候補でないときは空。"""
    head = label_html(info)
    if not head:
        return ''
    cap = (
        f'<div style="color:{MEMO_COLOR};font-size:0.82em;line-height:1.45;margin-top:2px;">'
        f'俗説の見た目印です。点数・順番・買い目には入れていません。</div>'
    )
    return head + cap
