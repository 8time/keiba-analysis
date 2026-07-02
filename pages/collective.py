# -*- coding: utf-8 -*-
"""🏛️ 集合知 — pages/collective.py

複数LLMエージェント(個性違い)がレースデータ+DB実データで討論する2ch風掲示板。
論文ベースの5つの改善:
  1. 自信度付き重み投票 (ReConcile)
  2. 匿名化ラウンド (権威バイアス除去)
  3. 回顧学習 (Self-Evolving Agent)
  4. モデル異種混合 (Wisdom of Crowds)
  5. 分科会方式 (Divide-and-Conquer)
"""
import os
import io
import streamlit as st
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _post_html(post, round_num=1):
    """2ch風の1レス表示HTML。"""
    colors = {1: ('#1a1a2e', '#333'), 2: ('#1e2a1e', '#2a4a2a'),
              3: ('#2e1a1a', '#4a2a2a'), 4: ('#2a1a2e', '#4a2a4a')}
    bg, border = colors.get(round_num, ('#1a1a2e', '#333'))
    model_tag = ''
    if post.get('model'):
        model_tag = f' <span style="color:#555; font-size:10px;">[{post["model"]}]</span>'
    return f"""
<div style="background:{bg}; border:1px solid {border}; border-radius:6px;
            padding:10px 14px; margin-bottom:8px; font-family:monospace;">
    <div style="color:#8b8b8b; font-size:12px; margin-bottom:4px;">
        <span style="color:#6c9bd2; font-weight:bold;">{post['no']}</span>
        ：<span style="color:#3cb371; font-weight:bold;">{post['icon']} {post['name']}</span>
        <span style="color:#666;"> {post.get('trip','')}</span>
        ：{post['timestamp']}
        <span style="color:#555; font-size:11px;">({post['elapsed']}s)</span>{model_tag}
    </div>
    <div style="color:#ddd; font-size:13px; line-height:1.6; white-space:pre-wrap;">{post['content']}</div>
</div>
"""


