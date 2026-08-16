# -*- coding: utf-8 -*-
"""C中庸3連単 RRV構造の再現性検証。

1. ファミリー統合検証 (RRV/NRV/RRR/NRR/NNV/NNN)
2. 形の感度分析 (a,b,c grid)
3. VHの再順位付け効果
4. 配当帯別 RRV vs RRR
5. 年別分析
6. 最終判定

Usage: python scripts/rrv_structure_verify.py
"""
import os, sys, io, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8
ZONE_LO, ZONE_HI = 50, 70

FAMILIES = {
    'RRV': (1, 1, 2),
    'NRV': (0, 1, 2),
    'RRR': (1, 1, 1),
    'NRR': (0, 1, 1),
    'NNV': (0, 0, 2),
    'NNN': (0, 0, 0),
}
SHAPES = [(1,3,5),(1,3,7),(1,4,7),(2,3,6),(2,4,7),(2,5,8)]
PAY_BANDS = [(0,5000,'低'),(5000,20000,'中'),(20000,100000,'高'),(100000,9e9,'超高')]


def load_payouts_trifecta():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    result = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo).strip()
        if len(c) == 6 and c.isdigit():
            key = (int(c[:2]), int(c[2:4]), int(c[4:]))
            result[str(rk)].append((key, float(pay)))
    con.close()
    return dict(result)


def build_races():
    print('CSV読込...', file=sys.stderr)
    h = cd.load_horses(cols=['race_key','day','umaban','ninki','win_odds',
                             'chakujun','ability_score','vh2_score'])
    r = cd.load_races(cols=['race_key','field_size','kigo','is_handi1'])
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        odds_list = g['win_odds'].tolist()
        m = meta.get(rk)
        rv = vs.race_value_score(
            odds_list, {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                        'kigo': str(getattr(m, 'kigo', '') or '')},
            n_horses=len(g))
        if not rv or not (ZONE_LO <= rv['score'] < ZONE_HI):
            continue

        ninki_ord = g.sort_values('ninki', ascending=True)['umaban'].astype(int).tolist()
        rank_ord = g.sort_values('ability_score', ascending=True)['umaban'].astype(int).tolist()
        vh_ord = g.sort_values('vh2_score', ascending=False, na_position='last')['umaban'].astype(int).tolist()
        orders = [ninki_ord, rank_ord, vh_ord]

        fin = g.sort_values('chakujun')
        top3_ub = fin['umaban'].astype(int).tolist()[:3]
        if len(top3_ub) < 3:
            continue
        top3_pos = [[orders[oi].index(ub)+1 for ub in top3_ub] for oi in range(3)]
        hp = np.array([[orders[oi].index(ub)+1 for oi in range(3)]
                       for ub in g['umaban'].astype(int).tolist()], dtype=np.int16)

        horse_info = []
        for _, row in g.iterrows():
            ub = int(row['umaban'])
            horse_info.append(dict(
                ub=ub,
                ninki=int(row['ninki']) if pd.notna(row['ninki']) else 99,
                ninki_pos=ninki_ord.index(ub)+1,
                vh_pos=vh_ord.index(ub)+1,
                rank_pos=rank_ord.index(ub)+1,
                chakujun=int(row['chakujun']) if pd.notna(row['chakujun']) else 99,
            ))

        day_val = int(g['day'].iloc[0])
        yr = day_val // 10000
        period = 'train' if yr <= 2022 else ('val' if yr <= 2024 else
                 ('holdout' if yr == 2025 else 'recent'))

        out.append(dict(top3=tuple(top3_ub), day=day_val, year=yr,
                        period=period, n=len(g), top3_pos=top3_pos,
                        orders=orders, horse_pos=hp, rk=rk,
                        horse_info=horse_info))
    return out


