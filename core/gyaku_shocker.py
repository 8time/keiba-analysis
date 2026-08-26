# -*- coding: utf-8 -*-
"""逆ショッカーの『出走前リーチ』判定 — 表示専用。

今井雅宏氏Mの法則。穴馬ハンターの判断材料として色文字を出すだけ。
vh_score / combo / 材料数 / 推奨買い方 / 予測スコアには一切足さない。

原典の完成条件は3つ:
  ① 前走3角が5番手以降（中団〜後方）
  ② 今回は前走より距離が短い
  ③ 今回3角が8番手以内（位置を押し上げた）
③はレース中の結果。事前に③を入れると「前に行けた馬は強い」という
結果論になる（scripts/shocker_backtest.py・verified_shocker_leak:
完成込み単ROI128% → ①②だけだと残差-0.3pp・ROI71%でエッジ消滅）。

このモジュールは ①② だけを見る。③は受け取らない。
ラベルは『適合』ではなく『候補』（完成はまだ分からない）。
"""
import re
import html as _html
from datetime import date as _date

# 紫。0.5秒差の赤字とは色を分ける。
LABEL_COLOR = '#6a1b9a'
MEMO_COLOR = '#555555'
LABEL = '🟣 逆ショッカー候補'
# 候補かつ前走僅差(⏱️と同じ: 4着以下・勝ち馬まで0.3秒)のときだけ付ける。見る印。
PAIR_MARK = '🟣⏱️'


def _int(v):
    try:
        n = int(float(v))
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def corner3_from_passing(passing):
    """通過順文字列から3角の番手を取る。取れなければ None。

    netkeiba例: '10-10-8-7'(1〜4角) / '12-11'(短距離の3角-4角) / '8-8-7'。
    末尾が4角、その手前が3角、という並びを使う。数字が1個だけならそれを返す。
    """
    nums = [_int(n) for n in re.findall(r'\d+', str(passing or ''))]
    nums = [n for n in nums if n]
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0]
    return nums[-2]


def reach(prev_distance, current_distance, prev_passing):
    """出走前リーチか。①前走3角>=5 かつ ②距離短縮。今回3角は見ない。

    戻り: None（データ不足で判定しない）/ dict（該当）/ False（条件外れ）。
    None と False を分けるのは『該当しない』と『分からない』を混ぜないため。
    """
    prev_d = _int(prev_distance)
    cur_d = _int(current_distance)
    c3 = corner3_from_passing(prev_passing)
    if prev_d is None or cur_d is None or c3 is None:
        return None
    if prev_d <= cur_d:
        return False
    if c3 < 5:
        return False
    return {
        'prev_corner3': c3,
        'prev_distance': prev_d,
        'current_distance': cur_d,
    }


def is_prev_close(rank, margin):
    """ページの⏱️と同じ。前走4着以下かつ勝ち馬まで0.3秒以内。欠損は False。"""
    try:
        r = int(float(rank))
        m = float(margin)
    except (TypeError, ValueError):
        return False
    if r < 4 or r >= 99:
        return False
    if m < 0 or m >= 9.9:
        return False
    return m <= 0.3


def with_pair(info, rank=None, margin=None):
    """候補dictに 🟣⏱️ を足す。reach の戻りが dict のときだけ。点数には使わない。"""
    if not isinstance(info, dict):
        return info
    out = dict(info)
    if is_prev_close(rank, margin):
        out['pair_mark'] = PAIR_MARK
    return out


def pair_prefix(info):
    """カード見出し用。重なりのときだけ『🟣⏱️ 』。"""
    if isinstance(info, dict) and info.get('pair_mark'):
        return str(info['pair_mark']) + ' '
    return ''


def label_html(info):
    """穴馬ハンター用の色文字。info が dict のときだけ返す。"""
    if not isinstance(info, dict):
        return ''
    c3 = info.get('prev_corner3')
    pd = info.get('prev_distance')
    cd = info.get('current_distance')
    detail = f'前走3角{c3}番手・{pd}→{cd}m'
    mark = pair_prefix(info)
    mark_html = (
        f'<span style="font-size:1.15em;margin-right:4px;">{_html.escape(mark.strip())}</span>'
        if mark else ''
    )
    return (
        f'{mark_html}'
        f'<span style="color:{LABEL_COLOR};font-weight:bold;">{LABEL}</span>'
        f'<span style="color:{LABEL_COLOR};">（{detail}）</span>'
    )