def render():
    st.header("🏛️ 集合知（エージェント掲示板）")
    st.caption(
        "個性の異なるLLMエージェントたちがDB実データで討論し、合議で予想。"
        "各エージェントは「知らないこと」が違う＝個性。"
        "論文ベース: 自信度重み投票 / 匿名化R2 / 回顧学習 / モデル混合 / 分科会方式。"
    )

    from core import agent_forum as _af

    if not _af.check_ollama():
        st.error(f"Ollamaに接続できません（{_af.OLLAMA_URL}）。\n\n"
                 "1. `ollama serve` で起動\n"
                 "2. `ollama pull qwen2.5:7b` でモデル取得")
        return

    # ── 設定 ──
    _all_models = _af.get_available_models()

    _roster = _af.agent_roster()
    _pick_mode = st.radio(
        "人格の選び方", ['人数で自動', '人格を選ぶ（情報の切り口で多様化）'],
        horizontal=True, key="cf_agent_mode",
        help="『人格を選ぶ』で情報の切り口(血統/展開/騎手/オッズ…)が異なる人格を組めば"
             "予想が脱相関しアンサンブル(合議)が効く。同じ切り口を並べると相関が上がり無意味")
    _selected_ids = None
    _c1, _c2 = st.columns([1, 1])
    with _c2:
        _use_multi_model = st.checkbox("モデル異種混合", value=False, key="cf_multi_model",
                                       help="複数モデルを混ぜて多様性を高める(Wisdom of Crowds)")
    if _pick_mode.startswith('人数'):
        with _c1:
            _n_agents = st.slider("エージェント数", 3, 50, 5, key="cf_n_agents",
                                  help="5=基本 / 15=全専門家 / 16+=分科会方式自動発動")
    else:
        with _c1:
            _lbl2id = {f"{a['icon']} {a['name']}（{a['focus']}）": a['id'] for a in _roster}
            _def_ids = {'ken', 'taku', 'kei', 'riku', 'mari'}
            _defaults = [k for k, v in _lbl2id.items() if v in _def_ids]
            _picked = st.multiselect(
                "参加する人格（情報の切り口が被らないほど脱相関＝合議が効く）",
                list(_lbl2id.keys()), default=_defaults, key="cf_pick_agents")
            _selected_ids = [_lbl2id[k] for k in _picked]
        _n_agents = max(1, len(_selected_ids))
        # 情報の切り口の多様性を見える化(同じ切り口の重複=相関上昇の警告)
        _focuses = [next(a['focus'] for a in _roster if a['id'] == i) for i in _selected_ids]
        _uniq = sorted(set(_focuses))
        st.caption(f"🔗 情報の切り口: {'/'.join(_uniq)}（{len(_uniq)}種）"
                   + ("　⚠ 同じ切り口が重複＝予想が相関しやすい" if len(_uniq) < len(_focuses) else "　🟢 全て異なる切り口=良い多様性"))

    if _use_multi_model and len(_all_models) > 1:
        _selected_models = st.multiselect(
            "使用モデル（複数選択）", _all_models,
            default=_all_models[:min(3, len(_all_models))],
            key="cf_models_multi")
        _model = _selected_models[0] if _selected_models else _af.OLLAMA_MODEL
    else:
        _model = st.selectbox("LLMモデル", _all_models or [_af.OLLAMA_MODEL], key="cf_model")
        _selected_models = [_model]

    with st.expander("⚙️ 詳細設定", expanded=False):
        _s1, _s2, _s3 = st.columns(3)
        with _s1:
            _anonymous_r2 = st.checkbox("R2匿名化", value=True, key="cf_anon",
                                         help="権威バイアス除去: 誰が言ったか隠す")
        with _s2:
            _use_group = st.checkbox("分科会方式", value=(_n_agents > 15), key="cf_group",
                                      help="15体超で自動ON: 5体グループ→代表者会議")
        with _s3:
            _group_size = st.number_input("グループサイズ", 3, 10, 5, key="cf_gsize")

        # 回顧学習の過去戦績
        _retro = _af.load_retrospective(5)
        if _retro:
            _r_with_result = [r for r in _retro if r.get('result')]
            if _r_with_result:
                st.caption(f"📚 回顧学習: 直近{len(_r_with_result)}戦の記録あり → 各エージェントのsystem promptに自動注入中")

    # エージェント生成（人格選択 or 人数自動・モデル混合対応）
    _mdls = _selected_models if (_use_multi_model and len(_selected_models) > 1) else None
    if _selected_ids is not None:
        _agents = _af.agents_by_ids(_selected_ids, models=_mdls)
        if not _agents:
            st.warning("人格を1体以上選んでください（暫定で基本5人格を使用）。")
            _agents = _af.generate_agents(5, models=_mdls)
    else:
        _agents = _af.generate_agents(_n_agents, models=_mdls)

    with st.expander(f"👥 エージェント一覧 ({len(_agents)}体)", expanded=False):
        _ag_cols = st.columns(min(3, max(1, len(_agents))))
        for i, ag in enumerate(_agents):
            with _ag_cols[i % len(_ag_cols)]:
                model_tag = f"  \n`{ag['model']}`" if ag.get('model') else ""
                st.markdown(f"**{ag['icon']} {ag['name']}**  \n{ag['trip']}{model_tag}")

    st.divider()

    # ── データ入力 ──
    st.markdown("### 📋 レースデータ投入")
    _tab_auto, _tab_manual = st.tabs(["🏠 強適テーブルから自動取得", "📝 手動入力"])

    _csv_text = None
    _meta_text = ''
    _meta_dict = None
    _race_id = None

    with _tab_auto:
        st.caption("先にSRAでレースを解析してからここに来てください。")
        try:
            from core import score_cache as _sc
            _bridge_df, _bridge_meta, _bridge_rid = _sc.read_magi_bridge()
            if _bridge_df is not None and not _bridge_df.empty:
                _race_id = _bridge_rid
                _kf_v = str(_bridge_rid)[4:6] if _bridge_rid and len(str(_bridge_rid)) >= 6 else '01'
                _kf_dom = 'nar.netkeiba.com' if (_kf_v.isdigit() and int(_kf_v) > 10) else 'race.netkeiba.com'
                st.markdown(
                    f"🔗 [netkeibaでこのレースを開く](https://{_kf_dom}/race/shutuba.html?race_id={_bridge_rid})"
                    f"　｜　レースID: `{_bridge_rid}`　｜　{len(_bridge_df)}頭"
                )
                _show_cols = [c for c in [
                    'Umaban', 'Name', 'Popularity', 'Odds',
                    'BattleScore', 'Projected Score', 'SpeedIndex',
                    'AvgAgari', 'AvgPosition', 'Suitability (Y)',
                    'sire', 'broodmareSire', 'WeightHistory',
                ] if c in _bridge_df.columns]
                _export_df = _bridge_df[_show_cols].copy() if _show_cols else _bridge_df
                _rename = {
                    'Umaban': '馬番', 'Name': '馬名', 'Popularity': '人気',
                    'Odds': '単勝オッズ', 'BattleScore': '戦闘力',
                    'Projected Score': '予測スコア', 'SpeedIndex': 'スピード指数',
                    'AvgAgari': '平均上がり', 'AvgPosition': '平均位置取り',
                    'Suitability (Y)': '適性', 'sire': '父',
                    'broodmareSire': '母父', 'WeightHistory': '馬体重',
                }
                _export_df = _export_df.rename(columns={k: v for k, v in _rename.items()
                                                         if k in _export_df.columns})
                st.dataframe(_export_df, hide_index=True, use_container_width=True, height=200)
                _buf = io.StringIO()
                _export_df.to_csv(_buf, index=False)
                _csv_text = _buf.getvalue()
                _meta_parts = []
                if _bridge_meta:
                    _meta_dict = _bridge_meta
                    for k in ['race_name', 'surface', 'distance', 'condition', 'grade']:
                        v = _bridge_meta.get(k)
                        if v:
                            _meta_parts.append(f"{k}: {v}")
                _meta_text = ' / '.join(_meta_parts) if _meta_parts else f'Race ID: {_bridge_rid}'
            else:
                st.info("SRAで解析済みデータがありません。先に🏠で解析してください。")
        except Exception as e:
            st.warning(f"データ読込エラー: {e}")

    with _tab_manual:
        _manual_meta = st.text_input("レース情報（任意）",
                                     placeholder="例: 東京11R 安田記念 芝1600m 良",
                                     key="cf_manual_meta")
        _manual_csv = st.text_area("出走馬データ（CSV形式）", height=200,
                                   placeholder="馬番,馬名,人気,単勝オッズ,戦闘力,父,母父\n1,ウマA,3,5.2,85.3,ディープ,キンカメ\n...",
                                   key="cf_manual_csv")
        if _manual_csv.strip():
            _csv_text = _manual_csv.strip()
            _meta_text = _manual_meta.strip()

    if not _csv_text:
        st.info("👆 レースデータを投入すると、エージェントたちが議論を始めます。")
        return

    st.divider()

    # ── 掲示板 ──
    _K1, _K2, _K3, _KG = 'cf_r1_posts', 'cf_r2_posts', 'cf_r3_posts', 'cf_group_posts'

    # ── 分科会方式 ──
    if _use_group and _n_agents > _group_size:
        st.markdown(f"### 💬 分科会方式 ({_n_agents}体 → {_group_size}体×{(_n_agents+_group_size-1)//_group_size}グループ)")
        _run_group = st.button("🏛️ 分科会討論スタート", key="cf_run_group",
                               type="primary", use_container_width=True)
        if _run_group:
            _bar = st.progress(0, text="分科会準備中...")
            def _gcb(i, total, name):
                _bar.progress(min((i + 1) / max(total, 1), 1.0), text=f"{name}")
            group_posts, rep_posts, final_ranking = _af.run_group_discussion(
                _csv_text, _meta_text, agents=_agents, model=_model,
                progress_cb=_gcb, meta=_meta_dict, group_size=_group_size)
            st.session_state[_KG] = {
                'group_posts': group_posts,
                'rep_posts': rep_posts,
                'ranking': final_ranking,
            }
            _bar.empty()

        if _KG in st.session_state:
            gd = st.session_state[_KG]
            with st.expander("📡 分科会討論（全投稿）", expanded=False):
                for p in gd['group_posts']:
                    st.markdown(_post_html(p, round_num=1), unsafe_allow_html=True)
            st.markdown("#### 👑 代表者会議")
            for p in gd['rep_posts']:
                st.markdown(_post_html(p, round_num=4), unsafe_allow_html=True)

            st.divider()
            st.markdown("### 📊 合議結果（自信度重み付き）")
            ranking = gd['ranking']
            if ranking:
                _show_ranking(ranking, _af, _race_id, _meta_text)
        return

    # ── 通常3ラウンド ──
    st.markdown("### 💬 予想スレッド")
    _has_r1 = _K1 in st.session_state
    _has_r2 = _K2 in st.session_state

    _b1, _b2, _b3 = st.columns(3)
    with _b1:
        _run_r1 = st.button("📡 R1: 各自の予想", key="cf_run_r1",
                            type="primary", use_container_width=True)
    with _b2:
        _r2_label = "🔥 R2: 匿名議論" if _anonymous_r2 else "🔥 R2: 相互議論"
        if _has_r1:
            _run_r2 = st.button(_r2_label, key="cf_run_r2",
                                type="primary", use_container_width=True)
        else:
            st.button(_r2_label, key="cf_run_r2", use_container_width=True, disabled=True)
            _run_r2 = False
    with _b3:
        if _has_r2:
            _run_r3 = st.button("⚖️ R3: 最終弁論", key="cf_run_r3",
                                type="primary", use_container_width=True)
        else:
            st.button("⚖️ R3: 最終弁論", key="cf_run_r3",
                      use_container_width=True, disabled=True)
            _run_r3 = False

    if _run_r1:
        st.session_state.pop(_K2, None)
        st.session_state.pop(_K3, None)
        _bar = st.progress(0, text="エージェント準備中...")
        def _cb1(i, total, name):
            _bar.progress((i + 1) / total, text=f"{name} が予想中... ({i+1}/{total})")
        posts = _af.run_discussion(
            _csv_text, _meta_text, agents=_agents, model=_model,
            progress_cb=_cb1, meta=_meta_dict)
        st.session_state[_K1] = posts
        _bar.empty()
        st.rerun()

    if _run_r2:
        _bar = st.progress(0, text="議論準備中...")
        def _cb2(i, total, name):
            _bar.progress((i + 1) / total, text=f"{name} が反論中... ({i+1}/{total})")
        debate = _af.run_debate(
            st.session_state[_K1], _csv_text, _meta_text,
            agents=_agents, model=_model, progress_cb=_cb2,
            meta=_meta_dict, anonymous=_anonymous_r2)
        st.session_state[_K2] = debate
        _bar.empty()
        st.rerun()

    if _run_r3:
        _bar = st.progress(0, text="最終弁論準備中...")
        def _cb3(i, total, name):
            _bar.progress((i + 1) / total, text=f"{name} が最終回答中... ({i+1}/{total})")
        all_prior = st.session_state[_K1] + st.session_state[_K2]
        final = _af.run_final_defense(
            all_prior, _csv_text, _meta_text,
            agents=_agents, model=_model, progress_cb=_cb3, meta=_meta_dict)
        st.session_state[_K3] = final
        _bar.empty()

    # ── スレッド表示 ──
    if _K1 in st.session_state:
        st.markdown("#### 📡 第1ラウンド（独立予想）")
        for p in st.session_state[_K1]:
            st.markdown(_post_html(p, round_num=1), unsafe_allow_html=True)

        if _K2 in st.session_state:
            st.markdown("---")
            _r2_label = "第2ラウンド（匿名議論）" if _anonymous_r2 else "第2ラウンド（相互議論）"
            st.markdown(f"#### 🔥 {_r2_label}")
            for p in st.session_state[_K2]:
                st.markdown(_post_html(p, round_num=2), unsafe_allow_html=True)

        if _K3 in st.session_state:
            st.markdown("---")
            st.markdown("#### ⚖️ 第3ラウンド（最終弁論）")
            for p in st.session_state[_K3]:
                st.markdown(_post_html(p, round_num=3), unsafe_allow_html=True)

        # ── 合議結果 ──
        st.divider()
        st.markdown("### 📊 合議結果（自信度重み付き）")

        if _K3 in st.session_state:
            _agg_target = st.session_state[_K3]
            _agg_label = "最終弁論(R3)の集計"
        elif _K2 in st.session_state:
            _agg_target = st.session_state[_K1] + st.session_state[_K2]
            _agg_label = "R1+R2の集計"
        else:
            _agg_target = st.session_state[_K1]
            _agg_label = "R1の集計"

        st.caption(_agg_label)
        ranking = _af.aggregate_predictions(_agg_target)
        if ranking:
            _show_ranking(ranking, _af, _race_id, _meta_text,
                          session_posts=(st.session_state.get(_K1, []) +
                                        st.session_state.get(_K2, []) +
                                        st.session_state.get(_K3, [])))

            # 🔗 エージェント相関診断: 人格が冗長(高相関)ならアンサンブルの意味が薄い
            with st.expander("🔗 エージェント相関診断（多様性チェック）", expanded=False):
                st.caption("アンサンブル(合議)が効くのは各人格が**独立した誤り**をする時だけ(記事の"
                           "『効かない条件=全モデルが同じ誤差』)。予想が高相関=冗長=平均する意味が薄い。"
                           "結果は不要=過去の予想だけで測れます。")
                try:
                    _corr = _af.agent_pick_correlation()
                    if _corr['n_races'] < 3 or _corr['mean_corr'] is None:
                        st.info(f"📊 {_corr['note']}（現在 {_corr['n_races']} レース分）")
                    else:
                        _mc = _corr['mean_corr']
                        _col = "🔴" if _mc >= 0.7 else "🟠" if _mc >= 0.4 else "🟢"
                        st.metric("平均ペア相関", f"{_col} {_mc:+.2f}",
                                  help="0.7以上=冗長(多様性なし) / 0.4未満=良い多様性")
                        _red = _corr['redundancy']
                        if _red:
                            _sorted = sorted(_red.items(), key=lambda x: x[1])
                            st.markdown(f"🟢 **最も独立**: {_sorted[0][0]}（平均相関{_sorted[0][1]:+.2f}）"
                                        f"　/　🔴 **最も冗長**: {_sorted[-1][0]}（{_sorted[-1][1]:+.2f}）")
                        _hi = [p for p in _corr['pairs'] if p['corr'] is not None and p['corr'] >= 0.7]
                        if _hi:
                            st.warning("⚠ 高相関ペア(冗長)＝どちらかは要らない or 直交エッジに紐付け直し: "
                                       + " / ".join(f"{p['a']}↔{p['b']}({p['corr']:+.2f})" for p in _hi[:6]))
                        st.caption(_corr['note'])
                except Exception as _ce:
                    st.caption(f"（相関診断スキップ: {_ce}）")

            if _K3 in st.session_state:
                with st.expander("📈 ラウンド別推移", expanded=False):
                    for rnd_label, rnd_key in [("R1", _K1), ("R2", _K2), ("R3", _K3)]:
                        if rnd_key in st.session_state:
                            rnd_agg = _af.aggregate_predictions(st.session_state[rnd_key])
                            if rnd_agg:
                                top3 = ' / '.join(
                                    f'{um}番={v["weighted"]:.1f}pt(自信{v.get("avg_conf",50):.0f}%)'
                                    for um, v in rnd_agg[:3])
                                st.markdown(f"**{rnd_label}**: {top3}")
        else:
            st.caption("予想フォーマット(◎XX番)が検出できませんでした。")
    else:
        st.markdown(
            '<div style="background:#111; border:1px solid #333; border-radius:8px; '
            'padding:40px; text-align:center; color:#666;">'
            '📡 「R1: 各自の予想」を押すとエージェントたちが予想を書き込みます'
            '</div>',
            unsafe_allow_html=True)

    # ── 回顧学習: 結果記入 ──
    st.divider()
    with st.expander("📚 回顧学習（レース結果の記録）", expanded=False):
        st.caption("レース結果を入力すると、次回から各エージェントの的中/外れが学習に反映されます。")
        _rc1, _rc2 = st.columns([2, 1])
        with _rc1:
            _result_input = st.text_input("3着内の馬番（カンマ区切り）",
                                          placeholder="例: 3,7,1",
                                          key="cf_result_input")
        with _rc2:
            _result_rid = st.text_input("レースID", value=_race_id or '', key="cf_result_rid")
        if st.button("結果を記録", key="cf_record_result"):
            if _result_input and _result_rid:
                try:
                    top3 = [int(x.strip()) for x in _result_input.split(',') if x.strip().isdigit()]
                    _af.record_result(_result_rid, top3)
                    st.success(f"記録完了: {_result_rid} → 3着内 {top3}")
                except Exception as e:
                    st.error(f"記録エラー: {e}")

        _retro_records = _af.load_retrospective(10)
        if _retro_records:
            _rr_with = [r for r in _retro_records if r.get('result')]
            if _rr_with:
                st.caption(f"記録済み: {len(_rr_with)}戦")
                for r in reversed(_rr_with[-5:]):
                    res = r['result']
                    st.markdown(f"  {r['date']} {r['meta'][:30]}… → {res.get('top3',[])} "
                                f"{'✅' if res.get('consensus_hit') else '❌'}")


