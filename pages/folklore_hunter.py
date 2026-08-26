# -*- coding: utf-8 -*-
"""🧪 競馬俗説ハンター — pages/folklore_hunter.py

世間で語られる俗説を、買い材料と消し材料に分けて馬ごとに集める実験ページ。
予想エンジン（能力Rank / 穴馬ハンター / 展開 / 血統SP）とは切り離す。
数が多いから買う、とは言わない。
見た目だけカードに分けて読みやすくする。点数・メーターは増やさない。
"""
import html as _html
import re
import streamlit as st
import pandas as pd

from core import folklore_lib as fl

_CSS = """
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stMainBlockContainer"] {
    background-color: #eef3f8 !important;
}
[data-testid="stHeader"] { background: transparent !important; }
div[data-testid="stExpander"] {
    background: #e7f0fa !important;
    border: 1px solid #d3e3f4 !important;
    border-radius: 12px !important;
}
div[data-testid="stExpander"] details { border: none !important; }
div[data-testid="stExpander"] summary { font-weight: 600; }
</style>
"""


def _extract_race_id(raw):
    s = str(raw or '').strip()
    if not s:
        return ''
    m = re.search(r'race_id=(\d{12,16})', s, re.I)
    if m:
        return m.group(1)[:12] if len(m.group(1)) >= 12 else m.group(1)
    m = re.search(r'(\d{12})', s)
    return m.group(1) if m else ''


def _inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def _verdict_chip(verdict):
    if verdict == fl.VERDICT_EFFECTIVE:
        return ("<span style='background:#e6f4ea;color:#1b5e20;padding:3px 10px;"
                "border-radius:999px;font-size:0.78em;font-weight:600;"
                "white-space:nowrap;'>実戦で使う</span>")
    if verdict == fl.VERDICT_REJECTED:
        return ("<span style='background:#fdecea;color:#b71c1c;padding:3px 10px;"
                "border-radius:999px;font-size:0.78em;font-weight:600;"
                "white-space:nowrap;'>否決済み</span>")
    return ("<span style='background:#fff3e0;color:#e65100;padding:3px 10px;"
            "border-radius:999px;font-size:0.78em;font-weight:600;"
            "white-space:nowrap;'>未検証</span>")


def _score_pill(text, kind):
    pal = {
        'pos': ('#e6f4ea', '#1b5e20'),
        'neg': ('#fdecea', '#b71c1c'),
        'master': ('#fff6e0', '#8a6d12'),
        'blue': ('#e8f1fb', '#1565c0'),
        'gray': ('#eceff1', '#546e7a'),
    }
    bg, fg = pal.get(kind, pal['gray'])
    return (
        f"<span style='background:{bg};color:{fg};border-radius:999px;"
        f"padding:3px 10px;font-weight:700;font-size:0.88em;white-space:nowrap;'>"
        f"{text}</span>"
    )


def _count_box(title, n, kind, sub):
    pal = {
        'pos': ('#e6f4ea', '#1b5e20', '#c8e6c9'),
        'neg': ('#fdecea', '#b71c1c', '#ffcdd2'),
        'master': ('#fff6e0', '#8a6d12', '#ffe082'),
        'blue': ('#e8f1fb', '#1565c0', '#bbdefb'),
        'gray': ('#f7f9fc', '#455a64', '#cfd8dc'),
    }
    bg, fg, bar = pal.get(kind, pal['gray'])
    return (
        f"<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        f"padding:14px 16px;box-shadow:0 1px 3px rgba(15,40,80,0.06);"
        f"border-top:4px solid {bar};'>"
        f"<div style='font-size:12px;color:#607d8b;'>{title}</div>"
        f"<div style='font-size:26px;font-weight:700;color:{fg};margin:4px 0 2px;'>{n}</div>"
        f"<div style='font-size:12px;color:#90a4ae;'>{sub}</div>"
        f"</div>"
    )


