# -*- coding: utf-8 -*-
"""🩸 血統SP（実験ラボ） — pages/blood_sp.py

血統だけでどこまで当たるかを試す実験場。種牡馬(父)・母父(BMS)の条件別成績(blood_dict.db: 既集計)
で、レースの出走馬を『血統スコア』順に並べ、実着順と見比べる。
良さげな信号が見つかったら必ず auto_feature_search でバックテストしてから強適スコアに採用する。

⚠検証メモ(2026-06): 血統は予測(着順当て)には完全に織込み済み=父×馬場(cond2)・母父(BMS)・
ニックス(cond6)とも LTR に上乗せ無し。唯一市場を破れた角度は『道悪(重・不良)×血統×人気上位帯』で、
これは予測でなく軸/消去の道具として core/track_bias.py に配線済み([[verified_baba_blood]])。
このラボはその検証済み判定の可視化＋探索用(予測器ではない)。
"""
import os
import sqlite3
import streamlit as st
import pandas as pd

try:
    from core import track_bias as _tb
except Exception:
    _tb = None

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')
_BLOOD_DB = os.path.join(_ROOT, 'data', 'blood_dict.db')

_POP_PLACE = 0.25  # 複勝率の母集団平均(縮小推定の事前値)
_SHRINK_K = 20     # 縮小係数(サンプルが少ない血統を母集団へ寄せる)


def _band(k):
    try:
        k = int(k)
    except Exception:
        return '中距離'
    if k <= 1400:
        return '短距離'
    if k <= 1800:
        return 'マイル'
    if k <= 2200:
        return '中距離'
    return '長距離'


def _ro(path):
    if not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
    except Exception:
        return None


