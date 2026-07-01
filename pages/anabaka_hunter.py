# -*- coding: utf-8 -*-
"""🎯 穴馬ハンター — pages/anabaka_hunter.py

人気薄(6番人気以下)の中から「激走根拠のある穴馬」を探すダッシュボード。
妙味スキャナー(オッズ構造)とは別軸で、条件変更/前走内容/馬体/騎手など
定性的な激走シグナルを一覧し、フラグ数で穴馬候補を絞り込む。

⚠ 検証ステータスの正直な前提:
  ・末脚top3/単複乖離/ダート外枠は残差バックテスト済みの検証済エッジ
  ・距離短縮/初ブリ/騎手乗替/前走着差は人気に織込み済み(priced-in)が判明済み
   → 表示はするが「参考」ラベルを付け、穴馬判定のスコアには加算しない
"""
import os
import re
from datetime import datetime as _dt
import streamlit as st
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_weight_change(w_str):
    """馬体重文字列 '480(+4)' → (480, 4)。パース失敗は (None, None)。"""
    if not w_str or w_str == '発走前のため未公開':
        return None, None
    m = re.match(r'(\d+)\s*[\(（]\s*([+\-]?\d+)\s*[\)）]', str(w_str))
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r'(\d+)', str(w_str))
    if m2:
        return int(m2.group(1)), None
    return None, None


def _agari_rank_in_field(past_runs_all_horses, target_agari, race_idx=0):
    """全出走馬の前走(race_idx番目)上がり3F中の順位を返す。"""
    if not target_agari or target_agari <= 0:
        return None, 0
    agaris = []
    for pr_list in past_runs_all_horses:
        if pr_list and len(pr_list) > race_idx:
            a = _safe_float(pr_list[race_idx].get('Agari'))
            if a > 0:
                agaris.append(a)
    if not agaris:
        return None, 0
    rank = sum(1 for a in agaris if a < target_agari) + 1
    return rank, len(agaris)


