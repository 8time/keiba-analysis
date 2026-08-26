# -*- coding: utf-8 -*-
"""🎯 穴馬ハンター — pages/anabaka_hunter.py

人気薄(6番人気以下)の中から「激走根拠のある穴馬＝妙味のある馬(市場が過小評価する3着内候補)」を
探すダッシュボード。穴馬(人気薄)と妙味馬(過小評価)は定義は違うが、ここでは混ぜて扱う。
条件変更/前走内容/馬体/騎手などのシグナルを一覧し、検証済エッジの合議(combo)で候補を絞る。

検証(scripts/value_longshot_research.py・7番人気以下の3着内傾向・直近3ヶ月+2.5年):
  検証済シグナル(🔵補正T z23 / 🧬血統 / 🔥末脚 / 🏃位置3以内 / 👑騎手 / ⚡33 / 🧬回収)の
  同時発火数comboが多いほど3着内率が単調上昇: combo0=4%→2=10%→4=19%(基準7.7%)。
  =妙味馬はcombo馬。単発の弱いシグナルだけの馬(combo0)はむしろ基準の半分で消し。

⚠ 検証ステータスの正直な前提:
  ・補正T/血統/末脚/位置取り/騎手/33/血統回収・combo・単複乖離・ダート外枠=残差バックテスト済み
  ・距離短縮/初ブリ/騎手乗替/前走着差は人気に織込み済み(priced-in)が判明済み
   → 表示はするが「参考」ラベルを付け、妙味判定のスコアには加算しない
  ・道悪×血統は1-3番人気の表示のみ(wet_fav_notes)。穴馬カード・点数・並びには入れない

【今後の予定】最終的にSRA内の『💀消し推奨馬(予測スコア下位30%)』『🎯推奨穴馬(Top Dark Horse)』を
置き換えてそこへ設置。表示はTop Dark Horseカード形式に寄せる。
"""
import os
import re
import html as _html
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


def _html_oneline(s):
    """Streamlit の markdown は、改行＋インデントの </div> を字面で出すことがある。1行に潰す。"""
    if not s:
        return ''
    return re.sub(r'\s*\n\s*', '', str(s)).strip()


def combo_n_of(umaban, combo_map):
    """合議の同時発火数。キーが int/str どちらでも取る。"""
    if not combo_map:
        return 0
    try:
        u = int(umaban)
    except (TypeError, ValueError):
        return 0
    v = combo_map.get(u)
    if v is None:
        v = combo_map.get(str(u))
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def blood_hi_umabans(df, surface, dist, bands):
    """血統の見立てが人気より上の馬番。点数には使わない。"""
    if df is None or getattr(df, 'empty', True) or not bands:
        return set()
    from core import blood_ev as bev
    hs = []
    for _, r in df.iterrows():
        u = _safe_int(r.get('Umaban'), 0)
        if not u:
            continue
        pop_m = re.search(r'\d+', str(r.get('Popularity', '') or ''))
        hs.append({
            'umaban': u,
            'sire': r.get('sire'),
            'bms': r.get('broodmareSire'),
            'odds': r.get('Odds'),
            'ninki': int(pop_m.group()) if pop_m else None,
        })
    if not hs:
        return set()
    marked = bev.annotate_race(hs, surface, dist, bands)
    return {int(r['umaban']) for r in marked if r.get('blood_label') == '高い'}


