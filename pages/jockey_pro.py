# -*- coding: utf-8 -*-
"""🏇 騎手分析Pro — pages/jockey_pro.py (app.pyから抽出)"""
import os
import re
import math
import streamlit as st
import pandas as pd
import numpy as np
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 戦法モジュール(任意)はモジュールglobalsに置く: コード内の `'trainer_tactics' in globals()`
# ガードを成立させるため。失敗時は未定義のまま=機能オフ(クラッシュしない)。
try:
    from core import trainer_tactics
except Exception:
    pass
try:
    from core import jockey_tactics
except Exception:
    pass


def _detect_public():
    """app.py の _detect_public と同等(破壊的削除はapp.py側に任せ、ここは検出のみ)。"""
    _ev = os.environ.get('KEIBA_PUBLIC')
    if _ev is not None:
        return _ev not in ('0', '', 'false', 'False')
    _db = os.path.join(_ROOT, 'data', 'jravan.db')
    if not os.path.exists(_db):
        return True
    try:
        import sqlite3 as _s
        _c = _s.connect(f"file:{_db}?mode=ro", uri=True)
        _has = _c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='results'").fetchone()
        _c.close()
        return not bool(_has)
    except Exception:
        return False


_IS_PUBLIC = _detect_public()
_PUB_REPL = [('JRA-VAN版', '限定版'), ('JRA-VAN実データ', '内部データ'),
             ('JRA-VANで', '内部データで'), ('JRA-VAN/JRA', 'JRA'),
             ('JRA-VAN', ''), ('JV-VAN', ''), ('JV-Data', '公式データ'),
             ('jravan.db', '内部DB')]


def _pub(s):
    """公開(限定)版では JRA-VAN 等の表記を中立語へ置換。ローカルではそのまま返す。"""
    if not _IS_PUBLIC or not isinstance(s, str):
        return s
    for _a, _b in _PUB_REPL:
        s = s.replace(_a, _b)
    return s.replace('  ', ' ')