def _legend_cards():
    items = [
        ('pos', '🟢 買い材料', '「この条件なら買い」と語られる俗説に、何個当たるか'),
        ('neg', '🔴 消し・危険', '「この条件は危ない／嫌う」と語られる俗説に、何個当たるか'),
        ('master', '⭐ 総合', '買いの個数から消しの個数を引いた数。同じ総合でも中身は違います'),
    ]
    cols = st.columns(3)
    for col, (kind, title, sub) in zip(cols, items):
        pal = {
            'pos': '#e6f4ea',
            'neg': '#fdecea',
            'master': '#fff6e0',
        }
        with col:
            st.markdown(
                f"<div style='background:{pal[kind]};border-radius:12px;padding:12px 14px;"
                f"min-height:108px;border:1px solid rgba(0,0,0,0.04);'>"
                f"<div style='font-weight:700;margin-bottom:6px;'>{title}</div>"
                f"<div style='font-size:13px;color:#546e7a;line-height:1.5;'>{sub}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_market_lens(show_title=True):
    """俗説を見るときの主指標。得点ではない。メーターにもしない。"""
    if show_title:
        st.markdown("### 俗説の読み方（市場を超えたか）")
    st.caption(
        f"{fl.LENS_WINDOW}の実測です。**買う点数ではありません。** "
        "「3着以内が多い」と「人気以上に来ている」は別です。"
        " 0〜100の有効度は作りません。"
    )
    rows = [
        "<table style='width:100%;border-collapse:collapse;font-size:0.92em;'>",
        "<tr style='background:#f4f7fb;'>"
        "<th style='text-align:left;padding:8px 10px;'>俗説</th>"
        "<th style='text-align:right;padding:8px 10px;'>生の3着以内の差</th>"
        "<th style='text-align:right;padding:8px 10px;'>人気をならしたあと</th>"
        "<th style='text-align:left;padding:8px 10px;'>読み</th>"
        "</tr>",
    ]
    for i, item in enumerate(fl.MARKET_LENS):
        raw = _html.escape(fl.fmt_signed_pt(item['raw_pt'], 1))
        resid = _html.escape(fl.fmt_signed_pt(item['resid_pt'], 2))
        verd = fl.market_lens_verdict(item['resid_pt'])
        if '優位性なし' in verd:
            vcol = '#607d8b'
        elif '来ていない' in verd:
            vcol = '#b71c1c'
        else:
            vcol = '#1b5e20'
        title = _html.escape(item['title'])
        bg = '#ffffff' if i % 2 == 0 else '#f7fafc'
        rows.append(
            f"<tr style='background:{bg};border-top:1px solid #eef2f6;'>"
            f"<td style='padding:8px 10px;'>{title}</td>"
            f"<td style='text-align:right;padding:8px 10px;'>{raw}</td>"
            f"<td style='text-align:right;padding:8px 10px;font-weight:600;'>{resid}</td>"
            f"<td style='padding:8px 10px;color:{vcol};'>{_html.escape(verd)}</td>"
            "</tr>"
        )
    rows.append("</table>")
    st.markdown(
        "<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        "padding:4px 6px;box-shadow:0 1px 3px rgba(15,40,80,0.06);'>"
        + "".join(rows) +
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "生の3着以内の差＝その俗説の馬の3着以内率 − その年の全馬平均。"
        " 人気をならしたあと＝同じ人気の平均と比べて、実際に3着以内が多かったか。"
        " 少頭数の先行も、頭数の底上げを除くと市場を超えなかったので、条件探しは一旦止めています。"
    )


def _render_full_catalog():
    grouped = fl.catalog_grouped()
    n = len(fl.CATALOG)
    n_pos = sum(1 for r in fl.CATALOG if r.get('sign', 1) > 0)
    n_neg = sum(1 for r in fl.CATALOG if r.get('sign', 1) < 0)
    st.markdown(
        f"**収録 {n} 件**（買い材料 {n_pos} ／ 消し・危険 {n_neg}）。"
        "数が多いから買う、ではありません。予想スコアには入れていません。"
    )
    vmark = {
        fl.VERDICT_EFFECTIVE: ('実戦', 'pos'),
        fl.VERDICT_REJECTED: ('否決', 'neg'),
        fl.VERDICT_UNVERIFIED: ('未検証', 'gray'),
    }
    cards = []
    for cat, rs in grouped.items():
        lines = [
            f"<div style='font-weight:700;margin-bottom:8px;'>{_html.escape(cat)}"
            f"<span style='color:#90a4ae;font-weight:500;font-size:12px;'>　{len(rs)}</span></div>"
        ]
        for r in rs:
            sm = '＋' if r.get('sign', 1) > 0 else '−'
            lab, kind = vmark.get(r['verdict'], ('未検証', 'gray'))
            lines.append(
                "<div style='display:flex;gap:6px;align-items:baseline;"
                "padding:3px 0;font-size:13px;'>"
                f"<span style='color:#90a4ae;width:1em;'>{sm}</span>"
                f"{_score_pill(lab, kind)}"
                f"<span>{_html.escape(r['title'])}</span>"
                "</div>"
            )
        cards.append(
            "<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
            "padding:12px 14px;box-shadow:0 1px 3px rgba(15,40,80,0.05);'>"
            + "".join(lines) +
            "</div>"
        )
    st.markdown(
        "<div style='display:grid;grid-template-columns:"
        "repeat(auto-fill,minmax(280px,1fr));gap:10px;'>"
        + "".join(cards) +
        "</div>",
        unsafe_allow_html=True,
    )


def _ninki_label(ninki):
    if ninki is None:
        return '人気—'
    try:
        return f"{int(ninki)}番人気"
    except (TypeError, ValueError):
        return '人気—'


def _rank_card(title, caption, rows, empty_msg, kind):
    """rows: (place, umaban, name, ninki, badge_text, extra_html). 人気は表示のみ。"""
    pal = {
        'pos': ('#e6f4ea', '#1b5e20', '#c8e6c9'),
        'neg': ('#fdecea', '#b71c1c', '#ffcdd2'),
        'master': ('#fff6e0', '#8a6d12', '#ffe082'),
    }
    head_bg, head_fg, circle = pal.get(kind, pal['master'])
    body = [
        "<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        "overflow:hidden;box-shadow:0 1px 3px rgba(15,40,80,0.06);min-height:248px;'>",
        f"<div style='background:{head_bg};color:{head_fg};padding:12px 14px;'>",
        f"<div style='font-weight:700;'>{title}</div>",
        f"<div style='font-size:12px;opacity:0.85;margin-top:2px;'>{caption}</div>",
        "</div>",
        "<div style='padding:6px 12px 10px;'>",
    ]
    if not rows:
        body.append(
            f"<div style='color:#90a4ae;font-size:13px;padding:12px 2px;'>{empty_msg}</div>"
        )
    else:
        for place, umaban, name, ninki, badge, extra in rows:
            mark = _html.escape(fl.umaban_mark(umaban))
            nm = _html.escape(name or '')
            nk = _html.escape(_ninki_label(ninki))
            top = "border-top:1px solid #f0f4f8;" if place != 1 else ""
            body.append(
                f"<div style='display:flex;align-items:center;gap:8px;"
                f"padding:8px 2px;{top}'>"
                f"<span style='display:inline-flex;align-items:center;justify-content:center;"
                f"width:22px;height:22px;border-radius:50%;background:{circle};color:{head_fg};"
                f"font-size:12px;font-weight:700;flex-shrink:0;'>{place}</span>"
                "<div style='flex:1;min-width:0;'>"
                f"<div style='font-weight:700;overflow:hidden;text-overflow:ellipsis;"
                f"white-space:nowrap;'>{mark} {nm}</div>"
                f"<div style='font-size:12px;color:#90a4ae;'>{nk}"
                f"{extra}</div>"
                "</div>"
                f"{_score_pill(_html.escape(badge), kind)}"
                "</div>"
            )
    body.append("</div></div>")
    return "".join(body)


def _hits_table(hits):
    order = {
        fl.VERDICT_EFFECTIVE: 0,
        fl.VERDICT_UNVERIFIED: 1,
        fl.VERDICT_REJECTED: 2,
    }
    hits = sorted(hits, key=lambda x: (order.get(x['verdict'], 9), x['category'], x['title']))
    lines = [
        "<table style='width:100%;border-collapse:collapse;font-size:0.95em;'>",
        "<tr style='background:#f4f7fb;'>"
        "<th style='text-align:left;padding:8px 10px;'>俗説</th>"
        "<th style='text-align:left;padding:8px 10px;'>この馬</th>"
        "<th style='text-align:left;padding:8px 10px;'>判定</th></tr>",
    ]
    for i, h in enumerate(hits):
        mark = '✅' if h['verdict'] != fl.VERDICT_REJECTED else '❌'
        note = _html.escape(h.get('note') or '')
        lens = fl.market_lens_for_catalog(h.get('id'))
        lens_html = ''
        if lens:
            lens_html = (
                "<div style='font-size:0.8em;color:#607d8b;margin-top:3px;'>"
                f"{_html.escape(fl.market_lens_short(lens))}</div>"
            )
        bg = '#ffffff' if i % 2 == 0 else '#f7fafc'
        lines.append(
            f"<tr style='background:{bg};border-top:1px solid #eef2f6;'>"
            f"<td style='padding:9px 10px;vertical-align:top;'>"
            f"{mark} {_html.escape(h['title'])}"
            f"<div style='font-size:0.8em;color:#90a4ae;margin-top:2px;'>"
            f"{_html.escape(h['category'])} ／ {note}</div>"
            f"{lens_html}</td>"
            f"<td style='padding:9px 10px;vertical-align:top;'>{_html.escape(h['detail'])}</td>"
            f"<td style='padding:9px 10px;vertical-align:top;'>{_verdict_chip(h['verdict'])}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _hit_section(title, kind, hits):
    pal = {
        'pos': ('#e6f4ea', '#1b5e20'),
        'neg': ('#fdecea', '#b71c1c'),
    }
    bg, fg = pal[kind]
    if not hits:
        empty = "この馬に当たった買い材料はありません。" if kind == 'pos' else "この馬に当たった消し材料はありません。"
        inner = f"<div style='padding:14px 16px;color:#90a4ae;font-size:13px;'>{empty}</div>"
    else:
        inner = _hits_table(hits)
    st.markdown(
        f"<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        f"overflow:hidden;box-shadow:0 1px 3px rgba(15,40,80,0.06);margin:8px 0 14px;'>"
        f"<div style='background:{bg};color:{fg};padding:10px 16px;font-weight:700;"
        f"display:flex;justify-content:space-between;align-items:center;'>"
        f"<span>{title}</span>"
        f"<span style='background:#fff;color:{fg};border-radius:999px;padding:2px 10px;"
        f"font-size:12px;'>{len(hits)}</span>"
        f"</div>{inner}</div>",
        unsafe_allow_html=True,
    )


def _hunter_captured(df, meta, race_id):
    """穴馬ハンターと同じ精鋭・広域網の馬番。失敗したら (set, False)。"""
    try:
        from core import consensus_view as cv
        aim = cv.build_edge_sets(df, meta, race_id)
        return fl.captured_umabans(aim.get('vh_tier')), True
    except Exception:
        return set(), False


def _render_signals(sigs, hunter_ok):
    """買う指示ではない。該当が無い日は目立たせない。"""
    if not hunter_ok:
        st.caption("🧪 俗説シグナル：穴馬ハンターの判定が取れなかったので、今回は出していません。")
        return
    if not sigs:
        st.caption("🧪 俗説シグナル：該当なし")
        return
    st.markdown("### 🧪 俗説シグナル")
    st.caption(
        "穴馬ハンターの精鋭・広域網には出ていない、6番人気以下の馬です。"
        "俗説の買い材料が集まっている、という知らせだけです。"
        " **買う指示ではありません。買い馬を足す材料にもしません。** "
        "下の一覧から馬を選ぶと、当たった俗説を全部見られます。"
    )
    rows = []
    for i, r in enumerate(sigs):
        mark = _html.escape(fl.umaban_mark(r.get('umaban')))
        nm = _html.escape(r.get('name') or '')
        nk = _html.escape(_ninki_label(r.get('ninki')))
        bd = "border-top:1px solid #e8eef4;" if i else ""
        rows.append(
            f"<div style='padding:10px 0;{bd}'>"
            f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>"
            f"<span style='font-weight:700;'>{mark} {nm}</span>"
            f"<span style='color:#90a4ae;font-size:12px;'>{nk}</span>"
            f"{_score_pill('俗説反応：強', 'blue')}"
            f"{_score_pill('穴馬ハンター：未捕捉', 'gray')}"
            "</div>"
            "<div style='font-size:13px;color:#607d8b;margin-top:4px;'>"
            f"買い材料 {int(r.get('n_pos') or 0)}　消し材料 {int(r.get('n_neg') or 0)}"
            "</div></div>"
        )
    st.markdown(
        "<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        "padding:10px 16px;box-shadow:0 1px 3px rgba(15,40,80,0.06);'>"
        + "".join(rows) +
        "</div>",
        unsafe_allow_html=True,
    )


def _filter_hits(hits, cat):
    if not cat or cat == 'すべて':
        return list(hits)
    return [h for h in hits if h.get('category') == cat]


def _cat_chips(horse):
    items = sorted(horse['by_category'].items(), key=lambda x: -x[1])
    if not items:
        return
    chips = []
    for k, v in items:
        chips.append(
            f"<span style='display:inline-block;margin:0 8px 8px 0;padding:5px 12px;"
            f"border-radius:999px;background:#e8f1fb;color:#1565c0;font-size:0.88em;'>"
            f"{_html.escape(k)}　<b>{v}</b></span>"
        )
    st.markdown(
        "<div style='margin:4px 0 10px;'>"
        "<div style='font-size:12px;color:#90a4ae;margin-bottom:6px;'>当たった俗説の種類（数は多いが同じ系統ばかり、も分かります）</div>"
        + "".join(chips) +
        "</div>",
        unsafe_allow_html=True,
    )


def render():
    _inject_css()
    st.header("🧪 競馬俗説ランキング")
    st.caption(
        "世間や動画で語られる俗説を、**買い材料（＋1）** と **消し・危険（−1）** に分けて数えます。"
        " 総合は「買いの個数 − 消しの個数」です。"
        " **数が多いから買う、ではありません。** "
        "今の予想（能力Rank・穴馬ハンター・3連単など）とは別の実験場です。"
    )
    _legend_cards()
    st.caption(
        "今は全部 ±1 で、強い俗説も弱い俗説も同じ1個です（重みはまだ付けません）。"
        " 読むときは **人気をならしたあと** を先に見る。"
        "3着以内が多いだけでは、すでに人気に織り込まれていることが多いです。"
        " 🧪 俗説シグナルは、穴馬ハンターに出ていない人気薄で俗説だけ反応が強いとき最大3頭。"
        "買う指示ではありません。"
    )

    _qp = st.query_params.get('race_id')
    if _qp and st.session_state.get('folk_url_from_qp') != _qp:
        st.session_state['folk_url'] = _qp
        st.session_state['folk_url_from_qp'] = _qp
    elif 'folk_url' not in st.session_state:
        _persist = st.session_state.get('persisted_main_race_id') or ''
        if _persist:
            st.session_state['folk_url'] = str(_persist)

    race_url = st.text_input(
        "レースURL または 12桁のID",
        placeholder="https://race.netkeiba.com/race/shutuba.html?race_id=202505030211",
        key="folk_url",
    )
    if not race_url:
        st.info("レースを入れると、買い材料・消し材料・総合の3つのランキングが出ます。")
        _render_market_lens()
        with st.expander("このページで何が分かるか"):
            st.markdown(
                "- 買い材料ばかりの馬と、消し材料も多い馬を分けて見られます\n"
                "- 総合が同じでも、横の「＋個数 / −個数」で中身の差が分かります\n"
                "- 馬を選ぶと、当たった俗説を全部展開します\n"
                "- 穴馬ハンターに出ていない人気薄で、俗説だけ反応が強い馬は"
                "「俗説シグナル」として最大3頭だけ出ます（買う指示ではありません）\n"
                "- 俗説の数字は「市場が織り込んだ期待を超えたか」で読みます。"
                "3着以内が多いだけでは買いではありません\n"
                "- 0〜100の有効度は作りません。予想スコアにも混ぜません"
            )
        with st.expander(f"収録している俗説を全部見る（{len(fl.CATALOG)}件）", expanded=True):
            _render_full_catalog()
        return

    race_id = _extract_race_id(race_url)
    if not race_id:
        st.error("12桁のレースIDを含むURLを入力してください。")
        return

    with st.spinner("出馬表を取得して、俗説に当てはまるかを見ています..."):
        try:
            from core.scraper import get_race_data
            df = get_race_data(race_id, use_storage=False)
        except Exception as e:
            st.error(f"データ取得に失敗しました: {e}")
            return

    if df is None or getattr(df, 'empty', True):
        st.warning("出馬表が取れませんでした。")
        return

    meta = df.attrs.get('metadata', {}) or {}
    race_name = meta.get('RaceName', '')
    surface = ''
    dist = ''
    try:
        surface = str(df.iloc[0].get('CurrentSurface', '') or '')
        dist = df.iloc[0].get('CurrentDistance', '')
    except Exception:
        pass
    n_horses = len(df)
    st.markdown(
        f"<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        f"padding:14px 16px;margin:4px 0 12px;box-shadow:0 1px 3px rgba(15,40,80,0.06);'>"
        f"<div style='font-size:20px;font-weight:700;'>{_html.escape(str(race_name))}</div>"
        f"<div style='color:#607d8b;margin-top:4px;'>{_html.escape(surface)}"
        f"{_html.escape(str(dist))}m　{n_horses}頭</div></div>",
        unsafe_allow_html=True,
    )

    tags = fl.race_tags(meta, n_horses, surface)
    if tags:
        pills = "".join(
            f"<span style='display:inline-block;margin:0 8px 6px 0;padding:4px 10px;"
            f"border-radius:999px;background:#e8f1fb;color:#1565c0;font-size:12px;'>"
            f"{_html.escape(t)}</span>"
            for t in tags
        )
        st.markdown(
            "<div style='font-size:12px;color:#90a4ae;margin-bottom:4px;'>レース全体"
            "（全馬に同じことが当てはまる話は、頭数の順位には入れていません）</div>"
            + pills,
            unsafe_allow_html=True,
        )

    with st.spinner("各馬の俗説を集計しています..."):
        results = fl.evaluate_race(df, race_id=race_id, meta=meta, enrich=True)

    if not results:
        st.warning("判定できる馬がいませんでした。")
        return

    pos5 = fl.top_pos(results, 5)
    neg5 = fl.top_neg(results, 5)
    sc5 = fl.top_score(results, 5)

    pos_rows = [
        (i, r['umaban'], r['name'], r.get('ninki'), f"＋{r['n_pos']}", '')
        for i, r in enumerate(pos5, 1)
    ]
    neg_rows = [
        (i, r['umaban'], r['name'], r.get('ninki'), f"−{r['n_neg']}", '')
        for i, r in enumerate(neg5, 1)
    ]
    sc_rows = [
        (i, r['umaban'], r['name'], r.get('ninki'),
         fl.fmt_signed(r['score']),
         f"　＋{r['n_pos']} / −{r['n_neg']}")
        for i, r in enumerate(sc5, 1)
    ]

    st.markdown("### 俗説ランキング（各 TOP5）")
    st.caption(
        "今は1件＝±1です。人気は見比べ用で、点数には入れていません。"
        "弱い俗説がたくさん集まっても、強い俗説1件と同じ扱いです。"
        " 当たった俗説の読み方は、下の表と馬の明細にあります。"
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            _rank_card(
                "🟢 ポジティブ材料 TOP5",
                "「買い」と語られる俗説の該当数",
                pos_rows,
                "買い材料に当たった馬はいません。",
                'pos',
            ),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _rank_card(
                "🔴 マイナス材料 TOP5",
                "「消し・危険」と語られる俗説が多い順",
                neg_rows,
                "消し材料に当たった馬はいません。",
                'neg',
            ),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            _rank_card(
                "⭐ 総合 TOP5",
                "買いの個数 − 消しの個数",
                sc_rows,
                "判定できる馬がいません。",
                'master',
            ),
            unsafe_allow_html=True,
        )

    with st.spinner("穴馬ハンターの拾い漏れを見ています..."):
        captured, hunter_ok = _hunter_captured(df, meta, race_id)
    sigs = fl.folklore_signals(results, captured) if hunter_ok else []
    _render_signals(sigs, hunter_ok)
    with st.expander("俗説の読み方（市場を超えたか）", expanded=False):
        _render_market_lens(show_title=False)

    rank_rows = []
    for r in results:
        cats = "、".join(f"{k}{v}" for k, v in sorted(r['by_category'].items(), key=lambda x: -x[1]))
        rank_rows.append({
            '順': r['rank'],
            '馬番': r['umaban'],
            '馬名': r['name'],
            '人気': r['ninki'] if r['ninki'] is not None else '—',
            '買い材料': r['n_pos'],
            '消し・危険': r['n_neg'],
            '総合': fl.fmt_signed(r['score']),
            '俗説バランス': r['balance'],
            '実戦で使う': r['n_effective'],
            '未検証': r['n_unverified'],
            '否決済み': r['n_rejected'],
            '内訳': cats or '—',
        })
    with st.expander("全頭の表（総合順）", expanded=False):
        st.dataframe(pd.DataFrame(rank_rows), hide_index=True, use_container_width=True)

    labels = [
        f"{r['umaban']}番 {r['name']}　{_ninki_label(r.get('ninki'))}　{r['balance']}"
        for r in results
    ]
    pick = st.selectbox(
        "馬を選ぶと、当たった俗説を全部見られます",
        options=list(range(len(results))),
        format_func=lambda i: labels[i],
        key="folk_pick",
    )
    horse = results[pick]

    st.markdown(
        f"<div style='background:#fff;border:1px solid #e8eef4;border-radius:12px;"
        f"padding:16px 18px;margin:8px 0 12px;box-shadow:0 1px 3px rgba(15,40,80,0.06);'>"
        f"<div style='font-size:22px;font-weight:700;'>"
        f"{horse['umaban']}番　{_html.escape(horse['name'] or '')}</div>"
        f"<div style='color:#607d8b;margin-top:4px;'>"
        f"{_html.escape(_ninki_label(horse.get('ninki')))}"
        f"　／　俗説バランス　{_html.escape(horse['balance'])}"
        f"<span style='color:#90a4ae;'>　（多い＝買い、ではありません）</span></div></div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(_count_box("買い材料", f"＋{horse['n_pos']}", 'pos',
                               "「買い」と語られる俗説"), unsafe_allow_html=True)
    with c2:
        st.markdown(_count_box("消し・危険", f"−{horse['n_neg']}", 'neg',
                               "「危ない」と語られる俗説"), unsafe_allow_html=True)
    with c3:
        st.markdown(_count_box("実戦で使う材料", horse['n_effective'], 'blue',
                               "今の予想でも見るもの"), unsafe_allow_html=True)
    with c4:
        st.markdown(_count_box("総合", fl.fmt_signed(horse['score']), 'master',
                               "買いの個数 − 消しの個数"), unsafe_allow_html=True)

    c5, c6 = st.columns(2)
    with c5:
        st.markdown(_count_box("未検証", horse['n_unverified'], 'gray',
                               "まだ測っていない俗説"), unsafe_allow_html=True)
    with c6:
        st.markdown(_count_box("否決済みの俗説", horse['n_rejected'], 'neg',
                               "単独では効かないと出たもの"), unsafe_allow_html=True)

    _cat_chips(horse)

    cat_opts = ['すべて'] + sorted(horse['by_category'].keys())
    if st.session_state.get('folk_cat_filter') not in cat_opts:
        st.session_state['folk_cat_filter'] = 'すべて'
    cat_filter = st.radio(
        "表示する俗説の種類",
        cat_opts,
        horizontal=True,
        key="folk_cat_filter",
        help="この馬に当たった俗説だけを、種類で絞って見ます。点数は変わりません。",
    )

    pos_hits = _filter_hits(horse.get('hits_pos') or [], cat_filter)
    neg_hits = _filter_hits(horse.get('hits_neg') or [], cat_filter)
    _hit_section("🟢 買い材料として当たった俗説", 'pos', pos_hits)
    _hit_section("🔴 消し・危険として当たった俗説", 'neg', neg_hits)

    with st.expander(f"当てはまらなかった俗説も見る（{len(horse['misses'])}件）"):
        for m in horse['misses']:
            sm = '＋' if m.get('sign', 1) > 0 else '−'
            st.markdown(
                f"❌ {sm} {_html.escape(m['title'])}  "
                f"<span style='color:#888;font-size:0.85em;'>{_html.escape(m['category'])} ／ "
                f"{_html.escape(m['note'])}</span>",
                unsafe_allow_html=True,
            )

    skips = horse.get('skips') or []
    if skips:
        with st.expander(f"このレースでは判定できない俗説（{len(skips)}件）"):
            st.caption("パドックや調教の観察、毛色、外厩、直前のオッズ記録など、出馬表に無いものはここに入ります。該当しない、ではありません。")
            for m in skips:
                sm = '＋' if m.get('sign', 1) > 0 else '−'
                st.markdown(
                    f"□ {sm} {_html.escape(m['title'])}  "
                    f"<span style='color:#888;font-size:0.85em;'>{_html.escape(m['note'])}</span>",
                    unsafe_allow_html=True,
                )

    with st.expander(f"収録している俗説を全部見る（{len(fl.CATALOG)}件）"):
        _render_full_catalog()

    with st.expander("なぜ予想と分けるのか"):
        st.markdown(
            "俗説をたくさん入れるほど、どれか1個が偶然よく見えてしまいます。"
            "だからこのページの数字は **予想スコアに足しません。**\n\n"
            "俗説シグナルも同じです。穴馬ハンターが見逃した馬の記録用で、"
            "出てきたから買い馬を足す、ではありません。\n\n"
            "今は全部 ±1 です。将来、検証済みだけ重くする、といった重み付けを"
            "別の実験として測れます。\n\n"
            "読むときは、生の3着以内の多さより **人気をならしたあと** を先に見ます。"
            "0〜100の有効度は作りません。"
        )