def attention_marks_html(combo=0, blood_hi=False):
    """精鋭・広域網の注目印。VHスコアには足さない。両方付いても加点しない。"""
    parts = []
    try:
        n = int(combo or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 2:
        parts.append(
            '<span style="display:inline-block;margin:0 8px 6px 0;padding:6px 12px;'
            'border-radius:6px;background:#c62828;color:#fff;font-weight:800;'
            'font-size:1.02em;letter-spacing:0.02em;">🎯 濃い穴'
            '<span style="font-weight:600;font-size:0.82em;opacity:0.92;">'
            '｜印が2つ以上</span></span>'
        )
    if blood_hi:
        parts.append(
            '<span style="display:inline-block;margin:0 8px 6px 0;padding:6px 12px;'
            'border-radius:6px;background:#6a1b9a;color:#fff;font-weight:800;'
            'font-size:1.02em;">🩸 血統注目'
            '<span style="font-weight:600;font-size:0.82em;opacity:0.92;">'
            '｜見立てが人気より上</span></span>'
        )
    if not parts:
        return ''
    return (
        '<div style="margin:8px 0 4px 0;">'
        + ''.join(parts) + '</div>'
    )


def attention_marks_md(combo=0, blood_hi=False):
    """SRAカード用の同じ印（markdown）。点数には足さない。"""
    bits = []
    try:
        n = int(combo or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 2:
        bits.append('🎯 **濃い穴**（印が2つ以上）')
    if blood_hi:
        bits.append('🩸 **血統注目**（見立てが人気より上）')
    return '　'.join(bits)


def wet_fav_notes(horses, surface, baba, tb_mod):
    """道悪のとき、1〜3番人気だけ血統メモを返す。表示専用。点数・並びには使わない。

    検証: 道悪×血統は人気上位だけで残る。6番人気以下の穴・逆張りは織込み済み。
    horses: umaban / name / ninki / sire を持つ dict の list。
    """
    if not tb_mod or baba not in ('重', '不良'):
        return []
    lines = []
    ranked = []
    for h in horses or []:
        try:
            nk = int(h.get('ninki') or 99)
        except (TypeError, ValueError):
            continue
        if 1 <= nk <= 3:
            ranked.append((nk, h))
    ranked.sort(key=lambda x: x[0])
    for nk, h in ranked:
        sire = str(h.get('sire') or '').strip()
        if not sire or sire == '-':
            continue
        bm = tb_mod.heavy_fav_blood_mod(sire, surface, baba)
        if not bm:
            continue
        um = h.get('umaban') or '?'
        nm = str(h.get('name') or '').strip()
        if bm.get('mod') == 'exempt':
            icon, why = '🟢', 'ダートの道悪で来やすい父'
        elif bm.get('mod') == 'intensify':
            icon, why = '⚠', '芝の道悪では人気ほど来にくい父'
        else:
            continue
        lines.append(f"{icon} {nk}人気 {um}番 {nm} … {why}")
    return lines


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
        "人気薄(6番人気以下)の激走シグナル＝**妙味のある馬(市場が過小評価する3着内候補)** を発見するツール。"
        "穴馬(人気薄)と妙味馬(過小評価)は定義は違うが、ここでは混ぜて扱う。"
        "**検証済**=バックテストで残差エッジ確認済み / **参考**=priced-inだが判断材料として表示。"
        "検証(scripts/value_longshot_research.py・7番人気以下の3着内傾向)では、検証済シグナルの同時発火数"
        "(combo)が多いほど3着内率が単調に上昇: combo0=4%→combo2=10%→combo4=19%(基準7.7%)。"
        " 穴の点数はオッズ＋補正Tのまま。"
        "その上で、赤い **濃い穴**＝印が2つ以上、紫の **血統注目**＝血統の見立てが人気より上"
        "（精鋭・広域網だけ。点数・順番には入れていません）。"
    )

    # ── 入力 ──
    # Race Scannerなどからのリンク(?race_id=...)を受けたら自動入力→そのまま自動分析開始。
    _qp_race_id = st.query_params.get('race_id')
    if _qp_race_id and st.session_state.get('hunter_url_from_qp') != _qp_race_id:
        st.session_state['hunter_url'] = _qp_race_id
        st.session_state['hunter_url_from_qp'] = _qp_race_id

    col_url, col_th = st.columns([3, 1])
    with col_url:
        race_url = st.text_input(
            "レースURL or ID",
            placeholder="https://race.netkeiba.com/race/shutuba.html?race_id=202505030211",
            key="hunter_url"
        )
    with col_th:
        # 既定6は動かさない。検証(scripts/longshot_threshold_backtest.py)で、4に下げると
        # 候補に4-5番人気が入りVHが人気順の劣化版になる(少頭数×堅いでVH2頭 59.1% vs
        # 人気2頭 59.6% ＝ -0.5ppで負ける)ことが判明したため。
        # 少頭数×堅いレースでは代わりに『相手候補(4-5番人気)』を別枠で案内する(下部)。
        pop_threshold = st.number_input("穴馬しきい値(人気)", min_value=4, max_value=18, value=6,
                                        help="この人気以下を穴馬候補とする。"
                                             "既定6は検証済み（4に下げると穴馬スコアが"
                                             "人気順とほぼ同じになり独自の価値が消えます）。"
                                             "逆ショッカーのリーチだけは4・5番人気も別枠で出します。",
                                        key="hunter_th")

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
    vs = None
    try:
        from core import value_scanner as vs
    except Exception:
        vs = None
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
    baba = str(meta.get('condition', '') or '')
    if baba in ('重', '不良'):
        cond_tags.append(f"🏷️ 道悪({baba})")
    if cond_tags:
        st.info("　".join(cond_tags))
    # 道悪×血統は人気上位の確認用。穴馬カードへは出さない・点数にも足さない。
    if baba in ('重', '不良'):
        _wet_hs = []
        for _, _wr in df.iterrows():
            _wsire = str(_wr.get('sire') or '').strip()
            if (not _wsire or _wsire == '-') and jj:
                try:
                    _wkt, _ = jj.resolve_horse(str(_wr.get('Name', '')))
                    if _wkt and _tb:
                        _wsire = _tb.sire_of_ketto(_wkt) or ''
                except Exception:
                    pass
            _wet_hs.append({
                'umaban': _safe_int(_wr.get('Umaban')),
                'name': str(_wr.get('Name', '')),
                'ninki': _safe_int(_wr.get('Popularity'), 99),
                'sire': _wsire,
            })
        _wet_lines = wet_fav_notes(_wet_hs, surface, baba, _tb)
        st.markdown(
            f"🩸 **馬場が{baba}です。** 血統は **1〜3番人気の軸を疑う／信じる** 材料です。"
            "下の穴馬カードの点数・並び・買い目には入れていません"
            "（穴での血統逆張りは、検証で残っていません）。"
        )
        if _wet_lines:
            for _wl in _wet_lines:
                st.caption(_wl)
        else:
            st.caption("1〜3番人気に、道悪で特に見る父はいません。能力はそのまま見てください。")
        st.caption("詳しい見方は左メニュー 🩸 血統SP。")
    elif baba == '稍重':
        st.caption(
            "稍重：人気上位に道悪向きの血統があるか、だけ軽く見る日です。"
            "穴馬の点数には使いません。"
        )

    # ── 🎯相手候補(4-5番人気) ── 少頭数×堅いレースでのみ表示 ──
    # 穴馬(6番人気以降＝市場の見落とし)とは**役割が違う**ので別枠にする。
    # 検証(scripts/longshot_threshold_backtest.py・少頭数×堅い4,991R):
    #   3着内が全て5番人気以内で決まる率が60.1%(多頭数32.1%の約2倍)
    #   → ここでは穴を掘るより上位人気の取りこぼしを防ぐ方が現実に合う。
    # ⚠ この帯は市場が既に評価済みなので、選び方はVHではなく**人気順**が正しい
    #   (同プール内でVH上位2頭は人気上位2頭に -0.5pp 負ける)。
    try:
        from core import longshot_threshold as _lst
        _cb = _lst.companion_band(df, meta)
    except Exception:
        _cb = None
    if _cb:
        _comp = []
        for _, _cr in df.iterrows():
            _cp = _safe_int(_cr.get('Popularity'), 99)
            if _cb['lo'] <= _cp <= _cb['hi']:
                _comp.append((_cp, _safe_int(_cr.get('Umaban')),
                              str(_cr.get('Name', '')), _safe_float(_cr.get('Odds'))))
        _comp.sort()
        if _comp:
            st.success(
                f"🎯 **相手候補（{_cb['lo']}〜{_cb['hi']}番人気）** — {_cb['reason']}　"
                + " ／ ".join(f"**{u}番 {nm}**（{p}人気 {o:.1f}倍）"
                              for p, u, nm, o in _comp))
            st.caption(
                "このレース形（少頭数×上位人気が堅い）では、**3着内が全て5番人気以内で"
                "決まる率が60.1%**（多頭数32.1%の約2倍・4,991R実測）。"
                "穴を掘るより上位人気の取りこぼしを防ぐ方が現実に合います。"
                "この帯は市場が既に評価済みなので、下の穴馬スコアではなく**人気順**で"
                "見てください（同じ範囲では穴馬スコアは人気順に負けます）。"
                "※穴馬しきい値は6のまま維持しています。")

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

    # ── 妙味馬ハンター 軽量スコア(検証済 recall70%@2.09x) ──
    # build_edge_setsが補正T/末脚/血統/combo/消去/オッズからvh_score(市場順序+補正T連続量)を返す。
    _vh_map = {}; _vh_tier = {}; _vh_edge_reasons = {}; _combo_map = {}
    try:
        from core import consensus_view as _cvh
        _aim_vh = _cvh.build_edge_sets(df, meta, race_id)
        _vh_map = _aim_vh.get('vh') or {}
        _vh_tier = _aim_vh.get('vh_tier') or {}
        _vh_edge_reasons = _aim_vh.get('edge_reasons') or {}
        _combo_map = _aim_vh.get('combo') or {}
    except Exception:
        pass

    # 血統注目は表示専用。網（精鋭・広域）に入った馬だけカードに出す。
    _blood_hi = set()
    try:
        from core import blood_ev as _bev_h
        _bands_h = st.session_state.get('_blood_ev_bands')
        if _bands_h is None:
            _bands_h = _bev_h.calibrate_bands()
            st.session_state['_blood_ev_bands'] = _bands_h
        _blood_hi = blood_hi_umabans(df, surface, dist, _bands_h)
    except Exception:
        _blood_hi = set()

    # 『前走内容』モジュール(表示専用・netkeibaのみ/JRA-VAN不使用)
    try:
        from core import prev_race as _prv
    except Exception:
        _prv = None
    try:
        from core import gyaku_shocker as _gys
    except Exception:
        _gys = None
    _gys_c3_ranks = {}
    if _gys:
        try:
            from core import ai_tenkai as _ait_h
            _gys_pk = f"nkt_pos_{race_id}"
            if _gys_pk not in st.session_state:
                st.session_state[_gys_pk] = _ait_h.fetch_tenkai_positions(race_id)
            _gys_pos_h = st.session_state.get(_gys_pk) or {}
            _gys_c3_ranks = _ait_h.ranks_from_left(
                {u: (v or {}).get('corner3') for u, v in _gys_pos_h.items()})
        except Exception:
            _gys_c3_ranks = {}

    def _gyaku_from_row(row):
        """全頭のリーチ判定。表示専用。スコア・しきい値には使わない。"""
        if not _gys:
            return None
        past_runs = row.get('PastRuns', []) or []
        prev = past_runs[0] if past_runs else {}
        try:
            hit = _gys.reach(prev.get('Distance'), dist, str(prev.get('Passing') or ''))
            if not isinstance(hit, dict):
                return None
            bw, _ = _parse_weight_change(str(row.get('Weight', '')))
            out = _gys.with_memo(
                hit,
                past_runs=past_runs,
                current_distance=dist,
                current_surface=surface,
                body_weight=bw,
                race_date=meta.get('date_val'),
                prev_date=prev.get('Date'),
            )
            out = _gys.with_pair(out, prev.get('Rank'), prev.get('Margin'))
            _pc3 = _gys_c3_ranks.get(_safe_int(row.get('Umaban')))
            _c3line = _gys.pred_c3_memo(_pc3)
            if _c3line:
                out['memo_lines'] = list(out.get('memo_lines') or []) + [_c3line]
            return out
        except Exception:
            return None

    # 逆ショッカーは公式リストどおり全頭に出る。穴馬しきい値(既定6)は動かさない
    # （4に下げるとVHが人気順の劣化版になる・verified）。4-5番人気のリーチだけここで別表示。
    _GYAKU_MID_LO = 4
    _gyaku_by_um = {}
    _gyaku_mid = []    # 4〜しきい値直前
    _gyaku_fav = []    # 1〜3番人気（本命側）
    for _, _gr in df.iterrows():
        _gu = _safe_int(_gr.get('Umaban'))
        if not _gu:
            continue
        _gg = _gyaku_from_row(_gr)
        if not _gg:
            continue
        _gyaku_by_um[_gu] = _gg
        _gp = _safe_int(_gr.get('Popularity'), 99)
        _item = (_gp, _gu, str(_gr.get('Name', '')), _safe_float(_gr.get('Odds')), _gg)
        if _GYAKU_MID_LO <= _gp < pop_threshold:
            _gyaku_mid.append(_item)
        elif _gp < _GYAKU_MID_LO:
            _gyaku_fav.append(_item)
    _gyaku_mid.sort()
    _gyaku_fav.sort()
    if _gyaku_mid:
        st.markdown("#### 逆ショッカー（4〜5番人気）")
        st.caption(
            "穴馬しきい値は6のままです。逆ショッカーのリーチは4・5番人気にもあるので、"
            "ここだけ別枠で出します。穴馬スコア・順番・買い目には入れていません。"
        )
        for _gp, _gu, _gn, _go, _gg in _gyaku_mid:
            _od = f"{_go:.1f}倍" if _go else "-"
            _pm = _gys.pair_prefix(_gg) if _gys else ''
            st.markdown(
                f"**{_pm}{_gu}番 {_html.escape(_gn)}**（{_gp}人気 {_od}）"
            )
            if _gys:
                st.markdown(_gys.block_html(_gg), unsafe_allow_html=True)
    if _gyaku_fav:
        st.caption(
            "1〜3番人気のリーチ: "
            + " ／ ".join(f"{u}番 {nm}（{p}人気）" for p, u, nm, _o, _g in _gyaku_fav)
            + "　本命側なので穴馬カードには出しません。"
        )

    _VH_BADGE_PFX = [
        ('🔵補正T', '🔵'), ('🔥末脚', '🔥'), ('⚡33', '⚡'),
        ('👑騎手', '👑'), ('⭐黄金', '⭐'), ('🏠厩舎', '🏠'),
        ('🧬血統回収', '💰'), ('🧬血統', '🧬'), ('🟢道悪', '🟢'),
    ]
    def _vh_badges(um):
        bs = []
        for r in (_vh_edge_reasons.get(um) or []):
            rs = str(r)
            for pfx, icon in _VH_BADGE_PFX:
                if rs.startswith(pfx) and icon not in bs:
                    bs.append(icon)
                    break
        return bs

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
                    # コース巧者への乗替(検証:乗替一律は織込み済みだが乗替先が当コース上位だと弱いプラス傾向)。
                    # スコアには加算せず参考表示(holdout有意水準未満のため)。
                    try:
                        _jcw = jj.jockey_course_winrate(jockey, jyo, surface) if jj else None
                        if _jcw and _jcw.get('runs', 0) >= 30 and (_jcw.get('win_rate') or 0) >= 0.15:
                            signals_ref.append(
                                f"🎇 コース巧者への乗替({jockey}=当コース勝率{_jcw['win_rate']*100:.0f}%"
                                f"・複勝{_jcw['top3_rate']*100:.0f}%／検証で弱いプラス傾向・参考)")
                    except Exception:
                        pass

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

        _bdg = _vh_badges(umaban)
        # 『前走内容』(表示専用・core/prev_race.py)。ここでは追加フェッチをせず、
        # 出馬表HTMLに元から入っている情報だけを取り出す。3着馬との差は後段で一括取得。
        # ⚠ スコア/ソート/材料数には一切influenceさせない(表示のみ)。
        _pv = None
        try:
            _pv = _prv.extract(past_runs) if _prv else None
            if _pv:
                _pv['_name'] = name
        except Exception:
            _pv = None
        _gyaku = _gyaku_by_um.get(umaban)
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
            'vh_score': _vh_map.get(umaban),
            'vh_tier': _vh_tier.get(umaban, ''),
            'badges': _bdg,
            'prev': _pv,
            # 逆ショッカー／濃い穴／血統注目は表示専用。材料数・ソートには入れない。
            'gyaku': _gyaku,
            'combo_n': combo_n_of(umaban, _combo_map),
            'blood_hi': umaban in _blood_hi,
        })

    if not candidates:
        st.warning(f"{pop_threshold}番人気以下の馬がいません（全{n_horses}頭）。")
        return

    # ── 『前走内容』の3着馬との差を一括取得(穴馬候補のみ・race_id単位で重複排除) ──
    # 前走race_idは出馬表HTMLに元から入っているため、race_idを得るための取得は不要。
    # 3着馬との差を出すため前走レース結果を1レースにつき1回だけ取得する
    # (同じ前走を走った馬が複数いても共有)。結果はレース単位でsession_stateにキャッシュ。
    # ⚠ ここで得た情報は表示専用。vh_score/妙味/ソート順/材料数には一切反映しない。
    if _prv:
        _pv_cache_key = f"_prevrace_results_{race_id}"
        _pv_cache = st.session_state.setdefault(_pv_cache_key, {})
        _pv_list = [c['prev'] for c in candidates if c.get('prev')]
        _pv_rids = _prv.collect_race_ids(_pv_list)
        _pv_todo = [r for r in _pv_rids if r not in _pv_cache]
        if _pv_todo:
            with st.spinner(f"前走レース結果を取得中… {len(_pv_todo)}件"
                            f"（穴馬候補{len(_pv_list)}頭ぶん・重複は共有）"):
                try:
                    _prv.fetch_results(_pv_todo, cache=_pv_cache)
                except Exception as _e_pv:
                    st.caption(f"（前走結果の取得を一部スキップ: {_e_pv}）")
        for _pv in _pv_list:
            try:
                _prv.attach_third_margin(_pv, _pv_cache)
            except Exception:
                pass

    # ── ソート: 妙味馬スコア(軽量vh)降順 → 検証済みフラグ数 → 人気順 ──
    # vhが使えないレース(オッズ欠損等)は従来のフラグ数ソートにフォールバック。
    candidates.sort(key=lambda c: (-(c['vh_score'] or -1), -c['n_verified'], -c['n_ref'], c['pop']))
    _max_bdg = max((len(c.get('badges', [])) for c in candidates), default=0)

    # ── 2カラムレイアウト: 左=精鋭 / 右=広域網 ──
    _elite = [c for c in candidates if c['vh_tier'] == '🎯精鋭']
    _net = [c for c in candidates if c['vh_tier'] == '🕸️広域網']
    _other = [c for c in candidates if c['vh_tier'] not in ('🎯精鋭', '🕸️広域網')]

    def _render_prev_detail(pv):
        """『前走内容』の詳細ブロック(見出し→条件→事実行)。表示専用。"""
        st.markdown("**前走内容**（表示専用・妙味スコアには影響しません）")
        _hd = _prv.detail_header(pv)
        _cd = _prv.detail_condition(pv)
        if _hd:
            st.markdown(f"**{_hd}**")
        if _cd:
            st.caption(_cd)
        for _k, _v in _prv.detail_rows(pv):
            if _k in ('3着馬との差', '1着馬', '2着馬') and _prv.is_close_margin(pv):
                st.markdown(
                    f"{_html.escape(_k)}：{_prv.emphasize_close_seconds(_v, pv)}",
                    unsafe_allow_html=True)
            else:
                st.caption(f"{_k}：{_v}")
        _b = _prv.badge(pv)
        if _b:
            st.markdown(f"<span style='color:#b8860b;font-weight:bold;'>{_b}</span>",
                        unsafe_allow_html=True)

    def _render_card(c, rank, tier='elite'):
        _bdgs_c = c.get('badges', [])
        _is_top = (rank == 1)
        _sc = f"{c['vh_score']*100:.0f}" if c['vh_score'] is not None else '-'
        _bdg_str = ''.join(_bdgs_c)
        if _is_top:
            _bg = '#fff0f0' if tier == 'elite' else '#fffde7'
            _bd_color = '#e57373' if tier == 'elite' else '#ffd54f'
        else:
            _bg = '#ffffff'
            _bd_color = '#e0e0e0'
        _trophy_txt = '🏆 ' if _is_top else ''
        _pair_txt = _gys.pair_prefix(c.get('gyaku')) if _gys else ''
        # 注目印は精鋭・広域網だけ。点数・順番には入れない。両方付いても加点しない。
        _attn_html = attention_marks_html(
            c.get('combo_n'), bool(c.get('blood_hi')))
        _badge_html = (f"{_bdg_str}　<b>{len(_bdgs_c)}材料</b>") if _bdgs_c else \
                      '<span style="color:#999">材料 0</span>'
        # 『前走内容』行(表示専用・妙味/材料数とは別軸なので区切り線で分ける)
        _pv_c = c.get('prev')
        _pv_html = ''
        _gys_html = _gys.block_html(c.get('gyaku')) if _gys else ''
        _gys_line = f'<br>{_gys_html}' if _gys_html else ''
        if _prv and _pv_c:
            _pv_sum = _prv.summary_line(_pv_c)
            _pv_mgn_html = _prv.margin_line_html(_pv_c)
            _pv_bdg = _prv.badge(_pv_c)
            if _pv_sum:
                _pv_html = (
                    '<div style="margin-top:8px;padding-top:6px;'
                    'border-top:1px dashed #ddd;font-size:0.92em;line-height:1.6;">'
                    f'<span style="color:#777">前走：</span>{_html.escape(_pv_sum)}'
                    + (f'<br>{_pv_mgn_html}' if _pv_mgn_html else '')
                    + (f'<br><span style="color:#b8860b;font-weight:bold;">{_html.escape(_pv_bdg)}</span>'
                       if _pv_bdg else '')
                    + _gys_line
                    + '</div>'
                )
            elif _gys_html:
                _pv_html = (
                    '<div style="margin-top:8px;padding-top:6px;'
                    'border-top:1px dashed #ddd;font-size:0.92em;line-height:1.6;">'
                    f'{_gys_html}</div>'
                )
        elif _gys_html:
            _pv_html = (
                '<div style="margin-top:8px;padding-top:6px;'
                'border-top:1px dashed #ddd;font-size:0.92em;line-height:1.6;">'
                f'{_gys_html}</div>'
            )
        st.markdown(_html_oneline(f'''<div style="
            background:{_bg};border:1px solid {_bd_color};
            border-radius:8px;padding:12px 16px;margin-bottom:4px;">
            <div style="font-weight:bold;font-size:1.05em;">
                {_trophy_txt}{_pair_txt}{rank}位　{c['umaban']}番 {c['name']}
            </div>
            {_attn_html}
            <div style="margin-top:4px;">
                {c['pop']}人気　{c['odds']:.1f}倍　　妙味 <b>{_sc}</b>
            </div>
            <div style="margin-top:4px;">{_badge_html}</div>
            {_pv_html}
        </div>'''), unsafe_allow_html=True)
        with st.expander("前走内容 / 検証済み / 参考 / 基本データ", expanded=False):
            if _gys_html:
                st.markdown(_html_oneline(_gys_html), unsafe_allow_html=True)
                st.caption("出走前に分かる条件だけ（前走は後ろめ＋今回は距離が短い）。完成は今回3角8番手以内で、レース後にしか分かりません。下の ↔バウンド／↔芝⇔ダ は読み補助です。点数には入れていません。")
            if _prv and _pv_c:
                _render_prev_detail(_pv_c)
                st.markdown("---")
            if c['signals_verified']:
                st.markdown("**検証済みエッジ**")
                for s in c['signals_verified']:
                    st.markdown(f"- {s}")
            if c['signals_ref']:
                st.markdown("**参考（priced-in）**")
                for s in c['signals_ref']:
                    st.markdown(f"- {s}")
            if c['info_items']:
                st.markdown("**基本データ**")
                for item in c['info_items']:
                    st.caption(item)
            if not c['signals_verified'] and not c['signals_ref'] and not c['info_items']:
                st.caption("情報なし")
            elif (not c['signals_verified'] and not c['signals_ref']
                    and len(c['info_items']) <= 1):
                st.caption(
                    "過去走が少なく、出せる数字がほとんどありません。"
                    "3歳未勝利ではよくあります。"
                )

    if _elite or _net:
        _col_l, _col_r = st.columns(2)
        with _col_l:
            st.markdown("#### 🎯 精鋭")
            st.caption("3着内率≈17-20%　基準の2.6倍。赤い「濃い穴」と紫の「血統注目」は見る順番用（点数には入れていません）。")
            if _elite:
                for _i, _c in enumerate(_elite):
                    _render_card(_c, _i + 1, tier='elite')
            else:
                st.info("該当なし")
        with _col_r:
            st.markdown("#### 🕸️ 広域網")
            st.caption("3着内率≈16%　基準の2.1倍。赤い「濃い穴」と紫の「血統注目」は見る順番用（点数には入れていません）。")
            if _net:
                for _i, _c in enumerate(_net):
                    _render_card(_c, _i + 1, tier='net')
            else:
                st.info("該当なし")
        st.caption(
            "🏆＝妙味スコア1位（検証済: 穴が来る時の的中率22%・ランダム8%の2.8倍）。"
            "材料(🔵🔥⚡👑⭐🏠🧬💰🟢)は判断参考＝数が多い馬を選ぶと逆効果（VH1位が+4pp勝ち・検証済）。"
            "⚠『3着内に来る馬の網羅リスト』であって『+EVリスト』ではありません。"
        )
        st.caption(
            "🎯 **濃い穴**＝検証の印が2つ以上重なった穴。🩸 **血統注目**＝血統の見立てが人気より上。"
            "穴を見つけるのは妙味スコア（オッズ＋補正T）のまま。"
            "そのあと、濃い穴 → 血統注目、の順で見る印です。"
            "両方付いても点数は足しません（「最注目」にもしません）。"
            "📋その他の穴馬には出しません。"
        )
        st.caption(
            "紫字 **🟣 逆ショッカー候補** ＝「前走は3角5番手より後ろ」かつ「今回は距離が短い」。"
            "下の ↔バウンド／↔芝⇔ダ と体重・間隔は、その候補を読むための事実メモです（○や加点ではありません）。"
            "見た目の判断材料だけで、**適合（完成）ではありません**。"
            "原典の完成は今回3角8番手以内＝レースが終わるまで分からない情報です。"
            "以前の検証では完成まで入れると当たったように見えますがリークで、"
            "候補だけだと妙味は消えています。点数・順番・買い目には入れていません。"
            "4〜5番人気のリーチは上の別枠（穴馬しきい値は6のまま）。"
            " **🟣⏱️** ＝逆ショッカー候補と、前走が4着以下で勝ち馬まで0.3秒以内、が重なった印。"
            "見つけやすくするための見た目だけで、点数・順番・買い目には入れていません。"
        )
    else:
        st.info("🎯精鋭・🕸️広域網に該当する穴馬候補はいません。")

    # ── tier外の穴馬候補 ──
    if _other:
        st.divider()
        st.markdown("#### 📋 その他の穴馬候補")
        st.caption(
            "精鋭・広域網に入らなかった穴馬です。精鋭が少ないときに、ここから別の穴を探す材料。"
            "前走の差がプラスでもマイナスでも **0.5秒以内** なら秒数だけ赤字"
            "（3着馬との差。取れなければ1着馬との差）。"
            "見た目だけの印で、妙味スコアや買い目には入れていません。"
            " 紫字 **🟣 逆ショッカー候補** も同じ（前走は後ろめ＋今回は距離が短い。完成ではない）。"
            "候補の下の ↔バウンド／↔芝⇔ダ と体重・間隔は読み補助の事実です。"
            " **🟣⏱️** が名前の前にある馬は、逆ショッカー候補と前走僅差が重なっています（見るだけ）。"
        )
        for _c in _other:
            _pv_o = _c.get('prev')
            _pv_sum_o = _prv.summary_line(_pv_o) if (_prv and _pv_o) else ''
            _pv_mgn_o = _prv.margin_line_html(_pv_o) if (_prv and _pv_o) else ''
            _pv_bdg_o = _prv.badge(_pv_o) if (_prv and _pv_o) else ''
            _gys_o = _gys.block_html(_c.get('gyaku')) if _gys else ''
            _nm_o = _html.escape(str(_c['name']))
            _sum_esc = _html.escape(_pv_sum_o) if _pv_sum_o else ''
            _bdg_esc = _html.escape(_pv_bdg_o) if _pv_bdg_o else ''
            # expander見出しは色が付けられないので、秒数の赤字・紫字はここに出す。
            st.markdown(
                _html_oneline(
                    f'<div style="padding:8px 12px 4px 12px;border:1px solid #eee;'
                    f'border-radius:8px 8px 0 0;background:#fafafa;">'
                    f'<b>{_gys.pair_prefix(_c.get("gyaku")) if _gys else ""}{int(_c["umaban"])}番 {_nm_o}</b>　'
                    f'{_c["pop"]}人気 {_c["odds"]:.1f}倍　'
                    f'<span style="color:#888">検証済{_c["n_verified"]} / 参考{_c["n_ref"]}</span>'
                    + (f'<br><span style="color:#777">前走：</span>{_sum_esc}' if _sum_esc else '')
                    + (f'　{_pv_mgn_o}' if _pv_mgn_o else '')
                    + (f'　<span style="color:#b8860b;font-weight:bold;">{_bdg_esc}</span>'
                       if _bdg_esc else '')
                    + (f'<br>{_gys_o}' if _gys_o else '')
                    + '</div>'
                ),
                unsafe_allow_html=True,
            )
            with st.expander(
                f"前走内容 / 検証済み / 参考 / 基本データ　"
                f"（{_c['umaban']}番 {_c['name']}）",
                expanded=False
            ):
                if _gys and _c.get('gyaku'):
                    st.markdown(_gys.block_html(_c.get('gyaku')), unsafe_allow_html=True)
                    st.caption("出走前の条件だけ。完成（今回3角8番手以内）はまだ分かりません。")
                if _prv and _pv_o:
                    _render_prev_detail(_pv_o)
                    st.markdown("---")
                if _c['signals_verified']:
                    st.markdown("**検証済みエッジ**")
                    for s in _c['signals_verified']:
                        st.markdown(f"- {s}")
                if _c['signals_ref']:
                    st.markdown("**参考（priced-in）**")
                    for s in _c['signals_ref']:
                        st.markdown(f"- {s}")
                if _c['info_items']:
                    st.markdown("**基本データ**")
                    for item in _c['info_items']:
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
| 赤字の秒数（±0.5秒以内） | 表示のみ | 📋その他などで前走の差が0.5秒以内なら秒数を赤字。スコアには足さない |
| 🟣 逆ショッカー候補 | 表示のみ | 前走3角5番手以降＋今回距離短縮。↔バウンド／↔芝⇔ダは事実メモ（加点しない） |
| 🟣⏱️ ショッカー×僅差 | 表示のみ | 逆ショッカー候補かつ前走4着以下・勝ち馬まで0.3秒。印だけで加点しない |
| 🎯 濃い穴 | 表示のみ | 精鋭・広域網で検証の印が2つ以上。見る順番用。点数・並びには入れない |
| 🩸 血統注目 | 表示のみ | 精鋭・広域網かつ血統の見立てが人気より上。見る順番用。点数には足さない |
| ⚡ 前走上がり上位 | 参考 | 末脚を使えたが展開不向き。次走改善の可能性 |
| 🏃 先行負け | 参考 | ハイペース先行→展開負け。条件好転で巻き返し候補 |
| 📏 距離変更 | 参考 | 短縮/延長とも人気に織込み済み（俗説5案で検証） |
| 🔄 芝ダ替わり | 参考 | 初ダートは外枠+460kg+で期待↑だが検証n不足 |
| 🏇 鞍上強化 | 参考 | トップ騎手への乗替わり。勝負気配だが織込み済み |
| 🔲 初ブリンカー | 参考 | 集中力UP効果あるが定量検証不可(DB収録少) |
| 🏆 前走格上 | 参考 | 前走OP以上で凡走→相手が強かっただけの可能性 |
| 📉 前走力出せず | 参考 | 前走人気≤5位なのに6着以下→不利/条件不適の可能性 |
| 🔄 叩き2走目 | 参考 | 前走が長期休養明け初戦で凡走→実戦勘回復期待 |
| ⭐ 重賞で好走 / 重賞で3着馬と接戦 | **検証済**（表示専用） | 前走が重賞/L かつ 3着馬との差≤0.3秒（文言は前走着順で変わるだけで条件は同一） |
""")
        st.markdown("""