def render():
    """騎手分析Proページのレンダリング。app.pyから呼び出す。"""
    st.header("🏇 騎手分析Pro")
    st.caption("N指数不使用 — 回収率・連対率ベースのスクリーニングエンジン")

    # --- コア/ユーティリティインポート ---
    from core import jockey_analyzer
    from utils.jockey_stats_db import JockeyStatsDB
    from utils.jockey_screening import screen_entry, ScreeningResult
    from utils.jockey_bayesian import bayesian_adjusted_rate
    from utils.jockey_track_condition import fetch_track_conditions, get_condition_for_venue

    _jpro_db = JockeyStatsDB()

    # --- カスタムCSS ---
    st.markdown("""
    <style>
    .jockey-flag-teppan {
        background: linear-gradient(135deg, #DC3545 0%, #C82333 100%);
        color: white; padding: 4px 10px; border-radius: 12px;
        font-weight: bold; font-size: 0.85em; display: inline-block;
        box-shadow: 0 2px 4px rgba(220,53,69,0.3);
    }
    .jockey-flag-myomi {
        background: linear-gradient(135deg, #FFC107 0%, #E0A800 100%);
        color: #333; padding: 4px 10px; border-radius: 12px;
        font-weight: bold; font-size: 0.85em; display: inline-block;
        box-shadow: 0 2px 4px rgba(255,193,7,0.3);
    }
    .jockey-flag-kiken {
        background: linear-gradient(135deg, #0D6EFD 0%, #0B5ED7 100%);
        color: white; padding: 4px 10px; border-radius: 12px;
        font-weight: bold; font-size: 0.85em; display: inline-block;
        box-shadow: 0 2px 4px rgba(13,110,253,0.3);
    }
    .jockey-card {
        background: #1e1e2e; border: 1px solid #333; border-radius: 12px;
        padding: 16px 20px; margin: 8px 0;
        transition: all 0.2s ease;
    }
    .jockey-card:hover {
        border-color: #666; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .jockey-stat-grid {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 8px; margin-top: 8px;
    }
    .jockey-stat-item {
        background: #2a2a3a; border-radius: 8px; padding: 8px 12px;
        text-align: center;
    }
    .jockey-stat-val {
        font-size: 1.3em; font-weight: bold; color: #6fcf97;
    }
    .jockey-stat-label {
        font-size: 0.75em; color: #888; margin-top: 2px;
    }
    </style>
    """, unsafe_allow_html=True)

    # --- メインUI: 1ページ完結体験（出馬表ビューを先頭に） ---
    jpro_tabJV, jpro_tab3, jpro_tab1, jpro_tab2, jpro_tab4 = st.tabs([
        _pub("🔥 JRA-VAN版 (調子・コンビ・黄金ライン)"),
        "✅ 最強予想ビュー (One-Push)",
        "🔍 詳細データ (コンビ/脚質)",
        "🚦 フラグ手動入力",
        "⚙️ 設定・データ管理",
    ])

    # =============================================
    # タブ(新): JRA-VAN実データ版 — J1〜J5＋調子/連敗
    # =============================================
    with jpro_tabJV:
        from core import jockey_jv as _jj
        import sqlite3 as _jjsq
        st.caption(_pub("netkeibaスクレイピング不使用。jravan.db（30年・283万走）から騎手の実力・相性・調子を直接集計。"))

        # オッズ期待値テーブル（USM較正用）はレース横断で共通。セッションにキャッシュ。
        if '_jj_expected' not in st.session_state:
            with st.spinner("オッズ期待値テーブルを較正中（初回のみ）..."):
                st.session_state['_jj_expected'] = _jj.calibrate_odds_expectation()
        _jj_exp = st.session_state['_jj_expected']

        # ── 📉 連敗中の騎手ピックアップ（オンカジ的パターン・正直ラベル付き）──
        with st.expander("📉 連敗中の騎手ピックアップ（現在の連敗・勝ち間隔パターン）", expanded=True):
            st.markdown(
                "<div style='background:#3a1c1c;border-left:6px solid #e63946;border-radius:8px;"
                "padding:10px 14px;font-size:12px;color:#ffd9d9;'>"
                "⚠️ <b>重要</b>：283万走のバックテストで、<b>連続して勝てない/3着以内に入れない長さは、次走で『勝つ・3着以内に来る』確率を上げも下げもしませんでした</b>"
                "（オッズ補正後の残差が連続0〜10+で平坦〜微マイナス＝『そろそろ来る』はギャンブラーの誤謬）。"
                "下表は<b>参考・話のタネ</b>で予測指標ではありません。騎手で本当に効くのは『コース相性・黄金ライン・実力(USM)』です。</div>",
                unsafe_allow_html=True)
            if st.button("🔄 連敗ランキングを更新", key="jj_streak_refresh") or '_jj_streaks' not in st.session_state:
                with st.spinner("直近騎乗騎手の連敗を集計中..."):
                    st.session_state['_jj_streaks'] = _jj.losing_streak_leaders(top=15)
            _streaks = st.session_state.get('_jj_streaks', [])
            if _streaks:
                _sdf = pd.DataFrame([{
                    "騎手": s['name'], "現在の連敗(未勝利)": s['lose_streak'],
                    "連続圏外(3着内なし)": s['no_top3'],
                    "最後の勝ちから": f"{s['cur_dry']}走",
                    "平均勝ち間隔": f"{s['win_gap_avg']}走に1勝",
                    "due比(>1=平均より長く未勝利)": s['due_ratio'],
                    "直近20複勝率": f"{s['recent_top3']*100:.0f}%",
                } for s in _streaks])
                st.dataframe(_sdf, hide_index=True, use_container_width=True)
                st.caption("「平均◯走に1勝」＝最近のパターン。due比が大きいほど『平均より長く勝っていない』"
                           "（が、それで次に勝ちやすくなる訳ではない点に注意）。")

        # ── レース単位の騎手指標（jravan.db に取り込み済みの過去レース）──
        st.markdown("---")
        _jj_rid = st.text_input("レースIDを入力（jravan.db取り込み済みの過去レース）",
                                value=str(st.session_state.get('_jj_last_rid', '')),
                                key="jj_race_id", placeholder="例: 202509030411")
        if _jj_rid:
            st.session_state['_jj_last_rid'] = _jj_rid
            try:
                # os.path.exists ガード必須: connect はファイルが無いと空DBを作り IS_PUBLIC 判定を壊す
                if not os.path.exists('data/jravan.db'):
                    raise FileNotFoundError('jravan.db')
                _jc = _jjsq.connect('file:data/jravan.db?mode=ro', uri=True)
                _jrow = _jc.execute(
                    "SELECT race_key, jyo, kyori, surface, race_name FROM races WHERE race_id=?",
                    (_jj_rid,)).fetchone()
                _jentries = []
                if _jrow:
                    _jentries = _jc.execute(
                        "SELECT umaban, jockey_name, bamei, trainer_code, ketto_num, ninki, chakujun "
                        "FROM results WHERE race_key=? ORDER BY umaban", (_jrow[0],)).fetchall()
                _jc.close()
            except Exception as _je:
                _jrow, _jentries = None, []
                st.caption(f"DB参照エラー: {_je}")

            if not _jrow:
                st.info("このレースIDは jravan.db に未取り込みです（未来のレースや体験版の反映前）。"
                        "過去のレースIDでお試しください。連敗ピックアップは上の表で確認できます。")
            elif _jentries:
                _rk, _jyo, _kyori, _surf, _rname = _jrow
                _venue = _jj._venue_name(_jyo)
                st.markdown(f"**{_rname or ''} {_venue}{_surf}{_kyori}m**（{len(_jentries)}頭）"
                            "　騎手指標はこのレース直前までの実績で算出（リーク無し）")
                _jrows = []
                for um, jk, bamei, tr, ketto, ninki, chaku in _jentries:
                    base = _jj.jockey_base_stats(jk, venue=_venue, distance=_kyori, before_key=_rk)
                    ov = base['overall']; vstat = base['venue'] or {}
                    tcombo = _jj.jockey_trainer_combo(jk, tr, before_key=_rk)
                    hcombo = _jj.jockey_horse_combo(jk, ketto, before_key=_rk)
                    mom = _jj.momentum(jk, before_key=_rk)
                    fac = _jj.jockey_factor(jk, venue=_venue, distance=_kyori,
                                            trainer_code=tr, expected=_jj_exp, before_key=_rk)
                    usm = _jj.jockey_usm(jk, _jj_exp, before_key=_rk)
                    # 🥇🥇=連対40%以上(検証で勝ち+2pp/連対+3pp の最強)・🥇=30-40%
                    _gmark = ("🥇🥇" if tcombo['rides'] >= 15 and tcombo['top2'] >= 0.40
                              else "🥇" if tcombo['rides'] >= 15 and tcombo['top2'] >= 0.30 else "")
                    _gold = f"{tcombo['top2']*100:.0f}%/{tcombo['rides']}走{_gmark}"
                    _combo = (f"{hcombo['top3']*100:.0f}%/{hcombo['rides']}走" if hcombo['rides'] > 0 else "初")
                    _jrows.append({
                        "馬番": um, "騎手": jk, "馬": bamei, "人気": ninki,
                        "全体勝率": f"{ov['win']*100:.0f}%", "全体複勝": f"{ov['top3']*100:.0f}%",
                        f"{_venue}連対": f"{vstat.get('top2',0)*100:.0f}%/{vstat.get('rides',0)}走",
                        "黄金ライン(対調教師)": _gold,
                        "コンビ(この馬)": _combo,
                        "USM複勝(100=平均)": usm['top3_usm'] if usm['top3_usm'] else "-",
                        "騎手係数": fac['mult'],
                        "調子(連敗/hot)": f"連{mom.get('lose_streak','-')}/{mom.get('hot',0):+.2f}",
                        "_sort": fac['mult'],
                    })
                _jdf = pd.DataFrame(_jrows).sort_values('_sort', ascending=False).drop(columns=['_sort'])
                st.dataframe(_jdf, hide_index=True, use_container_width=True)
                st.caption("USM=人気(オッズ期待値)に対し実際の複勝率が何%か（100超=人気以上に走らせる＝騎手の実力）。"
                           "🥇🥇=黄金ライン最強(対調教師15走以上・連対40%以上＝検証で勝ち+2pp/連対+3pp人気以上)・🥇=30-40%。"
                           "騎手係数=検証で『人気以上に来る』と確認できたUSM・場相性・黄金ラインのみで構成"
                           "（連敗/調子は予測力ゼロのため不採用）。")

    # =============================================
    # タブ1: コンビネーション分析
    # =============================================
    with jpro_tab1:
        st.subheader("マルチ・コンビネーション評価")

        jpro_analysis_type = st.radio(
            "分析タイプ",
            ["騎手×馬（継続騎乗・乗り替わり）", "騎手×厩舎（黄金コンビ）", "騎手×コース×脚質"],
            horizontal=True,
            key="jpro_analysis_type",
        )

        # --- 騎手×馬 ---
        if jpro_analysis_type == "騎手×馬（継続騎乗・乗り替わり）":
            st.markdown("##### 継続騎乗ボーナス & 乗り替わり期待値")

            jockey_name_input = st.text_input("騎手名で検索", key="jpro_jockey_horse",
                                               placeholder="例: ルメール")

            if jockey_name_input:
                try:
                    df_horse = _jpro_db.query_by_jockey(jockey_name_input, target_type="horse")
                    if not df_horse.empty:
                        # ベイズ補正を適用
                        avgs = _jpro_db.get_global_averages()
                        prior_strength = st.session_state.get("jpro_prior_strength", 20)
                        df_horse["補正連対率"] = df_horse.apply(
                            lambda r: bayesian_adjusted_rate(
                                r["top2_rate"], r["ride_count"],
                                avgs["avg_top2_rate"], prior_strength
                            ), axis=1
                        )
                        df_horse = df_horse.sort_values("補正連対率", ascending=False)

                        display_cols = {
                            "jockey_name": "騎手", "target_name": "馬名",
                            "ride_count": "騎乗回数", "win_count": "勝利数",
                            "top2_count": "連対数", "win_rate": "勝率",
                            "top2_rate": "生連対率", "補正連対率": "補正連対率",
                            "return_win": "単回収(%)", "return_place": "複回収(%)",
                            "updated_at": "更新日",
                        }
                        cols_to_show = [c for c in display_cols.keys() if c in df_horse.columns]
                        df_show = df_horse[cols_to_show].rename(columns=display_cols)

                        # 連対率50%以上をハイライト
                        def _highlight_top2(row):
                            if row.get("補正連対率", 0) >= 0.50:
                                return ["background-color: #FFEAEA"] * len(row)
                            elif row.get("補正連対率", 0) >= 0.30:
                                return ["background-color: #FFF8E1"] * len(row)
                            return [""] * len(row)

                        st.dataframe(
                            df_show.style.apply(_highlight_top2, axis=1),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.caption(f"📊 {len(df_show)}件のデータ（ベイズ補正済み、事前強度={prior_strength}）")
                    else:
                        st.info(f"「{jockey_name_input}」のデータがDBにありません。⚙️設定タブからCSVインポートまたはDB初期化してください。")
                except Exception as e:
                    st.warning(f"DB検索エラー: {e}")
                    st.info("⚙️設定タブからDB初期化を実行してください。")

        # --- 騎手×厩舎 ---
        elif jpro_analysis_type == "騎手×厩舎（黄金コンビ）":
            st.markdown("##### 黄金コンビ抽出")
            st.caption("単勝回収率120%以上 & 最低騎乗回数を満たすコンビを「黄金コンビ 🥇」として強調")

            min_rides_trainer = st.slider("最低騎乗回数", 5, 50, 15, key="jpro_trainer_min_rides")

            try:
                df_trainer = _jpro_db.query_by_target("trainer", min_rides=min_rides_trainer)
                if not df_trainer.empty:
                    avgs = _jpro_db.get_global_averages()
                    prior_strength = st.session_state.get("jpro_prior_strength", 20)
                    df_trainer["補正連対率"] = df_trainer.apply(
                        lambda r: bayesian_adjusted_rate(
                            r["top2_rate"], r["ride_count"],
                            avgs["avg_top2_rate"], prior_strength
                        ), axis=1
                    )
                    df_trainer = df_trainer.sort_values("return_win", ascending=False)

                    # 黄金コンビフラグ
                    df_trainer["黄金"] = df_trainer["return_win"].apply(
                        lambda x: "🥇 黄金コンビ" if x >= 120 else ""
                    )

                    display_cols = {
                        "jockey_name": "騎手", "target_name": "厩舎",
                        "ride_count": "騎乗回数", "win_count": "勝利数",
                        "top2_rate": "連対率", "補正連対率": "補正連対率",
                        "return_win": "単回収(%)", "return_place": "複回収(%)",
                        "黄金": "判定",
                    }
                    cols_to_show = [c for c in display_cols.keys() if c in df_trainer.columns]
                    df_show = df_trainer[cols_to_show].rename(columns=display_cols)

                    # ヒートマップスタイル（連対率カラーリング）
                    def _color_top2_rate(val):
                        try:
                            v = float(val)
                            if v >= 0.50:
                                return "color: #D32F2F; font-weight: bold"
                            elif v >= 0.30:
                                return "color: #F57C00"
                            elif v < 0.10:
                                return "color: #9E9E9E"
                        except (ValueError, TypeError):
                            pass
                        return ""

                    styled = df_show.style
                    if "補正連対率" in df_show.columns:
                        styled = styled.map(_color_top2_rate, subset=["補正連対率"])

                    st.dataframe(styled, use_container_width=True, hide_index=True)
                    st.caption(f"📊 {len(df_show)}件（最低{min_rides_trainer}回騎乗、ベイズ補正済み）")
                else:
                    st.info("該当データがありません。⚙️設定タブからCSVインポートしてください。")
            except Exception as e:
                st.warning(f"DB検索エラー: {e}")
                st.info("⚙️設定タブからDB初期化を実行してください。")

        # --- 騎手×コース×脚質 ---
        elif jpro_analysis_type == "騎手×コース×脚質":
            st.markdown("##### コース適性 & 馬場状態別成績")

            # 馬場状態の自動取得（キャッシュ: session_state）
            if "jpro_track_conditions" not in st.session_state:
                st.session_state["jpro_track_conditions"] = []
            if st.button("🌤️ 本日の馬場を取得", key="jpro_fetch_track"):
                with st.spinner("馬場状態を取得中..."):
                    conditions = fetch_track_conditions()
                    st.session_state["jpro_track_conditions"] = conditions
                    if conditions:
                        for c in conditions:
                            st.caption(f"🏟️ {c.venue} {c.surface}: **{c.condition}** ({c.updated_at})")
                    else:
                        st.info("馬場データを自動取得できませんでした。手動で選択してください。")

            col1, col2, col3 = st.columns(3)
            with col1:
                course_options = [
                    "全体",
                    "東京芝1600", "東京芝2000", "東京芝2400", "東京ダ1600",
                    "中山芝2000", "中山芝2500", "中山ダ1200", "中山ダ1800",
                    "阪神芝1600", "阪神芝1800", "阪神芝2000", "阪神ダ1400",
                    "京都芝1600", "京都芝2000", "京都ダ1400", "京都ダ1800",
                    "中京芝2000", "中京ダ1800",
                    "新潟芝1600", "新潟芝2000",
                    "小倉芝1200", "小倉芝1800",
                    "札幌芝1800", "函館芝1200", "福島芝1800",
                ]
                course_select = st.selectbox("コース", course_options, key="jpro_course")
            with col2:
                style_select = st.selectbox("脚質", ["全体", "逃げ", "先行", "差し", "追込"], key="jpro_style")
            with col3:
                # 馬場自動取得結果をデフォルト値に反映
                track_options = ["全体", "良", "稍重", "重", "不良"]
                auto_idx = 0
                _tc = st.session_state.get("jpro_track_conditions", [])
                if _tc and course_select != "全体":
                    # コースから会場名を抽出（先頭2文字）
                    _venue_hint = course_select[:2] if len(course_select) >= 2 else ""
                    _auto_cond = get_condition_for_venue(_tc, _venue_hint)
                    if _auto_cond and _auto_cond in track_options:
                        auto_idx = track_options.index(_auto_cond)
                track_select = st.selectbox("馬場", track_options, index=auto_idx, key="jpro_track")

            try:
                target_name = None if course_select == "全体" else course_select
                df_course = _jpro_db.query_by_target("course", target_name=target_name)

                if not df_course.empty:
                    # 脚質フィルタ
                    if style_select != "全体":
                        df_course = df_course[df_course["running_style"] == style_select]
                    # 馬場フィルタ
                    if track_select != "全体":
                        df_course = df_course[df_course["track_condition"] == track_select]

                    if not df_course.empty:
                        avgs = _jpro_db.get_global_averages()
                        prior_strength = st.session_state.get("jpro_prior_strength", 20)
                        df_course["補正連対率"] = df_course.apply(
                            lambda r: bayesian_adjusted_rate(
                                r["top2_rate"], r["ride_count"],
                                avgs["avg_top2_rate"], prior_strength
                            ), axis=1
                        )
                        df_course = df_course.sort_values("補正連対率", ascending=False)

                        display_cols = {
                            "jockey_name": "騎手", "target_name": "コース",
                            "ride_count": "騎乗回数", "win_count": "勝利数",
                            "top2_rate": "連対率", "補正連対率": "補正連対率",
                            "return_win": "単回収(%)", "return_place": "複回収(%)",
                            "running_style": "脚質", "track_condition": "馬場",
                        }
                        cols_to_show = [c for c in display_cols.keys() if c in df_course.columns]
                        df_show = df_course[cols_to_show].rename(columns=display_cols)

                        st.dataframe(df_show, use_container_width=True, hide_index=True)
                        st.caption(f"📊 {len(df_show)}件（ベイズ補正済み）")
                    else:
                        st.info("フィルタ条件に合致するデータがありません。")
                else:
                    st.info("該当データがありません。⚙️設定タブからCSVインポートしてください。")
            except Exception as e:
                st.warning(f"DB検索エラー: {e}")
                st.info("⚙️設定タブからDB初期化を実行してください。")


    # =============================================
    # タブ2: スクリーニング
    # =============================================
    with jpro_tab2:
        st.subheader("🚦 フラグ自動判定")

        st.markdown("""
        | フラグ | 条件 | 意味 |
        |:---:|---|---|
        | 🔴 鉄板 | コースまたは厩舎の連対率≧40% & 騎乗30回以上 | 高確率で馬券に絡む軸候補 |
        | 🟡 妙味 | コースまたは厩舎の単回収≧120% & 騎乗15回以上 | 人気薄だが一発あり |
        | 🔵 危険 | 1〜3番人気 & コース連対率＜15% | 過剰人気の飛び候補 |
        """)

        st.markdown("---")

        # === 手動入力フォーム ===
        st.markdown("##### レースデータ入力")

        num_horses = st.number_input("出走頭数", 2, 18, 12, key="jpro_num_horses")

        # 閾値をsession_stateから取得（設定タブで変更可能）
        _iron_th = st.session_state.get("jpro_iron_threshold", 40) / 100.0
        _iron_rides = st.session_state.get("jpro_iron_min_rides", 30)
        _value_th = st.session_state.get("jpro_value_threshold", 120)
        _value_rides = st.session_state.get("jpro_value_min_rides", 15)
        _danger_th = st.session_state.get("jpro_danger_threshold", 15) / 100.0

        _custom_thresholds = {
            "iron_top2_rate": _iron_th,
            "iron_min_rides": _iron_rides,
            "value_return_win": float(_value_th),
            "value_min_rides": _value_rides,
            "danger_top2_rate": _danger_th,
            "danger_min_rides": 10,
            "danger_max_popularity": 3,
        }

        entries = []
        for i in range(int(num_horses)):
            with st.expander(f"馬番{i+1}", expanded=(i < 3)):
                cols = st.columns([2, 2, 1, 1, 1, 1, 1])
                horse = cols[0].text_input("馬名", key=f"jpro_scr_horse_{i}")
                jockey = cols[1].text_input("騎手", key=f"jpro_scr_jockey_{i}")
                pop = cols[2].number_input("人気", 0, 18, 0, key=f"jpro_scr_pop_{i}", help="0=未定")
                c_top2 = cols[3].number_input("コース連対%", 0.0, 100.0, 0.0, key=f"jpro_scr_ctop2_{i}")
                c_rides = cols[4].number_input("コース回数", 0, 999, 0, key=f"jpro_scr_crides_{i}")
                c_ret = cols[5].number_input("コース単回収%", 0.0, 500.0, 0.0, key=f"jpro_scr_cret_{i}")
                t_top2 = cols[6].number_input("厩舎連対%", 0.0, 100.0, 0.0, key=f"jpro_scr_ttop2_{i}")

                # 厩舎の追加入力
                cols2 = st.columns([1, 1])
                t_rides = cols2[0].number_input("厩舎回数", 0, 999, 0, key=f"jpro_scr_trides_{i}")
                t_ret = cols2[1].number_input("厩舎単回収%", 0.0, 500.0, 0.0, key=f"jpro_scr_tret_{i}")

                entries.append({
                    "馬番": i + 1,
                    "馬名": horse,
                    "騎手": jockey,
                    "人気": pop if pop > 0 else None,
                    "c_top2": c_top2 / 100,
                    "c_rides": c_rides,
                    "c_ret": c_ret,
                    "t_top2": t_top2 / 100,
                    "t_rides": t_rides,
                    "t_ret": t_ret,
                })

        if st.button("🚦 スクリーニング実行", key="jpro_run_screen", type="primary"):
            results = []
            for e in entries:
                if not e["馬名"]:
                    continue
                r = screen_entry(
                    jockey_course_top2_rate=e["c_top2"],
                    jockey_course_ride_count=e["c_rides"],
                    jockey_course_return_win=e["c_ret"],
                    jockey_trainer_top2_rate=e["t_top2"],
                    jockey_trainer_ride_count=e["t_rides"],
                    jockey_trainer_return_win=e["t_ret"],
                    popularity=e["人気"],
                    thresholds=_custom_thresholds,
                )
                results.append({
                    "馬番": e["馬番"],
                    "馬名": e["馬名"],
                    "騎手": e["騎手"],
                    "判定": r.label,
                    "理由": r.reason,
                })

            df_result = pd.DataFrame(results)
            st.session_state["jpro_screening_result"] = df_result

            # 色付き表示
            def highlight_flag(row):
                if "🔴" in str(row["判定"]):
                    return ["background-color: #FFEAEA"] * len(row)
                elif "🟡" in str(row["判定"]):
                    return ["background-color: #FFF8E1"] * len(row)
                elif "🔵" in str(row["判定"]):
                    return ["background-color: #E3F2FD"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_result.style.apply(highlight_flag, axis=1),
                use_container_width=True,
                hide_index=True,
            )

    # =============================================
    # タブ3: 出馬表ビュー (Jockey Ranking Table)
    # =============================================
    with jpro_tab3:
        st.markdown("### 🏇 騎手ランキング — レースID一発分析")
        st.caption("レースIDを1回入力するだけで、全騎手の全指標を取得・スコア化してランキング表示します。")

        # ── レースID入力 ──
        jp3_col1, jp3_col2 = st.columns([3, 1])
        with jp3_col1:
            jp_race_input = st.text_input(
                "レースID または URL",
                placeholder="例: 202505021211 または https://race.netkeiba.com/race/shutuba.html?race_id=...",
                value=st.session_state.get("main_race_id_input", ""),
                key="jp_race_input",
            )
        with jp3_col2:
            st.write("")
            jp_analyze_btn = st.button("🏇 分析開始", type="primary", key="jp_analyze_btn", use_container_width=True)

        jp_race_id = ""
        if jp_race_input:
            _m = re.search(r'(\d{12})', jp_race_input)
            if _m:
                jp_race_id = _m.group(1)

        if 'jp_analysis_result' not in st.session_state:
            st.session_state.jp_analysis_result = None

        # ── 💡 騎手分析Pro：総合スコア影響率（ウェイト）設定 ──
        _WEIGHTS_FILE_JOCKEY = os.path.join(_ROOT, ".score_weights_jockey.json")
        _jockey_weight_defaults = {
            "調子P": 0.0, "単回収%": 0.0, "人気": 0.0, "オッズ": 0.0,
            "PW指数": 0.0, "単勝USM": 0.0, "連対USM": 0.0, "複勝USM": 0.0,
            "フラグボーナス": 50.0,
            "騎乗数": 0.0
        }
        if 'score_weights_jockey' not in st.session_state:
            if os.path.exists(_WEIGHTS_FILE_JOCKEY):
                try:
                    import json as _json
                    with open(_WEIGHTS_FILE_JOCKEY, 'r', encoding='utf-8') as _wf:
                        _loaded = _json.load(_wf)
                    st.session_state['score_weights_jockey'] = {**_jockey_weight_defaults, **_loaded}
                except Exception:
                    st.session_state['score_weights_jockey'] = _jockey_weight_defaults.copy()
            else:
                st.session_state['score_weights_jockey'] = _jockey_weight_defaults.copy()

        sw_jockey = st.session_state['score_weights_jockey']
        for k, v in _jockey_weight_defaults.items():
            if k not in sw_jockey: sw_jockey[k] = v

        with st.expander("📊 騎手分析Pro：総合スコア影響率（ウェイト）設定", expanded=False):
            st.caption("各指標の生の値に、設定した影響率ウェイト（乗数）を乗算して総合スコアに加算します。フラグボーナス値は「妙味」「危険」フラグ時のポイント加算値です。")
            j_col1, j_col2 = st.columns(2)

            _J_WEIGHTS_CONFIG = [
                ("📈 調子Pウェイト", "調子P", "調子ポイント(好不調)の乗数ウェイト。", 0.0, 100.0, 0.01),
                ("💰 単回収%ウェイト", "単回収%", "コース単勝回収率(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("👥 人気ウェイト", "人気", "人気値(1〜18、1人気ほど高得点化)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("オッズウェイト", "オッズ", "オッズ値(1.0〜150.0)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥋 PW指数ウェイト", "PW指数", "PW指数(0〜150程度、/10)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🎯 単勝USMウェイト", "単勝USM", "単勝USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥈 連対USMウェイト", "連対USM", "連対USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🥉 複勝USMウェイト", "複勝USM", "複勝USM(割合換算)の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🏇 騎乗数ウェイト", "騎乗数", "騎乗数の乗数ウェイト。", 0.0, 10.0, 0.01),
                ("🚩 フラグボーナス値", "フラグボーナス", "「妙味」や「危険」フラグがついた際に、総合スコアに加算するポイントボーナス。", 0.0, 100.0, 1.0)
            ]

            def _sync_slider_jockey(sld_key, num_key):
                st.session_state[num_key] = st.session_state[sld_key]
            def _sync_num_jockey(num_key, sld_key):
                st.session_state[sld_key] = st.session_state[num_key]

            for _i, (label, sw_key, help_text, min_v, max_v, step_v) in enumerate(_J_WEIGHTS_CONFIG):
                sld_key = f"wsld_jockey_{sw_key}"
                num_key = f"wnum_jockey_{sw_key}"
                cur_v = float(sw_jockey.get(sw_key, 50.0 if sw_key == "フラグボーナス" else 0.0))

                cur_v = max(min_v, min(max_v, cur_v))

                if sld_key not in st.session_state: st.session_state[sld_key] = cur_v
                if num_key not in st.session_state: st.session_state[num_key] = cur_v

                target_col = j_col1 if _i % 2 == 0 else j_col2
                with target_col:
                    c_sld, c_num = st.columns([3, 1])
                    with c_sld:
                        st.slider(label, min_v, max_v, step=step_v, key=sld_key, 
                                  help=help_text, on_change=lambda sk=sld_key, nk=num_key: _sync_slider_jockey(sk, nk))
                    with c_num:
                        st.write("")
                        st.number_input("", min_v, max_v, step=step_v, key=num_key, label_visibility="collapsed",
                                        on_change=lambda nk=num_key, sk=sld_key: _sync_num_jockey(nk, sk))

                    sw_jockey[sw_key] = float(st.session_state.get(num_key, cur_v))

            st.session_state['score_weights_jockey'] = sw_jockey

            jb_col1, jb_col2 = st.columns(2)
            with jb_col1:
                if st.button("💾 影響率を保存（全ランキングに適用）", key="btn_save_weights_jockey"):
                    try:
                        import json as _json
                        with open(_WEIGHTS_FILE_JOCKEY, 'w', encoding='utf-8') as _wf:
                            _json.dump(sw_jockey, _wf, ensure_ascii=False, indent=2)
                        st.success("✅ 騎手分析影響率を保存しました。")
                    except Exception as _e:
                        st.error(f"保存失敗: {_e}")
            with jb_col2:
                st.caption("💡 スライダーを動かすと、リアルタイムに下のランキングが再計算されます。")

        # ── 分析実行 ──
        if jp_analyze_btn and jp_race_id:


            _jp_pb = st.progress(0)
            _jp_st = st.empty()

            def jp_progress(current, total, msg):
                if total > 0:
                    _jp_pb.progress(min(1.0, current / total))
                _jp_st.caption(msg)

            with st.spinner("騎手データを収集中... (しばらくお待ちください)"):
                try:
                    _jp_result = jockey_analyzer.analyze_race(jp_race_id, progress_callback=jp_progress)
                    st.session_state.jp_analysis_result = _jp_result
                except Exception as _e:
                    st.error(f"分析エラー: {_e}")
                    import traceback
                    st.code(traceback.format_exc())

            _jp_pb.empty()
            _jp_st.empty()

        elif jp_analyze_btn and not jp_race_id:
            st.warning("有効なレースID（12桁の数字）を入力してください。")

        # ── 結果表示 ──
        _jp_res = st.session_state.get('jp_analysis_result')
        if _jp_res and _jp_res.get('entries'):


            _jp_venue = _jp_res.get('venue', '')
            _jp_entries = _jp_res.get('entries', [])

            st.success(f"✅ {_jp_venue}  {len(_jp_entries)}頭の分析完了")


            # ── スコアリング（全指標を集計） ──
            def _compute_full_score(entry, venue, weights=None):
                """全取得可能指標を合計してスコア化"""
                vs  = entry.get('venue_stats') or {}
                pr  = entry.get('jockey_profile') or {}
                ys  = pr.get('year_stats') or {}
                flg = entry.get('flags', [])
                score = 0.0
                breakdown = {}

                # 1) コース連対率 (補正済) — 最大配点40
                v_top2 = vs.get('adj_top2_rate', 0)
                s1 = v_top2 * 200
                score += s1
                breakdown['コース連対率'] = round(s1, 1)

                # 2) 本年勝率 — 最大配点30
                y_win = ys.get('win_rate', 0)
                s2 = y_win * 300
                score += s2
                breakdown['本年勝率'] = round(s2, 1)

                # 3) 本年連対率 — 最大配点20
                y_top2 = ys.get('top2_rate', 0)
                s3 = y_top2 * 100
                score += s3
                breakdown['本年連対率'] = round(s3, 1)

                # 4) 単回収率（コース）— 超過分のみ加点
                win_ret = vs.get('adj_win_return', 80)
                s4 = max(0, (win_ret - 80)) * 0.5
                score += s4
                breakdown['単回収率超過'] = round(s4, 1)

                # 5) 騎乗経験（コース）— ログスケール
                rides = vs.get('rides', 0)
                s5 = math.log10(rides + 1) * 8
                score += s5
                breakdown['コース騎乗経験'] = round(s5, 1)

                # 6) 通算騎乗数（信頼度）
                total_rides = ys.get('total', 0)
                s6 = math.log10(total_rides + 1) * 5
                score += s6
                breakdown['通算経験'] = round(s6, 1)

                # 7) コース複勝率（3着以内率）— 純粋な実力指標
                v_top3 = vs.get('top3_rate', 0)
                s7 = v_top3 * 80
                score += s7
                breakdown['コース複勝率'] = round(s7, 1)

                # 8) 本年複勝率
                y_top3 = ys.get('top3_rate', 0)
                s8 = y_top3 * 60
                score += s8
                breakdown['本年複勝率'] = round(s8, 1)

                # 9) PW指数 — 0~999の整数値想定、100点で最大10点加算
                pw_idx = entry.get('pw_index')
                if pw_idx is not None:
                    try:
                        s9 = float(pw_idx) * 0.1
                        score += s9
                        breakdown['PW指数'] = round(s9, 1)
                    except (TypeError, ValueError):
                        pass

                # 10) db-keiba ボーナス/減点（今レースにマッチした条件のみ加算）
                bonuses = entry.get('bonuses') or {}
                s10_add = bonuses.get('matched_bonus_score', 0.0)
                s10_sub = bonuses.get('matched_penalty_score', 0.0)  # 既に負値
                if s10_add != 0:
                    score += s10_add
                    breakdown['加算ボーナス'] = round(s10_add, 1)
                if s10_sub != 0:
                    score += s10_sub
                    breakdown['減点ペナルティ'] = round(s10_sub, 1)

                # 11) PRB (Percentage of Rivals Beaten) — 0.5が平均、高いほど良い
                _madv = entry.get('matched_adv') or {}
                prb_val = _madv.get('prb_overall', 0.5)
                s11 = (prb_val - 0.5) * 80
                if abs(s11) > 0.5:
                    score += s11
                    breakdown['PRB'] = round(s11, 1)

                # 12) Hot/Cold — 直近好調なら加点、不調なら減点
                hc = _madv.get('hot_cold', '—')
                if hc == 'HOT':
                    score += 10
                    breakdown['好調'] = 10
                elif hc == 'COLD':
                    score -= 8
                    breakdown['不調'] = -8

                # 13) 調子P（Jockey Form Score）
                form_score = entry.get('advanced_stats', {}).get('form_score', 0.0)
                if form_score != 0:
                    s13 = max(-15.0, min(15.0, form_score * 0.3))
                    score += s13
                    breakdown['調子P'] = round(s13, 1)

                # ── 🧠 人間変数＆作戦連携加減点（騎手分析Pro特別アップグレード） ──
                adv = entry.get('advanced_stats') or {}
                pos_skill = adv.get('pos_skill', 50.0)
                drive_power = adv.get('drive_power', 0.0)
                clutch_score = adv.get('clutch_score', 50.0)
                gate_adapt = adv.get('gate_adapt', 50.0)

                # 14) 位置取り力（ポジション奪取力）の実力加減点
                s14 = (pos_skill - 50.0) * 0.1
                if abs(s14) > 0.1:
                    score += s14
                    breakdown['位置取り力'] = round(s14, 1)

                # 15) 剛腕追い上げ数（差し馬との連携）
                r_style = _madv.get('riding_style', '—')
                s15 = drive_power * 0.5
                if r_style in ['差し・追込', '中団']:
                    s15 = s15 * 1.5  # 差し馬に乗る際は追い上げ力が1.5倍に生きる
                s15 = min(s15, 10.0) # 最大でも10点の加点に抑える
                if abs(s15) > 0.1:
                    score += s15
                    breakdown['剛腕追い上げ'] = round(s15, 1)

                # 16) プレッシャー耐性（人気との連携）
                try:
                    pop_val = int(entry.get('popularity', 99))
                    if pop_val <= 3:  # 上位人気のときにプレッシャー耐性が生きる
                        s16 = (clutch_score - 50.0) * 0.1
                        if abs(s16) > 0.1:
                            score += s16
                            breakdown['プレ耐性'] = round(s16, 1)
                except:
                    pass

                # 17) 外枠克服力（馬番・枠順との連携）
                try:
                    umaban_val = int(entry.get('umaban', 0))
                    if umaban_val >= 10:  # 外枠のときに外枠克服力が生きる
                        s17 = (gate_adapt - 50.0) * 0.1
                        if abs(s17) > 0.1:
                            score += s17
                            breakdown['外枠克服'] = round(s17, 1)
                except:
                    pass

                # 18) 専門家脚質作戦完全一致ボーナス（厩舎×騎手×馬）
                t_name = entry.get('trainer_name', '')
                j_name = entry.get('jockey_name', '')
                t_tac = trainer_tactics.get_trainer_tactics(t_name) if 'trainer_tactics' in globals() else None
                j_tac = jockey_tactics.get_jockey_tactics(j_name) if 'jockey_tactics' in globals() else None

                if t_tac or j_tac:
                    s18_t = 0.0
                    s18_j = 0.0
                    if r_style in ['逃げ・番手', '先行']:
                        if t_tac:
                            t_front = t_tac.get('逃げ', 0) + t_tac.get('先行', 0)
                            s18_t = (t_front - 35.0) * 0.25  # 35%を基準平均とする
                        if j_tac:
                            j_front = j_tac.get('逃げ', 0) + j_tac.get('先行', 0)
                            s18_j = (j_front - 35.0) * 0.25
                    elif r_style in ['差し・追込', '中団']:
                        if t_tac:
                            t_back = t_tac.get('中団', 0) + t_tac.get('後方', 0) + t_tac.get('マクリ', 0)
                            s18_t = (t_back - 65.0) * 0.25  # 65%を基準平均とする
                        if j_tac:
                            j_back = j_tac.get('中団', 0) + j_tac.get('後方', 0) + j_tac.get('マクリ', 0)
                            s18_j = (j_back - 65.0) * 0.25

                    s18 = s18_t + s18_j
                    if abs(s18) > 0.1:
                        score += s18
                        breakdown['作戦一致'] = round(s18, 1)

                # ── 👑 [NEW] 影響率（ウェイト）の加算 ──
                if weights:
                    # 1) 調子P
                    form_score_val = float(entry.get('advanced_stats', {}).get('form_score', 0.0))
                    score += form_score_val * weights.get('調子P', 0.0)

                    # 2) 単回収% (割合換算)
                    win_ret_val = float(vs.get('adj_win_return', 0))
                    score += (win_ret_val / 100.0) * weights.get('単回収%', 0.0)

                    # 3) 人気 (1人気ほど加点)
                    pop = entry.get('popularity', 99)
                    if pop < 99:
                        score += (19.0 - float(pop)) * weights.get('人気', 0.0)

                    # 4) オッズ (大穴加点、そのまま乗算)
                    odds = float(entry.get('odds', 0.0))
                    score += odds * weights.get('オッズ', 0.0)

                    # 5) PW指数 (/10でベーススケール調整)
                    pw_idx_val = entry.get('pw_index')
                    if pw_idx_val is not None:
                        try:
                            score += (float(pw_idx_val) / 10.0) * weights.get('PW指数', 0.0)
                        except (TypeError, ValueError):
                            pass

                    # 6) 単勝USM, 7) 連対USM, 8) 複勝USM (割合換算)
                    usm_data = entry.get('advanced_stats', {}).get('usm', {})
                    win_usm = usm_data.get('win_usm')
                    top2_usm = usm_data.get('top2_usm')
                    top3_usm = usm_data.get('top3_usm')

                    if isinstance(win_usm, int):
                        score += (win_usm / 100.0) * weights.get('単勝USM', 0.0)
                    if isinstance(top2_usm, int):
                        score += (top2_usm / 100.0) * weights.get('連対USM', 0.0)
                    if isinstance(top3_usm, int):
                        score += (top3_usm / 100.0) * weights.get('複勝USM', 0.0)

                    # 9) 騎乗数
                    _rides_val = float(vs.get('rides', 0))
                    score += _rides_val * weights.get('騎乗数', 0.0)

                # ── 👑 [NEW] フラグボーナス (妙味・危険) ──
                # 妙味または危険フラグがつくと、総合スコアにユーザー設定のボーナスポイントを加算する
                _flg_list = entry.get('flags', [])
                _bonus_v = weights.get('フラグボーナス', 50.0) if weights else 50.0
                _flag_bonus = 0.0
                for _f in _flg_list:
                    if "妙味" in _f or "危険" in _f:
                        _flag_bonus += _bonus_v
                if _flag_bonus > 0:
                    score += _flag_bonus
                    breakdown['フラグボーナス'] = _flag_bonus

                return round(score, 1), breakdown

            # 各エントリのスコアを計算
            scored = []
            for _e in _jp_entries:
                _sc, _bd = _compute_full_score(_e, _jp_venue, weights=sw_jockey)
                _vs = _e.get('venue_stats') or {}
                _pr = _e.get('jockey_profile') or {}
                _ys = _pr.get('year_stats') or {}
                _flg = _e.get('flags', [])
                _madv = _e.get('matched_adv') or {}
                _adv_full = _e.get('advanced_stats') or {}
                _prb = _madv.get('prb_overall', 0.5)
                _hc = _madv.get('hot_cold', '—')
                _hc_icon = {'HOT': '🔥', 'COLD': '🧊'}.get(_hc, '')
                _rstyle = _madv.get('riding_style', '—')
                _usm = _adv_full.get('usm', {})
                _win_usm = _usm.get('win_usm', '-')
                _top2_usm = _usm.get('top2_usm', '-')
                _top3_usm = _usm.get('top3_usm', '-')

                # フラグ表示のアップデート (妙味/危険があれば+50.0ボーナス内訳を付記)
                _flag_bonus_val = _bd.get('フラグボーナス', 0.0)
                _flag_str = " ".join(_flg) if _flg else "—"
                if _flag_bonus_val > 0:
                    _flag_display = f"{_flag_str} (+{_flag_bonus_val:.1f})"
                else:
                    _flag_display = _flag_str

                # 加減点表示のアップデート (フラグボーナス内訳をわかりやすく付記)
                _bonuses = _e.get('bonuses') or {}
                _b_score = _bonuses.get('matched_bonus_score', 0.0)
                _p_score = _bonuses.get('matched_penalty_score', 0.0)

                _kagenten_str = '—'
                if _b_score != 0 or _p_score != 0:
                    _kagenten_str = f"+{_b_score:.1f} / {_p_score:.1f}"
                if _flag_bonus_val > 0:
                    if _kagenten_str == '—':
                        _kagenten_str = f"フラグ加点: +{_flag_bonus_val:.1f}"
                    else:
                        _kagenten_str += f" (フラグ: +{_flag_bonus_val:.1f})"

                scored.append({
                    '_umaban': _e.get('umaban', 0),
                    '_score': _sc,
                    '_breakdown': _bd,
                    '順位': 0,
                    '評価': '',
                    '馬番': _e.get('umaban', ''),
                    '馬名': _e.get('horse_name', ''),
                    '騎手': _e.get('jockey_name', ''),
                    '厩舎': _e.get('trainer_name', ''),
                    '人気': _e.get('popularity', 99) if _e.get('popularity', 99) < 99 else '—',
                    'オッズ': f"{_e.get('odds', 0):.1f}" if _e.get('odds', 0) > 0 else '—',
                    '調子P': f"{_adv_full.get('form_score', 0.0):.1f}",
                    'PRB': f"{_prb:.1f}",
                    '調子': f"{_hc_icon}{_hc}" if _hc != '—' else '—',
                    '脚質傾向': _rstyle,
                    '単勝USM': f"{float(_win_usm):.1f}%" if isinstance(_win_usm, int) else "-",
                    '連対USM': f"{float(_top2_usm):.1f}%" if isinstance(_top2_usm, int) else "-",
                    '複勝USM': f"{float(_top3_usm):.1f}%" if isinstance(_top3_usm, int) else "-",
                    'コース連対%': f"{_vs.get('adj_top2_rate', 0)*100:.1f}",
                    'コース複勝%': f"{_vs.get('top3_rate', 0)*100:.1f}",
                    '単回収%': f"{float(_vs.get('adj_win_return', 0)):.1f}",
                    '騎乗数': _vs.get('rides', 0),
                    '本年勝率': f"{_ys.get('win_rate', 0)*100:.1f}",
                    '本年連対%': f"{_ys.get('top2_rate', 0)*100:.1f}",
                    '本年複勝%': f"{_ys.get('top3_rate', 0)*100:.1f}",
                    'フラグ': _flag_display,
                    'PW指数': f"{float(_e['pw_index']):.1f}" if _e.get('pw_index') is not None else '—',
                    '加減点': _kagenten_str,
                    '総合スコア': _sc,  # Stylerや判定用にfloatのままとし、表示上のHTMLでのみ後から丸める
                    '_bonuses': _bonuses,
                    '_adv': _adv_full,
                    '_matched_adv': _madv,
                })

            scored.sort(key=lambda x: x['_score'], reverse=True)
            _eval_marks = ['◎', '◎', '◎', '○', '▲', '△', '×']
            for _i, _s in enumerate(scored):
                _s['順位'] = _i + 1
                _s['評価'] = _eval_marks[_i] if _i < len(_eval_marks) else '—'

            # ── サマリーメトリクス ──
            _iron_n   = sum(1 for s in scored if "🔴 鉄板" in s['フラグ'])
            _value_n  = sum(1 for s in scored if "🟡 妙味" in s['フラグ'])
            _danger_n = sum(1 for s in scored if "🔵 危険" in s['フラグ'])
            _top1 = scored[0] if scored else {}

            _mc1, _mc2, _mc3, _mc4 = st.columns(4)
            _mc1.metric("🥇 本命", f"{_top1.get('馬番', '?')}番 {_top1.get('騎手', '?')[:4]}", f"スコア {float(_top1.get('総合スコア', 0)):.1f}")
            _mc2.metric("🔴 鉄板フラグ", f"{_iron_n}騎手")
            _mc3.metric("🟡 妙味フラグ", f"{_value_n}騎手")
            _mc4.metric("🔵 危険フラグ", f"{_danger_n}騎手")

            st.divider()

            # ── ランキング表 ──
            st.subheader("📊 騎手ランキング（騎手の力・調子の数値化）")
            st.caption("このレースで『馬に勝たせてもらっている』のか『馬の力を引き出している』のかを見る列に絞り込み。"
                       "**USM(馬力絞り出しメーター)**=単勝オッズ帯ごとの平均成績から推定した期待値に対し実際の成績が何%か。"
                       "100%超=人気以上に走らせる＝騎手の実力／100%割れ=取りこぼし。"
                       "単=勝ち切る力 / 連=2着内に入れる力 / 複=3着内に残す力。"
                       "PRB=ライバルを上回った割合(0.5平均)・PW指数=騎乗の強さ・単回収%=コース単勝回収率。")

            _display_cols = ['順位', '評価', '馬番', '馬名', '騎手', '厩舎',
                             '人気', 'オッズ', 'PRB', 'PW指数',
                             '単勝USM', '連対USM', '複勝USM', '単回収%', '総合スコア']
            _df_rank = pd.DataFrame(scored)[_display_cols]

            def _to_numeric(val):
                if val is None:
                    return float('inf')
                s = str(val).strip()
                if s in ('—', '—', '-', 'None', 'nan', ''):
                    return float('inf')
                s = s.replace('%', '')
                try:
                    return float(s)
                except ValueError:
                    return float('inf')

            def _style_top3_per_col(df):
                style_df = pd.DataFrame('', index=df.index, columns=df.columns)
                col_ascending_map = {
                    '人気': True,
                    'オッズ': True,
                    '調子P': False,
                    'PRB': False,
                    '単勝USM': False,
                    '連対USM': False,
                    '複勝USM': False,
                    'コース連対%': False,
                    'コース複勝%': False,
                    '単回収%': False,
                    '騎乗数': False,
                    '本年勝率': False,
                    '本年連対%': False,
                    '本年複勝%': False,
                    'PW指数': False,
                    '総合スコア': False
                }
                for col, asc in col_ascending_map.items():
                    if col in df.columns:
                        nums = df[col].map(_to_numeric)
                        valid_nums = nums[nums != float('inf')]
                        if len(valid_nums) > 0:
                            ranks = valid_nums.rank(method='min', ascending=asc)
                            top3_idx = ranks[ranks <= 3].index
                            for idx in top3_idx:
                                style_df.at[idx, col] = 'border: 2px solid #FF1744; box-shadow: inset 0 0 0 2px #FF1744;'
                return style_df

            def _style_rank_row(row):
                rank = row['順位']
                flag = str(row.get('フラグ', ''))  # フラグ列は表示から除外したため安全参照
                if rank == 1:
                    return ['background-color: #2a2200; color: #FBC02D; font-weight: bold; border-top: 1px solid #FBC02D; border-bottom: 1px solid #FBC02D;'] * len(row)
                if rank == 2:
                    return ['background-color: #2a1100; color: #F57C00; font-weight: bold; border-top: 1px solid #F57C00; border-bottom: 1px solid #F57C00;'] * len(row)
                if rank == 3:
                    return ['background-color: #001a00; color: #66BB6A; font-weight: bold; border-top: 1px solid #66BB6A; border-bottom: 1px solid #66BB6A;'] * len(row)
                if "🔵 危険" in flag:
                    return ['color: #7B9FFF;'] * len(row)
                return [''] * len(row)

            def _style_eval(val):
                if val == '◎': return 'color:#FF1744; font-weight:bold; font-size:1.3em;'
                if val == '○': return 'color:#FF9100; font-weight:bold;'
                if val == '▲': return 'color:#FFEA00; font-weight:bold;'
                return 'color:#888;'

            def _style_score(val):
                try:
                    v = float(str(val).replace('%', ''))
                    if v >= 120: return 'color:#FF5252; font-weight:bold;'
                    if v >= 90:  return 'color:#FFAB40;'
                    if v < 40:   return 'color:#666;'
                except: pass
                return ''

            # 列名を画面表示用にリネーム（旧 st.dataframe の column_config 設定に準拠）
            _df_rank_display = _df_rank.rename(columns={
                '脚質傾向': '脚質',
                'コース連対%': f'{_jp_venue}連対%',
                'コース複勝%': f'{_jp_venue}複勝%',
            })

            # スタイル適用（インデックス非表示化および小数点第1位フォーマットも Styler 側で実現）
            _styled = (_df_rank_display.style
                .hide(axis='index')
                .format(subset=['総合スコア'], formatter="{:.1f}")
                .apply(_style_rank_row, axis=1)
                .map(_style_eval, subset=['評価'])
                .map(_style_score, subset=['総合スコア'])
                .apply(_style_top3_per_col, axis=None)
            )

            # HTMLテーブル生成
            _styled.set_uuid("jpro_rank")
            _table_html = _styled.to_html(escape=False)

            # プレミアムダークテーマCSSおよびインタラクティブJavaScriptソーター
            _premium_table_html = f"""
            <div class="premium-table-container">
              <style>
                .premium-table-container {{
                    background: #0d0d1a;
                    border: 1px solid #2d1b4e;
                    border-radius: 12px;
                    padding: 16px;
                    margin-bottom: 24px;
                    box-shadow: 0 4px 25px rgba(0,0,0,0.6);
                    overflow-x: auto;
                }}
                .premium-table-container table {{
                    width: 100%;
                    border-collapse: separate;
                    border-spacing: 0;
                    color: #eee;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    font-size: 0.85rem;
                }}
                .premium-table-container th {{
                    background: #121225;
                    color: #b388ff;
                    font-weight: bold;
                    text-align: center;
                    padding: 12px 10px;
                    border-bottom: 2px solid #2d1b4e;
                    cursor: pointer;
                    user-select: none;
                    white-space: nowrap;
                    position: relative;
                    transition: background 0.2s, color 0.2s;
                }}
                .premium-table-container th:hover {{
                    background: #1e1e3f;
                    color: #ffffff;
                }}
                .premium-table-container th::after {{
                    content: " ↕";
                    font-size: 0.75em;
                    color: #666;
                    margin-left: 4px;
                }}
                .premium-table-container th.sorted-asc::after {{
                    content: " ▲" !important;
                    color: #ffab40 !important;
                }}
                .premium-table-container th.sorted-desc::after {{
                    content: " ▼" !important;
                    color: #ffab40 !important;
                }}
                .premium-table-container td {{
                    padding: 10px 10px;
                    border-bottom: 1px solid #1a1a35;
                    text-align: center;
                    white-space: nowrap;
                    transition: background 0.15s;
                }}
                .premium-table-container tr:hover td {{
                    background: rgba(255, 255, 255, 0.05) !important;
                }}
              </style>

              {_table_html}

              <script>
                (function() {{
                    const table = document.querySelector('.premium-table-container table');
                    if (!table) return;
                    const headers = table.querySelectorAll('th');
                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;

                    headers.forEach((header, index) => {{
                        let asc = true;
                        header.addEventListener('click', () => {{
                            const rows = Array.from(tbody.querySelectorAll('tr'));

                            rows.sort((rowA, rowB) => {{
                                const cellA = rowA.children[index].innerText.trim();
                                const cellB = rowB.children[index].innerText.trim();

                                const clean = (val) => {{
                                    val = val.replace('%', '').replace('🔥', '').replace('🧊', '').trim();
                                    if (val === '—' || val === '-' || val === '' || val === 'None') {{
                                        return asc ? Infinity : -Infinity;
                                    }}
                                    const num = parseFloat(val);
                                    return isNaN(num) ? val : num;
                                }};

                                const valA = clean(cellA);
                                const valB = clean(cellB);

                                if (typeof valA === 'number' && typeof valB === 'number') {{
                                    return asc ? valA - valB : valB - valA;
                                }}
                                return asc ? String(valA).localeCompare(String(valB)) : String(valB).localeCompare(String(valA));
                            }});

                            rows.forEach(row => tbody.appendChild(row));
                            asc = !asc;

                            headers.forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));
                            header.classList.add(asc ? 'sorted-desc' : 'sorted-asc');
                        }});
                    }});
                }})();
              </script>
            </div>
            """

            st.html(_premium_table_html)

            # ── 📈 勝ち指数バー（HTML+CSSプレミアムグラデーションバー） ──
            st.divider()
            st.subheader("📈 勝ち指数バー（上位5頭）")
            _top5 = scored[:5]

            _gradients = [
                "linear-gradient(90deg, #FFE082, #FFB300)",  # 1位 金ゴールド
                "linear-gradient(90deg, #FFF59D, #FBC02D)",  # 2位 黄ゴールド
                "linear-gradient(90deg, #FFE082, #F57F17)",  # 3位 濃ゴールド
                "linear-gradient(90deg, #E0E0E0, #757575)",  # 4位 銀
                "linear-gradient(90deg, #FFCC80, #CA8A04)",  # 5位 銅
            ]

            _max_score = max([s['総合スコア'] for s in _top5]) if _top5 else 100

            _bars_html = ""
            for _idx, _s in enumerate(_top5):
                _pct = max(10, min(100, int((_s['総合スコア'] / _max_score) * 85)))
                _grad = _gradients[_idx] if _idx < len(_gradients) else "linear-gradient(90deg, #424242, #212121)"
                _eval = _s.get('評価', '—')
                _eval_color = '#FFD700' if _eval == '◎' else '#C0C0C0' if _eval == '○' else '#CD7F32' if _eval == '▲' else '#aaa'

                _bars_html += f"""
                <div style="margin-bottom: 14px;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; font-size: 0.9em;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span style="font-weight: bold; color: {_eval_color}; width: 20px; text-align: center; font-size: 1.1em;">{_eval}</span>
                      <span style="color: #fff; font-weight: bold; background: #222; padding: 2px 6px; border-radius: 4px; font-size: 0.85em;">{_s.get('馬番', '')}番</span>
                      <span style="color: #fff; font-weight: 500;">{_s.get('馬名', '')[:10]}</span>
                      <span style="color: #888; font-size: 0.85em;">({_s.get('騎手', '')[:4]})</span>
                    </div>
                    <span style="font-weight: bold; color: #FFF; font-size: 1.1em; font-family: monospace;">{_s['総合スコア']:.1f} pt</span>
                  </div>
                  <div style="background: #111; border: 1px solid #222; border-radius: 6px; height: 18px; width: 100%; overflow: hidden; display: flex; align-items: center; padding: 1px;">
                    <div style="background: {_grad}; width: {_pct}%; height: 100%; border-radius: 5px; 
                                transition: width 0.8s ease-in-out; 
                                box-shadow: 0 0 10px rgba(255,171,64,0.15);"></div>
                  </div>
                </div>
                """

            st.html(f"""
            <div style="background: #0d0d1a; border: 1px solid #2d1b4e; border-radius: 12px; padding: 18px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
              {_bars_html}
            </div>
            """)

            # ── 上位3頭の詳細カード ──
            st.divider()
            st.subheader("🃏 評価付き7頭 詳細カード")
            for _s in scored[:7]:
                _ent = next((e for e in _jp_entries if e.get('umaban') == _s['_umaban']), None)
                if not _ent: continue
                _vs2  = _ent.get('venue_stats') or {}
                _pr2  = _ent.get('jockey_profile') or {}
                _ys2  = _pr2.get('year_stats') or {}
                _t_name = _s.get('厩舎', '')
                _j_name = _s.get('騎手', '')
                _t_tac = trainer_tactics.get_trainer_tactics(_t_name) if 'trainer_tactics' in globals() else None
                _j_tac = jockey_tactics.get_jockey_tactics(_j_name) if 'jockey_tactics' in globals() else None
                _flg2 = _ent.get('flags', [])
                _rank_color_map = {
                    1: '#FFD700', 2: '#FFD700', 3: '#FFD700',  # ◎ 金
                    4: '#C0C0C0',                               # ○ 銀
                    5: '#CD7F32',                               # ▲ 銅
                    6: '#4A90D9',                               # △ 青
                    7: '#888888',                               # × グレー
                }
                _rank_color = _rank_color_map.get(_s['順位'], '#555555')
                _bd   = _s['_breakdown']
                _bd_html = "".join(
                    f'<span style="background:#1e1e2e;border:1px solid #444;padding:3px 8px;border-radius:8px;font-size:0.8em;margin:2px;display:inline-block;">'
                    f'{k}: <b style="color:#FFAB40;">{v:+.0f}</b></span>'
                    for k, v in _bd.items() if v != 0
                )
                _badge_html2 = "".join(
                    f'<span style="background:{"#8B0000" if "鉄板" in f else "#7B6000" if "妙味" in f else "#0D47A1"};'
                    f'color:white;padding:2px 8px;border-radius:10px;font-size:0.85em;margin-right:4px;">{f}</span>'
                    for f in _flg2
                ) or '<span style="color:#666;">フラグなし</span>'

                _pw2 = _ent.get('pw_index')
                _pw2_str = f"{float(_pw2):.1f}" if _pw2 is not None else '—'
                _pw2_color = '#6fcf97' if _pw2 is not None and _pw2 >= 100 else '#FFAB40' if _pw2 is not None and _pw2 >= 50 else '#fff'
                _bon2 = _s.get('_bonuses') or {}
                _add100 = _bon2.get('add_100', [])
                _add90  = _bon2.get('add_90', [])
                _sub70  = _bon2.get('sub_70', [])
                _sub60  = _bon2.get('sub_60', [])
                _bonus_score   = _bon2.get('bonus_score', 0.0)
                _penalty_score = _bon2.get('penalty_score', 0.0)
                _cadv = _s.get('_adv') or {}
                _cmadv = _s.get('_matched_adv') or {}
                _cprb = _cmadv.get('prb_overall', 0.5)
                _cprb_color = '#6fcf97' if _cprb >= 0.60 else '#FFAB40' if _cprb >= 0.50 else '#ef4444'
                _chc = _cmadv.get('hot_cold', '—')
                _chc_str = {'HOT': '🔥 HOT', 'COLD': '🧊 COLD'}.get(_chc, '— 平常')
                _chc_color = '#FF5252' if _chc == 'HOT' else '#64B5F6' if _chc == 'COLD' else '#888'
                _c_rstyle = _cmadv.get('riding_style', '—')

                _tactics_html = ""
                if _t_tac or _j_tac:
                    _tactics_html = f"""
                    <div style="font-size:0.75em;color:#888;margin:8px 0 2px 0;">🏠 生涯脚質・作戦傾向（専門家集計データ / 2016年〜2026年）</div>
                    <div style="background:#222;border:1px solid #333;border-radius:8px;padding:8px;margin:2px 0 8px 0;">
                      <table style="width:100%;font-size:0.85em;text-align:center;color:#eee;border-collapse:collapse;">
                        <tr style="border-bottom:1px solid #444;"><th style="color:#aaa;padding:4px;">対象</th><th>逃げ</th><th>先行</th><th>中団</th><th>後方</th><th>マクリ</th></tr>
                    """
                    if _t_tac:
                        _tactics_html += f"<tr><td style='color:#b388ff;font-weight:bold;padding:4px;border-bottom:1px solid #333;'>厩舎({_t_name[:4]})</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('逃げ', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('先行', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('中団', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('後方', 0)}%</td><td style='border-bottom:1px solid #333;'>{_t_tac.get('マクリ', 0)}%</td></tr>"
                    if _j_tac:
                        _tactics_html += f"<tr><td style='color:#b388ff;font-weight:bold;padding:4px;'>騎手({_j_name[:4]})</td><td>{_j_tac.get('逃げ', 0)}%</td><td>{_j_tac.get('先行', 0)}%</td><td>{_j_tac.get('中団', 0)}%</td><td>{_j_tac.get('後方', 0)}%</td><td>{_j_tac.get('マクリ', 0)}%</td></tr>"

                    _tactics_html += """
                      </table>
                    </div>
                    """

                # Recent Form bars
                _rf = _cadv.get('recent_form', {})
                _rf_html = ""
                _prev_sample = -1
                for _rfd, _rfl in [('14d', '14日'), ('30d', '30日'), ('90d', '90日')]:
                    _rfv = _rf.get(_rfd)
                    if _rfv:
                        _sample_size = _rfv.get('sample', 0)
                        if _sample_size > 0 and _sample_size == _prev_sample:
                            continue
                        _prev_sample = _sample_size

                        _rfp = _rfv.get('prb', 0.5)
                        _rfn = _sample_size
                        _rft3 = _rfv.get('top3_rate', 0)
                        _rfbar_w = int(min(_rfp * 100, 100))
                        _rfbar_c = '#6fcf97' if _rfp >= 0.60 else '#FFAB40' if _rfp >= 0.50 else '#ef4444'
                        _rf_html += (
                            f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">'
                            f'<span style="width:32px;font-size:0.7em;color:#aaa;">{_rfl}</span>'
                            f'<div style="flex:1;background:#222;border-radius:4px;height:14px;overflow:hidden;">'
                            f'<div style="width:{_rfbar_w}%;background:{_rfbar_c};height:100%;border-radius:4px;"></div>'
                            f'</div>'
                            f'<span style="font-size:0.75em;color:{_rfbar_c};width:60px;">{_rfp:.2f} ({_rfn}走)</span>'
                            f'<span style="font-size:0.7em;color:#888;">複{_rft3*100:.0f}%</span>'
                            f'</div>'
                        )

                # 順位に応じたバッジ色
                _badge_bg = "#FBC02D" if _s['順位'] == 1 else "#F57C00" if _s['順位'] == 2 else "#757575"
                _badge_color = "#000" if _s['順位'] == 1 else "#fff"

                st.html(f"""
                <div style="border: 1px solid #333; border-radius: 12px; padding: 16px; margin-bottom: 16px; background: #1c1c1c;">
                  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center;">
                      <!-- 順位バッジ -->
                      <div style="width: 28px; height: 28px; border-radius: 6px; background: {_badge_bg}; color: {_badge_color}; font-weight: bold; font-size: 1.1em; display: flex; align-items: center; justify-content: center; margin-right: 12px;">
                        {_s['順位']}
                      </div>
                      <span style="font-size: 1.3em; font-weight: bold; color: #fff;">
                        {_s['馬番']}番 {_s['馬名']}
                      </span>
                      <span style="color: #aaa; margin-left: 12px; font-size: 0.9em;">
                        🏇 {_s['騎手']} ／ 🏠 {_s['厩舎']}
                      </span>
                    </div>
                    <div style="text-align: right;">
                      <div style="font-size: 1.6em; font-weight: bold; color: #fff;">{_s['総合スコア']:.1f} <span style="font-size: 0.6em; color: #888;">pt</span></div>
                    </div>
                  </div>
                  <div style="margin-bottom: 12px;">{_badge_html2}</div>

                  <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 12px 0;">
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_vs2.get('adj_top2_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">{_jp_venue}連対率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_vs2.get('top3_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">{_jp_venue}複勝率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: {'#6fcf97' if _vs2.get('adj_win_return',0)>=100 else '#fff'};">{_vs2.get('adj_win_return', 0):.0f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">単回収率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_vs2.get('rides', 0)}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">騎乗数</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: {_pw2_color};">{_pw2_str}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">PW指数</div>
                    </div>
                  </div>

                  <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 8px 0;">
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: {_cprb_color};">{_cprb:.2f}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">PRB</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.1em; font-weight: bold; color: {_chc_color};">{_chc_str}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">調子</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1em; font-weight: bold; color: #fff;">{_c_rstyle}</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">脚質傾向</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_ys2.get('win_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">本年勝率</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 10px;">
                      <div style="font-size: 1.3em; font-weight: bold; color: #fff;">{_ys2.get('top3_rate', 0)*100:.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 4px;">本年複勝率</div>
                    </div>
                  </div>

                  <!-- 人間変数 -->
                  <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 8px 0 12px 0;">
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('pos_skill', 50.0):.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">位置取り奪取力</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('drive_power', 0.0):+.2f}頭/R</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">剛腕追い上げ数</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('clutch_score', 50.0):.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">プレッシャー耐性</div>
                    </div>
                    <div style="text-align: center; background: #2a2a2a; border-radius: 8px; padding: 8px;">
                      <div style="font-size: 1.2em; font-weight: bold; color: #ddd;">{_cadv.get('gate_adapt', 50.0):.1f}%</div>
                      <div style="font-size: 0.75em; color: #aaa; margin-top: 2px;">外枠克服力</div>
                    </div>
                  </div>
                  {_tactics_html}
                  <!-- Recent Form -->
                  <div style="background:#0a0a1a;border-radius:8px;padding:8px 12px;margin:8px 0;">
                    <div style="font-size:0.75em;color:#888;margin-bottom:4px;">📈 Recent Form (PRB推移)</div>
                    {_rf_html if _rf_html else '<span style="color:#666;font-size:0.8em;">データなし</span>'}
                  </div>
                  <div style="font-size:0.8em;color:#888;margin-top:6px;">📐 スコア内訳: {_bd_html}</div>
                </div>
                """)

                # ── ボーナス/減点内訳（Expander） ──
                _m_add100 = _bon2.get('matched_add_100', [])
                _m_add90  = _bon2.get('matched_add_90', [])
                _m_sub70  = _bon2.get('matched_sub_70', [])
                _m_sub60  = _bon2.get('matched_sub_60', [])
                _m_bonus  = _bon2.get('matched_bonus_score', 0.0)
                _m_penalty= _bon2.get('matched_penalty_score', 0.0)
                _has_bonus_data = _add100 or _add90 or _sub70 or _sub60
                _has_match = _m_add100 or _m_add90 or _m_sub70 or _m_sub60

                _bonus_label_parts = []
                if _m_bonus > 0:
                    _bonus_label_parts.append(f"✅ 加算 +{_m_bonus:.0f}pt")
                if _m_penalty < 0:
                    _bonus_label_parts.append(f"⚠️ 減点 {_m_penalty:.0f}pt")
                if not _has_match and _has_bonus_data:
                    _bonus_label_parts.append("今レースは条件不一致")
                _expander_label = (
                    f"📊 ボーナス/減点内訳 （{'・'.join(_bonus_label_parts) if _bonus_label_parts else 'データなし'}）"
                )
                with st.expander(_expander_label, expanded=False):
                    if not _has_bonus_data:
                        st.caption("db-keibaからボーナスデータを取得できませんでした。")
                    else:
                        # レースメタ情報を表示
                        _rm = _ent.get('race_meta') or {}
                        if _rm:
                            _rm_parts = []
                            if _rm.get('surface'): _rm_parts.append(_rm['surface'])
                            if _rm.get('distance'): _rm_parts.append(f"{_rm['distance']}m")
                            if _rm.get('condition'): _rm_parts.append(f"馬場:{_rm['condition']}")
                            if _rm.get('weather'): _rm_parts.append(f"天候:{_rm['weather']}")
                            if _rm.get('race_class'): _rm_parts.append(_rm['race_class'])
                            if _rm.get('waku'): _rm_parts.append(f"{_ent.get('waku',0)}枠")
                            if _ent.get('trainer_name'): _rm_parts.append(f"厩舎:{_ent['trainer_name']}")
                            if _ent.get('owner_name'): _rm_parts.append(f"馬主:{_ent['owner_name']}")
                            st.caption(f"🔍 照合条件: {' / '.join(_rm_parts)}")

                        _bcol1, _bcol2 = st.columns(2)
                        with _bcol1:
                            st.markdown("#### ✅ 加算条件")
                            if _add100:
                                st.markdown("🟢 **回収率100%以上** `+15pt/件`")
                                for _cond in _add100:
                                    _hit = _cond in _m_add100
                                    _prefix = "🎯 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if _add90:
                                st.markdown("🟡 **回収率90%以上** `+8pt/件`")
                                for _cond in _add90:
                                    _hit = _cond in _m_add90
                                    _prefix = "🎯 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if not _add100 and not _add90:
                                st.caption("加算条件なし")
                        with _bcol2:
                            st.markdown("#### ⚠️ 減点条件")
                            if _sub60:
                                st.markdown("🔴 **回収率60%未満** `-15pt/件`")
                                for _cond in _sub60:
                                    _hit = _cond in _m_sub60
                                    _prefix = "💥 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if _sub70:
                                st.markdown("🟠 **回収率70%未満** `-8pt/件`")
                                for _cond in _sub70:
                                    _hit = _cond in _m_sub70
                                    _prefix = "💥 **" if _hit else "　"
                                    _suffix = "** ← 今レース発動！" if _hit else ""
                                    st.markdown(f"- {_prefix}{_cond}{_suffix}")
                            if not _sub60 and not _sub70:
                                st.caption("減点条件なし")

                # ── 条件別PRB内訳（Expander） ──
                _cadv_data = _s.get('_adv') or {}
                if _cadv_data.get('sample_size', 0) > 0:
                    with st.expander(f"📈 条件別PRB・複勝率 （直近{_cadv_data.get('sample_size',0)}走）", expanded=False):
                        def _render_prb_table(title, data_dict, highlight_key=None):
                            if not data_dict:
                                st.caption(f"{title}: データなし")
                                return
                            _rows = []
                            for _dk, _dv in data_dict.items():
                                _rows.append({
                                    '条件': ('→ ' + _dk if _dk == highlight_key else _dk),
                                    'PRB': f"{_dv['prb']:.2f}",
                                    '勝率': f"{_dv.get('win_rate',0)*100:.1f}%",
                                    '複勝率': f"{_dv.get('top3_rate',0)*100:.1f}%",
                                    'サンプル': _dv.get('sample', 0),
                                })
                            st.markdown(f"**{title}**")
                            st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

                        _rm2 = _ent.get('race_meta') or {}
                        _dist_hl = None
                        if _rm2.get('distance'):
                            _dist_hl = jockey_analyzer._classify_distance(_rm2['distance'])
                        _cond_hl = _rm2.get('condition', '')
                        _gate_hl = None
                        if _ent.get('umaban', 0) > 0:
                            _gate_hl = jockey_analyzer._classify_gate(_ent['umaban'])

                        _pcol1, _pcol2, _pcol3 = st.columns(3)
                        with _pcol1:
                            _render_prb_table("距離区分別", _cadv_data.get('by_distance', {}), _dist_hl)
                            _render_prb_table("馬場状態別", _cadv_data.get('by_condition', {}), _cond_hl)
                        with _pcol2:
                            _render_prb_table("枠順別", _cadv_data.get('by_gate', {}), _gate_hl)
                            _render_prb_table("レースクラス別", _cadv_data.get('by_class', {}))
                        with _pcol3:
                            _render_prb_table("オッズ帯別", _cadv_data.get('by_odds_band', {}))
                            _render_prb_table("斤量別", _cadv_data.get('by_weight', {}))

            # ── 買い目サジェスト ──
            st.divider()
            st.subheader("🎯 買い目サジェスト")
            _honmei = scored[0] if len(scored) > 0 else None
            _taikou = scored[1] if len(scored) > 1 else None
            _tanaka  = scored[2] if len(scored) > 2 else None
            _myomi_list = [s for s in scored if "🟡 妙味" in s['フラグ'] and s['順位'] > 3][:2]

            _buy_lines = []
            if _honmei and _taikou:
                _buy_lines.append(f"**単勝**: {_honmei['馬番']}番（{_honmei['騎手']}）")
                _buy_lines.append(f"**馬連**: {_honmei['馬番']}番 ー {_taikou['馬番']}番")
            if _honmei and _taikou and _tanaka:
                _buy_lines.append(f"**3連複**: {_honmei['馬番']}番 ー {_taikou['馬番']}番 ー {_tanaka['馬番']}番")
                _buy_lines.append(f"**3連単（軸1頭流し）**: {_honmei['馬番']}番 → {_taikou['馬番']}番, {_tanaka['馬番']}番 ...")
            if _myomi_list:
                _myomi_str = "・".join([f"{s['馬番']}番（{s['騎手']}）" for s in _myomi_list])
                _buy_lines.append(f"**妙味馬（ヒモ候補）**: {_myomi_str}")

            for _line in _buy_lines:
                st.markdown(f"- {_line}")

            # ── CSVダウンロード ──
            st.divider()
            _csv_bytes = _df_rank.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                "💾 ランキング結果をCSVダウンロード",
                data=_csv_bytes,
                file_name=f"jockey_ranking_{jp_race_id}.csv",
                mime="text/csv",
                key="jp_csv_download",
            )

        elif _jp_res and _jp_res.get('error'):
            st.warning(_jp_res['error'])
        elif not _jp_res:
            st.info("⬆️ レースIDを入力して「分析開始」ボタンを押してください。")


    # =============================================
    # タブ4: 設定・データ管理
    # =============================================
    with jpro_tab4:
        st.subheader("⚙️ 設定")

        st.markdown("##### フラグ閾値設定")
        col1, col2 = st.columns(2)
        with col1:
            st.number_input("🔴鉄板：連対率閾値（%）", 10, 80, 40, key="jpro_iron_threshold")
            st.number_input("🔴鉄板：最低騎乗回数", 5, 100, 30, key="jpro_iron_min_rides")
        with col2:
            st.number_input("🟡妙味：単回収閾値（%）", 80, 300, 120, key="jpro_value_threshold")
            st.number_input("🟡妙味：最低騎乗回数", 5, 100, 15, key="jpro_value_min_rides")

        st.number_input("🔵危険：連対率上限（%）", 5, 30, 15, key="jpro_danger_threshold")

        st.markdown("---")

        st.markdown("##### ベイズ補正設定")
        st.number_input(
            "事前分布の強さ（擬似サンプル数）", 5, 100, 20,
            key="jpro_prior_strength",
            help="数値が大きいほど、少数サンプルのデータが全体平均に強く引き寄せられる"
        )

        st.markdown("---")

        st.markdown("##### データ管理")

        # DB状態表示
        try:
            if _jpro_db.table_exists():
                rec_count = _jpro_db.get_record_count()
                st.success(f"✅ jockey_statsテーブル: {rec_count}件のレコード")
            else:
                st.warning("⚠️ jockey_statsテーブルが存在しません。下のボタンで初期化してください。")
        except Exception:
            st.warning("⚠️ DB接続エラー。下のボタンで初期化してください。")

        if st.button("🗄️ DBテーブル初期化（jockey_stats）", key="jpro_init_db"):
            try:
                _jpro_db.init_table()
                st.success("✅ jockey_statsテーブルを初期化しました。")
            except Exception as e:
                st.error(f"❌ 初期化エラー: {e}")

        st.markdown("---")

        st.markdown("##### CSVインポート")
        st.caption("""
        **必須カラム**: jockey_id, jockey_name, target_type, target_id, target_name, ride_count, win_count, top2_count, win_rate, top2_rate, return_win

        **target_type**: `course` / `trainer` / `horse` のいずれか

        **オプション**: top3_count, top3_rate, return_place, running_style, track_condition
        """)

        uploaded = st.file_uploader(
            "騎手成績CSVをアップロード",
            type=["csv"],
            key="jpro_csv_upload",
        )
        if uploaded:
            try:
                df_csv = pd.read_csv(uploaded, encoding="utf-8")
            except UnicodeDecodeError:
                df_csv = pd.read_csv(uploaded, encoding="utf-8-sig")

            st.dataframe(df_csv.head(10), use_container_width=True)
            st.caption(f"プレビュー: {len(df_csv)}件、カラム: {list(df_csv.columns)}")

            if st.button("📥 インポート実行", key="jpro_csv_import", type="primary"):
                try:
                    # テーブルが無ければ先に初期化
                    if not _jpro_db.table_exists():
                        _jpro_db.init_table()

                    count = _jpro_db.import_csv(df_csv)
                    st.success(f"✅ {count}件をインポートしました。")
                except Exception as e:
                    st.error(f"❌ インポートエラー: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        st.markdown("---")

        # =============================================
        # netkeibaデータ自動取得
        # =============================================
        st.markdown("##### 📥 netkeibaデータ自動取得")
        st.caption("騎手IDを入力すると、コース別/厩舎別/馬別の成績をnetkeibaから取得しDBに保存します。")

        _fetch_col1, _fetch_col2 = st.columns([3, 1])
        with _fetch_col1:
            _fetch_jid = st.text_input(
                "騎手ID（netkeiba 5桁）",
                placeholder="例: 05212 (ルメール)",
                key="jpro_fetch_jockey_id",
            )
        with _fetch_col2:
            st.write("")
            _fetch_single_btn = st.button("📥 単独取得", key="jpro_fetch_single", use_container_width=True)

        if _fetch_single_btn and _fetch_jid.strip():
            from utils.jockey_scraper import JockeyScraper
            _scraper = JockeyScraper()
            with st.spinner(f"騎手ID {_fetch_jid.strip()} のデータを取得中..."):
                try:
                    stats = _scraper.fetch_all_stats(_fetch_jid.strip())
                    total_fetched = 0
                    if not _jpro_db.table_exists():
                        _jpro_db.init_table()
                    for target_type, df in stats.items():
                        if not df.empty:
                            records = df.to_dict("records")
                            count = _jpro_db.upsert(records)
                            total_fetched += count
                            st.caption(f"  {target_type}: {count}件")
                    if total_fetched > 0:
                        st.success(f"✅ 合計{total_fetched}件のデータを取得・保存しました。")
                    else:
                        st.warning("データを取得できませんでした。騎手IDを確認してください。")
                except Exception as e:
                    st.error(f"取得エラー: {e}")

        # バッチ取得（リーディング上位）
        with st.expander("🔄 一括取得（リーディング上位）"):
            _batch_top_n = st.slider("上位N名", 5, 30, 10, key="jpro_batch_top_n")
            if st.button(f"🔄 上位{_batch_top_n}名を一括取得", key="jpro_batch_fetch"):
                from utils.jockey_scraper import JockeyScraper, TOP_JOCKEYS
                _scraper = JockeyScraper()
                jockey_ids = list(TOP_JOCKEYS.keys())[:_batch_top_n]
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_batch = 0
                if not _jpro_db.table_exists():
                    _jpro_db.init_table()
                for idx, jid in enumerate(jockey_ids):
                    jname = TOP_JOCKEYS.get(jid, jid)
                    progress_bar.progress((idx + 1) / len(jockey_ids))
                    status_text.caption(f"取得中: {jname} ({jid}) [{idx+1}/{len(jockey_ids)}]")
                    try:
                        stats = _scraper.fetch_all_stats(jid)
                        for ttype, df in stats.items():
                            if not df.empty:
                                total_batch += _jpro_db.upsert(df.to_dict("records"))
                    except Exception:
                        pass
                progress_bar.empty()
                status_text.empty()
                st.success(f"✅ {_batch_top_n}名から合計{total_batch}件を取得・保存しました。")

        st.markdown("---")

        # =============================================
        # LightGBMウェイト算出
        # =============================================
        st.markdown("##### 🤖 機械学習ウェイト算出（LightGBM）")
        st.caption("DB内の騎手成績データから、各相性数値が回収率にどれだけ影響するかを客観的に算出します。")

        _ml_col1, _ml_col2 = st.columns([2, 1])
        with _ml_col1:
            _ml_target = st.selectbox(
                "目的変数",
                ["回収率（return_win）", "着順（finish_position）"],
                key="jpro_ml_target",
            )
        with _ml_col2:
            st.write("")
            _ml_train_btn = st.button("🤖 ウェイト算出", key="jpro_ml_train_btn", use_container_width=True)

        if _ml_train_btn:
            try:
                from utils.jockey_ml import train_weights
                target = "return_win" if "回収率" in _ml_target else "finish_position"
                with st.spinner("学習中（数秒〜数十秒）..."):
                    weights = train_weights(target=target, db_path=_jpro_db.db_path)
                if weights:
                    st.success("✅ ウェイト算出完了！")
                    df_w = pd.DataFrame([
                        {"特徴量": k, "重要度": v} for k, v in weights.items()
                    ])
                    st.bar_chart(df_w.set_index("特徴量"))
            except Exception as e:
                st.error(f"ウェイト算出エラー: {e}")
                import traceback
                st.code(traceback.format_exc())

        # 現在のウェイト表示
        with st.expander("📊 現在のウェイト"):
            try:
                from utils.jockey_ml import get_weights
                current_weights = get_weights(db_path=_jpro_db.db_path)
                for feat, w in current_weights.items():
                    bar_len = int(w * 200)
                    st.markdown(
                        f"**{feat}**: `{w:.4f}` "
                        f"{'█' * bar_len}{'░' * max(0, 20 - bar_len)}"
                    )
            except Exception as e:
                st.info(f"ウェイト未算出: {e}")

        st.markdown("---")

        # =============================================
        # 外部指数インポート（PW指数等）
        # =============================================
        st.markdown("##### 🔢 外部指数インポート（PW指数等）")
        st.caption("PakkaWinのPW指数やタイム指数などのCSVデータをインポートし、出馬表ビューに統合表示します。")

        pw_uploaded = st.file_uploader(
            "PW指数データCSV",
            type=["csv"],
            key="jpro_pw_upload",
            help="必須カラム: horse_id, horse_name, pw_index / オプション: race_id",
        )
        if pw_uploaded:
            try:
                df_pw = pd.read_csv(pw_uploaded, encoding="utf-8")
            except UnicodeDecodeError:
                df_pw = pd.read_csv(pw_uploaded, encoding="utf-8-sig")

            st.dataframe(df_pw.head(10), use_container_width=True)
            st.caption(f"プレビュー: {len(df_pw)}件、カラム: {list(df_pw.columns)}")

            if st.button("📥 PW指数インポート", key="jpro_pw_import", type="primary"):
                try:
                    import sqlite3
                    conn = sqlite3.connect(_jpro_db.db_path)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS external_index (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            race_id TEXT NOT NULL DEFAULT '',
                            horse_id TEXT NOT NULL,
                            horse_name TEXT NOT NULL,
                            index_name TEXT NOT NULL,
                            index_value REAL NOT NULL,
                            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                            UNIQUE(race_id, horse_id, index_name)
                        )
                    """)
                    pw_count = 0
                    for _, row in df_pw.iterrows():
                        conn.execute(
                            """INSERT OR REPLACE INTO external_index
                               (race_id, horse_id, horse_name, index_name, index_value)
                               VALUES (?, ?, ?, 'PW', ?)""",
                            (
                                str(row.get("race_id", "")),
                                str(row.get("horse_id", "")),
                                str(row.get("horse_name", "")),
                                float(row.get("pw_index", 0.0)),
                            ),
                        )
                        pw_count += 1
                    conn.commit()
                    conn.close()
                    st.success(f"✅ PW指数 {pw_count}件をインポートしました。")
                except Exception as e:
                    st.error(f"❌ PW指数インポートエラー: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        st.markdown("---")

        # =============================================
        # レース一括ボーナス条件作成モード
        # =============================================
        st.markdown("##### 🏇 レース一括ボーナス条件作成モード")
        st.caption("レースIDを入力するだけで出走騎手のCSVテンプレートとdb-keibaリンクを一括生成します。")

        _bulk_race_id = st.text_input(
            "netkeibaレースIDを入力",
            placeholder="例: 202504050811",
            key="bonus_bulk_race_id",
        )
        if st.button("🔍 騎手一覧を抽出してテンプレート生成", key="bonus_bulk_btn", type="primary"):
            if not _bulk_race_id.strip():
                st.warning("レースIDを入力してください。")
            else:
                with st.spinner("出走騎手を取得中..."):
                    try:
                        _bulk_entries = jockey_analyzer.extract_jockey_ids_from_race(_bulk_race_id.strip())
                    except Exception as _bulk_e:
                        _bulk_entries = []
                        st.error(f"取得失敗: {_bulk_e}")

                if _bulk_entries:
                    st.success(f"{len(_bulk_entries)}人の騎手を抽出しました。")

                    # db-keibaスラッグ変換（ローマ字）— 既知の主要騎手マッピング
                    _SLUG_MAP = {
                        '川田将雅': 'kawada', '福永祐一': 'fukunaga', '武豊': 'take',
                        'ルメール': 'lemaire', 'デムーロ': 'demuro', '横山典弘': 'yokoyama-n',
                        '横山武史': 'yokoyama-t', '松山弘平': 'matsuyama', '岩田康誠': 'iwata-k',
                        '岩田望来': 'iwata-m', '戸崎圭太': 'tosaki', '浜中俊': 'hamanaka',
                        '池添謙一': 'ikezoe', '和田竜二': 'wada', '藤岡佑介': 'fujioka-y',
                        '藤岡康太': 'fujioka-k', '幸英明': 'miyuki', '丸山元気': 'maruyama',
                        '三浦皇成': 'miura', '田辺裕信': 'tanabe', '内田博幸': 'uchida',
                        '北村友一': 'kitamura-t', '北村宏司': 'kitamura-h', '石橋脩': 'ishibashi',
                        '坂井瑠星': 'sakai', '津村明秀': 'tsumura', '鮫島克駿': 'samejima',
                        '鮫島良太': 'samejima-r', '永野猛蔵': 'nagano', '西村淳也': 'nishimura',
                        '菅原明良': 'sugawara', '団野大成': 'danno', '古川吉洋': 'furukawa',
                        '角田大河': 'tsunoda', '角田大和': 'tsunoda-y', '小沢大仁': 'ozawa',
                        'モレイラ': 'moreira', 'ムーア': 'moore', 'ビュイック': 'buick',
                    }

                    # 表示用DataFrame
                    _bulk_rows = []
                    for _be in _bulk_entries:
                        _jname = _be.get('jockey_name', '')
                        _jid   = _be.get('jockey_id', '')
                        _slug  = _SLUG_MAP.get(_jname, '')
                        _dburl = f"https://db-keiba.com/jockey-{_slug}/" if _slug else '（スラッグ不明）'
                        _bulk_rows.append({
                            '馬番':    _be.get('umaban', ''),
                            '馬名':    _be.get('horse_name', ''),
                            '騎手名':  _jname,
                            '騎手ID':  _jid,
                            'db-keiba傾向URL': _dburl,
                        })
                    _bulk_df = pd.DataFrame(_bulk_rows)

                    # テーブル表示（URLはリンクとして）
                    st.dataframe(
                        _bulk_df,
                        column_config={
                            '馬番':  st.column_config.NumberColumn(width='small'),
                            '馬名':  st.column_config.TextColumn(width='medium'),
                            '騎手名': st.column_config.TextColumn(width='medium'),
                            '騎手ID': st.column_config.TextColumn(width='small'),
                            'db-keiba傾向URL': st.column_config.LinkColumn(
                                "db-keiba傾向ページ",
                                display_text="傾向を見る",
                                width='medium',
                            ),
                        },
                        hide_index=True,
                        use_container_width=True,
                    )

                    # CSVテンプレート自動生成（既知騎手は傾向DBから条件を自動埋め込み）
                    JOCKEY_TENDENCY_DB = jockey_analyzer.JOCKEY_TENDENCY_DB
                    _tmpl_rows = []
                    _known_count = 0
                    _unknown_count = 0
                    for _be in _bulk_entries:
                        _jid = _be.get('jockey_id', '')
                        if not _jid:
                            continue
                        _jname = _be.get('jockey_name', '')
                        _tendency = JOCKEY_TENDENCY_DB.get(_jid)
                        if _tendency:
                            _known_count += 1
                            # 既知騎手: 傾向DBから条件を自動埋め込み
                            for _typ in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                                for _cond in _tendency.get(_typ, []):
                                    _tmpl_rows.append({
                                        'jockey_id': _jid,
                                        'jockey_name': _jname,
                                        'type': _typ,
                                        'condition': _cond,
                                    })
                            # 余白行（追記用）
                            for _typ in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                                _tmpl_rows.append({
                                    'jockey_id': _jid,
                                    'jockey_name': _jname,
                                    'type': _typ,
                                    'condition': '',
                                })
                        else:
                            _unknown_count += 1
                            # 未知騎手: 空欄×2行
                            for _typ in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                                for _ in range(2):
                                    _tmpl_rows.append({
                                        'jockey_id': _jid,
                                        'jockey_name': _jname,
                                        'type': _typ,
                                        'condition': '',
                                    })
                    _tmpl_df = pd.DataFrame(_tmpl_rows)
                    _tmpl_csv = _tmpl_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')

                    if _known_count > 0:
                        st.info(f"✅ {_known_count}人は傾向DBから条件を自動入力済みです。"
                                f"{'（残り' + str(_unknown_count) + '人は手動入力が必要）' if _unknown_count > 0 else ''}")
                    st.download_button(
                        "📥 CSVテンプレートをダウンロード（既知騎手は条件自動入力済み）",
                        data=_tmpl_csv,
                        file_name=f"bonus_{_bulk_race_id.strip()}.csv",
                        mime="text/csv",
                        key="bonus_bulk_dl",
                        type="primary",
                    )
                    st.caption(
                        "既知騎手（約20名）の条件はDB自動入力済みです。"
                        "未知騎手の `condition` 欄はdb-keibaの傾向ページを参照しながら入力してください。"
                        "入力後、下の「ボーナス条件CSVインポート」からアップロードしてください。"
                    )
                elif _bulk_entries is not None:
                    st.warning("出走騎手を取得できませんでした。レースIDを確認してください。")

        st.markdown("---")

        # =============================================
        # 騎手ボーナス条件 統合エディタ
        # （登録・修正・削除・新規追加をひとつの表で管理）
        # =============================================
        import json as _json_tendency

        # グリーン基調のヘッダー
        st.markdown("""
    <div style="background:linear-gradient(90deg,#1a6e3c,#27ae60);
            padding:12px 18px;border-radius:8px;margin-bottom:12px;">
      <span style="color:#fff;font-size:1.1rem;font-weight:700;">
    🟢 騎手ボーナス条件エディタ
      </span>
      <span style="color:#d4f5e2;font-size:0.85rem;margin-left:12px;">
    登録・追加・修正・削除をこの表で一括管理
      </span>
    </div>
    """, unsafe_allow_html=True)

        # 保存先CSVパス
        _BONUS_CSV_PATH = os.path.join(
            _ROOT, "data", "bonus_conditions.csv"
        )

        # ---- キャッシュ → DataFrame に展開 ----
        _UE_CACHE = jockey_analyzer._DBKEIBA_BONUS_CACHE
        _ue_rows = []
        for _uejid, _uebd in _UE_CACHE.items():
            _uename = _uebd.get('name', _uejid)
            for _uetyp in ['add_100', 'add_90', 'sub_70', 'sub_60']:
                for _uecond in _uebd.get(_uetyp, []):
                    _ue_rows.append({
                        'jockey_id':   _uejid,
                        'jockey_name': _uename,
                        'type':        _uetyp,
                        'condition':   _uecond,
                    })
        _ue_df = pd.DataFrame(_ue_rows) if _ue_rows else pd.DataFrame(
            columns=['jockey_id','jockey_name','type','condition'])

        # ---- 統計サマリをグリーンカードで表示 ----
        _ue_jcount = _ue_df['jockey_id'].nunique() if len(_ue_df) else 0
        _ue_rcount = len(_ue_df)
        _ua1, _ua2, _ua3, _ua4 = st.columns(4)
        _ua1.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #27ae60;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#1a6e3c;font-size:1.4rem;font-weight:700;">{_ue_jcount}</div>
            <div style="color:#2e7d52;font-size:0.8rem;">登録騎手数</div></div>""",
            unsafe_allow_html=True)
        _ua2.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #27ae60;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#1a6e3c;font-size:1.4rem;font-weight:700;">{_ue_rcount}</div>
            <div style="color:#2e7d52;font-size:0.8rem;">条件総数</div></div>""",
            unsafe_allow_html=True)
        _ue_add = len(_ue_df[_ue_df['type'].isin(['add_100','add_90'])]) if len(_ue_df) else 0
        _ua3.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #2ecc71;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#1a6e3c;font-size:1.4rem;font-weight:700;">+{_ue_add}</div>
            <div style="color:#2e7d52;font-size:0.8rem;">加算条件</div></div>""",
            unsafe_allow_html=True)
        _ue_sub = len(_ue_df[_ue_df['type'].isin(['sub_70','sub_60'])]) if len(_ue_df) else 0
        _ua4.markdown(f"""<div style="background:#fdf0f0;border-left:4px solid #e74c3c;
            padding:8px 12px;border-radius:6px;text-align:center;">
            <div style="color:#922b21;font-size:1.4rem;font-weight:700;">-{_ue_sub}</div>
            <div style="color:#922b21;font-size:0.8rem;">減点条件</div></div>""",
            unsafe_allow_html=True)

        st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
        st.markdown("""<div style="background:#f0faf4;border:1px solid #a8dbb8;
            border-radius:6px;padding:8px 14px;font-size:0.85rem;color:#1a5e34;">
            💡 <b>使い方</b>：セルをクリックして直接編集 ／ 下の「＋」ボタンで行追加（新騎手登録も可）
            ／ 行選択→ Delete で削除 ／ 編集後は <b>💾 保存</b> ボタンを押してください
        </div>""", unsafe_allow_html=True)
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

        # ---- data_editor ----
        _ue_edited = st.data_editor(
            _ue_df,
            column_config={
                'jockey_id': st.column_config.TextColumn(
                    '騎手ID', width='small',
                    help='netkeibaの5桁ID（例: 01167）',
                ),
                'jockey_name': st.column_config.TextColumn(
                    '騎手名', width='small',
                ),
                'type': st.column_config.SelectboxColumn(
                    'タイプ', width='medium',
                    options=['add_100','add_90','sub_70','sub_60'],
                    help='add_100=+15pt / add_90=+8pt / sub_70=-8pt / sub_60=-15pt',
                ),
                'condition': st.column_config.TextColumn(
                    '条件', width='large',
                    help='例: 芝逃げ / 東京芝コース / 前走逃げ馬 など',
                ),
            },
            num_rows='dynamic',
            use_container_width=True,
            hide_index=True,
            key="unified_bonus_editor",
        )

        # ---- ボタン行 ----
        _ubtn1, _ubtn2, _ubtn3 = st.columns([2, 2, 3])
        with _ubtn1:
            _ue_save = st.button(
                "💾 保存して反映",
                type="primary",
                key="unified_bonus_save",
                use_container_width=True,
            )
        with _ubtn2:
            _ue_dl_csv = _ue_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                "⬇️ CSVダウンロード",
                data=_ue_dl_csv,
                file_name="bonus_conditions_export.csv",
                mime="text/csv",
                key="unified_bonus_dl",
                use_container_width=True,
            )
        with _ubtn3:
            st.markdown(
                "<span style='color:#888;font-size:0.8rem;line-height:2.4rem;'>"
                "※ 保存するとキャッシュとCSVファイルに即時反映されます</span>",
                unsafe_allow_html=True,
            )

        if _ue_save:
            _ue_new_cache = {}
            for _, _uer in _ue_edited.iterrows():
                _ueid   = str(_uer.get('jockey_id','')).strip().zfill(5)
                _uetyp2 = str(_uer.get('type','')).strip()
                _uecnd  = str(_uer.get('condition','')).strip()
                _uenm   = str(_uer.get('jockey_name','')).strip()
                if not _ueid or not _uetyp2 or not _uecnd or _uecnd in ('nan',''):
                    continue
                if _ueid not in _ue_new_cache:
                    _ue_new_cache[_ueid] = {
                        'name': _uenm,
                        'add_100':[], 'add_90':[], 'sub_70':[], 'sub_60':[],
                    }
                if _uetyp2 in ('add_100','add_90','sub_70','sub_60'):
                    _ue_new_cache[_ueid][_uetyp2].append(_uecnd)

            # キャッシュ更新
            _UE_CACHE.clear()
            _UE_CACHE.update(_ue_new_cache)

            # CSV永続保存
            _ue_save_rows = []
            for _us_id, _us_bd in _ue_new_cache.items():
                for _us_typ in ['add_100','add_90','sub_70','sub_60']:
                    for _us_cnd in _us_bd.get(_us_typ,[]):
                        _ue_save_rows.append({
                            'jockey_id':   _us_id,
                            'jockey_name': _us_bd.get('name', _us_id),
                            'type':        _us_typ,
                            'condition':   _us_cnd,
                        })
            pd.DataFrame(_ue_save_rows).to_csv(
                _BONUS_CSV_PATH, index=False, encoding='utf-8-sig'
            )

            _ue_jc2 = len(_ue_new_cache)
            _ue_rc2 = len(_ue_save_rows)
            st.markdown(f"""<div style="background:#e8f8ee;border-left:4px solid #27ae60;
                border-radius:6px;padding:10px 16px;margin-top:8px;">
                ✅ <b>{_ue_jc2}騎手 / {_ue_rc2}件</b> を保存しました。次回分析から反映されます。
            </div>""", unsafe_allow_html=True)
            st.rerun()

        st.markdown("---")

        # =============================================
        # ボーナス/減点条件CSVインポート
        # =============================================
        st.markdown("##### 🎯 ボーナス/減点条件CSVインポート")

        st.markdown("**📖 使い方**")
        st.markdown("""
    1. **db-keiba.com** で騎手ページを開く（例: `https://db-keiba.com/jockey-kawada/`）
    2. 「条件別成績・回収率まとめ」を参照し、回収率の高い／低い条件を確認
    3. 下の **CSVテンプレート** をダウンロードしてExcelやメモ帳で条件を入力して保存
    4. 保存したCSVをアップロード → 「インポート」ボタンを押す
    5. 次回の騎手ランキング分析時にスコアへ自動反映。詳細カードの「📊 ボーナス/減点内訳」で発動状況を確認
    """)
        st.markdown("**typeの種類（condition 1件あたりの加減点）:**")
        _tc1, _tc2, _tc3, _tc4 = st.columns(4)
        _tc1.success("add_100: 回収率100%以上 +15pt")
        _tc2.warning("add_90 : 回収率90%以上  +8pt")
        _tc3.warning("sub_70 : 回収率70%未満  -8pt")
        _tc4.error("sub_60 : 回収率60%未満  -15pt")
        st.markdown(
            "**騎手ID確認:** netkeibaの騎手URLの5桁数字 "
            "（例: `db.netkeiba.com/jockey/01167/` → `01167`）  \n"
            "**condition例:** 芝 / ダート / 東京 / 阪神 / 中山 / 京都 / 良 / 重 / 稍重 / "
            "マイル / 短距離 / 中距離 / 長距離 / 1600m / G1 / オープン / 新馬 / 厩舎名 / 馬主名 など"
        )

        # CSVテンプレートダウンロード
        _bonus_template = (
            "jockey_id,type,condition\n"
            "01167,add_100,芝\n"
            "01167,add_100,阪神\n"
            "01167,add_90,マイル\n"
            "01167,sub_70,ダート\n"
            "01167,sub_60,新馬\n"
        )
        st.download_button(
            "📄 CSVテンプレートをダウンロード",
            data=_bonus_template.encode('utf-8-sig'),
            file_name="bonus_conditions_template.csv",
            mime="text/csv",
            key="bonus_template_dl",
            help="このテンプレートに騎手IDと条件を入力して保存し、下からアップロードしてください",
        )

        _bonus_csv_uploaded = st.file_uploader(
            "ボーナス条件CSV",
            type=["csv"],
            key="bonus_csv_upload",
            help="必須カラム: jockey_id, type, condition",
        )
        if _bonus_csv_uploaded:
            try:
                try:
                    _df_bonus = pd.read_csv(_bonus_csv_uploaded, dtype=str, encoding='utf-8-sig').fillna('')
                except UnicodeDecodeError:
                    _bonus_csv_uploaded.seek(0)
                    _df_bonus = pd.read_csv(_bonus_csv_uploaded, dtype=str, encoding='cp932').fillna('')
                _df_bonus.columns = [c.strip() for c in _df_bonus.columns]
                st.dataframe(_df_bonus.head(15), use_container_width=True, hide_index=True)
                st.caption(f"プレビュー: {len(_df_bonus)}件 / カラム: {list(_df_bonus.columns)}")

                if st.button("📥 ボーナス条件をインポート", key="bonus_csv_import", type="primary"):
                    # CSVを一時ファイルに保存してload_bonus_csvで読み込む
                    _bonus_csv_path = os.path.join(
                        _ROOT, "data", "bonus_conditions.csv"
                    )
                    os.makedirs(os.path.dirname(_bonus_csv_path), exist_ok=True)
                    _bonus_csv_uploaded.seek(0)
                    with open(_bonus_csv_path, 'wb') as _f:
                        _f.write(_bonus_csv_uploaded.read())

                    # キャッシュをリセットしてから再読み込み
                    jockey_analyzer._DBKEIBA_BONUS_CACHE.clear()
                    jockey_analyzer.load_bonus_csv(_bonus_csv_path)

                    _loaded_ids = len(jockey_analyzer._DBKEIBA_BONUS_CACHE)
                    _loaded_rows = sum(
                        len(v['add_100']) + len(v['add_90']) + len(v['sub_70']) + len(v['sub_60'])
                        for v in jockey_analyzer._DBKEIBA_BONUS_CACHE.values()
                    )
                    st.success(f"✅ {_loaded_ids}騎手 / {_loaded_rows}件のボーナス条件をインポートしました。")
                    st.caption("次回の分析実行時から自動的にスコアへ反映されます。")

            except Exception as _be:
                st.error(f"❌ ボーナスCSVエラー: {_be}")


        # 起動時: 傾向DBを自動ロード → 保存済みCSVがあれば上書き
        try:
            _DBKEIBA_BONUS_CACHE = jockey_analyzer._DBKEIBA_BONUS_CACHE
            JOCKEY_TENDENCY_DB = jockey_analyzer.JOCKEY_TENDENCY_DB
            get_tendency_as_bonus_dict = jockey_analyzer.get_tendency_as_bonus_dict
            load_bonus_csv = jockey_analyzer.load_bonus_csv
            # Step1: JOCKEY_TENDENCY_DBから既知騎手を自動ロード
            if not _DBKEIBA_BONUS_CACHE:
                for _jid_t, _tdata in JOCKEY_TENDENCY_DB.items():
                    _DBKEIBA_BONUS_CACHE[_jid_t] = get_tendency_as_bonus_dict(_jid_t)

            # Step2: 保存済みCSVがあれば追加ロード（CSV側が優先）
            _auto_bonus_path = os.path.join(
                _ROOT, "data", "bonus_conditions.csv"
            )
            if os.path.exists(_auto_bonus_path):
                load_bonus_csv(_auto_bonus_path)
        except Exception:
            pass



