# -*- coding: utf-8 -*-
"""🎯 強適消去エンジン（検証済み）の計算本体。

app.py 🧹消去フィルター と 🏠 Single Race Analysis の自動実行から共用する。
"""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd


def border_max(n_horses, race_id=None):
    """ボーダー残しスライダーの上限。"""
    n = int(n_horses or 0)
    keep = (n + 1) // 2
    cut_zone = n - keep
    return max(0, min(3, cut_zone - 1)) if n >= 6 else 0


def default_border_count(n_horses, race_id=None):
    """UI スライダー既定値 = min(3, border_max)。"""
    bm = border_max(n_horses, race_id)
    return min(3, bm) if bm else 0


def compute_elim_rows(df, race_id, metadata, nk_spurt_map=None):
    """強適消去スコア行を生成。app.py の _erows と同型。"""
    from core import bet_optimizer as _bo
    from core import corrected_time as _ct
    from core import elim_reasons as _er
    from core import jockey_jv as _jj
    from core import score_cache as _sc2
    from core import track_bias as _tb
    from core import value_scanner as _vs_gb

    metadata = metadata or {}
    nk_spurt_map = nk_spurt_map or {}
    scache = _sc2.read_scores(race_id)
    score_by_um = {}
    odds_by_um = {}
    if scache and df is not None and not df.empty:
        for _, rp in df.iterrows():
            try:
                u = int(pd.to_numeric(rp.get('Umaban'), errors='coerce'))
            except Exception:
                continue
            pj = (scache.get(u) or {}).get('proj')
            od = pd.to_numeric(rp.get('Odds'), errors='coerce')
            if pj is not None:
                score_by_um[u] = float(pj)
            if pd.notnull(od) and od > 0:
                odds_by_um[u] = float(od)
    winp = _bo.blended_win_probs(score_by_um, odds_by_um) if score_by_um else {}
    all_um = list(winp.keys())
    try:
        gap_below = _vs_gb.odds_gap_below(odds_by_um)
    except Exception:
        gap_below = set()

    def _top2_prob(wp, a, allu):
        s = wp.get(a, 0.0)
        for b in allu:
            if b != a:
                s += _bo._p2(wp, b, a)
        return s

    jyo = str(race_id)[4:6]
    surf = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns and not df.empty else '芝'
    baba = str(metadata.get('condition', '') or '')
    try:
        dist = int(pd.to_numeric(df['CurrentDistance'].iloc[0], errors='coerce'))
    except Exception:
        dist = None
    dv = str(metadata.get('date_val', '') or '')
    mo = int(dv[4:6]) if len(dv) >= 6 and dv[4:6].isdigit() else 0
    miny = str(int(dv[:4]) - 3) if dv[:4].isdigit() else None

    spurt_rank = []
    for _, r0 in df.iterrows():
        kt0, _ = _jj.resolve_horse(str(r0.get('Name', '')))
        c0 = _jj.horse_recent_context(kt0) if kt0 else None
        si0 = (c0 or {}).get('spurt_index')
        sr0 = (c0 or {}).get('spurt_runs', 0)
        if si0 is None and str(r0.get('Name', '')) in nk_spurt_map:
            si0, sr0 = nk_spurt_map[str(r0.get('Name', ''))]
        if si0 is not None and sr0 >= 2:
            try:
                spurt_rank.append((int(r0.get('Umaban')), float(si0)))
            except Exception:
                pass
    spurt_top3 = {u for u, _ in sorted(spurt_rank, key=lambda x: -x[1])[:3]}

    erows = []
    for _, r in df.iterrows():
        nm = str(r.get('Name', ''))
        try:
            um = int(r.get('Umaban'))
        except Exception:
            um = 0
        pop = pd.to_numeric(r.get('Popularity'), errors='coerce')
        odds = pd.to_numeric(r.get('Odds'), errors='coerce')
        jky = str(r.get('Jockey', '') or '')
        sa = str(r.get('SexAge', '') or '')
        kt, tc = _jj.resolve_horse(nm)
        g = _jj.jockey_trainer_combo(jky, tc) if tc else None
        gold = _jj.is_golden_line(g)
        cs = _jj.trainer_course_winrate(tc, jyo, surf, min_year=miny) if tc else None
        tcwr = (cs.get('win_rate_shrunk') if cs else None)
        if tcwr is None and cs:
            tcwr = cs.get('win_rate')
        tcok = bool(cs and cs.get('runs', 0) >= 10
                    and (tcwr or 0) >= _jj.TRAINER_COURSE_GATE)
        ctx = _jj.horse_recent_context(kt) if kt else None
        fade = ('牝' in sa) and mo in (12, 1, 2, 3, 4, 5)
        distchg = bool(ctx and ctx.get('prev_dist') and dist
                     and abs(dist - ctx['prev_dist']) >= 400)
        hatsud = ('ダ' in surf) and bool(ctx) and ctx.get('dirt_runs', 0) == 0
        fluke = bool(ctx and ctx.get('prev_ninki') and ctx.get('prev_chaku')
                     and ctx['prev_ninki'] >= 6 and ctx['prev_chaku'] <= 3)

        def _njk(s):
            return ''.join(str(s or '').split())

        def _same_jk(a, b):
            return bool(a and b and (a == b or (len(a) >= 2 and len(b) >= 2
                       and (a.startswith(b) or b.startswith(a)))))

        curj = _njk(r.get('Jockey', ''))
        pvj = (ctx or {}).get('prev_jockey')
        topswap = bool(ctx and pvj and _jj.jockey_is_top(pvj)
                       and not _same_jk(curj, _njk(pvj)))
        kinratio = False
        try:
            fk = float(r.get('WeightCarried'))
            bwm = re.match(r'(\d+)', str(r.get('Weight', '')))
            if bwm and int(bwm.group(1)) > 0 and fk / int(bwm.group(1)) >= 0.126:
                kinratio = True
        except Exception:
            pass
        rest = False
        gap_days = None
        try:
            pdt = (ctx or {}).get('prev_date')
            if pdt and len(dv) >= 8:
                gap = (datetime.strptime(dv[:8], '%Y%m%d')
                       - datetime.strptime(pdt, '%Y%m%d')).days
                gap_days = gap
                if gap >= 180:
                    rest = True
        except Exception:
            pass
        zg_e = None
        mzg_e = re.search(r'\(([-+]?\d+)\)', str(r.get('Weight', '') or ''))
        if mzg_e:
            try:
                zg_e = int(mzg_e.group(1))
            except Exception:
                zg_e = None
        nige = bool(ctx and ctx.get('prev_kyaku') == '1')
        si = (ctx or {}).get('spurt_index')
        sr = (ctx or {}).get('spurt_runs', 0)
        if si is None and nm in nk_spurt_map:
            si, sr = nk_spurt_map[nm]
        spurt = bool(um in spurt_top3 and sr >= 2
                     and pd.notnull(pop) and pop >= 6)
        babafav = bool(
            pd.notnull(pop) and pop == 1 and (
                ('芝' in surf and baba in ('重', '不良')) or
                ('ダ' in surf and baba == '不良')))
        wetaxis = None
        fadewet = False
        if pd.notnull(pop) and pop <= 3 and baba in ('重', '不良'):
            hsire = str(r.get('sire') or '').strip()
            if not hsire or hsire == '-':
                hsire = _tb.sire_of_ketto(kt) if kt else None
            bmod = _tb.heavy_fav_blood_mod(hsire, surf, baba) if hsire else None
            if bmod and bmod['mod'] == 'exempt':
                babafav = False
                wetaxis = bmod
            elif bmod and bmod['mod'] == 'intensify':
                fadewet = True
        posr = []
        if gold:
            posr.append(f"黄金ライン(連対{g['top2']:.0%}/{g['rides']})")
        if tcok:
            posr.append(f"厩舎当ｺｰｽ{cs['win_rate']:.0%}")
        if spurt:
            posr.append(f"🔥末脚救出(指数{si:.1f})")
        if wetaxis:
            posr.append(f"🟢道悪軸(高含水○血統・ダ{baba})")
        negr = []
        if fade:
            negr.append('牝' + ('冬' if mo in (12, 1, 2) else '春') + 'ﾌｪｰﾄﾞ')
        if distchg:
            negr.append('大幅距離変更')
        if hatsud:
            negr.append('初ダート')
        if fluke:
            negr.append('前走フロック')
        if topswap:
            negr.append('トップ騎手乗替')
        if kinratio:
            negr.append('斤量比≥12.6%')
        if rest:
            negr.append('半年休み明け')
        # 指定記事の大幅増区分は前走比+20kg以上。ROI改善は未検証で、
        # 単独の強制消去にはせず、既存の危険材料と同じ集約ペナルティを使う。
        # https://note.com/rapid_toucan2286/n/nfa6e329b8a41
        if zg_e is not None and zg_e >= 20:
            negr.append('馬体重大幅増(+20kg以上)')
        if babafav:
            bf_txt = f'🌧️{baba}馬場×1番人気(複勝-5〜9pp検証)'
            if fadewet:
                bf_txt += '⚠瞬発/ステゴ系で裏付け'
            negr.append(bf_txt)
        if nige:
            negr.append('前走逃げ')
        try:
            agv = int(''.join(c for c in str(sa or '') if c.isdigit()) or 0)
            if agv >= 7:
                negr.append('高齢(7歳+)')
        except (TypeError, ValueError):
            pass
        try:
            prv = r.get('PastRuns')
            if isinstance(prv, list) and prv:
                if int(prv[0].get('Rank')) >= 5:
                    negr.append('前走5着以下')
        except (TypeError, ValueError):
            pass
        if um in gap_below:
            negr.append('🌊断層直下')
        pos = bool(posr)
        neg = bool(negr)
        score = -(float(pop) if pd.notnull(pop) else 18) + (1.5 if pos else 0) - (1.5 if neg else 0)
        tags = sorted(_er.compute_tags(
            ninki=(float(pop) if pd.notnull(pop) else None),
            prev_dist=(ctx or {}).get('prev_dist'), cur_dist=dist,
            layoff_days=gap_days, spurt_index=si, spurt_runs=sr,
            zogen=zg_e, sex_age=sa, prev_kyaku=(ctx or {}).get('prev_kyaku'),
            surface=surf, dirt_runs=(ctx or {}).get('dirt_runs'),
            topswap=topswap))
        figd = (_ct.get_figure(kt, surf) or _ct.get_figure(kt, None)) if kt else None
        ctbest = (figd or {}).get('fig')
        p = winp.get(um)
        ev = _bo.ev(p, odds) if (p and pd.notnull(odds)) else None
        fuk = _bo.place_prob(winp, um, all_um) if (p and len(all_um) >= 4) else None
        ren = _top2_prob(winp, um, all_um) if (p and len(all_um) >= 3) else None
        erows.append({'馬番': um, '馬名': nm,
                      '人気': int(pop) if pd.notnull(pop) else None,
                      'オッズ': float(odds) if pd.notnull(odds) else None,
                      'score': score, 'pos': pos, 'neg': neg,
                      '妙味材料': ' / '.join(posr) or '-',
                      '危険材料': (' / '.join(
                          ('🔴' + m if any(p in m for p in
                           ('🌧️', '半年休み明け', '高齢(7歳+)', '牝', '🌊断層')) else m)
                           for m in negr) or '-'),
                      '_ctbest': ctbest,
                      '_ev': ev, '_fuk': fuk, '_ren': ren,
                      '_tags': tags})
    return erows