---
**⭐ 重賞で好走 / ⭐ 重賞で3着馬と接戦 について**

「前走が重賞またはL」かつ「前走の3着馬との差が0.3秒以内」に該当した事実を表示するものです。
文言は前走1〜3着なら「重賞で好走」、4着以下なら「重賞で3着馬と接戦」と変わりますが、
**判定条件は同一**です。
**AI評価でも妙味でもありません。** 妙味スコア・材料数・順位には一切影響しません。

検証内容（4期間・2016〜2026年6月）:
Rank(能力評価)の分位で統制しても3着内率が**+5.5〜9pp**上がることを全期間で確認。
ただし**複勝の回収率は安定してプラスにならず**、さらに穴馬ハンターの対象母集団
(7番人気以下)で妙味スコアを統制すると追加効果はほぼ0でした。
＝「当たりやすさは上がるが市場も既に知っている」情報のため、
**スコアには組み込まず、人間が最終比較するための材料としてのみ表示**しています。

⚠ 前走の3着馬との差が取得できなかった場合、条件を満たさないとは扱わず
バッジを表示しません（推測で補完しません）。
""")
        if _is_nankan:
            st.markdown("""
---
**🐴 南関東補完 (nankankeiba.com)**

JRA-VANに地方競馬データがないため、nankankeiba.comのレースIDを入力すると
過去走の上がり3Fから末脚指数を計算します。nankankeiba.comの出馬表ページ
(`/syousai/XXXXXXXXXXXXXXXX.do`) のURLから16桁数字を入力してください。
""")