def _show_ranking(ranking, _af, race_id, meta_text, session_posts=None):
    """合議結果テーブルと保存ボタン。"""
    _agg_rows = []
    for um, v in ranking:
        marks = ' '.join(v['agents'])
        _agg_rows.append({
            '馬番': um,
            '◎': v['honmei'],
            '○': v['taikou'],
            '▲': v['anaume'],
            '重みpt': round(v['weighted'], 1),
            '自信度': f"{v.get('avg_conf', 50):.0f}%",
            '支持': marks,
        })
    st.dataframe(pd.DataFrame(_agg_rows), hide_index=True, use_container_width=True)

    _top = ranking[0]
    _consensus = f"**合議◎ {_top[0]}番**（{_top[1]['weighted']:.1f}pt / 自信{_top[1].get('avg_conf',50):.0f}%）"
    if len(ranking) > 1:
        _s = ranking[1]
        _consensus += f" / **○ {_s[0]}番**（{_s[1]['weighted']:.1f}pt）"
    if len(ranking) > 2:
        _t = ranking[2]
        _consensus += f" / **▲ {_t[0]}番**（{_t[1]['weighted']:.1f}pt）"
    st.success(f"🏆 {_consensus}")

    # 🧠 Brier加重合議（カード8=過去成績で当たらないペルソナの票を自動で軽くする）
    if session_posts:
        try:
            _w = _af.agent_weights()  # 台帳から。精算済み成績が無ければ {}
            if _w:  # 成績がある時だけ表示（無ければ均等=上と同じなので出さない）
                _wc = _af.weighted_consensus(session_posts, _w)
                if _wc:
                    _wtop = " / ".join(f"{um}番({v['weighted']:.1f}pt)" for um, v in _wc[:3])
                    st.info(f"🧠 **Brier加重合議（成績反映版）**: {_wtop}\n\n"
                            "※過去に当てたペルソナの票を重く・外し続けたペルソナを軽くした版。"
                            "上の均等版と食い違う時は、成績の裏付けがある加重版を優先。")
        except Exception:
            pass

    # 回顧学習に保存
    if race_id and session_posts and st.button("💾 この予測を回顧学習に保存", key="cf_save_retro"):
        consensus_data = {
            'top3_umaban': [ranking[i][0] for i in range(min(3, len(ranking)))],
        }
        agent_picks = _af.extract_agent_picks(session_posts)
        _af.save_prediction(race_id, meta_text, consensus_data, agent_picks)
        st.success("保存しました。レース後に結果を記入すると学習に反映されます。")