def apply_verdict(erows, race_id, border_cnt=None, record_fired=True, apply_learning=True):
    """半分カット＋ボーダー残し＋学習残しを適用した DataFrame を返す。"""
    from core import elim_reasons as _er

    if not erows:
        return pd.DataFrame()
    edf = pd.DataFrame(erows).sort_values('score', ascending=False).reset_index(drop=True)
    n = len(edf)
    keep_n = (n + 1) // 2
    if border_cnt is None:
        border_cnt = default_border_count(n, race_id)
    try:
        border_cnt = int(border_cnt)
    except (TypeError, ValueError):
        border_cnt = 0
    border_max_n = border_max(n, race_id)
    border_cnt = max(0, min(border_cnt, border_max_n))

    def _verdict(i):
        if i < keep_n:
            return '✅残し'
        if border_cnt and keep_n <= i < keep_n + border_cnt:
            return '🛟ボーダー残し'
        return '🧹消し'

    edf['判定'] = [_verdict(i) for i in range(n)]
    if record_fired:
        try:
            fired_now = {}
            for ix, rr in edf.iterrows():
                if edf.at[ix, '判定'] == '🧹消し':
                    fired_now[int(rr['馬番'])] = list(rr.get('_tags') or [])
            if fired_now:
                _er.record_fired(race_id, fired_now)
        except Exception:
            pass
    edf['学習残し'] = ''
    if apply_learning:
        try:
            ledger = _er.load_ledger()
            learned = _er.learned_tags(ledger)
            if learned:
                for ix, rr in edf.iterrows():
                    if edf.at[ix, '判定'] == '🧹消し':
                        hit = sorted(set(rr.get('_tags') or []) & learned)
                        if hit:
                            edf.at[ix, '判定'] = '✅残し'
                            edf.at[ix, '学習残し'] = '♻️' + '/'.join(
                                _er.TAG_LABEL.get(k, k) for k in hit)
        except Exception:
            pass
    return edf


def keep_umaban_from_edf(edf):
    """✅残し＋🛟ボーダー残しの馬番リスト。"""
    if edf is None or edf.empty or '判定' not in edf.columns:
        return []
    return [int(x) for x in edf[edf['判定'] != '🧹消し']['馬番'].tolist()]


def run_and_persist(df, race_id, metadata, nk_spurt_map=None, border_cnt=None):
    """強適消去を実行し elim_keep / elim_verdict を保存。残馬 set を返す。"""
    from core import newspaper as _np
    from core import score_cache as _sc

    erows = compute_elim_rows(df, race_id, metadata, nk_spurt_map=nk_spurt_map)
    edf = apply_verdict(erows, race_id, border_cnt=border_cnt)
    keep_list = keep_umaban_from_edf(edf)
    if keep_list:
        _sc.write_elim_keep(race_id, keep_list)
    try:
        _np.write_elim_verdict_snapshot(
            race_id, edf[['馬番', '馬名', '判定']].to_dict('records'))
    except Exception:
        pass
    return set(keep_list), edf
