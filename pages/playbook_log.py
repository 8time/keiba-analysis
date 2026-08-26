# -*- coding: utf-8 -*-
"""📒 プレイブック成績 — 検証済み買い方の実券と、確定後の成績。

買い方は変えない。見るだけ。的中・払戻はレース確定後にだけ付ける。
"""
import streamlit as st
import pandas as pd

from core import playbook_ledger as pl


def _fmt_pct(v):
    return '—' if v is None else f'{v:.1f}%'


def _fmt_yen(v):
    if v is None:
        return '—'
    return f'{int(v):,}円'


def _ticket_preview(row, cap=4):
    tks = row.get('tickets') or []
    if row.get('skip') or not tks:
        return '見送り（0点）'
    kind = row.get('ticket_type') or ''
    sep = '→' if kind == '3連単' else '-'
    labels = [sep.join(str(x) for x in c) for c in tks[:cap]]
    more = len(tks) - cap
    s = ' / '.join(labels)
    if more > 0:
        s += f' …他{more}点'
    return s


def _metric_box(title, races, hit_rate, roi, note):
    st.markdown(
        f"<div style='border:1px solid #ddd;border-radius:8px;padding:10px 12px;'>"
        f"<div style='font-size:12px;color:#666;'>{title}</div>"
        f"<div style='font-size:15px;margin-top:4px;'>レース数 <b>{races}</b></div>"
        f"<div>的中率 <b>{_fmt_pct(hit_rate)}</b>"
        f"<span style='color:#888;font-size:12px;'>（当たったレースの割合）</span></div>"
        f"<div>回収率 <b>{_fmt_pct(roi)}</b>"
        f"<span style='color:#888;font-size:12px;'>（払戻÷投資。100%で元が取れる）</span></div>"
        f"<div style='font-size:12px;color:#888;margin-top:4px;'>{note}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render():
    st.title('📒 プレイブック成績')
    st.caption(
        '検証済みのデフォルト買い方だけを記録します。'
        '手動の3連複・3連単エンジンは含みません。'
        '的中と払戻は、レースが確定してから付けます。'
    )

    entries = pl.list_entries()
    summ = pl.summarize(entries)
    d, c, ba, all_ = summ['D'], summ['C'], summ['BA'], summ['ALL']

    col1, col2, col3 = st.columns(3)
    with col1:
        _metric_box(
            'D 鉄板（人気1〜4の3連複2点）',
            d['n_races'], d['hit_rate'], d['roi'],
            f"確定{d['n_settled']}R / 投資{_fmt_yen(d['investment'])} / 払戻{_fmt_yen(d['payout'])}",
        )
    with col2:
        _metric_box(
            'C 中庸（能力順2-4-7の3連単30点）',
            c['n_races'], c['hit_rate'], c['roi'],
            f"確定{c['n_settled']}R / 投資{_fmt_yen(c['investment'])} / 払戻{_fmt_yen(c['payout'])}",
        )
    with col3:
        _metric_box(
            '全体（DとCを合わせたもの）',
            all_['n_races'], all_['hit_rate'], all_['roi'],
            f"確定{all_['n_settled']}R / 投資{_fmt_yen(all_['investment'])} / 払戻{_fmt_yen(all_['payout'])}",
        )
    st.caption(
        f"B/A 荒れはデフォルト見送りです。"
        f"記録 {ba['n_races']} レース・券数 0。"
        f"回収率の集計には入れません。"
    )

    unsettled = [r for r in entries if not r.get('settled') and not r.get('skip')]
    if unsettled:
        if st.button(f'確定結果を取り込む（未確定 {len(unsettled)} レース）',
                     help='ローカル成績DBにあればそれを使い、無ければ結果ページから当選組だけ取ります。買い目は作り直しません。'):
            n_ok = 0
            for r in unsettled:
                out = pl.settle(r['race_id'], fetch_remote=True)
                if out:
                    n_ok += 1
            st.success(f'{n_ok} レースに払戻を付けました。ページを再読み込みしてください。')
            st.rerun()

    if not entries:
        st.info('まだプレイブックの記録がありません。Single Race Analysis でレースを表示すると保存されます。')
        return

    zone_filter = st.selectbox(
        '表示するゾーン',
        ['全部', 'D', 'C', 'B/A'],
        index=0,
    )
    rows = entries
    if zone_filter == 'D':
        rows = [r for r in entries if r.get('zone') == 'D']
    elif zone_filter == 'C':
        rows = [r for r in entries if r.get('zone') == 'C']
    elif zone_filter == 'B/A':
        rows = [r for r in entries if r.get('zone') == 'BA' or r.get('skip')]

    table = []
    for r in rows:
        hit_txt = '—'
        if r.get('skip'):
            hit_txt = '見送り'
        elif r.get('settled'):
            hit_txt = '的中' if r.get('hit') else '外れ'
        table.append({
            '日付': r.get('race_date') or '',
            'レースID': r.get('race_id'),
            'ゾーン': r.get('ui_line') or r.get('zone') or '',
            '券種': r.get('ticket_type') or '見送り',
            '点数': r.get('ticket_count'),
            '実券': _ticket_preview(r),
            '結果': hit_txt,
            '投資': r.get('investment'),
            '払戻': r.get('payout') if r.get('settled') else None,
            '回収率(%)': r.get('roi') if r.get('settled') else None,
        })
    st.subheader('レース一覧')
    st.caption('実券は保存されたプレイブックそのものです。下の行をクリックせず、表で確認できます。')
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)

    with st.expander('1レースの全買い目を見る', expanded=False):
        ids = [r.get('race_id') for r in rows]
        if ids:
            pick = st.selectbox('レースID', ids)
            chosen = next((r for r in rows if r.get('race_id') == pick), None)
            if chosen:
                st.write({
                    '日付': chosen.get('race_date'),
                    'ゾーン': chosen.get('zone'),
                    '買い方': chosen.get('strategy'),
                    '券種': chosen.get('ticket_type'),
                    '点数': chosen.get('ticket_count'),
                    '投資': chosen.get('investment'),
                    '的中': chosen.get('hit'),
                    '払戻': chosen.get('payout'),
                    '回収率': chosen.get('roi'),
                    '確定の組': chosen.get('actual_result'),
                })
                tks = chosen.get('tickets') or []
                kind = chosen.get('ticket_type') or ''
                sep = '→' if kind == '3連単' else '-'
                if tks:
                    st.dataframe(
                        pd.DataFrame({'買い目': [sep.join(map(str, c)) for c in tks]}),
                        hide_index=True, use_container_width=True)
                else:
                    st.caption('このレースのデフォルト券はありません（見送り）。')