def _lookup(blood, table, parent, surface, band):
    """blood_dict から (parent, surface, dist_band) の成績を引く。"""
    if not parent:
        return None
    try:
        r = blood.execute(
            f"SELECT runs, top3, wins, place_rate, win_rate, win_roi FROM {table} "
            f"WHERE parent=? AND surface=? AND dist_band=?", (parent, surface, band)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    runs, top3, wins, place_rate, win_rate, win_roi = r
    adj = (top3 + _SHRINK_K * _POP_PLACE) / (runs + _SHRINK_K) if runs else _POP_PLACE
    return {'runs': runs, 'top3': top3, 'place_rate': place_rate, 'win_rate': win_rate,
            'win_roi': win_roi, 'adj_place': adj}


def render():
    st.header("🩸 血統SP（実験ラボ）")
    st.caption("血統だけでどこまで当たるかを試す実験場。父(種牡馬)・母父(BMS)の条件別成績で出走馬を"
               "『血統スコア』順に並べ、実着順と見比べます。"
               "⚠血統は予測(着順当て)には完全に織込み済み(検証: 父×馬場cond2・母父/ニックスcond6とも"
               "LTRに上乗せ無し)。唯一の妙味は『道悪×血統×人気上位』(検証済→track_biasに配線済)。"
               "下表の『道悪判定』列がその検証済みシグナル。")

    blood = _ro(_BLOOD_DB)
    jv = _ro(_JV_DB)
    if blood is None or jv is None:
        st.error("blood_dict.db または jravan.db が見つかりません。")
        return

    tabA, tabB = st.tabs(["🏁 レース血統ランク", "🔎 種牡馬/母父しらべ"])

    # ── タブA: レースの馬を血統スコア順に ──
    with tabA:
        st.caption("過去レース(jravan.db収録)のIDを入れると、各馬の父・母父の条件別成績から"
                   "血統スコアを計算し、実着順と並べます。血統だけで何位まで当たるかの実験。")
        _c1, _c2, _c3 = st.columns([2, 1, 1])
        rid = _c1.text_input("レースID（過去・例: 202405021211）", key="blood_rid").strip()
        w_sire = _c2.slider("父の重み", 0.0, 1.0, 0.6, 0.1, key="blood_wsire")
        w_bms = round(1.0 - w_sire, 1)
        _c3.metric("母父の重み", f"{w_bms}")

        if rid:
            race = jv.execute(
                "SELECT surface, kyori, race_name, baba_shiba, baba_dirt, year, monthday, jyo "
                "FROM races WHERE race_id=? LIMIT 1", (rid,)).fetchone()
            horses = jv.execute(
                "SELECT r.umaban, r.ketto_num, r.bamei, r.chakujun, r.ninki "
                "FROM results r WHERE r.race_id=? AND r.chakujun>0 ORDER BY r.umaban", (rid,)).fetchall()
            if not race or not horses:
                st.warning("そのレースIDは jravan.db に見つかりません（未取込 or 入力ミス）。過去の中央レースで試してください。")
            else:
                surface, kyori, rname, _bsh, _bdt, _yr, _md, _jyo = race
                band = _band(kyori)
                # 実馬場状態(検証済み道悪判定用): 芝はbaba_shiba/ダはbaba_dirt
                _bcode = str(_bsh if (surface or '') == '芝' else _bdt)
                baba = {'1': '良', '2': '稍重', '3': '重', '4': '不良'}.get(_bcode, '不明')
                # 含水率(track_condにある日のみ)
                _moist = None
                try:
                    _mr = jv.execute(
                        "SELECT dirt_moisture FROM track_cond WHERE year=? AND monthday=? AND jyo=? LIMIT 1",
                        (_yr, _md, _jyo)).fetchone()
                    _moist = _mr[0] if _mr else None
                except Exception:
                    _moist = None
                _mtxt = f"・含水{_moist:.1f}%" if _moist is not None else ""
                st.markdown(f"**{rname or rid}**　{surface}{kyori}m（{band}）　馬場:{baba}{_mtxt}　{len(horses)}頭")
                rows = []
                for um, ketto, bamei, chaku, ninki in horses:
                    h = jv.execute("SELECT sire, bms FROM horses WHERE ketto_num=? LIMIT 1", (str(ketto),)).fetchone()
                    sire, bms = (h if h else (None, None))
                    s = _lookup(blood, 'sire_stats', sire, surface, band)
                    b = _lookup(blood, 'bms_stats', bms, surface, band)
                    s_adj = s['adj_place'] if s else _POP_PLACE
                    b_adj = b['adj_place'] if b else _POP_PLACE
                    score = (w_sire * s_adj + w_bms * b_adj) * 100
                    # ── 検証済み道悪判定(core/track_bias) ──
                    _verdict = '-'
                    if _tb is not None and sire:
                        _bm = _tb.heavy_fav_blood_mod(sire, surface, baba)
                        if _bm:
                            _verdict = _bm['flag']
                        elif _moist is not None and 'ダ' in (surface or ''):
                            _dm = _tb.dirt_moisture_bloodtype(sire, _moist)
                            if _dm:
                                _verdict = _dm['flag']
                    rows.append({
                        '馬番': um, '馬名': bamei, '父': sire or '-', '母父': bms or '-',
                        '父複勝%(n)': f"{s['place_rate']:.0f}%({s['runs']})" if s else '-',
                        '母父複勝%(n)': f"{b['place_rate']:.0f}%({b['runs']})" if b else '-',
                        '血統スコア': round(score, 1),
                        '道悪判定': _verdict,
                        '人気': ninki if ninki and ninki < 90 else '-',
                        '着順': chaku,
                    })
                df = pd.DataFrame(rows).sort_values('血統スコア', ascending=False).reset_index(drop=True)
                df.insert(0, '血統順', range(1, len(df) + 1))

                # 血統だけの的中チェック
                top3_blood = set(df.head(3)['馬番'])
                actual_top3 = set(df[df['着順'] <= 3]['馬番'])
                hit = len(top3_blood & actual_top3)
                winner_um = df[df['着順'] == 1]['馬番'].tolist()
                win_blood_rank = df[df['着順'] == 1]['血統順'].tolist()
                m1, m2 = st.columns(2)
                m1.metric("血統上位3頭 of 実3着内", f"{hit}/3")
                m2.metric("1着馬の血統順位", f"{win_blood_rank[0] if win_blood_rank else '-'}位")

                def _hl(row):
                    if row['着順'] == 1:
                        return ['background-color:#3a2e00;color:#FBC02D;font-weight:bold'] * len(row)
                    if row['着順'] <= 3:
                        return ['background-color:#1a2a1a;color:#A5D6A7'] * len(row)
                    return [''] * len(row)
                st.dataframe(df.style.apply(_hl, axis=1), hide_index=True, use_container_width=True)
                st.caption("黄=1着 / 緑=2-3着。血統順と着順がどれだけ一致するか観察。"
                           "血統スコア=父複勝率×重み＋母父複勝率×重み（サンプル少は母集団へ縮小推定）。"
                           "『道悪判定』🟢道悪軸=ダ重不良でシニミニ系等が好走(危険人気から免除)/"
                           "⚠瞬発系道悪=芝重不良でディープ・ステゴ系の人気馬は割引(検証済)。"
                           "※この妙味は人気上位(1-3番人気)で検証。良/稍重では発火しません。")

    # ── タブB: 種牡馬/母父の条件別成績しらべ ──
    with tabB:
        st.caption("種牡馬または母父の名前を入れて、馬場×距離別の産駒成績(blood_dict.db)を見る。")
        _b1, _b2, _b3 = st.columns([2, 1, 1])
        pname = _b1.text_input("血統名（部分一致・例: ディープインパクト / キングカメハメハ）", key="blood_pname").strip()
        ptype = _b2.radio("種別", ["父(種牡馬)", "母父(BMS)"], key="blood_ptype")
        min_runs = _b3.number_input("最小出走数", 0, 2000, 50, 10, key="blood_minruns")
        if pname:
            table = 'sire_stats' if ptype.startswith('父') else 'bms_stats'
            q = blood.execute(
                f"SELECT parent, surface, dist_band, runs, top3, wins, place_rate, win_rate, win_roi "
                f"FROM {table} WHERE parent LIKE ? AND runs>=? ORDER BY place_rate DESC",
                ('%' + pname + '%', int(min_runs))).fetchall()
            if not q:
                st.warning("該当なし（名前 or 最小出走数を調整）。")
            else:
                bdf = pd.DataFrame(q, columns=['血統', '馬場', '距離', '出走', '複勝', '勝', '複勝%', '勝率%', '単ROI%'])
                st.dataframe(bdf, hide_index=True, use_container_width=True)
                st.caption("⚠単ROIは分散大・小標本注意。複勝%×出走数の多い条件が信頼できる。"
                           "ここで強そうな血統条件を見つけたら、auto_feature_searchでバックテストして残差を確認。")

    blood.close()
    jv.close()