def eval_trf(sel, pall, strat, shape):
    o1, o2, o3 = strat
    a, b, c = shape
    recs = []
    for d in sel:
        entries = pall.get(d['rk'])
        if not entries:
            continue
        hp = d['horse_pos']
        inA = hp[:,o1] <= a; inB = hp[:,o2] <= b; inC = hp[:,o3] <= c
        sA,sB,sC = int(inA.sum()),int(inB.sum()),int(inC.sum())
        sAB = int((inA&inB).sum()); sAC = int((inA&inC).sum()); sBC = int((inB&inC).sum())
        sABC = int((inA&inB&inC).sum())
        tc = max(0, sA*sB*sC - sAB*sC - sAC*sB - sBC*sA + 2*sABC)
        if tc == 0:
            continue
        cost = tc * 100
        pos = d['top3_pos']
        pay = 0
        if pos[o1][0] <= a and pos[o2][1] <= b and pos[o3][2] <= c:
            for combo, p in entries:
                if combo == d['top3']:
                    pay = p; break
        recs.append(dict(day=d['day'], year=d['year'], cost=cost, ret=pay, hit=pay>0, tc=tc))
    return recs


def summarise(recs):
    if not recs:
        return None
    tc = sum(r['cost'] for r in recs)
    tr = sum(r['ret'] for r in recs)
    hits = [r for r in recs if r['hit']]
    pnl = np.array([r['ret']-r['cost'] for r in recs], dtype=float)
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = float((peak - cum).max()) if len(cum) else 0
    med_hit = float(np.median([r['ret']/r['cost'] for r in hits])) if hits else 0
    return dict(n=len(recs), hit=len(hits),
                rate=len(hits)/len(recs)*100,
                roi=tr/tc*100 if tc else 0,
                med_hit_roi=med_hit*100,
                max_dd=dd, total_cost=tc, total_ret=tr)


def yearly_stats(recs):
    by_yr = defaultdict(list)
    for r in recs:
        by_yr[r['year']].append(r)
    out = {}
    for yr in sorted(by_yr):
        yr_recs = by_yr[yr]
        tc = sum(r['cost'] for r in yr_recs)
        tr = sum(r['ret'] for r in yr_recs)
        hits = [r for r in yr_recs if r['hit']]
        pnl = np.array([r['ret']-r['cost'] for r in yr_recs], dtype=float)
        cum = np.cumsum(pnl)
        peak = np.maximum.accumulate(cum)
        dd = float((peak - cum).max()) if len(cum) else 0
        out[yr] = dict(n=len(yr_recs), hit=len(hits),
                       rate=len(hits)/len(yr_recs)*100 if yr_recs else 0,
                       roi=tr/tc*100 if tc else 0,
                       avg_pay=np.mean([r['ret'] for r in hits]) if hits else 0,
                       med_pay=np.median([r['ret'] for r in hits]) if hits else 0,
                       max_dd=dd)
    return out


# ─────────────────────────────────────────
# Section 1: Family comparison
# ─────────────────────────────────────────
def section1(races, pall):
    print(f'\n{"="*78}')
    print('■ 1. ファミリー統合検証（形ごとのROI分布）')
    print(f'{"="*78}')

    PERIODS = [('train','≤2022'), ('val','2023-24'), ('holdout','2025')]
    for plbl, pdisp in PERIODS:
        sel = [d for d in races if d['period'] == plbl]
        if len(sel) < 30:
            continue
        print(f'\n  ━━ {pdisp} ({len(sel):,}R) ━━')
        print(f'  {"ファミリー":>10} {"形":>10} {"R数":>5} {"的中":>4} {"率%":>5}'
              f' {"ROI%":>6} {"的中時中央ROI%":>14} {"maxDD千円":>10}')
        print(f'  {"-"*72}')

        family_summary = {}
        for flbl, strat in FAMILIES.items():
            rois = []
            total_n = total_hit = 0; total_cost = total_ret = 0.0
            for sh in SHAPES:
                recs = eval_trf(sel, pall, strat, sh)
                s = summarise(recs)
                if not s:
                    continue
                slbl = f'{sh[0]}-{sh[1]}-{sh[2]}'
                print(f'  {flbl:>10} {slbl:>10} {s["n"]:>5} {s["hit"]:>4} {s["rate"]:>5.1f}'
                      f' {s["roi"]:>6.0f} {s["med_hit_roi"]:>14.0f} {s["max_dd"]/1000:>10.0f}')
                rois.append(s['roi'])
                total_n += s['n']; total_hit += s['hit']
                total_cost += s['total_cost']; total_ret += s['total_ret']

            if rois:
                pool_roi = total_ret/total_cost*100 if total_cost else 0
                family_summary[flbl] = dict(
                    median_roi=np.median(rois), min_roi=min(rois),
                    max_roi=max(rois), pooled_roi=pool_roi, std=np.std(rois))
                print(f'  {flbl:>10} {"★集約":>10}  ROI中央値{np.median(rois):.0f}%'
                      f'  範囲{min(rois):.0f}-{max(rois):.0f}%'
                      f'  プール{pool_roi:.0f}%  SD{np.std(rois):.1f}')
            print()

        if family_summary:
            print(f'  ── ファミリー順位（プールROI） ──')
            for flbl, fs in sorted(family_summary.items(), key=lambda x: -x[1]['pooled_roi']):
                print(f'    {flbl}: プールROI {fs["pooled_roi"]:.0f}%'
                      f'  中央値{fs["median_roi"]:.0f}%  SD{fs["std"]:.1f}')


