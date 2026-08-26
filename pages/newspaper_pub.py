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


def _orientation_value(label):
    """用紙ラジオの表示ラベル→opts['orientation']の内部値。"""
    if label.startswith('A3'):
        return 'a3_portrait'
    if label.startswith('A4 横'):
        return 'landscape'
    return 'portrait'


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


def _render_batch_analyze():
    """⚡ 一括解析セクション(🔍スキャン結果 or 📅日付指定)。

    1レースずつ🏠SRAを手で開く代わりに、まとめて自動解析する。
    実処理は別プロセス(scripts/batch_sra_publish.py)で走らせ、ここは
    進捗ファイル(core.batch_analyze.read_status)を読んで表示するだけにする。
    ページ内で同期実行すると30〜60分ページが固まり、さらに自動化が
    同じStreamlitサーバへ接続するため自己ブロックの危険がある。
    """
    import time as _t
    from core import batch_analyze as _ba

    st.subheader("⚡ まとめて解析（新聞のもとを作る）")
    status = _ba.read_status()
    running = _ba.is_running()

    # ── 実行中: 進捗表示に専念する ──
    if running:
        i = status.get('i', 0)
        n = status.get('n', 0) or 1
        state = status.get('state', 'running')
        _phase = '📰 新聞を組版中…' if state == 'publishing' else '🏇 解析中…'
        st.progress(min(i / n, 1.0), text=f"{_phase} {i}/{status.get('n', 0)}R")
        _m = st.columns(4)
        _m[0].metric("完了", status.get('ok', 0))
        _m[1].metric("スキップ", status.get('skipped', 0))
        _m[2].metric("失敗", status.get('failed', 0))
        _el = int(_t.time() - (status.get('started_ts') or _t.time()))
        _m[3].metric("経過", f"{_el // 60}分{_el % 60}秒")
        if status.get('lines'):
            st.code('\n'.join(status['lines'][-10:]), language=None)
        _bc = st.columns([1, 1, 3])
        if _bc[0].button("⏹ 中止", key="np_batch_stop"):
            _ba.stop_batch()
            st.rerun()
        if _bc[1].button("🔄 更新", key="np_batch_refresh"):
            st.rerun()
        st.caption("解析はこのページを閉じても裏で続きます。1レースあたり約1〜2分が目安です。")
        _t.sleep(3)
        st.rerun()
        return

    # ── 直前の実行結果 ──
    if status and status.get('state') in ('done', 'error', 'stopped'):
        _st = status['state']
        _msg = (f"✅ 完了: {status.get('ok', 0)}R解析 / "
                f"{status.get('skipped', 0)}R既存 / {status.get('failed', 0)}R失敗")
        if _st == 'done':
            st.success(_msg)
        elif _st == 'stopped':
            st.warning("⏹ 中止しました。" + _msg)
        else:
            st.error(f"❌ エラー: {status.get('error')}")
        _pub = status.get('publish') or {}
        if _pub.get('pdf_path') and os.path.exists(_pub['pdf_path']):
            try:
                with open(_pub['pdf_path'], 'rb') as f:
                    st.download_button(f"📥 発行された新聞をダウンロード（{_pub.get('n', '?')}R）",
                                       data=f.read(),
                                       file_name=os.path.basename(_pub['pdf_path']),
                                       mime="application/pdf", type="primary",
                                       key="np_batch_dl")
            except Exception:
                pass
        if _st in ('done', 'stopped'):
            st.caption("解析したレースは下の「① 収録レースを選ぶ」にも出ています。"
                       "列や用紙を変えて発行し直したい時は、いつも通り①②③をお使いください"
                       "（出てこない時は①の「🔄 一覧を更新」を押してください）。")
        if status.get('lines'):
            with st.expander("実行ログを見る"):
                st.code('\n'.join(status['lines']), language=None)
        if st.button("🗑 この結果を消す", key="np_batch_clear"):
            _ba.clear_status()
            _races_cached.clear()
            st.rerun()

    # ── どのレースを解析するか ──
    _src = st.radio("解析するレースの選び方",
                    ['🔍 スキャン結果から（Race Scannerで絞ったレース）', '📅 日付を指定して全レース'],
                    key="np_batch_src", horizontal=True)
    use_scan = _src.startswith('🔍')

    targets = []       # [{'race_id','venue','label'}]
    date_str = datetime.date.today().strftime('%Y%m%d')

    if use_scan:
        # スキャン結果はディスク(data/newspaper/scan_digest.json)から毎回読み直す。
        # 「新しくスキャンしたのに古い結果が出る」時はStreamlitがモジュールを
        # プロセス内キャッシュしているのが原因なので、日時を必ず出して気付けるようにする。
        _sd = np_mod.load_scan_digest()
        if not _sd or not _sd.get('rows'):
            st.info("スキャン結果がまだありません。🔍 Race Scanner (Batch) でスキャンしてから"
                    "ここに戻ってください。")
            return
        _rows = _sd['rows']
        _sd_dt = datetime.datetime.fromtimestamp(_sd.get('ts') or 0)
        _sd_ts = _sd_dt.strftime('%m/%d %H:%M')
        _age_min = (datetime.datetime.now() - _sd_dt).total_seconds() / 60
        _rc1, _rc2 = st.columns([3, 1])
        _rc1.caption(f"読み込んだスキャン結果: **{_sd_ts}**（{_age_min / 60:.1f}時間前）　全{len(_rows)}R"
                     f"　対象日 {str((_rows[0] or {}).get('date_val') or '?')}")
        if _rc2.button("🔄 スキャン結果を再読込", key="np_batch_reload",
                       help="スキャンしたのに古い結果が出る時に押してください"):
            st.rerun()
        if _age_min > 60 * 12:
            st.warning("⚠ このスキャン結果は12時間以上前のものです。"
                       "新しくスキャンしたのにここが古いままなら、Streamlitを完全再起動"
                       "（Ctrl+C → `streamlit run app.py`）してください。"
                       "ブラウザのリロードや Rerun では直りません。")

        _f1, _f2 = st.columns([1.4, 1.6])
        _gate_lbl = _f1.radio("どのレースを解析する？",
                              ['✅買えるレースだけ', '✅買える＋🟡軸注意', 'スキャンした全レース'],
                              key="np_batch_gate",
                              help="⛔見送りレースまで解析すると時間がぶんだけ長くなります")
        _lean_lbl = _f2.radio("決着タイプ",
                              ['すべて', '②穴妙味（荒れ・大穴）のみ', '本線向きのみ（荒れ回避）'],
                              key="np_batch_lean", horizontal=True)
        _gate_ok = {'✅買えるレースだけ': {'buy'},
                    '✅買える＋🟡軸注意': {'buy', 'axis_warn'},
                    'スキャンした全レース': None}[_gate_lbl]
        _lean_want = {'すべて': None, '②穴妙味（荒れ・大穴）のみ': '②穴妙味向き',
                      '本線向きのみ（荒れ回避）': '本線向き'}[_lean_lbl]
        for r in _rows:
            rid = str(r.get('id') or '')
            if not rid:
                continue
            if _gate_ok is not None and str(r.get('gate') or '') not in _gate_ok:
                continue
            if _lean_want and np_mod._lean_of(r) != _lean_want:
                continue
            _vn = np_mod.VENUE_BY_CODE.get(rid[4:6], '?')
            _rno = rid[-2:].lstrip('0') or '?'
            _gi = {'buy': '✅', 'axis_warn': '🟡', 'skip': '⛔'}.get(str(r.get('gate') or ''), '')
            targets.append({
                'race_id': rid, 'venue': _vn,
                'label': f"{_gi}{_vn}{_rno}R {r.get('title') or ''}".strip(),
            })
            if r.get('date_val'):
                date_str = str(r['date_val'])[:8] or date_str
    else:
        _d = st.date_input("解析する開催日", value=datetime.date.today(), key="np_batch_date")
        date_str = _d.strftime('%Y%m%d')
        _lk = f"np_batch_list_{date_str}"
        if st.button("🔍 この日のレースを調べる", key="np_batch_fetch"):
            with st.spinner("開催レースを取得中…"):
                try:
                    st.session_state[_lk] = _ba.fetch_day_race_ids(date_str)
                except Exception as e:
                    st.session_state[_lk] = []
                    st.error(f"レース一覧の取得に失敗しました: {e}")
        _day = st.session_state.get(_lk)
        if _day is None:
            st.info("まず「🔍 この日のレースを調べる」を押すと、その日の開催レースが出ます。")
            return
        if not _day:
            st.warning("この日には開催レースが見つかりませんでした（開催がない日かもしれません）。")
            return
        _all_venues = sorted({t.get('venue') or '?' for t in _day})
        _vsel = st.multiselect("開催場をしぼる（空欄=すべて）", _all_venues,
                               default=[], key="np_batch_venues")
        targets = [{'race_id': t['race_id'], 'venue': t.get('venue') or '?',
                    'label': f"{t.get('venue', '')}{t.get('race_num', '')}"}
                   for t in _day if not _vsel or t.get('venue') in _vsel]

    if not targets:
        st.warning("条件に合うレースがありません。上の絞り込みをゆるめてください。")
        return

    # ── オプション ──
    _o1, _o2 = st.columns(2)
    do_elim = _o1.checkbox("消去フィルターも実行（✅残し/🧹消しを紙面に載せる）",
                           value=True, key="np_batch_elim",
                           help="OFFにすると速くなりますが、紙面の✅🛟🧹バッジが付きません")
    do_publish = _o1.checkbox("解析が終わったら新聞も自動発行する",
                              value=True, key="np_batch_pub",
                              help="②紙面設定で保存した設定を使ってPDFを作ります")
    skip_existing = _o2.checkbox("解析済みは飛ばす", value=True, key="np_batch_skip",
                                 help="OFFにすると全レースを解析し直します（時間がかかります）")
    with_signal = _o2.checkbox("🔬当日シグナルも取得（J◎/T◎/T●）", value=True,
                               key="np_batch_signal",
                               help="騎手◎・厩舎◎●を取得して強適スコアの🔬列に反映します。"
                                    "当日全レースを走査しますが、結果は日付ごとに保存されるので"
                                    "実際に走るのはその日の最初の1レースだけです（中央のみ）。")

    _new = sum(1 for t in targets if not all(_ba._has_snapshots(t['race_id'])))
    _est = max(1, (_new if skip_existing else len(targets))) * (2 if do_elim else 1.5)
    st.caption(f"対象 **{len(targets)}R**（うち未解析 {_new}R）／ 所要目安 **約{int(_est)}分**")
    with st.expander(f"対象レースを確認する（{len(targets)}R）"):
        st.write('　/　'.join(t['label'] for t in targets))

    if st.button(f"⚡ 一括解析を開始（{len(targets)}R）", type="primary",
                 key="np_batch_start"):
        pid = _ba.start_batch_subprocess(
            date_str=date_str,
            race_ids=[t['race_id'] for t in targets],
            skip_existing=skip_existing,
            sra_only=not do_elim, publish=do_publish,
            with_signal=with_signal)
        if pid:
            st.success(f"解析を開始しました（PID {pid}）。進捗をここに表示します。")
            _t.sleep(1)
            st.rerun()
        else:
            st.error("解析プロセスの起動に失敗しました。")


