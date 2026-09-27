# -*- coding: utf-8 -*-
"""Vエリア P1：既存検証済み注記の表示用集約（判定ロジックは各モジュールに委譲）。"""
import html
import re

from core.pace_map import finish_push_delta, resolve_v_pos

# 表示順（固定）
TAG_SPURT = '🔥末脚'
TAG_DANGER = '⚠危険'
TAG_DRAW = '◆枠'
TAG_VENUE = '◇場'


def _pop_of(row, pop_key='Popularity'):
    try:
        v = row.get(pop_key) if hasattr(row, 'get') else None
        if v is None and hasattr(row, '__getitem__'):
            v = row.get('Popularity') or row.get('ninki')
        return int(float(v)) if v is not None and str(v).strip() not in ('', 'nan') else None
    except (TypeError, ValueError):
        return None


def _waku_of(row):
    for k in ('Waku', 'waku', 'Frame'):
        try:
            v = row.get(k) if hasattr(row, 'get') else None
            if v is not None and str(v).strip() not in ('', 'nan'):
                return int(float(v))
        except (TypeError, ValueError):
            pass
    return None


def push_display_flag(umaban, name, score, profiles, pos4, finish):
    """≫表示用。build_v_matrix と同じ finish_push_delta 契約（表示のみ）。"""
    pos, src = resolve_v_pos(umaban, name, score, profiles=profiles, pos4=pos4)
    fin = None
    if finish:
        fin = finish.get(umaban)
        if fin is None:
            fin = finish.get(str(umaban))
    delta = finish_push_delta(pos, fin, src)
    from core.pace_map import V_FINISH_PUSH_MIN
    return delta is not None and delta >= V_FINISH_PUSH_MIN


def collect_horse_annotations(
        horses, profiles, df_rows, race_id, tb_emp=None, surface='',
        distance=None, pos4=None, finish=None, v_umaban_set=None,
        track_bias_mod=None, blood_course_mod=None):
    """
    既存関数の結果を馬番ごとに集約。新閾値・新スコアは作らない。

    df_rows: iterable of dict/Series with Umaban, Popularity, Waku, Name
    戻り値: {umaban: {'name', 'in_v', 'push', 'tags': [str,...]}}
    """
    v_set = set(v_umaban_set or [])
    pos4 = pos4 or {}
    finish = finish or {}
    profiles = profiles or {}
    tb = track_bias_mod
    bc = blood_course_mod
    jyo = str(race_id)[4:6] if race_id else ''
    surf = str(surface or '')
    tosu = len(list(df_rows)) if df_rows is not None else len(horses or [])

    row_by_uma = {}
    if df_rows is not None:
        for row in df_rows:
            try:
                u = int(row.get('Umaban') or row.get('umaban'))
                row_by_uma[u] = row
            except (TypeError, ValueError):
                continue

    out = {}
    for h in horses or []:
        u = h.get('umaban')
        if u is None:
            continue
        name = h.get('name', '')
        score = h.get('score', 0.5)
        tags = []
        row = row_by_uma.get(u)

        # 末脚妙味（app.py 既存条件と同一）
        pop = _pop_of(row) if row is not None else None
        prof = profiles.get(name) or {}
        ag = prof.get('agari')
        if ag is not None and ag <= 0.33 and pop is not None and pop >= 6:
            tags.append(TAG_SPURT)

        # 危険人気
        if tb and tb_emp and pop is not None:
            dpi = tb.danger_popular_inner(tb_emp, u, tosu, pop)
            if dpi:
                tags.append(TAG_DANGER)

        # ダート枠信号
        if tb and 'ダ' in surf and row is not None:
            wk = _waku_of(row)
            if wk is not None and pop is not None:
                dds = tb.dirt_draw_signal(wk, pop, 'ダート', jyo=jyo, kyori=distance)
                if dds:
                    tags.append(TAG_DRAW)

        # 場×人気（1-3人気のみ・既存 venue_fav_note）
        if bc and pop is not None:
            vf = bc.venue_fav_note(jyo, surf, pop)
            if vf:
                tags.append(TAG_VENUE)

        _tag_order = {TAG_SPURT: 0, TAG_DANGER: 1, TAG_DRAW: 2, TAG_VENUE: 3}
        tags.sort(key=lambda t: _tag_order.get(t, 99))

        in_v = u in v_set
        push = push_display_flag(u, name, score, profiles, pos4, finish)
        if in_v or push or tags:
            out[u] = {'name': name, 'in_v': in_v, 'push': push, 'tags': tags}
    return out


def format_annotation_lines(annotations, horses_order=None):
    """Markdown/plain 行リスト。V / ≫ → tags 固定順。"""
    if not annotations:
        return []
    order = horses_order
    if order is None:
        order = sorted(annotations.keys())
    lines = []
    for u in order:
        if u not in annotations:
            continue
        a = annotations[u]
        parts = [f"**{u}番**"]
        if a['in_v']:
            parts.append('🏆V')
        if a['push']:
            parts.append('≫')
        parts.extend(a['tags'])
        if len(parts) > 1:
            lines.append(' '.join(parts))
    return lines


def _markdown_bold_to_html(line):
    """format_annotation_lines の **bold** を HTML に変換（エスケープ付き）。"""
    s = html.escape(line, quote=False)
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)


def render_annotations_html(annotations, horses_order=None):
    """Streamlit markdown 用 HTML（ライトテーマで読めるコントラスト）。"""
    lines = format_annotation_lines(annotations, horses_order)
    if not lines:
        return ''
    body = ''.join(
        f"<div style='padding:4px 0;font-size:14px;color:#1f2937;line-height:1.45;'>"
        f"{_markdown_bold_to_html(ln)}</div>"
        for ln in lines)
    return (
        "<div style='margin:8px 0 4px;padding:10px 12px;"
        "background:#f3f4f6;border-radius:8px;"
        "border:1px solid #d1d5db;border-left:4px solid #6b7280;'>"
        "<div style='font-size:12px;color:#374151;font-weight:600;margin-bottom:6px;'>"
        "補助注記（V地図と独立・買い加点なし）</div>"
        f"{body}</div>"
    )