# ─────────────────────────────────────────
# Section 2: Sensitivity grid
# ─────────────────────────────────────────
def section2(races, pall):
    print(f'\n{"="*78}')
    print('■ 2. RRV 形の感度分析 (1着=Rank a, 2着=Rank b, 3着=VH c)')
    print(f'{"="*78}')

    PERIODS = [('train','≤2022'), ('val','2023-24'), ('holdout','2025')]
    strat = (1, 1, 2)
    for plbl, pdisp in PERIODS:
        sel = [d for d in races if d['period'] == plbl]
        if len(sel) < 30:
            continue
        print(f'\n  ━━ {pdisp} ({len(sel):,}R) ━━')

        for a in [1, 2, 3]:
            print(f'\n  1着=Rank上位{a}頭')
            cs = list(range(3, 11))
            print(f'  {"2着＼3着":>8}', end='')
            for c in cs:
                print(f' {"VH"+str(c):>6}', end='')
            print()
            for b in range(max(2, a), 7):
                print(f'  {"R"+str(b):>8}', end='')
                for c in cs:
                    recs = eval_trf(sel, pall, strat, (a, b, c))
                    s = summarise(recs)
                    roi = s['roi'] if s else 0
                    print(f' {roi:>5.0f}%', end='')
                print()


# ─────────────────────────────────────────
# Section 3: VH re-ranking effect
# ─────────────────────────────────────────
def section3(races):
    print(f'\n{"="*78}')
    print('■ 3. VHの再順位付け効果（人気上位7頭の順位変動と3着内率）')
    print(f'{"="*78}')

    TOP = 7
    all_periods = [d for d in races if d['period'] in ('train', 'val')]

    move_top3 = defaultdict(lambda: [0, 0])
    for d in all_periods:
        top3_set = set(d['top3'])
        for hi in d['horse_info']:
            if hi['ninki_pos'] > TOP:
                continue
            delta = hi['ninki_pos'] - hi['vh_pos']
            if delta >= 2:
                cat = 'VH昇格(+2↑)'
            elif delta <= -2:
                cat = 'VH降格(-2↓)'
            else:
                cat = '同等(±1)'
            in_top3 = hi['chakujun'] <= 3
            move_top3[cat][0] += 1
            if in_top3:
                move_top3[cat][1] += 1

    print(f'\n  人気上位{TOP}頭のVH順位変動 → 3着内率')
    print(f'  {"カテゴリ":>16} {"頭数":>8} {"3着内":>6} {"3着内率":>8}')
    print(f'  {"-"*42}')
    for cat in ['VH昇格(+2↑)', '同等(±1)', 'VH降格(-2↓)']:
        total, top3 = move_top3[cat]
        rate = top3/total*100 if total else 0
        print(f'  {cat:>16} {total:>8,} {top3:>6,} {rate:>7.1f}%')

    print(f'\n  詳細: 人気→VH順位ごとの3着内率')
    print(f'  {"人気":>4} → {"VH":>4} {"頭数":>8} {"3着内率":>8}')
    print(f'  {"-"*30}')
    detail = defaultdict(lambda: [0, 0])
    for d in all_periods:
        for hi in d['horse_info']:
            if hi['ninki_pos'] > TOP:
                continue
            key = (hi['ninki_pos'], min(hi['vh_pos'], 10))
            detail[key][0] += 1
            if hi['chakujun'] <= 3:
                detail[key][1] += 1

    for nk in range(1, TOP+1):
        for vk in [1, 2, 3, 4, 5, 7]:
            total, top3 = detail.get((nk, vk), [0, 0])
            if total < 100:
                continue
            rate = top3/total*100
            mark = '★' if abs(nk - vk) >= 3 else ''
            print(f'  {nk:>4} → {vk:>4} {total:>8,} {rate:>7.1f}% {mark}')

    print(f'\n  ── 1着入線率（人気×VH順位変動）──')
    win_data = defaultdict(lambda: [0, 0])
    for d in all_periods:
        for hi in d['horse_info']:
            if hi['ninki_pos'] > 3:
                continue
            delta = hi['ninki_pos'] - hi['vh_pos']
            cat = 'VH昇格' if delta >= 2 else ('VH降格' if delta <= -2 else '同等')
            win_data[cat][0] += 1
            if hi['chakujun'] == 1:
                win_data[cat][1] += 1
    print(f'  {"カテゴリ":>12} {"頭数":>8} {"勝率":>8}')
    for cat in ['VH昇格', '同等', 'VH降格']:
        total, wins = win_data[cat]
        print(f'  {cat:>12} {total:>8,} {wins/total*100 if total else 0:>7.1f}%')