def render():
    st.title("📰 新聞発行")
    st.caption("🏠 Single Race Analysis で解析したレースを、A4のPDF競馬新聞として発行します。"
               "強適Ranking Tableは**アプリで表示中の列そのまま**を紙面化"
               "（🏠で解析した瞬間の表示スナップショットを使用）。"
               "解析スナップショットが無い過去レースは代表列で再構成します。")

    prefs = _load_prefs()

    # ⚡ 一括解析(1レースずつ🏠を開かずに済ませる導線)。
    # 「発行できるレースがまだありません」でreturnする前に置く:
    # 未解析ゼロの状態こそ、この機能が最も必要とされる場面のため。
    with st.expander("⚡ スキャン結果をまとめて解析する（1レースずつ🏠を開かなくて済みます）",
                     expanded=False):
        _render_batch_analyze()
    st.divider()

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
        _orient_opts = ['A4 横(推奨)', 'A4 縦', 'A3 縦(コンビニ印刷向け)']
        _orient_val = prefs.get('orientation', 'landscape')
        _orient_idx = {'landscape': 0, 'portrait': 1, 'a3_portrait': 2}.get(_orient_val, 0)
        orientation = _r1[2].radio("用紙", _orient_opts, index=_orient_idx, key="np_orient",
                                   help="A3縦=A4横のちょうど2倍の高さ(297×420mm)。"
                                        "A4横2ページ分の内容が1枚に収まりやすく、"
                                        "セブンイレブン等のネットプリントでA3カラー印刷に"
                                        "対応した設定です(印刷料金は店舗により異なります)。")

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
                    return [c for c in ((v0 or {}).get('order') or [])
                            if c in _colpairs and c not in np_mod.HIDE_ON_PAPER]

                if _ordkey not in st.session_state:
                    _init = [c for c in custom_cols if c in _colpairs
                             and c not in np_mod.HIDE_ON_PAPER] or _app_display_cols()
                    st.session_state[_ordkey] = _init
                    for c in _colpairs:
                        st.session_state[_ck(c)] = (
                            c in _init and c not in np_mod.HIDE_ON_PAPER)
                else:
                    for c in _colpairs:
                        if _ck(c) not in st.session_state:
                            st.session_state[_ck(c)] = False
                    for c in np_mod.HIDE_ON_PAPER:
                        if c in _colpairs:
                            st.session_state[_ck(c)] = False

                _bc = st.columns(3)
                if _bc[0].button("↩️ アプリ表示列に戻す", key="np_ck_reset"):
                    _init = _app_display_cols()
                    for c in _colpairs:
                        st.session_state[_ck(c)] = (c in _init)
                    st.session_state[_ordkey] = _init
                if _bc[1].button("✅ 全選択", key="np_ck_all"):
                    for c in _colpairs:
                        st.session_state[_ck(c)] = c not in np_mod.HIDE_ON_PAPER
                    st.session_state[_ordkey] = [
                        c for c in _colpairs if c not in np_mod.HIDE_ON_PAPER]
                if _bc[2].button("🗑 全解除", key="np_ck_none"):
                    for c in _colpairs:
                        st.session_state[_ck(c)] = False
                    st.session_state[_ordkey] = []

                _grid = st.columns(3)
                _vis_i = 0
                for c, lb in _colpairs.items():
                    if c in np_mod.HIDE_ON_PAPER:
                        continue
                    with _grid[_vis_i % 3]:
                        st.checkbox(lb, key=_ck(c))
                    _vis_i += 1
                if any(c in _colpairs for c in np_mod.HIDE_ON_PAPER):
                    st.caption("「逆シ」は強適テーブル専用です。新聞の列には出しません。")

                # チェック順を再構成（既存チェック順を保ち、新規チェックは末尾へ）
                _prev = st.session_state.get(_ordkey, [])
                _sel_c = [c for c in _prev if c in _colpairs
                          and c not in np_mod.HIDE_ON_PAPER
                          and st.session_state.get(_ck(c))]
                for c in _colpairs:
                    if (c not in np_mod.HIDE_ON_PAPER
                            and st.session_state.get(_ck(c)) and c not in _sel_c):
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
        for _off in np_mod.HIDE_ON_PAPER:
            if _off in _colpairs and _off not in _excl_saved:
                _excl_saved.append(_off)
        if 'np_excl' in st.session_state:
            _ex_now = list(st.session_state.get('np_excl') or [])
            for _off in np_mod.HIDE_ON_PAPER:
                if _off in _colpairs and _off not in _ex_now:
                    _ex_now.append(_off)
            st.session_state['np_excl'] = _ex_now
        exclude_cols = st.multiselect(
            "除外する列（紙面に載せない列）", options=list(_colpairs.keys()),
            default=_excl_saved, format_func=lambda c: _colpairs.get(c, c), key="np_excl")
        st.caption("「逆シ」は強適テーブル専用です。列セットの選び方に関係なく新聞には載せません。")

        _has_nar = any(str(r).startswith('NAR') or
                       (len(str(r)) >= 6 and str(r)[4:6] > '10')
                       for r in sel_rids)
        _nar_tag = ' 🌟' if _has_nar else ''
        if _has_nar:
            st.info("🌟 地方競馬レースが含まれています。テーブル列が中央より少ないため、"
                    "🌟マークのセクションをONにすると紙面の情報量が増えます。")
        st.markdown("**セクション**")
        _s = st.columns(4)
        sec_cover = _s[0].checkbox("表紙(目次+凡例)", value=bool(prefs.get('sec_cover', True)), key="np_s_cover")
        sec_digest = _s[1].checkbox(f"📋レースダイジェスト(結論+展開+波乱度){_nar_tag}",
                                    value=bool(prefs.get('sec_digest', _has_nar)), key="np_s_digest",
                                    help="馬柱の前に本命◎/相手○/押さえ▲/穴を総合点つきで一覧表示。"
                                         "地方版では紙面の情報量を補います")
        sec_cv = _s[2].checkbox(f"合議カード(本命/相手/穴/切る){_nar_tag}",
                                value=bool(prefs.get('sec_cv', True)), key="np_s_cv")
        sec_gate = _s[3].checkbox("Gate判定バッジ(買い/見送り)",
                                  value=bool(prefs.get('sec_gate', True)), key="np_s_gate")
        _s2 = st.columns(4)
        sec_buy = _s2[0].checkbox("買い目メタ(点数/合成オッズ/残し馬)",
                                  value=bool(prefs.get('sec_buy', True)), key="np_s_buy")
        sec_hplus = _s2[1].checkbox(f"予想ヘッダー(荒れ予報/妙味度/軸候補/危険人気馬){_nar_tag}",
                                    value=bool(prefs.get('sec_hplus', True)), key="np_s_hplus")
        sec_bets = _s2[2].checkbox(f"おすすめ買い目(3連複/3連単/馬連馬単/ワイド){_nar_tag}",
                                   value=bool(prefs.get('sec_bets', True)), key="np_s_bets",
                                   help="SRAで各エンジンを開いた時の買い目を自動保存→紙面化。未生成のレースは非表示")
        sec_pace = _s2[3].checkbox("展開・隊列(直線到達想定+AI照合💀)",
                                   value=bool(prefs.get('sec_pace', True)), key="np_s_pace")
        _s2b = st.columns(4)
        sec_odds = _s2b[0].checkbox("オッズ動向(朝一↔直前)",
                                    value=bool(prefs.get('sec_odds', True)), key="np_s_odds",
                                    help="オッズ記録(📥/常駐ランナー)があるレースのみ表示")
        if sec_bets:
            st.caption("↳ おすすめ買い目の券種を選択")
            _bt = st.columns(5)
            bt_trio = _bt[0].checkbox("3連複", value=bool(prefs.get('bt_trio', True)),
                                      key="np_bt_trio")
            bt_trifecta = _bt[1].checkbox("3連単", value=bool(prefs.get('bt_trifecta', True)),
                                          key="np_bt_trifecta")
            bt_quinella = _bt[2].checkbox("馬連", value=bool(prefs.get('bt_quinella', True)),
                                          key="np_bt_quinella")
            bt_exacta = _bt[3].checkbox("馬単", value=bool(prefs.get('bt_exacta', True)),
                                        key="np_bt_exacta")
            bt_wide = _bt[4].checkbox("ワイド", value=bool(prefs.get('bt_wide', True)),
                                      key="np_bt_wide")
        else:
            bt_trio = bool(prefs.get('bt_trio', True))
            bt_trifecta = bool(prefs.get('bt_trifecta', True))
            bt_quinella = bool(prefs.get('bt_quinella', True))
            bt_exacta = bool(prefs.get('bt_exacta', True))
            bt_wide = bool(prefs.get('bt_wide', True))
        _s3 = st.columns(4)
        sec_elim = _s3[0].checkbox("消去フィルター(強適消去エンジンの消去馬+消去クロス+残し馬)",
                                   value=bool(prefs.get('sec_elim', True)), key="np_s_elim",
                                   help="🎯強適消去エンジンを実行したレースは、残し/ボーダー残し"
                                        "以外(消去された馬)の馬名も紙面に載ります。")
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
        sec_j5 = _s4[3].checkbox("🏇騎手係数込みスコア(黄金ライン/内訳/DB条件内訳)",
                                 value=bool(prefs.get('sec_j5', False)), key="np_s_j5",
                                 help="🏠SRAの『騎手係数込み 総合スコア』表を紙面に追加します。"
                                      "SRAでそのレースを解析した時の表示内容（騎手影響率スライダーの値ごと）"
                                      "をそのまま載せます。SRAで開いていないレースには出ません。")
        _s5 = st.columns(4)
        sec_devth = _s5[0].checkbox(f"🧠開発者の予想プロセス(思考の見える化){_nar_tag}",
                                    value=bool(prefs.get('sec_devth', True)), key="np_s_devth",
                                    help="①〜⑧の思考プロセス(何を根拠にどう判断したか)をそのまま紙面化。"
                                         "新しい予想を作るのではなく、上の合議カードと同じ結論に至った"
                                         "考え方の順番を見せるだけです。🏠SRAでそのレースを解析していないと"
                                         "出ません。")
        sec_ai_commentary = _s5[1].checkbox(f"🎭AIコメント欄(4-6人格・要API課金){_nar_tag}",
                                            value=bool(prefs.get('sec_ai_commentary', False)),
                                            key="np_s_aicom",
                                            help="合議結果(本命/相手/穴/消し)を4-6人格が解説する読み物欄。"
                                                 "新しい予想は作らず、既にある結論をなぞって説明するだけです。"
                                                 "ONにするとこの下に生成ボタンが出ます(生成にはAPI課金が"
                                                 "発生するため自動生成はしません)。")
        sec_value_zone = _s5[2].checkbox("📈複勝率×回収率マップ(ゾーン別)",
                                         value=bool(prefs.get('sec_value_zone', True)),
                                         key="np_s_vzone",
                                         help="🏠SRAの散布図(①勝ちゾーン等)をテーブル形式で紙面化。"
                                              "図ではなく表にすることでPDF生成コストを抑えています。"
                                              "🏠SRAでそのレースを解析していないと出ません。")
        sec_value_zone_chart = _s5[3].checkbox("📊ZONEシート散布図(図版・既定OFF)",
                                               value=bool(prefs.get('sec_value_zone_chart', False)),
                                               key="np_s_vzone_chart",
                                               help="複勝率×回収率マップと同じデータを図(散布図)で"
                                                    "追加表示します。紙面の末尾(余ったスペース)に"
                                                    "配置されますが、頭数が多いレースでは1ページ増える"
                                                    "ことがあります。コンビニ印刷は容量に関わらず"
                                                    "料金定額の場合が多いため、空きを活用したい時にON。")

        if sec_ai_commentary:
            with st.expander("🎭 AIコメント欄の生成", expanded=False):
                st.caption("収録レースぶんの合議結果を4-6人格に解説させます。"
                           "一度生成すればレースごとに保存され、次回以降は課金なしで再利用されます。")
                _com_est = None
                try:
                    from core import newspaper_commentary as _nc_est
                    _com_est = _nc_est.estimate_cost(len(sel_rids))
                except Exception:
                    pass
                if _com_est:
                    st.info(f"⚡ 呼び出し回数の目安: {_com_est['n_races']}R × "
                           f"{_com_est['n_personas']}人格 = **{_com_est['calls']}コール**"
                           "（実際の料金は使用量により変動します。生成済みレースはスキップされ"
                           "コールされません）")
                if st.button(f"🎭 {len(sel_rids)}R ぶんコメントを生成", key="np_gen_commentary",
                             disabled=not sel_rids):
                    import os as _os_com
                    from dotenv import load_dotenv as _ld_com
                    _ld_com(override=True)
                    _gk = _os_com.getenv("GEMINI_API_KEY")
                    if not _gk:
                        st.error("GEMINI_API_KEYが設定されていません(.env等を確認してください)。")
                    else:
                        from core import newspaper_commentary as _nc_gen
                        _ok, _skip, _fail = 0, 0, 0
                        _prog = st.progress(0.0)
                        for _i, _rid in enumerate(sel_rids, 1):
                            if _nc_gen.load_commentary(_rid):
                                _skip += 1
                            else:
                                try:
                                    _cm = _nc_gen.generate_commentary(_rid, _gk)
                                    if _cm:
                                        _nc_gen.write_commentary_snapshot(_rid, _cm)
                                        _ok += 1
                                    else:
                                        _fail += 1
                                except Exception:
                                    _fail += 1
                            _prog.progress(_i / max(len(sel_rids), 1))
                        st.success(f"生成完了: 新規{_ok}件 / 既存流用{_skip}件 / 失敗{_fail}件")
        footer_text = st.text_input("フッター注記（毎号入れる注意書き等）",
                                    value=prefs.get('footer_text',
                                                    '本紙は検証済みエッジの合議に基づく参考情報です。馬券の購入は自己責任で。'),
                                    key="np_footer")

        if st.button("💾 この設定を既定として保存", key="np_save_prefs"):
            ok = _save_prefs({
                'title': title, 'subtitle': subtitle,
                'orientation': _orientation_value(orientation),
                'font_pt': font_pt, 'scale': scale, 'cell_max': cell_max,
                'row_order': {'アプリ表示順(スコア順)': 'app', '馬番順': 'umaban', '人気順': 'pop'}[row_order],
                'col_mode': {'アプリの表示列(保存列順)': 'app', '全列': 'all', '軽量セット': 'lite',
                             'カスタム(チェック式)': 'custom'}[col_mode],
                'custom_cols': custom_cols,
                'page_per_race': page_per_race, 'keep_table': keep_table,
                'mono': mono, 'page_numbers': page_numbers,
                'exclude_cols': exclude_cols,
                'sec_cover': sec_cover, 'sec_digest': sec_digest,
                'sec_cv': sec_cv, 'sec_buy': sec_buy, 'sec_gate': sec_gate,
                'sec_hplus': sec_hplus, 'sec_bets': sec_bets, 'sec_pace': sec_pace,
                'sec_odds': sec_odds, 'sec_elim': sec_elim, 'sec_vh': sec_vh,
                'sec_evidence': sec_evidence, 'sec_pci': sec_pci,
                'sec_upset': sec_upset, 'sec_stress': sec_stress,
                'sec_alerts': sec_alerts, 'sec_j5': sec_j5, 'sec_devth': sec_devth,
                'sec_ai_commentary': sec_ai_commentary, 'sec_value_zone': sec_value_zone,
                'sec_value_zone_chart': sec_value_zone_chart,
                'bt_trio': bt_trio, 'bt_trifecta': bt_trifecta, 'bt_quinella': bt_quinella,
                'bt_exacta': bt_exacta, 'bt_wide': bt_wide,
                'footer_text': footer_text,
            })
            st.toast("設定を保存しました ✅" if ok else "保存に失敗しました ⚠️")

    # ────────────────── ③ 発行 ──────────────────
    st.subheader("③ 発行")
    opts = {
        'title': title, 'subtitle': subtitle,
        'orientation': _orientation_value(orientation),
        'scale': scale, 'font_pt': font_pt, 'cell_max': cell_max,
        'row_order': {'アプリ表示順(スコア順)': 'app', '馬番順': 'umaban', '人気順': 'pop'}[row_order],
        'col_mode': {'アプリの表示列(保存列順)': 'app', '全列': 'all', '軽量セット': 'lite',
                     'カスタム(チェック式)': 'custom'}[col_mode],
        'custom_cols': custom_cols,
        'exclude_cols': exclude_cols, 'page_per_race': page_per_race,
        'keep_table': keep_table, 'mono': mono,
        'page_numbers': page_numbers, 'footer_text': footer_text,
        'sections': {'cover': sec_cover, 'digest': sec_digest, 'consensus': sec_cv,
                     'buymeta': sec_buy, 'gate': sec_gate,
                     'header_plus': sec_hplus, 'bets': sec_bets, 'pace': sec_pace,
                     'odds_moves': sec_odds, 'elim': sec_elim, 'vh': sec_vh,
                     'evidence': sec_evidence, 'pci': sec_pci,
                     'pace_upset': sec_upset, 'stress': sec_stress,
                     'alerts': sec_alerts, 'j5': sec_j5, 'dev_thoughts': sec_devth,
                     'ai_commentary': sec_ai_commentary, 'value_zone': sec_value_zone,
                     'value_zone_chart': sec_value_zone_chart},
        'bet_types': {'trio': bt_trio, 'trifecta': bt_trifecta, 'quinella': bt_quinella,
                      'exacta': bt_exacta, 'wide': bt_wide},
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
                _pdf_fmt, _pdf_landscape = np_mod.resolve_page_format(opts['orientation'])
                out['pdf'] = np_mod.html_to_pdf(
                    html, landscape=_pdf_landscape, page_format=_pdf_fmt,
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

    # ────────────────── ⑤b 初心者競馬新聞（実験） ──────────────────
    st.divider()
    st.subheader("🔰 初心者競馬新聞（実験版）")
    st.caption("競馬初心者の方向けに、専門用語を減らして◎○▲☆の印と"
               "スコアバー・かんたん買い目ガイドで構成したシンプルな新聞です。"
               "上の①で選んだレースが対象になります。既存の強適競馬新聞とは別の紙面です。")

    _bg_c1, _bg_c2 = st.columns([2, 1])
    _bg_title = _bg_c1.text_input("新聞のタイトル", value="かんたん競馬新聞",
                                   key="bg_title")
    _bg_sub = _bg_c2.text_input("サブタイトル（空欄=今日の日付）", value="",
                                 key="bg_sub")

    if st.button(f"🔰 初心者新聞を発行する（{len(sel_rids)}R）", type="secondary",
                 disabled=not sel_rids, key="bg_publish"):
        with st.spinner("初心者向け紙面を組版中…"):
            bg_opts = {'title': _bg_title, 'subtitle': _bg_sub}
            bg_html, bg_issued = np_mod.build_beginner_newspaper_html(sel_rids, bg_opts)
            if not bg_html:
                st.error("紙面を作れませんでした（選択レースのデータが読めません）。")
            else:
                _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
                bg_out = {'html': bg_html, 'issued': bg_issued,
                          'fname': f"beginner_shimbun_{_ts}",
                          'pdf': None, 'pdf_err': None}
                try:
                    bg_out['pdf'] = np_mod.html_to_pdf(
                        bg_html, landscape=False, scale=1.0, page_numbers=True)
                except Exception as e:
                    bg_out['pdf_err'] = f"{type(e).__name__}: {e}"
                st.session_state['bg_out'] = bg_out

    bg_out = st.session_state.get('bg_out')
    if bg_out:
        if bg_out['pdf']:
            _bgm = st.columns(3)
            _bgm[0].metric("PDFサイズ", f"{len(bg_out['pdf']) / 1024:.0f} KB")
            _bgm[1].metric("ページ数", np_mod.pdf_page_count(bg_out['pdf']) or '—')
            _bgm[2].metric("収録レース", f"{len(bg_out['issued'])}R")
            _bgd1, _bgd2 = st.columns(2)
            _bgd1.download_button("📥 PDFをダウンロード", data=bg_out['pdf'],
                                  file_name=bg_out['fname'] + '.pdf', mime="application/pdf",
                                  type="primary", use_container_width=True, key="bg_dl_pdf")
            _bgd2.download_button("🌐 HTML版", data=bg_out['html'].encode('utf-8'),
                                  file_name=bg_out['fname'] + '.html', mime="text/html",
                                  use_container_width=True, key="bg_dl_html")
        else:
            st.error(f"PDF変換に失敗: {bg_out.get('pdf_err')}")
            st.download_button("🌐 HTML版をダウンロード", data=bg_out['html'].encode('utf-8'),
                               file_name=bg_out['fname'] + '.html', mime="text/html",
                               key="bg_dl_html2")
        with st.expander("👀 プレビュー", expanded=True):
            import streamlit.components.v1 as components
            components.html(bg_out['html'], height=640, scrolling=True)

    # ────────────────── ⑤c 地方競馬(NAR)新聞 ──────────────────
    st.divider()
    st.subheader("🏇 地方競馬(NAR)かんたん新聞")
    st.caption("地方競馬の出走表を keiba.go.jp から取得し、"
               "初心者向けの◎○▲☆印つき新聞を発行します。"
               "平日の地方開催に対応しています。")

    from core import nar_scraper as nar

    _nar_c1, _nar_c2 = st.columns([1, 1])
    _nar_date = _nar_c1.date_input(
        "開催日", value=datetime.date.today(), key="nar_date")
    _nar_date_str = _nar_date.strftime('%Y/%m/%d')

    if 'nar_venues' not in st.session_state:
        st.session_state['nar_venues'] = None
    if 'nar_fetched_rids' not in st.session_state:
        st.session_state['nar_fetched_rids'] = []

    if _nar_c2.button("🔍 開催場を検索", key="nar_search_venues"):
        with st.spinner("keiba.go.jp で開催場を検索中…"):
            nar.reset_session()
            venues = nar.fetch_today_venues(_nar_date_str)
            st.session_state['nar_venues'] = venues
            st.session_state['nar_fetched_rids'] = []

    _nar_venues = st.session_state.get('nar_venues')
    if _nar_venues:
        venue_labels = [f"{v['venue']}（{v['baba_code']}）" for v in _nar_venues]
        _sel_venues = st.multiselect(
            f"開催場を選択（{len(_nar_venues)}場開催）",
            options=range(len(_nar_venues)),
            default=list(range(len(_nar_venues))),
            format_func=lambda i: venue_labels[i],
            key="nar_sel_venues")

        _nar_mc1, _nar_mc2 = st.columns([1, 1])
        _nar_max_r = _nar_mc1.number_input(
            "取得レース数（場ごとの上限）", min_value=1, max_value=12,
            value=12, key="nar_max_races")
        _nar_mode = _nar_mc2.radio(
            "新聞の種類",
            options=["通常版（過去走つき表形式）", "初心者版（◎印+スコアバー）"],
            index=0, key="nar_mode", horizontal=True)
        _nar_is_full = _nar_mode.startswith("通常")

        if st.button(f"📥 出走表を取得して新聞データを作成",
                     type="secondary",
                     disabled=not _sel_venues, key="nar_fetch"):
            selected = [_nar_venues[i] for i in _sel_venues]
            # 騎手リーディングデータを自動取得(キャッシュ有効なら即返る)
            with st.spinner("騎手リーディングデータを確認中…"):
                try:
                    jstats = nar.fetch_nar_jockey_stats()
                    if jstats:
                        st.toast(f"騎手データ: {len(jstats)}人のリーディング情報を読み込み済み")
                except Exception:
                    pass
            nar.reset_session()
            fetched_rids = []
            _prog = st.progress(0, text="出走表を取得中…")
            total = len(selected) * _nar_max_r
            done = 0
            for vi, venue in enumerate(selected):
                races = nar.fetch_race_list(_nar_date_str, venue['baba_code'])
                if not races:
                    done += _nar_max_r
                    continue
                for r in races[:_nar_max_r]:
                    _prog.progress(
                        min(done / max(total, 1), 1.0),
                        text=f"{venue['venue']} R{r['race_no']} を取得中…")
                    entry = nar.fetch_entry_table(
                        _nar_date_str, venue['baba_code'], r['race_no'])
                    if entry:
                        rid = nar.save_nar_for_newspaper(entry,
                                                         full=_nar_is_full)
                        if rid:
                            fetched_rids.append(rid)
                    done += 1
            _prog.progress(1.0, text="完了")
            st.session_state['nar_fetched_rids'] = fetched_rids
            st.session_state['nar_is_full'] = _nar_is_full
            st.success(f"{len(fetched_rids)}レースの出走表を取得しました。")

    _nar_rids = st.session_state.get('nar_fetched_rids', [])
    if _nar_rids:
        _nar_sel = st.multiselect(
            f"新聞に収録するレース（{len(_nar_rids)}R取得済み）",
            options=_nar_rids,
            default=_nar_rids,
            key="nar_sel_rids")

        _nc1, _nc2 = st.columns([2, 1])
        _nar_full_saved = st.session_state.get('nar_is_full', False)
        _default_title = "地方競馬新聞" if _nar_full_saved else "地方競馬かんたん新聞"
        _nar_title = _nc1.text_input(
            "タイトル", value=_default_title, key="nar_title")
        _nar_sub = _nc2.text_input(
            "サブタイトル", value="", key="nar_sub")

        _btn_label = (f"🏇 NAR新聞を発行する（{len(_nar_sel)}R・"
                      f"{'通常版' if _nar_full_saved else '初心者版'}）")
        if st.button(_btn_label, type="primary",
                     disabled=not _nar_sel, key="nar_publish"):
            with st.spinner("地方競馬新聞を組版中…"):
                nar_opts = {'title': _nar_title, 'subtitle': _nar_sub}
                if _nar_full_saved:
                    nar_opts['orientation'] = 'landscape'
                    nar_html, nar_issued = np_mod.build_newspaper_html(
                        _nar_sel, nar_opts)
                else:
                    nar_html, nar_issued = np_mod.build_beginner_newspaper_html(
                        _nar_sel, nar_opts)
                if not nar_html:
                    st.error("紙面を作れませんでした。")
                else:
                    _ts = datetime.datetime.now().strftime('%Y%m%d_%H%M')
                    _is_landscape = _nar_full_saved
                    nar_out = {
                        'html': nar_html, 'issued': nar_issued,
                        'fname': f"nar_shimbun_{_ts}",
                        'pdf': None, 'pdf_err': None,
                    }
                    try:
                        nar_out['pdf'] = np_mod.html_to_pdf(
                            nar_html, landscape=_is_landscape,
                            scale=0.7 if _is_landscape else 1.0,
                            page_numbers=True)
                    except Exception as e:
                        nar_out['pdf_err'] = f"{type(e).__name__}: {e}"
                    st.session_state['nar_out'] = nar_out

    nar_out = st.session_state.get('nar_out')
    if nar_out:
        if nar_out['pdf']:
            _nm = st.columns(3)
            _nm[0].metric("PDFサイズ", f"{len(nar_out['pdf']) / 1024:.0f} KB")
            _nm[1].metric("ページ数",
                          np_mod.pdf_page_count(nar_out['pdf']) or '—')
            _nm[2].metric("収録レース", f"{len(nar_out['issued'])}R")
            _nd1, _nd2 = st.columns(2)
            _nd1.download_button(
                "📥 PDFをダウンロード", data=nar_out['pdf'],
                file_name=nar_out['fname'] + '.pdf',
                mime="application/pdf",
                type="primary", use_container_width=True, key="nar_dl_pdf")
            _nd2.download_button(
                "🌐 HTML版", data=nar_out['html'].encode('utf-8'),
                file_name=nar_out['fname'] + '.html',
                mime="text/html",
                use_container_width=True, key="nar_dl_html")
        else:
            st.error(f"PDF変換に失敗: {nar_out.get('pdf_err')}")
            st.download_button(
                "🌐 HTML版をダウンロード",
                data=nar_out['html'].encode('utf-8'),
                file_name=nar_out['fname'] + '.html',
                mime="text/html", key="nar_dl_html2")
        with st.expander("👀 プレビュー", expanded=True):
            import streamlit.components.v1 as components
            components.html(nar_out['html'], height=640, scrolling=True)

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

    # ────────────────── ⑦ 成績台帳 ──────────────────
    st.divider()
    _render_track_record(sel_rids, races)
