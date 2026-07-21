# -*- coding: utf-8 -*-
"""検証済みエッジの合議(統合)ビュー。

2つの役割:
1. build_edge_sets(): 1レース分の『検証済みエッジ/危険馬/穴セット』を全馬について1回だけ
   計算する(旧app.pyインライン _aim ブロックの抽出=全券種・強適シートで共有)。
2. integrate(): 荒れ予報レジーム(trio_lean)別に、独立した検証済みエッジを合議して
   本命/相手/穴/消しへ再グルーピングする。

**正直な前提(scripts/consensus_backtest.py で検証済)**:
独立エッジの『一致(合議数)』は複勝率を単調に上げる(本物): ベース複9.4% → votes=2で16%
→ votes=3で27%(ROI最大96%)。ただしフラット単勝で黒字化はしない=市場を出し抜く予測器ではなく
『本命の信頼度を測り、相手/穴を絞る』道具。荒れ予報6シグナルは人気薄(6番人気以下)×荒れレースで
holdout検証済([[verified_arare_signal_check]])のため、value票は人気薄限定で数える。
"""

# 荒れ予報6シグナル(edge_reasonsラベルの接頭辞)。人気薄×荒れでholdout有意(z順):
#   🔵補正T z+10.4 / 🧬血統上位 z+7.6 / 🧬血統回収 z+6.4 / 👑騎手 z+3.8 / ⚡33 z+2.6 / 🔥末脚 z+2.3
_SIG6 = ('🔵補正T', '🧬血統上位', '🧬血統回収', '👑騎手', '⚡33', '🔥末脚')
# 市場/能力の裏付けエッジ(人気帯を問わず本命・相手の信頼度に効く検証済み軸)
_MARKET_EDGES = ('⭐黄金ライン', '🏠厩舎当ｺｰｽ', '🟢道悪軸')


