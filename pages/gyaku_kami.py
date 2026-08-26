# -*- coding: utf-8 -*-
"""🚨 逆神ウォッチ — リンク集のみ。予想の取得・評価はしない。"""
import html as _html
import streamlit as st

from core import gyaku_kami as gk


def _card_html(acc, button_label):
    name = _html.escape(acc.get('name') or '')
    note = _html.escape(acc.get('note') or '')
    handle = acc.get('handle')
    handle_html = ''
    if handle:
        shown = str(handle)
        if acc.get('platform') == gk.PLAT_X and not shown.startswith('@'):
            shown = '@' + shown
        handle_html = (
            f"<div style='font-size:12px;color:#888;margin-top:2px;'>"
            f"{_html.escape(shown)}</div>"
        )
    url = acc.get('url')
    if url:
        href = _html.escape(url, quote=True)
        action = (
            f"<a href='{href}' target='_blank' rel='noopener noreferrer' "
            f"style='text-decoration:none;color:#ffffff;background:#1f6feb;"
            f"border:1px solid #1f6feb;padding:6px 11px;border-radius:7px;"
            f"font-weight:600;font-size:0.88em;display:inline-block;'>"
            f"{_html.escape(button_label)}</a>"
        )
    else:
        action = (
            "<span style='color:#888;font-size:0.88em;'>URL未登録</span>"
        )
    return (
        "<div style='border:1px solid #ddd;border-radius:8px;padding:10px 12px;"
        "min-height:118px;display:flex;flex-direction:column;"
        "justify-content:space-between;'>"
        f"<div><div style='font-weight:700;'>{name}</div>"
        f"{handle_html}"
        f"<div style='font-size:12px;color:#666;margin-top:4px;'>{note}</div></div>"
        f"<div style='text-align:right;margin-top:10px;'>{action}</div>"
        "</div>"
    )


def _grid(accounts, button_label):
    if not accounts:
        st.caption('登録がありません。')
        return
    cards = ''.join(_card_html(a, button_label) for a in accounts)
    st.markdown(
        "<div style='display:grid;grid-template-columns:"
        "repeat(auto-fill,minmax(240px,1fr));gap:10px;'>"
        f"{cards}</div>",
        unsafe_allow_html=True,
    )


def render():
    st.title('🚨 逆神ウォッチ')
    st.caption(
        '競馬予想で「逆神」として話題になるアカウント・チャンネルをまとめています。\n'
        '予想の自動取得・評価は行わず、各アカウントを直接確認できます。'
    )
    st.caption(
        '一覧に載っているだけで、当たる・外れるの判定はしていません。'
        ' URLが確認できていないものは「URL未登録」です。推測でアドレスは作っていません。'
    )

    x_rows = gk.accounts_for(gk.PLAT_X)
    yt_rows = gk.accounts_for(gk.PLAT_YOUTUBE)

    st.markdown('---')
    st.subheader('𝕏 X')
    st.caption('アカウント一覧')
    _grid(x_rows, '𝕏 開く')

    st.markdown('---')
    st.subheader('▶ YouTube')
    st.caption('チャンネル一覧')
    _grid(yt_rows, '▶ YouTubeを見る')