TABLE_HIT = '〇'
TABLE_MISS = '-'


def table_cell(info):
    """強適テーブル用。候補なら『〇』だけ（横幅を使わない）。スコアには使わない。"""
    return TABLE_HIT if isinstance(info, dict) else TABLE_MISS


def pred_c3_memo(pred_corner3):
    """穴馬ハンター／🎯妙味馬用。AI予測3角の1行。本番の今回3角ではない。"""
    p = _int(pred_corner3)
    if p is None:
        return ''
    return f'予測3角：{p}番手（netkeiba AI・本番の3角ではない）'


def table_cell_pred(info, pred_corner3=None):
    """詳細用。テーブルには使わない（〇だけ）。予測が無ければ TABLE_HIT。"""
    if not isinstance(info, dict):
        return TABLE_MISS
    line = pred_c3_memo(pred_corner3)
    if not line:
        return TABLE_HIT
    return line


def _parse_day(s):
    t = str(s or '').replace('.', '').replace('-', '').replace('/', '')[:8]
    if len(t) == 8 and t.isdigit():
        try:
            return _date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        except ValueError:
            return None
    return None


def interval_text(prev_date, race_date):
    """間隔の事実。加点はしない。中N週は N＝日数÷7（資料の中5週＝35日に合わせる）。"""
    a = _parse_day(prev_date)
    b = _parse_day(race_date)
    if not a or not b:
        return ''
    days = (b - a).days
    if days < 0:
        return ''
    if days < 7:
        return f'{days}日'
    return f'中{days // 7}週'


def _surf_tag(s):
    t = str(s or '')
    if 'ダ' in t:
        return 'ダ'
    if '芝' in t:
        return '芝'
    return ''


def _is_bound_shorten(d2, d1, d0):
    """1200→1400→1200 型。表示ラベル用で、スコアには使わない。"""
    return (d2 is not None and d1 is not None and d0 is not None
            and d2 <= d0 and d1 > d0 and d1 > d2)


def _is_track_bound(s2, s1, s0):
    """芝→ダ→芝 / ダ→芝→ダ。表示ラベル用で、スコアには使わない。"""
    return bool(s2 and s1 and s0 and s2 == s0 and s1 != s0)


def memo_lines(past_runs=None, current_distance=None, body_weight=None,
               race_date=None, prev_date=None, current_surface=None):
    """候補の下に置く事実メモ。○や点数は付けない。欠損・非該当は行ごと出さない。"""
    runs = list(past_runs or [])
    d0 = _int(current_distance)
    d1 = _int(runs[0].get('Distance')) if runs else None
    d2 = _int(runs[1].get('Distance')) if len(runs) >= 2 else None
    s0 = _surf_tag(current_surface)
    s1 = _surf_tag(runs[0].get('Surface')) if runs else ''
    s2 = _surf_tag(runs[1].get('Surface')) if len(runs) >= 2 else ''
    lines = []
    if _is_bound_shorten(d2, d1, d0):
        lines.append(f'↔ バウンド：{d2}→{d1}→{d0}')
    if _is_track_bound(s2, s1, s0):
        lines.append(f'↔ 芝⇔ダ：{s2}→{s1}→{s0}')
    wt = ''
    try:
        w = int(float(body_weight))
        if w > 0:
            wt = f'体重：{w}kg'
    except (TypeError, ValueError):
        wt = ''
    gap = interval_text(prev_date, race_date)
    iv = f'間隔：{gap}' if gap else ''
    if wt or iv:
        lines.append('　'.join(x for x in (wt, iv) if x))
    return lines


def with_memo(info, **kwargs):
    """reach() の dict にメモ行を足して返す。False/None はそのまま。"""
    if not isinstance(info, dict):
        return info
    out = dict(info)
    out['memo_lines'] = memo_lines(**kwargs)
    return out


def block_html(info):
    """紫の候補行＋灰色の事実メモ。候補でないときは空。"""
    head = label_html(info)
    if not head:
        return ''
    parts = [head]
    for ln in (info.get('memo_lines') or []):
        parts.append(
            f'<div style="color:{MEMO_COLOR};font-size:0.82em;line-height:1.45;margin-top:2px;">'
            f'{_html.escape(ln)}</div>'
        )
    return ''.join(parts)