# ─────────────────────────────────────────
# Section 4: Payout band comparison
# ─────────────────────────────────────────
def section4(races, pall):
    print(f'\n{"="*78}')
    print('■ 4. 配当帯別 RRV vs RRR （全形プール）')
    print(f'{"="*78}')

    sel = [d for d in races if d['period'] in ('train', 'val')]

    for flbl, strat in [('RRV', (1,1,2)), ('RRR', (1,1,1))]:
        all_hits = []
        for sh in SHAPES:
            recs = eval_trf(sel, pall, strat, sh)
            for r in recs:
                if r['hit']:
                    all_hits.append(r)

        print(f'\n  【{flbl}】的中{len(all_hits):,}回')
        print(f'  {"配当帯":>8} {"件数":>6} {"構成比":>7} {"平均配当":>10} {"中央値":>10}')
        print(f'  {"-"*48}')
        for lo, hi, lbl in PAY_BANDS:
            band = [h for h in all_hits if lo <= h['ret'] < hi]
            if not band:
                continue
            avg = np.mean([h['ret'] for h in band])
            med = np.median([h['ret'] for h in band])
            pct = len(band)/len(all_hits)*100
            print(f'  {lbl:>8} {len(band):>6} {pct:>6.1f}% {avg:>10,.0f} {med:>10,.0f}')

    print(f'\n  ── RRV vs RRR 配当帯構成比の差 ──')
    for compare_sh in [(2,4,7), (1,4,7)]:
        slbl = f'{compare_sh[0]}-{compare_sh[1]}-{compare_sh[2]}'
        rrv_recs = eval_trf(sel, pall, (1,1,2), compare_sh)
        rrr_recs = eval_trf(sel, pall, (1,1,1), compare_sh)
        rrv_hits = [r for r in rrv_recs if r['hit']]
        rrr_hits = [r for r in rrr_recs if r['hit']]
        if not rrv_hits or not rrr_hits:
            continue

        print(f'\n  形{slbl}:')
        print(f'  {"帯":>6} {"RRV件":>6} {"RRV%":>6} {"RRR件":>6} {"RRR%":>6} {"差":>6}')
        for lo, hi, lbl in PAY_BANDS:
            v_cnt = sum(1 for h in rrv_hits if lo <= h['ret'] < hi)
            r_cnt = sum(1 for h in rrr_hits if lo <= h['ret'] < hi)
            v_pct = v_cnt/len(rrv_hits)*100
            r_pct = r_cnt/len(rrr_hits)*100
            print(f'  {lbl:>6} {v_cnt:>6} {v_pct:>5.1f}% {r_cnt:>6} {r_pct:>5.1f}%'
                  f' {v_pct-r_pct:>+5.1f}')


