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
             'combo': {}, 'elim': {}, 'edge_reasons': {}, 'danger_reasons': {}}
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
        ereason = {}; dreason = {}
        race_date = dv if len(dv) >= 8 else None
        is_handi = bool(meta.get('is_handicap'))

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
            kt, tc = jj.resolve_horse(str(r.get('Name', '')))
            jky = str(r.get('Jockey', '') or '')
            sire = str(r.get('sire') or '').strip()
            if (not sire or sire == '-') and kt:
                sire = tb.sire_of_ketto(kt)
            vr = dg.danger_veto(
                ninki=(int(pop) if pd.notnull(pop) else None),
                surface=surf, baba=baba, sire=sire,
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
                if tcw and tcw.get('runs', 0) >= 5 and tcw.get('win_rate', 0) >= 0.20:
                    _addr(ereason, u, f"🏠厩舎当ｺｰｽ{tcw['win_rate']*100:.0f}%")
            if tc and jky:
                gl = jj.jockey_trainer_combo(jky, tc)
                if gl and gl.get('rides', 0) >= 10 and gl.get('top2', 0) >= 0.40:
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

        return {'edge': set(ereason.keys()), 'danger': danger, 'ana': ana,
                'veto': veto, 'combo': combo, 'elim': elim,
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
        # 危険人気馬(severity≥2=veto)は本命/相手から外す方向へ減点(fade)
        if veto:
            bonus -= 12.0
        elif danger and pop is not None and pop <= 3:
            bonus -= 5.0
        # 消去クロス重複が多い=来にくさ(検証:重複数→複勝率単調低下)。統合順位を下げて切る側へ
        bonus -= 4.0 * max(0, elim_n - 2)

        out.append({
            'umaban': u, 'name': r.get('name', ''), 'pop': pop, 'odds': r.get('odds'),
            'proj': round(base, 1), 'axis_mark': mk,
            'votes': votes, 'value_votes': value_votes, 'combo': combo, 'elim': elim_n,
            'danger': danger, 'veto': veto,
            'reasons': ' '.join(labs),
            'integ': round(base + bonus, 1),
        })

    out.sort(key=lambda x: -x['integ'])

    # 役割グルーピング(優先順位方式・この機能は"意見"なので強気に切る):
    #   危険veto→本命→切る(消去クロス重複≥3を強気に切る)→穴(comboが活きるゾーン=combo≥2限定)
    #   →相手→残り。※穴は単発シグナル(⚡33等・全馬に出がち)を入れず、複数合議のcombo馬に絞る。
    ELIM_CUT = 3        # 消去クロスの重複がこれ以上=強気に切る(ユーザー方針: 重複3-4は切る)
    honmei, aite, ana_g, keshi = [], [], [], []
    assigned = set()
    for h in out:                                   # 危険人気veto → 消し
        if h['veto']:
            h['role'] = '💀消し(危険人気)'; keshi.append(h['umaban']); assigned.add(h['umaban'])
    for h in out:                                   # 本命 = 統合最上位の非veto
        if h['umaban'] in assigned:
            continue
        h['role'] = '◎本命'; honmei.append(h['umaban']); assigned.add(h['umaban']); break
    for h in out:                                   # 切る = 消去クロス重複≥3(来にくさ大)を強気に
        if h['umaban'] in assigned:
            continue
        if h.get('elim', 0) >= ELIM_CUT:
            h['role'] = f"💀切る(消去{h['elim']}重複)"; keshi.append(h['umaban']); assigned.add(h['umaban'])
    for h in out:                                   # 穴 = 人気薄(6+)×comboが活きるゾーン(combo≥2)
        if h['umaban'] in assigned:
            continue
        if (h['pop'] is not None and h['pop'] >= 6) and h['combo'] >= 2:
            h['role'] = '🎯穴(combo馬)'; ana_g.append(h['umaban']); assigned.add(h['umaban'])
    for h in out:                                   # 相手 = 残りの統合上位(最大3頭)
        if h['umaban'] in assigned:
            continue
        if len(aite) < 3:
            h['role'] = '〇▲相手'; aite.append(h['umaban']); assigned.add(h['umaban'])
    n = len(out)                                    # 残り = 下位1/3は消し候補・他は押さえ
    for idx, h in enumerate(out):
        if h['umaban'] in assigned:
            continue
        if idx >= n - max(1, n // 3):
            h['role'] = '消し候補'; keshi.append(h['umaban'])
        else:
            h['role'] = '押さえ'
    return {'horses': out, 'regime': regime,
            'groups': {'honmei': honmei, 'aite': aite, 'ana': ana_g, 'keshi': keshi}}