def build_edge_sets(df, meta, race_id):
    """1レース分の検証済みエッジ集合を返す(旧 _aim と同一shape・streamlit非依存)。

    戻り値: {'edge':set, 'danger':set, 'ana':set, 'veto':set, 'combo':{u:count},
             'edge_reasons':{u:[label..]}, 'danger_reasons':{u:[label..]}}
    失敗時は空shapeを返す(呼び元は必ず.get()で参照)。
    """
    empty = {'edge': set(), 'danger': set(), 'ana': set(), 'veto': set(),
             'combo': {}, 'elim': {}, 'vh': {}, 'vh_tier': {},
             'edge_reasons': {}, 'danger_reasons': {}}
    try:
        import re as _re_cv
        import pandas as pd
        from core import corrected_time as ct
        from core import jockey_jv as jj
        from core import track_bias as tb
        from core import danger_gate as dg
        from core import bloodline as bl
        from core import lap33 as l3
        from core import elim_cross as ec

        meta = meta or {}
        surf = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns and not df.empty else '芝'
        baba = str(meta.get('condition', '') or '')
        jyo = str(race_id)[4:6]
        dv = str(meta.get('date_val', '') or '')
        month = int(dv[4:6]) if len(dv) >= 6 and dv[4:6].isdigit() else None
        try:
            dist = int(pd.to_numeric(df['CurrentDistance'].iloc[0], errors='coerce'))
        except Exception:
            dist = None
        # 33ラップのコース平均(JRA限定=jyo<=10・Ranking Tableと同条件)
        l33c = None
        try:
            l33s = '芝' if '芝' in surf else ('ダ' if surf else None)
            if l33s and dist and jyo <= '10':
                l33c = l3.course_avg33(l33s, dist, jyo=jyo)
        except Exception:
            l33c = None

        ctfig = {}; spurt = {}; ana = set(); danger = set(); veto = set()
        bld = {}; jpw = {}; elim = {}   # elim=消去クロスの来にくさフラグ重複数(切る判定用)
        odds_map = {}                   # um -> 単勝オッズ(妙味馬ハンター軽量スコア用)
        ereason = {}; dreason = {}
        race_date = dv if len(dv) >= 8 else None
        is_handi = bool(meta.get('is_handicap'))
        # 複勝オッズ(ガラス人気馬=単複逆転FADEの判定用・事前市場値でリーク無し)。
        # build_edge_setsはセッションキャッシュされるため1レース1回のみfetch。失敗は無視。
        place_mid_map = {}
        try:
            from core.scraper import fetch_place_odds_api
            _pl = fetch_place_odds_api(race_id) or {}
            for _u, _pv in _pl.items():
                _m = (_pv or {}).get('Mid') if isinstance(_pv, dict) else None
                if _m:
                    place_mid_map[int(_u)] = float(_m)
        except Exception:
            place_mid_map = {}

        def _addr(d, u, lab):
            d.setdefault(u, [])
            if lab not in d[u]:
                d[u].append(lab)

        for _, r in df.iterrows():
            un = pd.to_numeric(r.get('Umaban'), errors='coerce')
            if pd.isnull(un):
                continue
            u = int(un)
            pop = pd.to_numeric(r.get('Popularity'), errors='coerce')
            if pd.notnull(pop) and pop >= 6:
                ana.add(u)
            _od = pd.to_numeric(r.get('Odds'), errors='coerce')
            if pd.notnull(_od) and _od > 0:
                odds_map[u] = float(_od)
            kt, tc = jj.resolve_horse(str(r.get('Name', '')))
            jky = str(r.get('Jockey', '') or '')
            sire = str(r.get('sire') or '').strip()
            if (not sire or sire == '-') and kt:
                sire = tb.sire_of_ketto(kt)
            _prev_chaku = None                       # 前走着順(危険人気馬の前走5着以下ソフト理由用)
            _lay_days = None                         # 休養日数(半年休み明け/中9週+ローテのソフト理由用)
            _pr = r.get('PastRuns')
            if isinstance(_pr, list) and _pr:
                try:
                    _prev_chaku = int(_pr[0].get('Rank'))
                except (TypeError, ValueError):
                    _prev_chaku = None
                try:
                    from datetime import datetime as _dt_lay
                    _pd8 = (str(_pr[0].get('Date', '') or '')
                            .replace('.', '').replace('-', '').replace('/', '')[:8])
                    if len(_pd8) == 8 and _pd8.isdigit() and race_date:
                        _lay_days = (_dt_lay.strptime(str(race_date)[:8], '%Y%m%d')
                                     - _dt_lay.strptime(_pd8, '%Y%m%d')).days
                        if _lay_days < 0:
                            _lay_days = None
                except Exception:
                    _lay_days = None
            vr = dg.danger_veto(
                ninki=(int(pop) if pd.notnull(pop) else None),
                surface=surf, baba=baba, sire=sire, prev_chaku=_prev_chaku,
                layoff_days=_lay_days,
                win_odds=(float(_od) if pd.notnull(_od) and _od > 0 else None),
                place_mid=place_mid_map.get(u),
                sex_age=str(r.get('SexAge', '') or ''), month=month)
            if vr['severity'] >= 1:
                danger.add(u)
                for rs in vr['reasons']:
                    _addr(dreason, u, rs)
                if vr['severity'] >= 2:
                    veto.add(u)
            bm = tb.heavy_fav_blood_mod(sire, surf, baba) if sire else None
            if bm and bm.get('mod') == 'exempt':
                _addr(ereason, u, '🟢道悪軸')
            if kt:
                fg = ct.get_figure(kt, surf)
                if fg and fg.get('fig') is not None:
                    ctfig[u] = fg['fig']
                cx = jj.horse_recent_context(kt)
                si = (cx or {}).get('spurt_index'); srn = (cx or {}).get('spurt_runs', 0)
                if si is not None and srn >= 2:
                    spurt[u] = si
                # 消去クロスの来にくさフラグ重複数(切る判定用・事前確定入力のみ)
                try:
                    es = jj.horse_elim_stats(kt) or {}
                    _zg = None
                    _mzg = _re_cv.search(r'\(([-+]?\d+)\)', str(r.get('WeightHistory', '') or ''))
                    if _mzg:
                        _zg = int(_mzg.group(1))
                    _age = None
                    _mage = _re_cv.search(r'(\d+)', str(r.get('SexAge', '') or ''))
                    if _mage:
                        _age = int(_mage.group(1))
                    _fl = ec.compute_flags(
                        last5_top3=es.get('last5_top3'), spurt_index=si, spurt_runs=srn,
                        avg_c4ratio=es.get('avg_c4ratio'),
                        prev_date=(cx or {}).get('prev_date'), race_date=race_date,
                        prev_dist=(cx or {}).get('prev_dist'), cur_dist=dist,
                        zogen=_zg, age=_age, is_handicap=is_handi)
                    elim[u] = ec.verified_count(_fl)   # 検証済みフラグの重複数(BAND根拠と同じ)
                except Exception:
                    pass
                if l33c:
                    try:
                        hv3 = (l3.horse_fit33(kt) or {}).get('avg_lap33')
                        if hv3 is not None and l3.fit_match(hv3, l33c['avg']) is True:
                            _addr(ereason, u, '⚡33ラップ適合')
                    except Exception:
                        pass
            try:
                bms = str(r.get('broodmareSire') or '').strip()
                if bms in ('nan', 'NaN', 'None', '不明', '-'):
                    bms = ''
                ss = bl.lookup_sire_stats(sire, surf, dist) if sire else None
                bs = bl.lookup_bms_stats(bms, surf, dist) if bms else None
                if ss or bs:
                    bld[u] = bl.blood_score(sire or None, bms or None, surf, dist)
                if ss and ss.get('win_roi', 0) >= 100:
                    _addr(ereason, u, '🧬血統回収100%+')
            except Exception:
                pass
            try:
                if jky:
                    jpv = jj.jockey_power(jj.resolve_jockey_name(jky)).get('jpower')
                    if jpv is not None:
                        jpw[u] = float(jpv)
            except Exception:
                pass
            if tc:
                tcw = jj.trainer_course_winrate(tc, jyo, surf)
                # 妙味ゲートは縮小推定した勝率で判定(5戦1勝=20%の誤発火を防ぐ)。
                # 閾値18%は縮小推定スケールでの再検証値(scripts/trainer_shrinkage_backtest.py):
                # shrunk>=18% は 3着内残差+0.0329/z+2.88 で 生>=20%(+0.0222/z+1.84)を上回る。
                # ※縮小推定は勝率を圧縮するため、生の20%とは尺度が違う(20%のままだとほぼ発火しない)。
                _twr = tcw.get('win_rate_shrunk') if tcw else None
                if _twr is None and tcw:
                    _twr = tcw.get('win_rate')
                if tcw and tcw.get('runs', 0) >= 5 and (_twr or 0) >= jj.TRAINER_COURSE_GATE:
                    _addr(ereason, u, f"🏠厩舎当ｺｰｽ{_twr*100:.0f}%")
            if tc and jky:
                gl = jj.jockey_trainer_combo(jky, tc)
                if jj.is_golden_line(gl):
                    _addr(ereason, u, f"⭐黄金ライン{gl['top2']*100:.0f}%")

        for u, rk in ct.field_ranks(ctfig).items():
            if rk <= 3:
                _addr(ereason, u, '🔵補正T上位')
        for u, _ in sorted(spurt.items(), key=lambda x: -x[1])[:3]:
            _addr(ereason, u, '🔥末脚top')
        for u, _ in sorted(bld.items(), key=lambda x: -x[1])[:3]:
            _addr(ereason, u, '🧬血統上位')
        for u, _ in sorted(jpw.items(), key=lambda x: -x[1])[:3]:
            _addr(ereason, u, '👑騎手力top')

        # 🧩シグナル重複数(荒れ予報6シグナルの同時発火。combo2+ z+9.2 / combo3+ z+8.2)
        combo = {}
        for u, labs in list(ereason.items()):
            c6 = sum(1 for p in _SIG6 if any(str(x).startswith(p) for x in labs))
            if c6:
                combo[u] = c6
                if c6 >= 2:
                    _addr(ereason, u, f'🧩{c6}重複')

        # 妙味馬ハンター軽量スコア(検証済: recall70%@precision2.09x・[[project_value_horse_hunter]])。
        # 主成分は市場情報(オッズ順序)+補正T連続量。3着内の網羅リストであって+EVではない。
        vh = {}; vh_tier = {}
        try:
            from core import value_hunter as _vh
            if _vh.available():
                _sc = _vh.score_race(ctfig, spurt, bld, combo, elim, odds_map)
                for u, d in _sc.items():
                    vh[u] = round(d['score'], 4)
                    vh_tier[u] = d['tier']
        except Exception:
            pass

        return {'edge': set(ereason.keys()), 'danger': danger, 'ana': ana,
                'veto': veto, 'combo': combo, 'elim': elim,
                'vh': vh, 'vh_tier': vh_tier,
                'edge_reasons': ereason, 'danger_reasons': dreason}
    except Exception:
        return empty