# ─────────────────────────────────────────
# Section 5: Yearly analysis
# ─────────────────────────────────────────
def section5(races, pall):
    print(f'\n{"="*78}')
    print('■ 5. RRV系 年別分析')
    print(f'{"="*78}')

    all_data = [d for d in races if d['period'] in ('train', 'val', 'holdout')]

    for flbl, strat in [('RRV', (1,1,2)), ('RRR', (1,1,1))]:
        print(f'\n  ─── {flbl} (全形プール) ───')
        all_recs = []
        for sh in SHAPES:
            all_recs.extend(eval_trf(all_data, pall, strat, sh))

        ys = yearly_stats(all_recs)
        print(f'  {"年":>6} {"R数":>5} {"的中":>4} {"率%":>5} {"ROI%":>6}'
              f' {"平均配当":>10} {"中央値":>10} {"maxDD千円":>10}')
        print(f'  {"-"*62}')
        roi_list = []
        for yr in sorted(ys):
            y = ys[yr]
            print(f'  {yr:>6} {y["n"]:>5} {y["hit"]:>4} {y["rate"]:>5.1f} {y["roi"]:>6.0f}'
                  f' {y["avg_pay"]:>10,.0f} {y["med_pay"]:>10,.0f} {y["max_dd"]/1000:>10.0f}')
            roi_list.append(y['roi'])

        if roi_list:
            above = sum(1 for r in roi_list if r >= 100)
            print(f'  ROI≥100%: {above}/{len(roi_list)}年'
                  f'  中央値{np.median(roi_list):.0f}% SD{np.std(roi_list):.1f}')

    print(f'\n  ─── 代表形の年別比較 (2-4-7) ───')
    for flbl, strat in [('RRV', (1,1,2)), ('RRR', (1,1,1)), ('NRV', (0,1,2))]:
        recs = eval_trf(all_data, pall, strat, (2,4,7))
        ys = yearly_stats(recs)
        rois = [ys[yr]['roi'] for yr in sorted(ys)]
        print(f'  {flbl}(2-4-7): ', end='')
        parts = [f'{yr}:{ys[yr]["roi"]:.0f}%' for yr in sorted(ys)]
        print(' '.join(parts))
        above = sum(1 for r in rois if r >= 100)
        print(f'    ROI≥100%: {above}/{len(rois)}年  中央値{np.median(rois):.0f}%')


