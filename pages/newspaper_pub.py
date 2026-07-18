# -*- coding: utf-8 -*-
"""📰 新聞発行 — pages/newspaper_pub.py

SRAで解析したレースをA4のPDF競馬新聞として発行する発行メニュー。
- 収録レース選択(日付/開催場フィルタ)
- 紙面設定(題字/用紙向き/縮尺/フォント/列セット/並び順/セクションON-OFF)
- 発行後の成果物確認(サイズ/ページ数/収録内訳/プレビュー/ダウンロード)
- そのレースの全情報CSVをワンクリックでダウンロード
設定は user_prefs.json の 'newspaper' キーに保存され次回も復元される。
"""
import os
import json
import datetime

import streamlit as st

from core import newspaper as np_mod

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PREFS_PATH = os.path.join(_ROOT, 'user_prefs.json')


def _load_prefs():
    try:
        with open(_PREFS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('newspaper', {}) or {}
    except Exception:
        return {}


def _save_prefs(d):
    try:
        try:
            with open(_PREFS_PATH, 'r', encoding='utf-8') as f:
                p = json.load(f)
        except Exception:
            p = {}
        p['newspaper'] = d
        with open(_PREFS_PATH, 'w', encoding='utf-8') as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def _races_cached():
    return np_mod.list_available_races()


@st.cache_data(ttl=60, show_spinner=False)
def _columns_of(rid):
    v = np_mod.load_view(rid)
    if not v:
        return []
    labels = v.get('labels') or {}
    return [(c, labels.get(c, c)) for c in (v.get('columns') or [])]


def render_scan_digest_ui(rows, key_prefix='sd'):
    """🔍スキャン新聞(ダイジェストPDF)の発行UI。Scannerページと新聞発行ページで共用。

    rows: Scanner結果(gate付き)。フィルタ→A4縦2列カード組版→PDF/HTMLダウンロード。
    """
    if not rows:
        st.info("スキャン結果がありません。")
        return

    def _k(s):
        return f"{key_prefix}_{s}"

    _c1, _c2, _c3 = st.columns([1.5, 1.5, 1])
    _lean_lbl = _c1.radio("対象レース",
                          ['すべて', '②穴妙味（荒れ・大穴）のみ', '本線向きのみ（荒れ回避）'],
                          key=_k('lean'),
                          help="②穴妙味=荒れ・大穴狙いのレースだけ／本線向き=荒れるレースを避けたい時")
    _ar = _c2.slider("荒れ予報%の範囲", 0, 100, (0, 100), 5, key=_k('ar'),
                     help="例: 大穴だけ→(60,100)、堅いレースだけ→(0,40)。荒れ予報なしのレースは通す")
    _ex = _c3.checkbox("⛔見送り除外", value=True, key=_k('ex'))
    _c4, _c5 = st.columns([1.5, 1.5])
    _mx = _c4.slider("最大レース数", 4, 24, 12, 2, key=_k('mx'))
    _so = _c5.radio("並び順", ['買える順（Gate階層）', '妙味度順'], horizontal=True, key=_k('so'))
    _lean_mode = {'すべて': 'all', '②穴妙味（荒れ・大穴）のみ': 'ana',
                  '本線向きのみ（荒れ回避）': 'honsen'}[_lean_lbl]
    opts = {'lean_mode': _lean_mode, 'arare_range': _ar, 'exclude_skip': _ex,
            'max_races': _mx, 'sort_by': ('value' if _so == '妙味度順' else 'priority')}
    _prev = np_mod.filter_scan_rows(rows, _lean_mode, _ar, _ex, _mx, opts['sort_by'])
    st.caption(f"対象 {len(rows)}R → フィルタ後 **{len(_prev)}R** を収録（A4縦・2列カード）")

    if st.button(f"📰 スキャン新聞を発行（{len(_prev)}R → PDF）", type="primary",
                 key=_k('go'), disabled=not _prev):
        with st.spinner("ダイジェストを組版してPDFに変換中…"):
            html, used = np_mod.build_scan_digest_html(rows, opts)
            if not html:
                st.error("収録できるレースがありません。")
                return
            _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
            out = {'html': html, 'n': len(used), 'fname': f"scan_shimbun_{_ts}",
                   'pdf': None, 'err': None}
            try:
                out['pdf'] = np_mod.html_to_pdf(html, landscape=False, scale=1.0,
                                                page_numbers=True)
            except Exception as e:
                out['err'] = f"{type(e).__name__}: {e}"
            st.session_state[_k('out')] = out

    out = st.session_state.get(_k('out'))
    if out:
        if out['pdf']:
            _m = st.columns(3)
            _m[0].metric("PDFサイズ", f"{len(out['pdf']) / 1024:.0f} KB")
            _m[1].metric("ページ数", np_mod.pdf_page_count(out['pdf']) or '—')
            _m[2].metric("収録レース", f"{out['n']}R")
            _d1, _d2 = st.columns(2)
            _d1.download_button("📥 PDFをダウンロード", data=out['pdf'],
                                file_name=out['fname'] + '.pdf', mime="application/pdf",
                                type="primary", use_container_width=True, key=_k('dl'))
            _d2.download_button("🌐 HTML版", data=out['html'].encode('utf-8'),
                                file_name=out['fname'] + '.html', mime="text/html",
                                use_container_width=True, key=_k('dlh'))
        else:
            st.error(f"PDF変換に失敗: {out.get('err')}（HTML版はブラウザ印刷でPDF化できます）")
            st.download_button("🌐 HTML版をダウンロード", data=out['html'].encode('utf-8'),
                               file_name=out['fname'] + '.html', mime="text/html", key=_k('dlh2'))
        with st.expander("👀 プレビュー", expanded=True):
            import streamlit.components.v1 as components
            components.html(out['html'], height=560, scrolling=True)


def _render_conclusion_cards(sel_rids):
    """⑤½ 結論カード: 全レースの結論だけを1枚に圧縮したPDF/HTMLを発行。"""
    st.subheader("🎯 結論カード（買い目まとめ）")
    st.caption("フル新聞とは別に、**結論だけ**を1レース1カードに圧縮した出力。"
               "軸・相手・穴・危険・買い目のみ。分析詳細は含みません。"
               "noteの有料記事やLINE配信で「今日の推奨」として使えます。")

    if not sel_rids:
        st.info("上の①で収録レースを選んでください。")
        return

    _cc1, _cc2 = st.columns([2, 1])
    _cc_title = _cc1.text_input("カード題字", value="今日の結論", key="cc_title")
    _cc_mono = _cc2.checkbox("モノクロ", value=False, key="cc_mono")
    _cc_excl = st.checkbox("スキャン新聞に載っているレースは除外する",
                           value=True, key="cc_excl_scan",
                           help="🔍スキャン新聞（ダイジェスト）に既に載っているレースを結論カードから外し、"
                                "商品として重複しないようにします。")

    # 除外対象のプレビュー
    _cc_targets = list(sel_rids)
    if _cc_excl:
        try:
            _sd = np_mod.load_scan_digest() or {}
            _scan_ids = {str(r.get('id')) for r in (_sd.get('rows') or []) if r.get('id')}
            _dropped = [r for r in sel_rids if str(r) in _scan_ids]
            _cc_targets = [r for r in sel_rids if str(r) not in _scan_ids]
            if _dropped:
                st.caption(f"スキャン新聞と重複する {len(_dropped)}R を除外 → "
                           f"結論カードは **{len(_cc_targets)}R** を収録")
        except Exception:
            pass

    if st.button(f"🎯 結論カードを発行（{len(_cc_targets)}R）", type="primary", key="cc_publish",
                 disabled=not _cc_targets):
        with st.spinner("結論カードを生成中…"):
            html, issued = np_mod.build_conclusion_card_html(
                sel_rids, {'title': _cc_title, 'mono': _cc_mono, 'exclude_scan': _cc_excl})
            if not html:
                st.error("結論データがありません（合議または買い目のスナップショットが必要です／"
                         "またはスキャン新聞と全て重複して除外されました）。")
                return
            _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
            out = {'html': html, 'issued': issued, 'fname': f"conclusion_{_ts}",
                   'pdf': None, 'pdf_err': None}
            try:
                out['pdf'] = np_mod.html_to_pdf(html, landscape=False, scale=1.0,
                                                 page_numbers=False)
            except Exception as e:
                out['pdf_err'] = f"{type(e).__name__}: {e}"
            st.session_state['cc_out'] = out

    out = st.session_state.get('cc_out')
    if out:
        issued = out['issued']
        if out['pdf']:
            _mc = st.columns(3)
            _mc[0].metric("PDFサイズ", f"{len(out['pdf']) / 1024:.0f} KB")
            _mc[1].metric("ページ数", np_mod.pdf_page_count(out['pdf']) or '—')
            _mc[2].metric("収録レース", f"{len(issued)}R")
            _dc1, _dc2 = st.columns(2)
            _dc1.download_button("📥 結論カードPDF", data=out['pdf'],
                                 file_name=out['fname'] + '.pdf', mime="application/pdf",
                                 type="primary", use_container_width=True, key="cc_dl_pdf")
            _dc2.download_button("🌐 HTML版", data=out['html'].encode('utf-8'),
                                 file_name=out['fname'] + '.html', mime="text/html",
                                 use_container_width=True, key="cc_dl_html")
        else:
            st.error(f"PDF変換に失敗: {out.get('pdf_err')}")
            st.download_button("🌐 HTML版をダウンロード", data=out['html'].encode('utf-8'),
                               file_name=out['fname'] + '.html', mime="text/html", key="cc_dl_html2")
        with st.expander("👀 プレビュー", expanded=True):
            import streamlit.components.v1 as components
            components.html(out['html'], height=520, scrolling=True)


def _render_track_record(sel_rids, races):
    """⑦ 成績台帳セクション: 予測登録・結果取得・成績表示。"""
    from core import track_record as tr

    st.subheader("📊 成績台帳")
    st.caption("発行した新聞の予測を記録し、レース後に結果を照合。"
               "的中率・回収率を自動集計してnote等に貼れる成績表を生成します。")

    # ── ワンクリック台帳更新(バッチ) ──
    with st.expander("⚡ ワンクリック台帳更新（重賞バッチ）", expanded=False):
        st.caption("jravan.dbの2026年重賞（G1-G3）を自動解析→台帳登録→結果取得。裁量ゼロ。")
        _bc1, _bc2 = st.columns([2, 1])
        _grade_opt = _bc1.selectbox("対象", ['全重賞(G1-G3)', 'G1のみ', 'G2のみ', 'G3のみ'],
                                    key="tr_batch_grade")
        _grade_map = {'全重賞(G1-G3)': None, 'G1のみ': 'G1', 'G2のみ': 'G2', 'G3のみ': 'G3'}
        if _bc2.button("⚡ バッチ実行", key="tr_batch_run"):
            from scripts.batch_track_record import _load_graded_from_db, analyze_and_register
            grade_f = _grade_map[_grade_opt]
            rows = _load_graded_from_db(grade_filter=grade_f)
            already = {r['race_id'] for r in tr.get_records()}
            new_rows = [(rid, g, name, d) for rid, g, name, d in rows if rid not in already]
            if not new_rows:
                st.info("新規の未登録レースはありません。全て台帳登録済みです。")
            else:
                prog = st.progress(0, text=f"0/{len(new_rows)}")
                ok, fail = 0, 0
                for i, (rid, g, name, d) in enumerate(new_rows, 1):
                    prog.progress(i / len(new_rows), text=f"{i}/{len(new_rows)} {name}")
                    try:
                        if analyze_and_register(rid, verbose=False):
                            ok += 1
                        else:
                            fail += 1
                    except Exception:
                        fail += 1
                prog.empty()
                st.success(f"解析完了: ✅{ok}件 / ❌{fail}件")
                with st.spinner("結果取得中…"):
                    tr.fetch_results_batch()
                st.rerun()

    # ── 登録 ──
    with st.expander("➕ レースを台帳に登録", expanded=False):
        st.caption("新聞に収録されているレースの予測(合議結果+買い目)を台帳にスナップショット化します。")
        _reg_c1, _reg_c2 = st.columns([2, 1])
        _reg_target = _reg_c1.radio(
            "登録対象", ['上の収録レース(①で選んだレース)', '新聞発行可能な全レース'],
            key="tr_reg_target", horizontal=True)
        target_ids = sel_rids if _reg_target.startswith('上') else [r['race_id'] for r in races]
        if _reg_c2.button(f"📝 {len(target_ids)}R を台帳に登録", key="tr_register",
                          disabled=not target_ids):
            with st.spinner("登録中…"):
                n = tr.register_multiple(target_ids)
            if n > 0:
                st.success(f"{n}件 登録しました")
            else:
                st.info("新規登録なし（全て登録済み or 予測データなし）")

    # ── 結果取得 ──
    summary = tr.get_summary()
    pending = summary.get('pending', 0)

    if pending > 0:
        with st.expander(f"🔄 結果を取得（未取得: {pending}件）", expanded=False):
            st.caption("レース確定後にクリックすると着順・配当を取得して的中判定を行います。")
            if st.button(f"🔄 未取得{pending}件の結果を一括取得", key="tr_fetch_all"):
                with st.spinner("netkeibaから結果を取得中…（1件ずつ取得します）"):
                    results = tr.fetch_results_batch()
                ok = sum(1 for v in results.values() if v[0])
                fail = sum(1 for v in results.values() if not v[0])
                if ok:
                    st.success(f"{ok}件 取得完了")
                if fail:
                    st.warning(f"{fail}件 取得失敗（未確定 or ネットワークエラー）")
                    for rid, (_, msg) in results.items():
                        if msg != 'OK':
                            st.caption(f"  {rid}: {msg}")
                summary = tr.get_summary()

    # ── サマリー表示 ──
    if summary.get('n_evaluated') and summary['n_evaluated'] > 0:
        st.markdown("---")
        st.markdown("### 通算成績")
        _mc = st.columns(5)
        _mc[0].metric("集計R数", f"{summary['n_evaluated']}R")
        _mc[1].metric("軸的中率", f"{summary['axis_rate']}%" if summary.get('axis_rate') is not None else '—')
        _mc[2].metric("3連複的中率", f"{summary['trio_rate']}%" if summary.get('trio_rate') is not None else '—')
        _mc[3].metric("3連複ROI", f"{summary['trio_roi']}%" if summary.get('trio_roi') is not None else '—')
        _mc[4].metric("消去精度", f"{summary['keshi_precision']}%" if summary.get('keshi_precision') is not None else '—')

        _mc2 = st.columns(4)
        _mc2[0].metric("3連単的中率", f"{summary['trifecta_rate']}%" if summary.get('trifecta_rate') is not None else '—')
        _mc2[1].metric("3連単ROI", f"{summary['trifecta_roi']}%" if summary.get('trifecta_roi') is not None else '—')
        _mc2[2].metric("何か的中率", f"{summary['any_hit_rate']}%" if summary.get('any_hit_rate') is not None else '—')
        _mc2[3].metric("結果待ち", f"{pending}件")

        # 『控えめに見た』数字(95%信頼の下限)。レース数が少ないうちは的中率がブレるので、
        # 実績として外に出す時はこちらを使う(盛らない)。
        _lo_parts = []
        for _lbl, _k in (("軸", 'axis_rate_lo'), ("3連複", 'trio_rate_lo'),
                         ("消去精度", 'keshi_precision_lo')):
            if summary.get(_k) is not None:
                _lo_parts.append(f"{_lbl} {summary[_k]}%")
        if _lo_parts:
            st.caption(
                "控えめに見た数字（レース数が少ない分を差し引いた堅めの値）： "
                + " / ".join(_lo_parts)
                + "　— 実績として人に見せる時はこちらを使うと誇大になりません。")

        # ── 月別成績 ──
        monthly = tr.get_monthly_summary()
        if monthly:
            with st.expander("📅 月別成績", expanded=False):
                import pandas as pd
                mdf = pd.DataFrame(monthly)
                mdf.columns = ['月', 'R数', '軸的中%', '3連複的中%', '3連複ROI%',
                               '3連単的中%', '3連単ROI%', '的中率%']
                st.dataframe(mdf, hide_index=True, use_container_width=True)

        # ── テキスト出力(note/SNS用) ──
        with st.expander("📋 テキスト成績表（コピペ用）", expanded=False):
            txt = tr.export_summary_text()
            st.code(txt, language=None)
            st.caption("↑ noteの無料記事やX(Twitter)に貼って実績アピールに使えます。")

    # ── レース別詳細 ──
    records = tr.get_records()
    if records:
        with st.expander(f"📜 レース別結果一覧（{len(records)}件）", expanded=False):
            import pandas as pd
            rows_for_df = []
            for r in records:
                ev = r.get('eval') or {}
                pred = r.get('prediction') or {}
                axis_txt = ','.join(str(u) for u in (pred.get('axis') or []))
                top3_txt = ','.join(str(u) for u in ((r.get('result') or {}).get('top3') or []))
                rows_for_df.append({
                    '日付': r.get('date', '')[:10],
                    '場': r.get('venue', ''),
                    'R': r.get('race_no', ''),
                    'レース名': (r.get('race_name') or '')[:12],
                    '軸': axis_txt,
                    'Top3': top3_txt or '(未取得)',
                    '軸○': '✅' if ev.get('axis_hit') else ('❌' if top3_txt else '—'),
                    '3複○': '✅' if ev.get('trio_hit') else ('❌' if top3_txt else '—'),
                    '3複配当': f"¥{ev['trio_return']:,}" if ev.get('trio_return') else '',
                    '3単○': '✅' if ev.get('trifecta_hit') else ('❌' if top3_txt else '—'),
                    '切り残': ev.get('keshi_survived', ''),
                })
            df = pd.DataFrame(rows_for_df)
            st.dataframe(df, hide_index=True, use_container_width=True, height=400)
    elif summary.get('total', 0) == 0:
        st.info("台帳にレースが登録されていません。上の「➕ レースを台帳に登録」から始めてください。")


def render():
    st.title("📰 新聞発行")
    st.caption("🏠 Single Race Analysis で解析したレースを、A4のPDF競馬新聞として発行します。"
               "強適Ranking Tableは**アプリで表示中の列そのまま**を紙面化"
               "（🏠で解析した瞬間の表示スナップショットを使用）。"
               "解析スナップショットが無い過去レースは代表列で再構成します。")

    prefs = _load_prefs()

    # ────────────────── ① 収録レース選択 ──────────────────
    st.subheader("① 収録レースを選ぶ")
    _fc1, _fc2, _fc3 = st.columns([1.2, 1.2, 1])
    races = _races_cached()
    if _fc3.button("🔄 一覧を更新", help="解析したてのレースが見えない時に押す"):
        _races_cached.clear()
        _columns_of.clear()
        races = _races_cached()
    if not races:
        st.info("発行できるレースがまだありません。先に 🏠 Single Race Analysis でレースを解析してください。")
        return

    _dates = sorted({str((r['meta'] or {}).get('date') or '?') for r in races}, reverse=True)
    # 既定は「解析が新しい順」: 開催日でなく解析時刻ベース。
    # (前日に翌日のレースを1つ解析すると『最新日のみ』がその1Rだけになり、
    #  既定選択が1レースに縮んで紙面が1R分しか出ない罠があった)
    _date_sel = _fc1.selectbox("対象", ['解析が新しい順(推奨)', '最新開催日のみ', 'すべて'] + _dates,
                               index=0, key="np_date",
                               help="『解析が新しい順』=いま解析したレースから順に既定12Rを選択。"
                                    "特定の開催日だけにしたい時は日付を選択")
    _venues = sorted({str((r['meta'] or {}).get('venue') or '?') for r in races})
    _venue_sel = _fc2.selectbox("開催場", ['すべて'] + _venues, index=0, key="np_venue")

    _latest = _dates[0] if _dates else None
    filtered = []
    for r in races:
        d = str((r['meta'] or {}).get('date') or '?')
        v = str((r['meta'] or {}).get('venue') or '?')
        if _date_sel == '最新開催日のみ' and d != _latest:
            continue
        if _date_sel not in ('解析が新しい順(推奨)', '最新開催日のみ', 'すべて') and d != _date_sel:
            continue
        if _venue_sel != 'すべて' and v != _venue_sel:
            continue
        filtered.append(r)
    if _date_sel == '解析が新しい順(推奨)':
        filtered.sort(key=lambda r: -(r.get('ts') or 0))

    _lbl = {}
    for r in filtered:
        mark = '🗞️紙面フル' if r['source'] == 'view' else '📄代表列'
        _lbl[r['race_id']] = f"{np_mod.race_label(r)} {mark}"
    _default = [r['race_id'] for r in filtered[:12]]
    if st.button("↻ フィルタ結果から既定の12Rを選び直す", key="np_resel",
                 help="下の収録レース選択を、現在のフィルタ結果の上位12Rにリセットします"):
        st.session_state.pop('np_races', None)
    sel_rids = st.multiselect(
        "収録レース（選んだ順ではなく一覧順で紙面化）",
        options=list(_lbl.keys()), default=_default,
        format_func=lambda rid: _lbl.get(rid, rid), key="np_races")
    st.caption(f"対象 {len(filtered)}R 中 **{len(sel_rids)}R** を収録。"
               "🗞️紙面フル＝アプリ表示列そのまま／📄代表列＝スナップショット未保存(🏠で再解析すると全列化)")

    # ────────────────── ② 紙面設定 ──────────────────
    st.subheader("② 紙面設定")
    with st.expander("🗞️ 紙面の細かい調整（クリックで開閉）", expanded=True):
        _r1 = st.columns([1.5, 1.5, 1])
        title = _r1[0].text_input("題字", value=prefs.get('title', '強適競馬新聞'), key="np_title")
        subtitle = _r1[1].text_input("サブタイトル（空欄=発行日を自動）",
                                     value=prefs.get('subtitle', ''), key="np_sub")
        orientation = _r1[2].radio("用紙", ['A4 横(推奨)', 'A4 縦'],
                                   index=0 if prefs.get('orientation', 'landscape') == 'landscape' else 1,
                                   key="np_orient")

        _r2 = st.columns(3)
        font_pt = _r2[0].slider("テーブル基本フォント(pt)", 5.0, 11.0,
                                float(prefs.get('font_pt', 6.8)), 0.2, key="np_font",
                                help="列が多い時は小さく。A4横×全列なら6.4〜7.2ptが目安")
        scale = _r2[1].slider("印刷縮尺", 0.5, 1.5, float(prefs.get('scale', 1.0)), 0.05,
                              key="np_scale", help="紙面全体の拡大縮小(Chromium印刷scale)")
        cell_max = _r2[2].slider("セル文字数上限(0=無制限)", 0, 120,
                                 int(prefs.get('cell_max', 46)), 2, key="np_cellmax",
                                 help="血統・ボーナス内訳など長文列を省略して行高を揃える")

        _r3 = st.columns(3)
        row_order = _r3[0].radio("行の並び", ['アプリ表示順(スコア順)', '馬番順', '人気順'],
                                 index={'app': 0, 'umaban': 1, 'pop': 2}.get(prefs.get('row_order', 'app'), 0),
                                 key="np_roworder")
        col_mode = _r3[1].radio("列セット", ['アプリの表示列(保存列順)', '全列', '軽量セット',
                                          'カスタム(チェック式)'],
                                index={'app': 0, 'all': 1, 'lite': 2, 'custom': 3}.get(
                                    prefs.get('col_mode', 'app'), 0),
                                key="np_colmode",
                                help="『アプリの表示列』=🏠の⚙列順設定で表示していた列をそのまま紙面へ。"
                                     "『カスタム』=非表示列も含む全項目からチェック式で選ぶ")
        _flags = _r3[2]
        page_per_race = _flags.checkbox("1レース=1ページ(改ページ)",
                                        value=bool(prefs.get('page_per_race', True)), key="np_ppr")
        keep_table = _flags.checkbox("テーブルの途中改ページを避ける",
                                     value=bool(prefs.get('keep_table', True)), key="np_keeptbl",
                                     help="ONだと表が残りスペースに入らない時、分割せず次ページ頭から始めます"
                                          "（表が1ページより大きい時は自動で分割されます）")
        mono = _flags.checkbox("モノクロ印刷向け", value=bool(prefs.get('mono', False)), key="np_mono")
        page_numbers = _flags.checkbox("ページ番号を付ける",
                                       value=bool(prefs.get('page_numbers', True)), key="np_pgno")

        # 列の和集合(選択レースから・非表示列も含む全項目)
        _colpairs = {}
        for rid in sel_rids:
            for c, lb in _columns_of(rid):
                _colpairs.setdefault(c, lb)

        # ── カスタム: チェック式の列選択（チェックした順=紙面の左からの並び） ──
        custom_cols = list(prefs.get('custom_cols') or [])
        if col_mode == 'カスタム(チェック式)':
            with st.expander("🧮 列を選ぶ（チェックした順に左から紙面に並びます）", expanded=True):
                if not _colpairs:
                    st.info("先に上で収録レースを選ぶと、そのレースが持つ全項目（非表示列含む）が出ます。")
                _ck = lambda c: f"np_ck_{c}"
                _ordkey = 'np_ck_order'

                def _app_display_cols():
                    v0 = np_mod.load_view(sel_rids[0]) if sel_rids else None
                    return [c for c in ((v0 or {}).get('order') or []) if c in _colpairs]

                if _ordkey not in st.session_state:
                    _init = [c for c in custom_cols if c in _colpairs] or _app_display_cols()
                    st.session_state[_ordkey] = _init
                    for c in _colpairs:
                        st.session_state[_ck(c)] = (c in _init)
                else:
                    for c in _colpairs:
                        if _ck(c) not in st.session_state:
                            st.session_state[_ck(c)] = False

                _bc = st.columns(3)
                if _bc[0].button("↩️ アプリ表示列に戻す", key="np_ck_reset"):
                    _init = _app_display_cols()
                    for c in _colpairs:
                        st.session_state[_ck(c)] = (c in _init)
                    st.session_state[_ordkey] = _init
                if _bc[1].button("✅ 全選択", key="np_ck_all"):
                    for c in _colpairs:
                        st.session_state[_ck(c)] = True
                    st.session_state[_ordkey] = list(_colpairs.keys())
                if _bc[2].button("🗑 全解除", key="np_ck_none"):
                    for c in _colpairs:
                        st.session_state[_ck(c)] = False
                    st.session_state[_ordkey] = []

                _grid = st.columns(3)
                for _i, (c, lb) in enumerate(_colpairs.items()):
                    with _grid[_i % 3]:
                        st.checkbox(lb, key=_ck(c))

                # チェック順を再構成（既存チェック順を保ち、新規チェックは末尾へ）
                _prev = st.session_state.get(_ordkey, [])
                _sel_c = [c for c in _prev if c in _colpairs and st.session_state.get(_ck(c))]
                for c in _colpairs:
                    if st.session_state.get(_ck(c)) and c not in _sel_c:
                        _sel_c.append(c)
                st.session_state[_ordkey] = _sel_c
                custom_cols = _sel_c
                if custom_cols:
                    _odr = " → ".join(_colpairs.get(c, c) for c in custom_cols[:14])
                    if len(custom_cols) > 14:
                        _odr += f" →…(+{len(custom_cols) - 14}列)"
                    st.caption(f"✅ {len(custom_cols)}列を選択中（紙面順）: {_odr}")
                else:
                    st.caption("⚠ 0列＝発行時はアプリ表示列にフォールバックします。")

        _excl_saved = [c for c in (prefs.get('exclude_cols') or []) if c in _colpairs]
        exclude_cols = st.multiselect(
            "除外する列（紙面に載せない列）", options=list(_colpairs.keys()),
            default=_excl_saved, format_func=lambda c: _colpairs.get(c, c), key="np_excl")

        st.markdown("**セクション**")
        _s = st.columns(4)
        sec_cover = _s[0].checkbox("表紙(目次+凡例)", value=bool(prefs.get('sec_cover', True)), key="np_s_cover")
        sec_cv = _s[1].checkbox("合議カード(本命/相手/押さえ/穴/切る)",
                                value=bool(prefs.get('sec_cv', True)), key="np_s_cv")
        sec_buy = _s[2].checkbox("買い目メタ(点数/合成オッズ/残し馬)",
                                 value=bool(prefs.get('sec_buy', True)), key="np_s_buy")
        sec_gate = _s[3].checkbox("Gate判定バッジ(買い/見送り)",
                                  value=bool(prefs.get('sec_gate', True)), key="np_s_gate")
        _s2 = st.columns(4)
        sec_hplus = _s2[0].checkbox("予想ヘッダー(荒れ予報/妙味度/軸候補/危険人気馬)",
                                    value=bool(prefs.get('sec_hplus', True)), key="np_s_hplus")
        sec_bets = _s2[1].checkbox("おすすめ買い目(3連複/3連単/馬連馬単/ワイド)",
                                   value=bool(prefs.get('sec_bets', True)), key="np_s_bets",
                                   help="SRAで各エンジンを開いた時の買い目を自動保存→紙面化。未生成のレースは非表示")
        sec_pace = _s2[2].checkbox("展開・隊列(4角想定+AI照合💀)",
                                   value=bool(prefs.get('sec_pace', True)), key="np_s_pace")
        sec_odds = _s2[3].checkbox("オッズ動向(朝一↔直前)",
                                   value=bool(prefs.get('sec_odds', True)), key="np_s_odds",
                                   help="オッズ記録(📥/常駐ランナー)があるレースのみ表示")
        _s3 = st.columns(4)
        sec_elim = _s3[0].checkbox("消去フィルター(消去クロス+残し馬)",
                                   value=bool(prefs.get('sec_elim', True)), key="np_s_elim")
        sec_vh = _s3[1].checkbox("穴馬ハンター(妙味馬+根拠)",
                                 value=bool(prefs.get('sec_vh', True)), key="np_s_vh")
        sec_evidence = _s3[2].checkbox("📊判定根拠エビデンス表",
                                       value=bool(prefs.get('sec_evidence', True)), key="np_s_ev")
        sec_pci = _s3[3].checkbox("⚡PCI&展開適合(ペース総合判定)",
                                  value=bool(prefs.get('sec_pci', True)), key="np_s_pci")
        _s4 = st.columns(4)
        sec_upset = _s4[0].checkbox("🏇展開分析&波乱確率(内訳/脚質構成)",
                                    value=bool(prefs.get('sec_upset', True)), key="np_s_upset")
        sec_stress = _s4[1].checkbox("🐎Stress Analyst(トラップ/スト2)",
                                     value=bool(prefs.get('sec_stress', True)), key="np_s_stress")
        sec_alerts = _s4[2].checkbox("🚨条件アラート集約(荒れ予報/軸不可/末脚妙味/枠順)",
                                     value=bool(prefs.get('sec_alerts', True)), key="np_s_alerts",
                                     help="レースごとに条件が揃った時だけ出る警告・妙味を1ブロックに集約")
        sec_j5 = _s4[3].checkbox("🏇騎手係数込みスコア(黄金ライン/順位変動)",
                                 value=bool(prefs.get('sec_j5', False)), key="np_s_j5",
                                 help="🏠SRAの『騎手係数込み 総合スコア』表を紙面に追加します。"
                                      "SRAでそのレースを解析した時の表示内容（騎手影響率スライダーの値ごと）"
                                      "をそのまま載せます。SRAで開いていないレースには出ません。")
        footer_text = st.text_input("フッター注記（毎号入れる注意書き等）",
                                    value=prefs.get('footer_text',
                                                    '本紙は検証済みエッジの合議に基づく参考情報です。馬券の購入は自己責任で。'),
                                    key="np_footer")

        if st.button("💾 この設定を既定として保存", key="np_save_prefs"):
            ok = _save_prefs({
                'title': title, 'subtitle': subtitle,
                'orientation': 'landscape' if orientation.startswith('A4 横') else 'portrait',
                'font_pt': font_pt, 'scale': scale, 'cell_max': cell_max,
                'row_order': {'アプリ表示順(スコア順)': 'app', '馬番順': 'umaban', '人気順': 'pop'}[row_order],
                'col_mode': {'アプリの表示列(保存列順)': 'app', '全列': 'all', '軽量セット': 'lite',
                             'カスタム(チェック式)': 'custom'}[col_mode],
                'custom_cols': custom_cols,
                'page_per_race': page_per_race, 'keep_table': keep_table,
                'mono': mono, 'page_numbers': page_numbers,
                'exclude_cols': exclude_cols,
                'sec_cover': sec_cover, 'sec_cv': sec_cv, 'sec_buy': sec_buy, 'sec_gate': sec_gate,
                'sec_hplus': sec_hplus, 'sec_bets': sec_bets, 'sec_pace': sec_pace,
                'sec_odds': sec_odds, 'sec_elim': sec_elim, 'sec_vh': sec_vh,
                'sec_evidence': sec_evidence, 'sec_pci': sec_pci,
                'sec_upset': sec_upset, 'sec_stress': sec_stress,
                'sec_alerts': sec_alerts, 'sec_j5': sec_j5,
                'footer_text': footer_text,
            })
            st.toast("設定を保存しました ✅" if ok else "保存に失敗しました ⚠️")

    # ────────────────── ③ 発行 ──────────────────
    st.subheader("③ 発行")
    opts = {
        'title': title, 'subtitle': subtitle,
        'orientation': 'landscape' if orientation.startswith('A4 横') else 'portrait',
        'scale': scale, 'font_pt': font_pt, 'cell_max': cell_max,
        'row_order': {'アプリ表示順(スコア順)': 'app', '馬番順': 'umaban', '人気順': 'pop'}[row_order],
        'col_mode': {'アプリの表示列(保存列順)': 'app', '全列': 'all', '軽量セット': 'lite',
                     'カスタム(チェック式)': 'custom'}[col_mode],
        'custom_cols': custom_cols,
        'exclude_cols': exclude_cols, 'page_per_race': page_per_race,
        'keep_table': keep_table, 'mono': mono,
        'page_numbers': page_numbers, 'footer_text': footer_text,
        'sections': {'cover': sec_cover, 'consensus': sec_cv,
                     'buymeta': sec_buy, 'gate': sec_gate,
                     'header_plus': sec_hplus, 'bets': sec_bets, 'pace': sec_pace,
                     'odds_moves': sec_odds, 'elim': sec_elim, 'vh': sec_vh,
                     'evidence': sec_evidence, 'pci': sec_pci,
                     'pace_upset': sec_upset, 'stress': sec_stress,
                     'alerts': sec_alerts, 'j5': sec_j5},
    }

    if st.button(f"📰 新聞を発行する（{len(sel_rids)}R → PDF）", type="primary",
                 disabled=not sel_rids, key="np_publish"):
        with st.spinner("紙面を組版してPDFに変換中…（初回は数十秒かかることがあります）"):
            html, issued = np_mod.build_newspaper_html(sel_rids, opts)
            if not html:
                st.error("紙面を作れませんでした（選択レースのデータが読めません）。")
                return
            _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
            out = {'html': html, 'issued': issued, 'fname': f"keiba_shimbun_{_ts}",
                   'pdf': None, 'pdf_err': None}
            try:
                out['pdf'] = np_mod.html_to_pdf(
                    html, landscape=(opts['orientation'] == 'landscape'),
                    scale=scale, page_numbers=page_numbers)
            except Exception as e:
                out['pdf_err'] = f"{type(e).__name__}: {e}"
            st.session_state['np_out'] = out

    # ────────────────── ④ 成果物の確認 ──────────────────
    out = st.session_state.get('np_out')
    if out:
        st.subheader("④ 発行結果（成果物の確認）")
        issued = out['issued']
        if out['pdf']:
            _m = st.columns(4)
            _m[0].metric("PDFサイズ", f"{len(out['pdf']) / 1024:.0f} KB")
            _pages = np_mod.pdf_page_count(out['pdf'])
            _m[1].metric("ページ数", _pages if _pages else "—")
            _m[2].metric("収録レース", f"{len(issued)}R")
            _full = sum(1 for i in issued if i['source'] == 'view')
            _m[3].metric("紙面フル/代表列", f"{_full} / {len(issued) - _full}")
            _d1, _d2 = st.columns(2)
            _d1.download_button("📥 PDFをダウンロード", data=out['pdf'],
                                file_name=out['fname'] + '.pdf', mime="application/pdf",
                                type="primary", use_container_width=True, key="np_dl_pdf")
            _d2.download_button("🌐 HTML版（ブラウザでCtrl+P印刷用）", data=out['html'].encode('utf-8'),
                                file_name=out['fname'] + '.html', mime="text/html",
                                use_container_width=True, key="np_dl_html")
        else:
            st.error(f"PDF変換に失敗しました: {out.get('pdf_err')}\n\n"
                     "HTML版をダウンロードしてブラウザの印刷(Ctrl+P)からPDF保存できます。")
            st.download_button("🌐 HTML版をダウンロード", data=out['html'].encode('utf-8'),
                               file_name=out['fname'] + '.html', mime="text/html", key="np_dl_html2")

        with st.expander("📋 収録内訳（レースごとの行数・列数）", expanded=False):
            import pandas as pd
            st.dataframe(pd.DataFrame([
                {'レース': i['label'], '馬数': i['n_rows'], '紙面列数': i['n_cols'],
                 'ソース': '🗞️アプリ表示列' if i['source'] == 'view' else '📄代表列'}
                for i in issued]), hide_index=True, use_container_width=True)
        with st.expander("👀 紙面プレビュー（HTML・実PDFとほぼ同等）", expanded=True):
            import streamlit.components.v1 as components
            components.html(out['html'], height=640, scrolling=True)

    # ────────────────── ⑤ レース情報CSVエクスポート ──────────────────
    st.divider()
    st.subheader("📥 レース情報CSVエクスポート（ワンクリック保存）")
    st.caption("そのレースの**すべての情報**（アプリ表示列＋解析生データ全列。過去走等のネスト情報は"
               "JSON文字列として同梱）を1枚のCSVでダウンロードします。")
    _all_lbl = {r['race_id']: np_mod.race_label(r) for r in races}
    _csv_rid = st.selectbox("対象レース", options=list(_all_lbl.keys()),
                            format_func=lambda rid: _all_lbl.get(rid, rid), key="np_csv_race")
    if _csv_rid:
        csv_bytes, n_rows, n_cols = np_mod.build_csv_bytes(_csv_rid)
        if csv_bytes:
            _dlc1, _dlc2 = st.columns([2, 1])
            _dlc1.download_button(
                f"📥 このレースの全情報CSVをダウンロード（{n_rows}頭 × {n_cols}列）",
                data=csv_bytes, file_name=f"race_all_{_csv_rid}.csv", mime="text/csv",
                type="primary", use_container_width=True, key="np_dl_csv")
            _dlc2.download_button(
                "📖 データ辞書（LLM向け列説明）",
                data=np_mod.csv_data_dictionary().encode('utf-8'),
                file_name="data_dictionary.md", mime="text/markdown",
                use_container_width=True, key="np_dl_dict",
                help="外部LLMにCSVを渡す時はこの辞書を一緒に渡すこと。"
                     "どの列が検証済みか・どの人気帯で有効か・市場内包列の注意・"
                     "検証で否定済みの俗説リストを説明しています。")
            st.caption("💡 外部LLMに予想させる場合: **CSVと📖データ辞書をセットで渡してください。**"
                       "辞書なしだと、人気を内包するProjected Score/LTRに引き寄せられ、"
                       "検証済みシグナル（🎯穴/🧩重複/末脚🔥/補正T🔵）を正しく重み付けできません"
                       "（2026-07七夕賞のLLM会議実験で実証）。CSVには合議の結論列"
                       "（合議役割/危険材料/R荒れ予報%等）も同梱済みです。")
        else:
            st.warning("このレースのデータを読めませんでした。")
    # まとめCSV = ①で選んだ複数レースを縦結合(RaceID_列付き)。1レース選択時は
    # 上の単一CSVとほぼ同じで紛らわしいため、2R以上選ばれている時だけ表示する。
    if sel_rids and len(sel_rids) >= 2:
        st.markdown("---")
        st.caption(f"**🧺 複数レースまとめCSV**：①で選んだ収録レース{len(sel_rids)}R全部を"
                   "縦に積んで1枚に（各行に`RaceID_`列付き）。1日分をExcel/LLMで横断分析したり、"
                   "データパックとしてまとめて渡す用。まず🧺で作成→📥で保存の2段階です。")
        if st.button(f"🧺 収録中の{len(sel_rids)}Rをまとめて1枚のCSVに", key="np_csv_all_btn"):
            import pandas as pd
            import io
            frames = []
            for rid in sel_rids:
                b, _, _ = np_mod.build_csv_bytes(rid)
                if b:
                    df = pd.read_csv(io.BytesIO(b), encoding='utf-8-sig')
                    df.insert(0, 'RaceID_', rid)
                    frames.append(df)
            if frames:
                merged = pd.concat(frames, ignore_index=True)
                st.session_state['np_csv_all'] = merged.to_csv(index=False).encode('utf-8-sig')
                st.session_state['np_csv_all_n'] = (len(merged), len(merged.columns))
        if st.session_state.get('np_csv_all') is not None:
            _n = st.session_state.get('np_csv_all_n', (0, 0))
            st.download_button(f"📥 まとめCSVをダウンロード（{_n[0]}行 × {_n[1]}列）",
                               data=st.session_state['np_csv_all'],
                               file_name=f"races_all_{datetime.date.today().strftime('%Y%m%d')}.csv",
                               mime="text/csv", key="np_dl_csv_all")

    # ────────────────── ⑤½ 結論カード（1レース1枚の結論圧縮版） ──────────────────
    st.divider()
    _render_conclusion_cards(sel_rids)

    # ────────────────── ⑥ スキャン新聞（Race Scannerダイジェスト） ──────────────────
    st.divider()
    st.subheader("🔍 スキャン新聞（Race Scannerダイジェスト）")
    st.caption("🔍 Race Scanner (Batch) の最新スキャン結果を、A4縦・2列カードの一覧PDFに発行します。"
               "「②穴妙味（荒れ・大穴）だけ」「本線向きだけ（荒れ回避）」の絞り込みに対応。")
    _sd = np_mod.load_scan_digest()
    if not _sd or not _sd.get('rows'):
        st.info("スキャン結果がまだありません。🔍 Race Scanner (Batch) でスキャンすると、"
                "最新結果がここから発行できるようになります。")
    else:
        _sd_ts = datetime.datetime.fromtimestamp(_sd.get('ts') or 0).strftime('%m/%d %H:%M')
        st.caption(f"最新スキャン: {_sd_ts}　全{len(_sd['rows'])}R")
        render_scan_digest_ui(_sd['rows'], key_prefix='np_sd')

        # ── 厳選N鞍 → 結論カード (ワンクリック配信用) ──
        st.markdown("---")
        st.markdown("#### 🎯 厳選レース → 結論カード配信")
        st.caption("スキャン上位から妙味度の高い鞍だけ選び、結論カード(軸/相手/買い目)を1枚で発行。"
                   "noteの有料記事やLINE配信に「今日の厳選○鞍」として使えます。")
        _pc1, _pc2, _pc3 = st.columns([1, 1, 1.5])
        _pick_n = _pc1.slider("厳選鞍数", 1, 6, 3, 1, key="pick_n")
        _pick_sort = _pc2.radio("選び方", ['妙味度順', '買える順'], horizontal=True, key="pick_sort")
        _pick_title = _pc3.text_input("題字", value=f"今日の厳選{_pick_n}鞍", key="pick_title")

        # フィルタ: buy gate only → sort → top N
        _buy_rows = [r for r in _sd['rows'] if str(r.get('gate', '')) != 'skip']
        if _pick_sort == '妙味度順':
            _buy_rows.sort(key=lambda r: -(float(r.get('vscore') or 0)))
        _top = _buy_rows[:_pick_n]
        _top_ids = [str(r.get('id', '')) for r in _top if r.get('id')]

        if _top_ids:
            _names = [f"{np_mod.VENUE_BY_CODE.get(str(rid)[4:6], '')}{np_mod.race_no(rid)}R"
                      for rid in _top_ids]
            st.caption(f"対象: **{'　'.join(_names)}**（✅買えるレースから上位{_pick_n}鞍）")

            if st.button(f"🎯 厳選{len(_top_ids)}鞍の結論カードを発行", type="primary", key="pick_go"):
                with st.spinner("結論カードを生成中…"):
                    html, issued = np_mod.build_conclusion_card_html(
                        _top_ids, {'title': _pick_title})
                    if not html:
                        st.error("結論データなし（対象レースを先に🏠SRAで解析してください）。")
                    else:
                        _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
                        out_pick = {'html': html, 'issued': issued,
                                    'fname': f"pick{len(issued)}_{_ts}", 'pdf': None, 'err': None}
                        try:
                            out_pick['pdf'] = np_mod.html_to_pdf(html, landscape=False,
                                                                  scale=1.0, page_numbers=False)
                        except Exception as e:
                            out_pick['err'] = str(e)
                        st.session_state['pick_out'] = out_pick

            _po = st.session_state.get('pick_out')
            if _po:
                if _po['pdf']:
                    _pm = st.columns(3)
                    _pm[0].metric("PDF", f"{len(_po['pdf']) / 1024:.0f} KB")
                    _pm[1].metric("レース数", f"{len(_po['issued'])}鞍")
                    _pm[2].metric("ページ", np_mod.pdf_page_count(_po['pdf']) or '1')
                    _pd1, _pd2 = st.columns(2)
                    _pd1.download_button("📥 厳選カードPDF", data=_po['pdf'],
                                         file_name=_po['fname'] + '.pdf', mime="application/pdf",
                                         type="primary", use_container_width=True, key="pick_dl")
                    _pd2.download_button("🌐 HTML版", data=_po['html'].encode('utf-8'),
                                         file_name=_po['fname'] + '.html', mime="text/html",
                                         use_container_width=True, key="pick_dl_h")
                else:
                    st.warning(f"PDF失敗: {_po.get('err')}")
                    st.download_button("🌐 HTML版", data=_po['html'].encode('utf-8'),
                                       file_name=_po['fname'] + '.html', mime="text/html",
                                       key="pick_dl_h2")
                with st.expander("👀 プレビュー", expanded=True):
                    import streamlit.components.v1 as components
                    components.html(_po['html'], height=420, scrolling=True)
        else:
            st.info("✅買えるレースがスキャン結果にありません。")

    # ────────────────── ⑦ 成績台帳 ──────────────────
    st.divider()
    _render_track_record(sel_rids, races)