def _count_sig6(labels):
    """edge_reasonsのラベル一覧から荒れ予報6シグナルの発火数を数える。"""
    return sum(1 for p in _SIG6 if any(str(x).startswith(p) for x in (labels or [])))


def integrate(rows, aim, regime):
    """検証済みエッジをレジーム別に合議し、本命/相手/穴/消しへ再グルーピングする。

    rows: [{'umaban','name','pop','odds','proj'(予測スコア),'axis_mark'('◎'/'〇'/'▲'/'')}]
    aim: build_edge_sets の戻り
    regime: '本線向き' | '②穴妙味向き' | '中立'(trio_lean判定)

    戻り値: {'horses': [{umaban,name,pop,proj,axis_mark,votes,value_votes,combo,
                        danger,veto,role,reasons(str),integ(統合スコア)}...(integ降順)],
             'groups': {'honmei':[u..],'aite':[u..],'ana':[u..],'keshi':[u..]},
             'regime': regime}
    ※統合スコアは『予測スコア + レジーム別の合議加点 − 危険減点』。市場を出し抜く数字ではなく
      本命信頼度と相手/穴の並べ替え用(consensus_backtest: votes一致で複勝率単調UP)。
    """
    aim = aim or {}
    edge_reasons = aim.get('edge_reasons') or {}
    danger_set = aim.get('danger') or set()
    veto_set = aim.get('veto') or set()
    combo_map = aim.get('combo') or {}
    elim_map = aim.get('elim') or {}
    vh_map = aim.get('vh') or {}
    vh_tier_map = aim.get('vh_tier') or {}
    mkval = {'◎': 3, '〇': 2, '▲': 1}

    out = []
    for r in rows:
        u = r.get('umaban')
        if u is None:
            continue
        pop = r.get('pop')
        labs = edge_reasons.get(u) or []
        sig6 = _count_sig6(labs)                 # 荒れ予報6シグナル発火数
        combo = combo_map.get(u, 0)
        elim_n = elim_map.get(u, 0)              # 消去クロスの来にくさフラグ重複数
        mk = str(r.get('axis_mark') or '')[:1]
        axis_v = mkval.get(mk, 0)                # 軸候補◎〇▲(オッズ別実複勝率=最直接の3着内根拠)
        market_v = sum(1 for e in _MARKET_EDGES if any(str(x).startswith(e) for x in labs))
        danger = u in danger_set
        veto = u in veto_set
        # value票は人気薄(6+)限定で数える(holdout検証はその母集団)。人気馬では素点(proj)に委ねる。
        is_ana = (pop is not None and pop >= 6)
        value_votes = sig6 if is_ana else 0
        votes = axis_v + market_v + value_votes  # 合議の一致数(consensus)

        base = float(r.get('proj') or 0.0)
        bonus = 0.0
        if regime == '②穴妙味向き':
            # 荒れ:人気薄×検証シグナルの合議を厚く。combo2+は単独最強を超える(z+9.2)
            bonus += 6.0 * value_votes + (10.0 if combo >= 3 else (7.0 if combo == 2 else 0.0))
            bonus += 3.0 * axis_v + 2.0 * market_v
        elif regime == '本線向き':
            # 堅:軸候補◎〇+市場エッジを厚く。穴シグナルは軽め(荒れでないと効きにくい)
            bonus += 5.0 * axis_v + 4.0 * market_v + 2.0 * value_votes + (3.0 if combo >= 2 else 0.0)
        else:  # 中立
            bonus += 4.0 * axis_v + 3.0 * market_v + 3.5 * value_votes + (5.0 if combo >= 2 else 0.0)
        # 危険人気馬: 注意マーク止まり。軸からは外さない(66R台帳: 警告あり軸77.5%的中=切ると損)。
        # severity≥2は押さえ推奨の軽い減点、severity==1は微減点。
        if veto:
            bonus -= 5.0
        elif danger and pop is not None and pop <= 3:
            bonus -= 3.0
        # 消去クロス重複が多い=来にくさ(検証:重複数→複勝率単調低下)。統合順位を下げて切る側へ
        bonus -= 4.0 * max(0, elim_n - 2)

        out.append({
            'umaban': u, 'name': r.get('name', ''), 'pop': pop, 'odds': r.get('odds'),
            'proj': round(base, 1), 'axis_mark': mk,
            'votes': votes, 'value_votes': value_votes, 'combo': combo, 'elim': elim_n,
            'vh': vh_map.get(u), 'vh_tier': vh_tier_map.get(u, ''),
            'danger': danger, 'veto': veto,
            'reasons': ' '.join(labs),
            'integ': round(base + bonus, 1),
        })

    out.sort(key=lambda x: -x['integ'])

    # 役割グルーピング(優先順位方式・この機能は"意見"なので強気に切る):
    #   危険veto→本命→切る→穴(comboが活きるゾーン=combo≥2限定)→相手→残り。
    #   切る=消去クロス重複≥3を強気に。ただしプラス材料(combo≥2/軸候補◎〇/統合上位1/3)のある馬は
    #   切らず穴/相手へ(消去フラグは来にくさだが、複数の検証済プラスやLTR上位を上書きしない)。
    #   ※穴は単発シグナル(⚡33等・全馬に出がち)を入れず、複数合議のcombo馬に絞る。
    ELIM_CUT = 3        # 消去クロスの重複がこれ以上=強気に切る(ユーザー方針: 重複3-4は切る)
    # 人気上位(1-5)は消去フラグが人気に織込み済み(priced-in)=フラグで切ると二重計上になる
    # ([[project_elimination_engine]]/elim_crossは単体priced-in)。重複が極端(≥5)な時だけ切る。
    ELIM_CUT_POPULAR = 5
    honmei, aite, ana_g, keshi = [], [], [], []
    assigned = set()
    # 旧: veto→消し。廃止(66R台帳で警告あり軸77.5%的中=消すと損)。
    # 危険人気馬は減点のみで通常フローに参加し、統合順位で自然に押さえ/穴へ降格する。
    for h in out:                                   # 本命 = 統合最上位の非veto
        if h['umaban'] in assigned:
            continue
        h['role'] = '◎本命'; honmei.append(h['umaban']); assigned.add(h['umaban']); break
    _cut_top_guard = max(3, len(out) // 3)          # 統合上位1/3は切らない(最良予測器が生存判定)
    for idx, h in enumerate(out):                   # 切る = 消去クロス重複≥3(来にくさ大)を強気に
        if h['umaban'] in assigned:
            continue
        # 強いプラス材料のある馬は消去フラグだけで切らない(ユーザー指摘202610020404/メイワキラリ:
        # 6番人気・平均位置上位・血統top3・補正T🔵・高LTRを切るのは誤り=有料販売ならクレーム源)。
        # 次のいずれかなら切らず穴/相手へ回す:
        #  ①combo≥2 … 荒れ6シグナル複数一致(combo2+ z+9.2の検証済プラス・穴ループの閾値と一致)。
        #             うちcombo3+×消去3+は穴ループで🔥敗者復活として明示(revival_backtest z+2.21)。
        #  ②軸候補◎〇 … オッズ実複勝率が上位(最直接の3着内根拠)。
        #  ③統合スコア上位1/3 … 検証AI(LTR)含む素点が高い=最良予測器が生存と判定した馬。
        #  ④妙味馬ハンター精鋭 … 軽量スコアの上位運用点(recall0.5・precision2.6x)。combo=0でも
        #     オッズ順序+補正T連続量で拾える層の救済(Fable検証: combo0好走の6割を捕捉)。
        if (h['combo'] >= 2 or h['axis_mark'] in ('◎', '〇') or idx < _cut_top_guard
                or h.get('vh_tier') == '🎯精鋭'):
            continue
        _en = h.get('elim', 0)
        _pop_top = (h['pop'] is not None and h['pop'] <= 5)   # 人気上位=priced-in
        # 人気上位はフラグが織込み済みなので重複が極端(≥5)な時だけ切る。人気薄(6+)は重複3で切る
        if _en >= (ELIM_CUT_POPULAR if _pop_top else ELIM_CUT):
            h['role'] = f"💀切る(消去{_en}重複)"; keshi.append(h['umaban']); assigned.add(h['umaban'])
    for h in out:                                   # 穴 = 人気薄(6+)×comboが活きるゾーン(combo≥2)
        if h['umaban'] in assigned:
            continue
        if (h['pop'] is not None and h['pop'] >= 6) and h['combo'] >= 2:
            # 切る帯(消去3+)から復活したcombo3+は🔥敗者復活として明示
            if h.get('elim', 0) >= 3 and h['combo'] >= 3:
                h['role'] = f"🔥敗者復活(combo{h['combo']}/消去{h['elim']})"
            else:
                h['role'] = '🎯穴(combo馬)'
            ana_g.append(h['umaban']); assigned.add(h['umaban'])
    for h in out:                                   # 相手 = 残りの統合上位(最大3頭)
        if h['umaban'] in assigned:
            continue
        if len(aite) < 3:
            h['role'] = '〇▲相手'; aite.append(h['umaban']); assigned.add(h['umaban'])
    n = len(out)                                    # 残り = 下位1/3は消し候補・他は押さえ
    osae = []
    for idx, h in enumerate(out):
        if h['umaban'] in assigned:
            continue
        if idx >= n - max(1, n // 3):
            h['role'] = '消し候補'; keshi.append(h['umaban'])
        else:
            # 押さえ=切らずに残す中位馬(実際に着内に来るのでグレー扱いにしない)。独立グループで返す。
            h['role'] = '押さえ'; osae.append(h['umaban'])
    return {'horses': out, 'regime': regime,
            'groups': {'honmei': honmei, 'aite': aite, 'ana': ana_g,
                       'osae': osae, 'keshi': keshi}}
