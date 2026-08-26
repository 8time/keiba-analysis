# -*- coding: utf-8 -*-
"""🩸 血統SP（実験ラボ） — pages/blood_sp.py

研究用: 血統だけでどこまで当たるかを試す。本番の予想の主役ではない。
種牡馬(父)・母父(BMS)の条件別成績(blood_dict.db)で出走馬を血統スコア順に並べ、実着順と見比べる。

⚠検証: 父×馬場(cond2)・母父/ニックス(cond6)・血統×コース形状・父×当該場は LTR に上乗せ無し。
本番で見るのは『道悪×血統×人気上位』(track_bias) と『場×人気の軸信頼度』(血統ではなく場)。
血統期待値の『高い』は見比べ用。点数・買い目には入れない。
"""
import os
import re
import sqlite3
import streamlit as st
import pandas as pd

try:
    from core import track_bias as _tb
except Exception:
    _tb = None

try:
    from core import blood_course as _bc
except Exception:
    _bc = None

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
    if k <= 1300:
        return '短距離'
    if k <= 1899:
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


def _extract_race_id(raw):
    """12桁IDでも出馬表URLでもレースIDを取る。取れなければ空文字。"""
    s = str(raw or '').strip()
    if not s:
        return ''
    m = re.search(r'race_id=(\d{12,16})', s, re.I)
    if m:
        return m.group(1)
    m = re.search(r'(\d{12,16})', s)
    if m:
        return m.group(1)
    return ''


def _normalize_parent(name):
    """英語名+国コード除去、ローマ数字→全角。build_blood_dict.pyと同じ正規化。"""
    if not name:
        return name
    s = name.strip()
    s = re.sub(r'\s*[\(（][^)）]{1,3}[\)）]\s*$', '', s)
    if re.search(r'[぀-ヿ一-鿿]', s):
        last_jp = -1
        for i, c in enumerate(s):
            if '぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or c in '０１２３４５６７８９':
                last_jp = i
        if last_jp >= 0:
            rest = s[last_jp + 1:]
            s = s[:last_jp + 1]
            m = re.match(r'^(IV|III|II)', rest)
            if m:
                s += {'IV': '４', 'III': '３', 'II': '２'}[m.group(1)]
    return s