# ─────────────────────────────────────────
# Section 6: Final verdict
# ─────────────────────────────────────────
def section6(races, pall):
    print(f'\n{"="*78}')
    print('■ 6. 最終判定')
    print(f'{"="*78}')

    PERIODS = [('train','≤2022'), ('val','2023-24'), ('holdout','2025')]
    verdict = {}
    for flbl, strat in [('RRV',(1,1,2)), ('RRR',(1,1,1)), ('NRV',(0,1,2)), ('NNV',(0,0,2))]:
        verdict[flbl] = {}
        for plbl, pdisp in PERIODS:
            sel = [d for d in races if d['period'] == plbl]
            if len(sel) < 30:
                continue
            rois = []
            for sh in SHAPES:
                recs = eval_trf(sel, pall, strat, sh)
                s = summarise(recs)
                if s:
                    rois.append(s['roi'])
            if rois:
                verdict[flbl][plbl] = dict(
                    median=np.median(rois), mean=np.mean(rois),
                    min=min(rois), max=max(rois), std=np.std(rois))

    print(f'\n  ── ファミリー別 ROI中央値の推移 ──')
    print(f'  {"ファミリー":>10}', end='')
    for _, pdisp in PERIODS:
        print(f' {pdisp:>10}', end='')
    print(f' {"安定性":>8}')
    print(f'  {"-"*50}')

    for flbl in ['RRV', 'NRV', 'RRR', 'NNV']:
        print(f'  {flbl:>10}', end='')
        vals = []
        for plbl, _ in PERIODS:
            v = verdict[flbl].get(plbl)
            if v:
                print(f' {v["median"]:>9.0f}%', end='')
                vals.append(v['median'])
            else:
                print(f' {"N/A":>10}', end='')
        if len(vals) >= 2:
            stability = np.std(vals)
            trend = vals[-1] - vals[0] if len(vals) >= 2 else 0
            print(f' SD{stability:.1f} Δ{trend:+.0f}')
        else:
            print()

    print(f'\n  ── 判定基準 ──')
    print(f'  A正式採用: 全期間ROI中央値≥90% + holdout≥train + SD<5')
    print(f'  B条件付き: 全期間≥85% + holdout≥85% + 一部形で100%超え')
    print(f'  C検証継続: holdout有望だが安定性不足')
    print(f'  D不採用:   holdout崩壊 or 全期間<85%')

    rrv = verdict.get('RRV', {})
    rrr = verdict.get('RRR', {})
    nrv = verdict.get('NRV', {})

    all_ok = True
    reasons = []

    train_v = rrv.get('train', {})
    val_v = rrv.get('val', {})
    hold_v = rrv.get('holdout', {})

    if train_v and val_v and hold_v:
        t_med, v_med, h_med = train_v['median'], val_v['median'], hold_v['median']

        if h_med >= t_med:
            reasons.append(f'holdout({h_med:.0f}%) ≥ train({t_med:.0f}%) ✓')
        else:
            reasons.append(f'holdout({h_med:.0f}%) < train({t_med:.0f}%) ✗')

        all_meds = [t_med, v_med, h_med]
        sd = np.std(all_meds)
        reasons.append(f'期間SD={sd:.1f}')

        rrr_h = rrr.get('holdout', {}).get('median', 0)
        if h_med > rrr_h:
            reasons.append(f'RRV({h_med:.0f}%) > RRR({rrr_h:.0f}%) in holdout ✓')
        else:
            reasons.append(f'RRV({h_med:.0f}%) ≤ RRR({rrr_h:.0f}%) in holdout ✗')

        if min(all_meds) >= 90 and h_med >= t_med and sd < 5:
            grade = 'A'
        elif min(all_meds) >= 85 and h_med >= 85:
            grade = 'B'
        elif h_med >= 85:
            grade = 'C'
        else:
            grade = 'D'
    else:
        grade = 'C'
        reasons.append('一部期間のデータ不足')

    print(f'\n  ══════════════════════════════════')
    print(f'  RRV構造の判定: 【{grade}】')
    print(f'  ══════════════════════════════════')
    for r in reasons:
        print(f'    {r}')

    if grade in ('A', 'B'):
        print(f'\n  ── 推奨運用 ──')
        print(f'  C中庸ゾーン(vscore 50-70)で3連単を購入する場合:')
        print(f'    1着: Rank上位 1-2頭')
        print(f'    2着: Rank上位 3-5頭')
        print(f'    3着: VH上位 5-8頭')
        print(f'    特定の形に固定せず、点数10-30点の範囲で調整')
    elif grade == 'C':
        print(f'\n  次回検証ポイント:')
        print(f'    - 2026年前半のout-of-time検証')
        print(f'    - 他のゾーンでの比較（D鉄板でNNVとの差など）')


def main():
    races = build_races()
    print(f'C中庸 {len(races):,}R', file=sys.stderr)
    pall = load_payouts_trifecta()

    n_t = sum(1 for d in races if d['period'] == 'train')
    n_v = sum(1 for d in races if d['period'] == 'val')
    n_h = sum(1 for d in races if d['period'] == 'holdout')
    print(f'C中庸 対象 {len(races):,}R (train: {n_t:,} / val: {n_v:,} / hold: {n_h:,})\n')

    section1(races, pall)
    section2(races, pall)
    section3(races)
    section4(races, pall)
    section5(races, pall)
    section6(races, pall)


if __name__ == '__main__':
    main()