def render():
    st.header("🎯 穴馬ハンター")
    st.caption(
        "人気薄(6番人気以下)の激走シグナルを一覧。"
        "**検証済**=バックテストで残差エッジ確認済み / **参考**=priced-inだが判断材料として表示"
    )

    # ── 入力 ──
    col_url, col_th = st.columns([3, 1])
    with col_url:
        race_url = st.text_input(
            "レースURL or ID",
            placeholder="https://race.netkeiba.com/race/shutuba.html?race_id=202505030211",
            key="hunter_url"
        )
    with col_th:
        pop_threshold = st.number_input("穴馬しきい値(人気)", min_value=4, max_value=18, value=6,
                                        help="この人気以下を穴馬候補とする", key="hunter_th")

    if not race_url:
        st.info("レースURLまたはIDを入力してください。")
        return

    # ── race_id 抽出 ──
    m = re.search(r'race_id=(\d{12})', str(race_url))
    if m:
        race_id = m.group(1)
    elif re.match(r'^\d{12}$', str(race_url).strip()):
        race_id = str(race_url).strip()
    else:
        st.error("12桁のレースIDを含むURLを入力してください。")
        return

    # ── スクレイピング ──
    with st.spinner("出馬表を取得中..."):
        try:
            from core.scraper import get_race_data, fetch_place_odds_api
            df = get_race_data(race_id, use_storage=False)
        except Exception as e:
            st.error(f"データ取得失敗: {e}")
            return

    if df is None or df.empty:
        st.warning("出馬表データが取得できませんでした。")
        return

    meta = df.attrs.get('metadata', {})
    race_name = meta.get('RaceName', df.iloc[0].get('RaceName', ''))
    surface = str(df.iloc[0].get('CurrentSurface', ''))
    dist = _safe_int(df.iloc[0].get('CurrentDistance'), 1600)
    jyo = str(race_id)[4:6]
    is_dirt = 'ダ' in surface
    is_handicap = meta.get('is_handicap', False)
    n_horses = len(df)

    st.subheader(f"{race_name}　{surface}{dist}m　{n_horses}頭")

    # ── Race Scanner連携: レースレベルの荒れ度+決着タイプ ──
    _rv_label = None
    if vs:
        _odds_all = [_safe_float(r.get('Odds')) for _, r in df.iterrows()
                     if _safe_float(r.get('Odds')) > 0]
        _rv = vs.race_value_score(_odds_all, meta, jyo, surface, dist, n_horses)
        _lean = vs.trio_lean(meta, n_horses, _rv['fav_odds'],
                             dist=dist, baba=str(meta.get('condition', '')),
                             odds_list=_odds_all)
        _rv_label = _rv['label']
        _lean_label = _lean['lean']
        _rv_color = {'S': '🔴', 'A': '🟢', 'B': '🟡', 'C': '🔵', 'D': '⚪'}
        _rv_icon = _rv_color.get(_rv_label[0], '')
        _lean_icon = {'②穴妙味向き': '🟠', '本線向き': '🔵', '中立': '⚪'}.get(_lean_label, '')
        cols_ctx = st.columns([2, 2, 2])
        with cols_ctx[0]:
            st.metric("荒れ度(Race Scanner)", f"{_rv_icon} {_rv['score']:.0f} {_rv_label}")
        with cols_ctx[1]:
            st.metric("決着タイプ", f"{_lean_icon} {_lean_label}")
        with cols_ctx[2]:
            st.markdown(
                f"[🔍 Single Race Analysis](/?race_id={race_id})"
                f"　[🔍 Race Scanner](/?nav=🔍 Race Scanner (Batch))"
            )
        if _rv['breakdown']:
            st.caption("荒れ度内訳: " + " / ".join(_rv['breakdown']))
        if _lean.get('pos') or _lean.get('neg'):
            _ln_parts = _lean.get('pos', []) + _lean.get('neg', [])
            st.caption("決着タイプ根拠: " + " / ".join(_ln_parts))

    # ── 複勝オッズ取得 ──
    place_odds = {}
    try:
        place_odds = fetch_place_odds_api(race_id) or {}
    except Exception:
        pass

    # ── JRA-VAN / モジュール読み込み ──
    jj = None
    try:
        from core import jockey_jv as jj
    except Exception:
        pass

    _tb = None
    try:
        from core import track_bias as _tb
    except Exception:
        pass

    vs = None
    try:
        from core import value_scanner as vs
    except Exception:
        pass

    # ── 南関東補完(nankankeiba.com): 大井/川崎/船橋/浦和の場合 ──
    _is_nankan = jyo in ('42', '43', '44', '45')
    _nankan_data = {}  # {馬名: {spurt_index, spurt_runs, ...}}
    if _is_nankan:
        try:
            from core import nankan_scraper as nk
        except Exception:
            nk = None
        if nk:
            nankan_id_input = st.text_input(
                "🐴 nankankeiba.com レースID (任意・末脚指数を計算)",
                placeholder="出馬表URL末尾の16桁数字 例: 2026070120050301",
                key="hunter_nankan_id",
                help="nankankeiba.com/syousai/XXXXXXXXXXXXXXXX.do のXXXX部分。"
                     "入力すると過去走上がり3Fから末脚指数を計算。"
            )
            nk_id = None
            if nankan_id_input:
                nm = re.search(r'(\d{16})', str(nankan_id_input))
                if nm:
                    nk_id = nm.group(1)
            if nk_id:
                with st.spinner("nankankeiba.com から過去走データを取得中..."):
                    try:
                        nk_entries = nk.fetch_entries(nk_id)
                        if nk_entries:
                            names = [str(r.get('Name', '')) for _, r in df.iterrows()]
                            name_to_id = nk.match_horses_by_name(names, nk_entries)
                            matched = sum(1 for v in name_to_id.values() if v)
                            st.caption(f"🐴 nankankeiba.com マッチ: {matched}/{len(names)}頭")
                            for horse_name, horse_id in name_to_id.items():
                                if not horse_id:
                                    continue
                                hist = nk.fetch_horse_history(horse_id)
                                if hist and hist.get('runs'):
                                    si, sr = nk.compute_spurt_index(hist['runs'])
                                    _nankan_data[horse_name] = {
                                        'spurt_index': si,
                                        'spurt_runs': sr,
                                        'sire': hist.get('sire', ''),
                                        'dam_sire': hist.get('dam_sire', ''),
                                        'runs': hist['runs'],
                                    }
                    except Exception as e:
                        st.warning(f"nankankeiba.com取得エラー: {e}")

    # ── レース条件 ──
    cond_tags = []
    if is_handicap:
        cond_tags.append("🏷️ ハンデ戦（荒れ+7.9pp 検証済）")
    if n_horses >= 16:
        cond_tags.append(f"🏷️ フルゲート{n_horses}頭（荒れ+3.4pp 検証済）")
    if n_horses <= 10:
        cond_tags.append(f"🏷️ 少頭数{n_horses}頭（堅傾向）")
    baba = meta.get('condition', '')
    if baba in ('重', '不良'):
        cond_tags.append(f"🏷️ 道悪({baba})")
    if cond_tags:
        st.info("　".join(cond_tags))

    # ── 全馬のPastRunsを収集(前走上がり順位計算用) ──
    all_past_runs = []
    for _, row in df.iterrows():
        all_past_runs.append(row.get('PastRuns', []) or [])

    # ── オッズ断層 ──
    gap_anchors = set()
    if vs:
        odds_map = {}
        for _, row in df.iterrows():
            u = row.get('Umaban')
            o = _safe_float(row.get('Odds'))
            if u and o > 0:
                odds_map[u] = o
        gap_anchors = vs.odds_gap_anchors(odds_map)

    # ── 穴馬候補を抽出 ──
    candidates = []
    for idx, row in df.iterrows():
        pop = _safe_int(row.get('Popularity'), 99)
        if pop < pop_threshold:
            continue

        odds = _safe_float(row.get('Odds'))
        name = str(row.get('Name', ''))
        umaban = _safe_int(row.get('Umaban'))
        waku = _safe_int(row.get('Waku'))
        jockey = str(row.get('Jockey', ''))
        sex_age = str(row.get('SexAge', ''))
        blinker_now = _safe_int(row.get('Blinker'))
        weight_str = str(row.get('Weight', ''))
        body_weight, weight_change = _parse_weight_change(weight_str)
        past_runs = row.get('PastRuns', []) or []
        prev = past_runs[0] if past_runs else {}

        signals_verified = []   # 検証済みエッジ
        signals_ref = []        # 参考(priced-in)
        info_items = []         # 情報表示

        # ===== A. 検証済みエッジ =====

        # A1. 単複乖離
        pm = None
        if place_odds and umaban in place_odds:
            pm = place_odds[umaban].get('Mid')
        if vs and pm is not None:
            div_lv, div_txt = vs.tanpuku_divergence(odds, pm)
            if div_lv > 0:
                signals_verified.append(f"💰 {div_txt}")
            if pm:
                info_items.append(f"複勝中間: {pm:.1f}倍")

        # A2. 末脚指数(JRA-VAN → nankankeiba.com フォールバック)
        ctx = None
        kt = None
        if jj:
            try:
                kt, tc = jj.resolve_horse(name)
                ctx = jj.horse_recent_context(kt) if kt else None
            except Exception:
                ctx = None
                tc = None
        si = (ctx or {}).get('spurt_index')
        sr = (ctx or {}).get('spurt_runs', 0)
        # nankankeiba.com補完: JRA-VAN未取得の場合
        if si is None and name in _nankan_data:
            nk_d = _nankan_data[name]
            si = nk_d.get('spurt_index')
            sr = nk_d.get('spurt_runs', 0)
        if si is not None and sr >= 2:
            # 末脚top3判定: レース内で上位3位以内のspurt_indexか
            if si >= 0.8:
                signals_verified.append(f"🔥 末脚指数{si:.2f}（top3圏 検証済エッジ）")
            else:
                info_items.append(f"末脚指数: {si:.2f}")

        # A3. ダート枠順シグナル
        if _tb and is_dirt:
            try:
                dsig = _tb.dirt_draw_signal(
                    waku=waku, ninki=pop, surface=surface, jyo=jyo,
                    kyori=dist
                )
                if dsig:
                    if dsig['type'] == 'boost':
                        signals_verified.append(f"🟢 {dsig['label']}（{dsig['detail']}）")
                    elif dsig['type'] == 'caution':
                        signals_ref.append(f"🟡 {dsig['label']}（{dsig['detail']}）")
            except Exception:
                pass

        # A4. オッズ断層
        if umaban in gap_anchors:
            signals_verified.append("📊 オッズ断層の上位グループ")

        # ===== B. 前走分析(参考) =====

        if prev:
            prev_rank = _safe_int(prev.get('Rank'), 99)
            prev_margin = _safe_float(prev.get('Margin'), 9.9)
            prev_dist = _safe_int(prev.get('Distance'))
            prev_surf = str(prev.get('Surface', ''))
            prev_agari = _safe_float(prev.get('Agari'))
            prev_pop = _safe_int(prev.get('Popularity'), 99)
            prev_passing = str(prev.get('Passing', ''))
            prev_jockey = str(prev.get('PrevJockey', ''))

            # 前走タイム差(参考)
            if prev_margin <= 0.3 and prev_rank >= 4:
                signals_ref.append(f"⏱️ 前走{prev_rank}着も僅差{prev_margin:.1f}秒差")
            elif prev_rank <= 3:
                info_items.append(f"前走{prev_rank}着({prev_margin:+.1f}秒差)")
            else:
                info_items.append(f"前走{prev_rank}着({prev_margin:+.1f}秒差)")

            # 前走上がり3F順位(参考)
            if prev_agari > 0:
                ag_rank, ag_total = _agari_rank_in_field(all_past_runs, prev_agari, 0)
                if ag_rank and ag_rank <= 3 and prev_rank >= 4:
                    signals_ref.append(f"⚡ 前走上がり{ag_rank}/{ag_total}位({prev_agari:.1f}秒)なのに{prev_rank}着")
                elif ag_rank:
                    info_items.append(f"前走上がり: {prev_agari:.1f}秒({ag_rank}/{ag_total}位)")

            # 前走ハイペース先行負け(参考)
            if prev_passing:
                positions = [_safe_int(p) for p in prev_passing.split('-') if p.strip()]
                if positions and positions[0] <= 3 and prev_rank >= 5:
                    signals_ref.append(f"🏃 前走先行({prev_passing})→{prev_rank}着（展開負け候補）")

            # 前走グレード(相手レベル: 格上挑戦からの降級)
            prev_grade = str(prev.get('Grade', ''))
            grade_order = {'G1': 8, 'G2': 7, 'G3': 6, 'OP': 5, '3勝': 4, '2勝': 3, '1勝': 2, '未勝利': 1, '新馬': 0}
            cur_class = str(meta.get('class', ''))
            pg = grade_order.get(prev_grade, -1)
            cg = grade_order.get(cur_class, -1)
            if pg >= 5 and prev_rank >= 4:
                signals_ref.append(f"🏆 前走{prev_grade}({prev_rank}着)→相手強かった")
            if pg > cg and pg >= 0 and cg >= 0:
                info_items.append(f"格下げ: {prev_grade}→{cur_class}")

            # 前走人気 vs 着順(力出せず判定)
            if prev_pop and prev_pop <= 5 and prev_rank >= 6:
                signals_ref.append(f"📉 前走{prev_pop}人気→{prev_rank}着（力出せず凡走）")

            # 距離変更(参考: priced-in)
            if prev_dist and prev_dist > 0:
                d_diff = dist - prev_dist
                if d_diff <= -200:
                    signals_ref.append(f"📏 距離短縮({prev_dist}→{dist}m)")
                elif d_diff >= 200:
                    signals_ref.append(f"📏 距離延長({prev_dist}→{dist}m)")
                else:
                    info_items.append(f"距離: {prev_dist}→{dist}m")

            # 芝↔ダート変更(参考)
            if prev_surf:
                prev_is_dirt = 'ダ' in prev_surf
                if prev_is_dirt and not is_dirt:
                    signals_ref.append("🔄 ダート→芝替わり")
                elif not prev_is_dirt and is_dirt:
                    is_first_dirt = (ctx or {}).get('dirt_runs', 0) == 0 if ctx else True
                    label = "初ダート" if is_first_dirt else "芝→ダート"
                    extras = []
                    if waku >= 6:
                        extras.append("外枠◎")
                    if body_weight and body_weight >= 460:
                        extras.append(f"{body_weight}kg◎")
                    tag = f"（{'・'.join(extras)}）" if extras else ""
                    signals_ref.append(f"🔄 {label}{tag}")

            # 騎手乗り替わり(参考)
            if prev_jockey and prev_jockey != '-':
                cur_jk = ''.join(jockey.split())
                prev_jk = ''.join(prev_jockey.split())
                if cur_jk and prev_jk and cur_jk != prev_jk:
                    is_top_new = jj.jockey_is_top(cur_jk) if jj else False
                    was_top = jj.jockey_is_top(prev_jk) if jj else False
                    if is_top_new and not was_top:
                        signals_ref.append(f"🏇 鞍上強化({prev_jockey}→{jockey})")
                    elif was_top and not is_top_new:
                        info_items.append(f"鞍上: {prev_jockey}→{jockey}(トップ騎手降り)")
                    else:
                        info_items.append(f"鞍上: {prev_jockey}→{jockey}")

        # ===== C. 馬体・馬具(参考) =====

        # 初ブリンカー
        if blinker_now and jj and kt:
            try:
                bh = jj.horse_blinker_history(kt)
                if bh and bh.get('blinker_runs', 0) == 0:
                    signals_ref.append("🔲 初ブリンカー")
            except Exception:
                pass

        # 馬体重
        if body_weight:
            info_items.append(f"馬体重: {body_weight}kg" +
                              (f"({weight_change:+d})" if weight_change is not None else ""))
            if weight_change is not None and abs(weight_change) >= 16:
                info_items.append(f"⚠ 馬体重大変動({weight_change:+d}kg)")

        # ===== C2. nankankeiba.com 血統補完 =====
        if name in _nankan_data:
            nk_d = _nankan_data[name]
            if nk_d.get('sire'):
                info_items.append(f"🐴父: {nk_d['sire']}")
            if nk_d.get('dam_sire'):
                info_items.append(f"🐴母父: {nk_d['dam_sire']}")

        # ===== D. 休み明け/叩き =====
        if ctx and ctx.get('prev_date'):
            try:
                pd_str = str(ctx['prev_date'])[:8]
                prev_dt = _dt.strptime(pd_str, '%Y%m%d')
                dv = meta.get('date_val', '')
                if dv and len(dv) >= 8:
                    race_dt = _dt.strptime(str(dv)[:8], '%Y%m%d')
                    gap_days = (race_dt - prev_dt).days
                    if gap_days >= 180:
                        info_items.append(f"🛌 長期休養明け({gap_days}日)")
                    elif gap_days >= 90:
                        info_items.append(f"🛌 中間休養明け({gap_days}日)")
            except Exception:
                pass

        # 叩き2走目: 2走前が長期休養明けで前走凡走→今走は実戦勘回復(参考)
        if len(past_runs) >= 2 and prev:
            prev2 = past_runs[1]
            prev_rank = _safe_int(prev.get('Rank'), 99)
            try:
                d1 = _dt.strptime(str(prev2.get('Date', '')).replace('.', ''), '%Y%m%d')
                d0 = _dt.strptime(str(prev.get('Date', '')).replace('.', ''), '%Y%m%d')
                gap_12 = (d0 - d1).days
                if gap_12 >= 120 and prev_rank >= 4:
                    signals_ref.append(f"🔄 叩き2走目（前走{gap_12}日ぶり→{prev_rank}着凡走後）")
            except Exception:
                pass

        # ===== E. 消去フラグ数(少ないほど良い) =====
        # elim_crossのフラグが少ない穴馬 = 消去されない = 地力ある
        elim_count = None
        try:
            from core.elim_cross import compute_flags, verified_count, band_fukusho
            last5_top3 = None
            if ctx:
                # 簡易: 直近5走3着内を推定(jravan context使用)
                pass  # elim_crossはapp.py側で別途計算済み → ここでは省略
        except Exception:
            pass

        # ===== 集計 =====
        n_verified = len(signals_verified)
        n_ref = len(signals_ref)

        candidates.append({
            'pop': pop,
            'odds': odds,
            'umaban': umaban,
            'waku': waku,
            'name': name,
            'jockey': jockey,
            'sex_age': sex_age,
            'signals_verified': signals_verified,
            'signals_ref': signals_ref,
            'info_items': info_items,
            'n_verified': n_verified,
            'n_ref': n_ref,
            'n_total': n_verified + n_ref,
        })

    if not candidates:
        st.warning(f"{pop_threshold}番人気以下の馬がいません（全{n_horses}頭）。")
        return

    # ── ソート: 検証済みフラグ数 → 参考フラグ数 → 人気順 ──
    candidates.sort(key=lambda c: (-c['n_verified'], -c['n_ref'], c['pop']))

    # ── サマリー ──
    has_verified = [c for c in candidates if c['n_verified'] > 0]
    if has_verified:
        names_v = ", ".join(f"**{c['name']}**({c['n_verified']})" for c in has_verified[:3])
        st.success(f"🎯 検証済みシグナル検出: {names_v}")
    else:
        st.info("検証済みシグナルを持つ穴馬候補はいません。参考情報を確認してください。")

    # ── 各馬の詳細表示 ──
    for c in candidates:
        emoji = "🎯" if c['n_verified'] >= 2 else ("💡" if c['n_verified'] >= 1 else "📋")
        with st.expander(
            f"{emoji} {c['umaban']}番 {c['name']}　"
            f"{c['pop']}人気 {c['odds']:.1f}倍　"
            f"検証済{c['n_verified']} / 参考{c['n_ref']}",
            expanded=(c['n_verified'] >= 1)
        ):
            col_v, col_r = st.columns(2)

            with col_v:
                st.markdown("##### 検証済みエッジ")
                if c['signals_verified']:
                    for s in c['signals_verified']:
                        st.markdown(f"- {s}")
                else:
                    st.caption("なし")

            with col_r:
                st.markdown("##### 参考情報（priced-in）")
                if c['signals_ref']:
                    for s in c['signals_ref']:
                        st.markdown(f"- {s}")
                else:
                    st.caption("なし")

            if c['info_items']:
                st.markdown("---")
                st.markdown("##### 基本データ")
                cols = st.columns(3)
                for i, item in enumerate(c['info_items']):
                    with cols[i % 3]:
                        st.caption(item)

    # ── 凡例 ──
    with st.expander("📖 シグナル定義と検証ステータス"):
        st.markdown("""
| シグナル | ステータス | 根拠 |
|---|---|---|
| 💰 単複乖離 | **検証済** | 単≥10倍×複≤3倍→勝率2.5→7%（残差+1.7pp） |
| 🔥 末脚top3 | **検証済** | 6番人気以下×末脚指数≥0.8→複勝率13.2%（ベース9.4%） |
| 🟢 ダート外枠 | **検証済** | 枠6-8×1-3人気→複勝残差+4.5pp(z+9.4) |
| 📊 オッズ断層 | **検証済** | 断層上位→3着内残差+3.9pp(z+12.3) |
| ⏱️ 前走僅差 | 参考 | 着差≤0.3秒は地力の証拠だが人気に織込み済み |
| ⚡ 前走上がり上位 | 参考 | 末脚を使えたが展開不向き。次走改善の可能性 |
| 🏃 先行負け | 参考 | ハイペース先行→展開負け。条件好転で巻き返し候補 |
| 📏 距離変更 | 参考 | 短縮/延長とも人気に織込み済み（俗説5案で検証） |
| 🔄 芝ダ替わり | 参考 | 初ダートは外枠+460kg+で期待↑だが検証n不足 |
| 🏇 鞍上強化 | 参考 | トップ騎手への乗替わり。勝負気配だが織込み済み |
| 🔲 初ブリンカー | 参考 | 集中力UP効果あるが定量検証不可(DB収録少) |
| 🏆 前走格上 | 参考 | 前走OP以上で凡走→相手が強かっただけの可能性 |
| 📉 前走力出せず | 参考 | 前走人気≤5位なのに6着以下→不利/条件不適の可能性 |
| 🔄 叩き2走目 | 参考 | 前走が長期休養明け初戦で凡走→実戦勘回復期待 |
""")
        if _is_nankan:
            st.markdown("""
---
**🐴 南関東補完 (nankankeiba.com)**

JRA-VANに地方競馬データがないため、nankankeiba.comのレースIDを入力すると
過去走の上がり3Fから末脚指数を計算します。nankankeiba.comの出馬表ページ
(`/syousai/XXXXXXXXXXXXXXXX.do`) のURLから16桁数字を入力してください。
""")