def _lookup(blood, table, parent, surface, band):
    """blood_dict から (parent, surface, dist_band) の成績を引く。"""
    if not parent:
        return None
    norm = _normalize_parent(parent)
    try:
        r = blood.execute(
            f"SELECT runs, top3, wins, place_rate, win_rate, win_roi FROM {table} "
            f"WHERE parent=? AND surface=? AND dist_band=?", (norm, surface, band)).fetchone()
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
    st.markdown(
        "血統は**予想の主役ではありません。** "
        "見る順は 予測・Rank → 人気 → 馬場 → コース → **血統は最後。**"
    )
    st.info(
        "**本番で見るのは2つだけ**  \n"
        "① **道悪 × 血統 × 人気上位**（下の表の『道悪判定』。良馬場では出ません）  \n"
        "② **場 × 人気の軸**（『コース軸補正』。東京芝は1-3人気が来やすい／小倉芝は来にくい。"
        "**血統ではなく場の効果**）"
    )
    with st.expander("いつ血統を見る？（良 / 稍重 / 重・不良）"):
        st.markdown(
            "- **良** … ほぼ無視してOK。Rank と人気を優先。\n"
            "- **稍重** … 人気上位に、道悪向きの血統があるかだけ軽く見る。\n"
            "- **重・不良** … ここで初めてちゃんと見る。"
            "能力は高いのに道悪血統が弱いなら警戒。\n"
            "- 父まで見れば十分。母父は補助。ニックスを細かく追う必要はない。\n"
            "- **『血統期待値が高い』は買う理由にしない。** 見比べ用です。"
        )
    with st.expander("なぜ主役にしないか（検証メモ）"):
        st.caption(
            "父×馬場・母父・ニックス・血統×コース形状・父×当該場は、"
            "すでに予測に織込み済みで、さらに上乗せしても的中は増えませんでした。"
            "細かく掘るとノイズが増えやすいです。"
            "血統期待値の『高い』は3年で単勝回収87%、2026年前半は67%。"
            "通常と血統の両方高いは3年102%でも誤差の範囲、2026年は87%。"
        )

    blood = _ro(_BLOOD_DB)
    jv = _ro(_JV_DB)
    if blood is None or jv is None:
        st.error("blood_dict.db または jravan.db が見つかりません。")
        return

    tabA, tabB, tabC = st.tabs(
        ["🏁 レース血統ランク", "🔎 種牡馬/母父しらべ", "🧪 血統期待値（試験）"])

    # ── タブA: レースの馬を血統スコア順に ──
    with tabA:
        st.caption("研究用。血統だけで何位まで当たったかの答え合わせです。"
                   "本番の判断は上の『いつ血統を見る』に従い、表では『道悪判定』と『コース軸補正』だけ見れば足ります。")
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
                # ── ライブ/未取込フォールバック: jravan.db未取込(直近レース・当日レース等)でも
                #    main.get_bloodline_data(netkeiba出馬表を直接scrape)はjravan非依存で
                #    sire/broodmareSireを返すため、血統スコアだけは表示できる。
                #    実着順との的中チェックは(未出走 or 結果未取込のため)非表示。
                _fb_ok = False
                try:
                    from core.scraper import get_race_data as _fb_grd
                    import main as _fb_main
                    _fdf = _fb_grd(rid, use_storage=False)
                    if _fdf is not None and not _fdf.empty and 'Umaban' in _fdf.columns:
                        _fsurf_raw = str(_fdf['CurrentSurface'].iloc[0]) if 'CurrentSurface' in _fdf.columns else ''
                        _fsurf = '芝' if '芝' in _fsurf_raw else ('ダート' if _fsurf_raw else None)
                        _fdist = None
                        try:
                            _fdist = int(pd.to_numeric(_fdf['CurrentDistance'].iloc[0], errors='coerce'))
                        except Exception:
                            _fdist = None
                        _fmeta = _fdf.attrs.get('metadata', {}) or {}
                        _fname = _fmeta.get('RaceName', '') or rid
                        _bres = _fb_main.get_bloodline_data(rid, track_override=_fsurf, dist_override=_fdist)
                        _bdata = (_bres or {}).get('data', [])
                        if _bdata:
                            _fb_ok = True
                            _fband = _band(_fdist)
                            st.info("⚠️ jravan.db未取込（直近/当日レース）のためnetkeibaからライブ取得して表示中。"
                                    "実着順との的中チェックはできません。")
                            st.markdown(f"**{_fname}**　{_fsurf or '?'}{_fdist or '?'}m（{_fband}）　{len(_bdata)}頭")
                            _pop_map = {}
                            for _, _pr in _fdf.iterrows():
                                try:
                                    _pu = int(pd.to_numeric(_pr.get('Umaban'), errors='coerce'))
                                except Exception:
                                    continue
                                _pop_map[_pu] = _pr.get('Popularity')
                            _frows = []
                            for _d in _bdata:
                                try:
                                    _fum = int(_d.get('number'))
                                except (TypeError, ValueError):
                                    continue
                                _fsire = _d.get('sire') or '-'
                                _fbms = _d.get('broodmareSire') or '-'
                                _fs = _lookup(blood, 'sire_stats', _fsire, _fsurf, _fband)
                                _fb_ = _lookup(blood, 'bms_stats', _fbms, _fsurf, _fband)
                                _fs_adj = _fs['adj_place'] if _fs else _POP_PLACE
                                _fb_adj = _fb_['adj_place'] if _fb_ else _POP_PLACE
                                _fscore = (w_sire * _fs_adj + w_bms * _fb_adj) * 100
                                _fpop = _pop_map.get(_fum)
                                _frows.append({
                                    '馬番': _fum, '馬名': _d.get('name', ''),
                                    '父': _fsire, '母父': _fbms,
                                    '父複勝%(n)': f"{_fs['place_rate']:.0f}%({_fs['runs']})" if _fs else '-',
                                    '母父複勝%(n)': f"{_fb_['place_rate']:.0f}%({_fb_['runs']})" if _fb_ else '-',
                                    '血統スコア': round(_fscore, 1),
                                    '人気': _fpop if _fpop and _fpop < 90 else '-',
                                })
                            _fdf2 = (pd.DataFrame(_frows).sort_values('血統スコア', ascending=False)
                                     .reset_index(drop=True))
                            _fdf2.insert(0, '血統順', range(1, len(_fdf2) + 1))
                            st.dataframe(_fdf2, hide_index=True, use_container_width=True)
                            st.caption("血統スコア=父複勝率×重み＋母父複勝率×重み（サンプル少は母集団へ縮小推定）。"
                                       "ライブ取得版のため道悪判定・馬場情報は非表示。")
                except Exception as _fb_e:
                    st.caption(f"ライブ取得フォールバックエラー: {_fb_e}")
                if not _fb_ok:
                    st.warning("そのレースIDは jravan.db に見つからず、ライブ取得にも失敗しました"
                               "（レースID・出馬表の公開状況をご確認ください）。")
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
                # ── 検証済み: 場×人気の軸信頼度(コースバイアス・血統ではない) ──
                _vfn = _bc.venue_fav_note(_jyo, surface, ninki=1) if _bc else None
                if _vfn:
                    (st.success if _vfn['shift'] > 0 else st.warning)(
                        f"{_vfn['flag']} {_vfn['detail']} — このコースの1-3番人気は"
                        f"人気(頭数補正後)より複勝{_vfn['shift']:+.1f}pp"
                        f"（検証済・血統ではなく場の効果）")
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
                    # 父系統(大系統・アンカー遡上)。表示用=血統×コースはpriced-in検証済
                    _line = _bc.sire_line(sire) if (_bc and sire) else '-'
                    # 場×人気の軸補正(1-3番人気のみ・検証済コースバイアス)
                    _axnote = ''
                    if _bc and ninki and 1 <= int(ninki) <= 3:
                        _vf = _bc.venue_fav_note(_jyo, surface, ninki)
                        if _vf:
                            _axnote = _vf['flag']
                    rows.append({
                        '馬番': um, '馬名': bamei, '父': sire or '-', '父系統': _line,
                        '母父': bms or '-',
                        '父複勝%(n)': f"{s['place_rate']:.0f}%({s['runs']})" if s else '-',
                        '母父複勝%(n)': f"{b['place_rate']:.0f}%({b['runs']})" if b else '-',
                        '血統スコア': round(score, 1),
                        '道悪判定': _verdict,
                        'コース軸補正': _axnote or '-',
                        '人気': ninki if ninki and ninki < 90 else '-',
                        '着順': chaku,
                    })
                df = pd.DataFrame(rows).sort_values('血統スコア', ascending=False).reset_index(drop=True)
                df.insert(0, '血統順', range(1, len(df) + 1))
                # 結果の印(色に頼らず着順が分かるように・色覚/モノクロ印刷対策)
                _MEDAL = {1: '🥇1着', 2: '🥈2着', 3: '🥉3着'}
                df.insert(1, '結果', [_MEDAL.get(int(c), '') for c in df['着順']])

                # 血統だけの的中チェック
                top3_blood = set(df.head(3)['馬番'])
                actual_top3 = set(df[df['着順'] <= 3]['馬番'])
                hit = len(top3_blood & actual_top3)
                winner_um = df[df['着順'] == 1]['馬番'].tolist()
                win_blood_rank = df[df['着順'] == 1]['血統順'].tolist()
                m1, m2 = st.columns(2)
                m1.metric("血統上位3頭 of 実3着内", f"{hit}/3")
                m2.metric("1着馬の血統順位", f"{win_blood_rank[0] if win_blood_rank else '-'}位")

                # 凡例は表の"上"に出す(下のキャプションは読み飛ばされて『色の意味は?』となるため)。
                # 色＝レース結果(答え合わせ)であって血統スコアの高さではない、を明言する。
                st.info(
                    "**この表は答え合わせです。**行の色と🥇🥈🥉は"
                    "**実際の着順**（結果）で、血統スコアの高さではありません。\n\n"
                    "🥇 黄色=1着 ／ 🥈🥉 緑=2〜3着 ／ 色なし=4着以下\n\n"
                    "→ 血統順（左端）の上の方に色が固まっていれば「血統どおりに決着した」、"
                    "下の方に散っていれば「血統は効かなかった」レースです。")

                def _hl(row):
                    if row['着順'] == 1:
                        return ['background-color:#3a2e00;color:#FBC02D;font-weight:bold'] * len(row)
                    if row['着順'] <= 3:
                        return ['background-color:#1a2a1a;color:#A5D6A7'] * len(row)
                    return [''] * len(row)
                st.dataframe(df.style.apply(_hl, axis=1).format({'血統スコア': '{:.1f}'}),
                             hide_index=True, use_container_width=True)
                st.caption("血統スコア=父複勝率×重み＋母父複勝率×重み（サンプル少は母集団へ縮小推定）。"
                           "『父系統』=アンカー遡上の大系統(表示用・系統×コースは織込み済で単独エッジなし)。"
                           "『道悪判定』🟢道悪軸=ダ重不良でシニミニ系等が好走(危険人気から免除)/"
                           "⚠瞬発系道悪=芝重不良でディープ・ステゴ系の人気馬は割引(検証済)。"
                           "『コース軸補正』=場×人気の検証済シグナル(東京芝1-3人気🟢+3.7pp・全年+/"
                           "小倉芝⚠-3.0pp)。※道悪判定は良/稍重では発火しません。")

    # ── タブB: 種牡馬/母父の条件別成績しらべ ──
    with tabB:
        st.caption("研究用の成績しらべ。本番では『この父だから東京芝が得意』と細かく読まなくてよい。"
                   "道悪になったとき、その父が重・不良でどうかを確認する程度で十分。")
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

    # ── タブC: 通常の期待値 vs 血統期待値 vs 重なり ──
    with tabC:
        st.markdown("#### 通常の期待値と、血統だけの見立てを並べる試験")
        st.caption(
            "見比べ用です。『高い』『両方高い』は買う理由にしません。"
            "点数・買い目・新聞には入れていません。"
            "スマート出馬表の国系統・シェア・評価A・双馬メモは、当アプリのDBに無いので使いません。"
        )
        st.markdown(
            "- **通常の期待値** … 同じオッズの馬が、これまで平均して単勝でいくら戻ったか"
            "（強適の✨期待値と同じ。その馬の予想ではありません）\n"
            "- **血統期待値** … 父・母父の成績を、同じレースの他馬とオッズと比べた数。"
            "1.00＝血統の見立てと人気が同じ。**1.25以上かつ血統がレース内の上位約4割**を『高い』\n"
            "- **重なり** … 通常も血統も『高い』。さらに単勝50倍超・12番人気以下は大穴として外す"
        )
        st.info(
            "検証（2023-25 → 2026年前半）: 血統『高い』を大穴除外すると、"
            "3年では人気のわりに少し来たが単勝回収87%。2026年前半は確認できず（回収67%）。"
            "重なりは3年で単勝102%でも誤差の範囲、2026年は87%。"
            "**今は点数に採用しません。買う材料にもしません。** 見比べ用です。"
        )
        with st.expander("このPDF（血統ビーム）と、試験で使っている／使っていないもの"):
            st.markdown(
                "**資料の考え方（14ページ）**  "
                "表面の着順やオッズだけを見ず、①血統（能力の設計図）②馬場・不利（環境）"
                "③人気のズレ（市場）の3つを重ねる、という話です。"
            )
            st.markdown(
                "| PDFの階層 | 資料が言っていること | この試験で出すもの |\n"
                "|---|---|---|\n"
                "| ①遺伝 | 大系統・サンデー小系統・国系統A/B | **出せる:** 父の大系統、父・母父の条件別複勝→血統期待値。"
                "**出せない:** P/T/D/Lサンデー、国系統A/B、シェアの逆張り色 |\n"
                "| ②環境 | 双馬メモ・評価A・トラックバイアス・テン/上がりP | **出せない**（スマート出馬表のメモ）。"
                "道悪×血統は別の検証済み表示（このタブでは足さない） |\n"
                "| ③市場 | 推定人気・人気ランクA〜E・合成オッズ | **出せる:** 通常の期待値、12番人気以下/50倍超を大穴として外す。"
                "**出せない:** 推定人気（精度90%の事前予測）、合成オッズの自動買い |\n"
            )
            st.caption(
                "評価Aの巻き返しを穴で買う話は、以前の検証で穴帯の回収が残りませんでした。"
                "シェア逆張りも、手元にシェア段階（1〜8）が無いので再現しません。"
            )
        _raw_c = st.text_input(
            "レースID または URL",
            key="blood_ev_rid",
            placeholder="12桁ID または https://race.netkeiba.com/race/shutuba.html?race_id=...",
        ).strip()
        rid_c = _extract_race_id(_raw_c)
        if _raw_c and not rid_c:
            st.warning("レースID（12桁）または出馬表URLを入れてください。")
        if not rid_c:
            rid_c = _extract_race_id(st.session_state.get("blood_rid") or "")
            if rid_c:
                st.caption(f"『レース血統ランク』のID {rid_c} を使います。")
        w_c = float(st.session_state.get("blood_wsire", 0.6))
        if rid_c:
            from core import blood_ev as _bev
            if "_blood_ev_bands" not in st.session_state:
                with st.spinner("オッズ帯の平均を準備中（初回だけ）…"):
                    st.session_state["_blood_ev_bands"] = _bev.calibrate_bands()
            _bands = st.session_state["_blood_ev_bands"]

            def _show_ev(horses_in, surface, kyori, finished):
                marked = _bev.annotate_race(horses_in, surface, kyori, _bands, w_sire=w_c)
                out = []
                for r in marked:
                    we, be = r.get("win_ev"), r.get("blood_ev")
                    mark = ""
                    if r.get("skip_e"):
                        mark = "対象外（12番人気以下・50倍超）"
                    elif r.get("overlap"):
                        mark = "両方高い"
                    _line = '-'
                    if _bc and r.get('sire'):
                        try:
                            _line = _bc.sire_line(r.get('sire')) or '-'
                        except Exception:
                            _line = '-'
                    out.append({
                        "馬番": r.get("umaban"),
                        "馬名": r.get("name"),
                        "父系統": _line,
                        "人気": r.get("ninki") if r.get("ninki") else "-",
                        "単勝": r.get("odds"),
                        "通常の期待値": (
                            f"{r.get('win_label')} {we*100:.0f}%" if we is not None else "不明"),
                        "血統期待値": (
                            f"{r.get('blood_label')} {be:.2f}" if be is not None else "不明"),
                        "血統順": r.get("blood_rank"),
                        "重なり": mark,
                        "着順": r.get("chaku") if finished else "-",
                        "_bev": be if be is not None else -1,
                    })
                df_e = pd.DataFrame(out)
                if df_e.empty:
                    st.warning("表示できる馬がいません。")
                    return
                df_e = (df_e.sort_values("_bev", ascending=False)
                        .drop(columns=["_bev"]).reset_index(drop=True))
                st.caption(
                    "父系統の薄い色は系統の見分けです（点数には使いません）。"
                    "緑＝その列が『高い』（大穴でも数字の色は付ける）。"
                    "黄＝両方高い。灰＝12番人気以下・50倍超で対象外（SRAのニュースには出さない）。"
                )

                def _line_color(col):
                    return pd.Series(
                        [f"background-color:{_bc.line_bg(v)}" if (_bc and _bc.line_bg(v)) else ""
                         for v in col],
                        index=col.index,
                    )

                def _high_color(col):
                    return pd.Series(
                        ["background-color:#C8E6C9;color:#1B5E20" if str(v).startswith("高い") else ""
                         for v in col],
                        index=col.index,
                    )

                def _overlap_color(col):
                    out = []
                    for v in col:
                        t = str(v)
                        if "両方高い" in t:
                            out.append("background-color:#FFF9C4;color:#F57F17;font-weight:bold")
                        elif "対象外" in t:
                            out.append("background-color:#EEEEEE;color:#616161")
                        else:
                            out.append("")
                    return pd.Series(out, index=col.index)

                sty = df_e.style
                if "父系統" in df_e.columns:
                    sty = sty.apply(_line_color, subset=["父系統"])
                sty = sty.apply(_high_color, subset=["通常の期待値", "血統期待値"])
                if "重なり" in df_e.columns:
                    sty = sty.apply(_overlap_color, subset=["重なり"])
                st.dataframe(sty, hide_index=True, use_container_width=True)
                both = [r for r in marked if r.get("overlap")]
                bhi = [r for r in marked if r.get("blood_label") == "高い" and not r.get("skip_e")]
                whi = [r for r in marked if r.get("win_label") == "高い" and not r.get("skip_e")]
                c1, c2, c3 = st.columns(3)
                c1.metric("通常の期待値が高い", f"{len(whi)}頭")
                c2.metric("血統期待値が高い", f"{len(bhi)}頭")
                c3.metric("両方高い（重なり）", f"{len(both)}頭")
                if both:
                    st.success(
                        "両方高い: "
                        + " ／ ".join(
                            f"{r.get('umaban')}番 {r.get('name')}（{r.get('ninki')}人気）"
                            for r in sorted(both, key=lambda x: x.get("umaban") or 0)
                        )
                    )
                else:
                    skipped_hi = [
                        r for r in marked
                        if r.get("skip_e")
                        and r.get("win_label") == "高い"
                        and r.get("blood_label") == "高い"
                    ]
                    if skipped_hi:
                        st.caption(
                            "数字は高い馬がいますが、12番人気以下または単勝50倍超のため"
                            "『両方高い』にしていません: "
                            + " ／ ".join(
                                f"{r.get('umaban')}番 {r.get('name')}（{r.get('ninki')}人気）"
                                for r in sorted(skipped_hi, key=lambda x: x.get("umaban") or 0)
                            )
                            + "。SRAのニュースにも出しません。"
                        )
                    else:
                        st.caption("このレースに『両方高い』の馬はいません。")
                if finished:
                    hit_b = sum(1 for r in bhi if (r.get("chaku") or 99) <= 3)
                    hit_o = sum(1 for r in both if (r.get("chaku") or 99) <= 3)
                    st.caption(
                        f"答え合わせ（3着内）: 血統高い {hit_b}/{len(bhi) or 0}　"
                        f"重なり {hit_o}/{len(both) or 0}"
                    )

            race = jv.execute(
                "SELECT surface, kyori, race_name FROM races WHERE race_id=? LIMIT 1",
                (rid_c,)).fetchone()
            horses_jv = jv.execute(
                "SELECT r.umaban, r.bamei, r.ninki, r.win_odds, r.chakujun, h.sire, h.bms "
                "FROM results r LEFT JOIN horses h ON h.ketto_num=r.ketto_num "
                "WHERE r.race_id=? AND r.chakujun>0 ORDER BY r.umaban",
                (rid_c,)).fetchall()
            if race and horses_jv:
                surface, kyori, rname = race
                st.markdown(f"**{rname or rid_c}**　{surface}{kyori}m")
                hs = []
                for um, nm, nk, od, ch, sire, bms in horses_jv:
                    hs.append({
                        "umaban": um, "name": nm, "ninki": nk, "odds": od,
                        "chaku": ch, "sire": sire, "bms": bms,
                    })
                _show_ev(hs, surface, kyori, True)
            else:
                try:
                    from core.scraper import get_race_data as _ev_grd
                    import main as _ev_main
                    _edf = _ev_grd(rid_c, use_storage=False)
                    if _edf is None or _edf.empty:
                        st.warning("そのレースIDは見つかりませんでした。")
                    else:
                        _esurf_raw = str(_edf['CurrentSurface'].iloc[0]) if 'CurrentSurface' in _edf.columns else ''
                        _esurf = '芝' if '芝' in _esurf_raw else ('ダート' if _esurf_raw else '芝')
                        _edist = None
                        try:
                            _edist = int(pd.to_numeric(_edf['CurrentDistance'].iloc[0], errors='coerce'))
                        except Exception:
                            _edist = 1600
                        _emeta = _edf.attrs.get('metadata', {}) or {}
                        st.info("jravan未取込のため出馬表から表示（答え合わせなし）。")
                        st.markdown(f"**{_emeta.get('RaceName') or rid_c}**　{_esurf}{_edist}m")
                        _bres = _ev_main.get_bloodline_data(
                            rid_c, track_override=_esurf, dist_override=_edist)
                        _bmap = {}
                        for _d in (_bres or {}).get('data', []) or []:
                            try:
                                _bmap[int(_d.get('number'))] = _d
                            except (TypeError, ValueError):
                                pass
                        hs = []
                        for _, _pr in _edf.iterrows():
                            try:
                                _u = int(pd.to_numeric(_pr.get('Umaban'), errors='coerce'))
                            except Exception:
                                continue
                            _bd = _bmap.get(_u) or {}
                            hs.append({
                                "umaban": _u,
                                "name": str(_pr.get('Name') or _bd.get('name') or ''),
                                "ninki": _pr.get('Popularity'),
                                "odds": _pr.get('Odds'),
                                "chaku": None,
                                "sire": _bd.get('sire') or _pr.get('sire'),
                                "bms": _bd.get('broodmareSire') or _pr.get('broodmareSire'),
                            })
                        _show_ev(hs, _esurf, _edist, False)
                except Exception as _ee:
                    st.warning(f"取得できませんでした: {_ee}")

    blood.close()
    jv.close()
