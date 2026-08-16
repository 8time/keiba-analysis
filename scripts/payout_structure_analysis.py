# -*- coding: utf-8 -*-
"""妙味度×配当構造×馬のタイプ 条件付き分析。

A 妙味度分類 → B 配当分布 → C 馬の特徴 → D 重なり → E 着順別 → F 買い方ルール

train≤2022 / val=2023-2024 / holdout=2025

Usage: python scripts/payout_structure_analysis.py
"""
import os, sys, io, sqlite3
from collections import defaultdict
from math import comb

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd
from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8
ZONES = [('D鉄板', 0, 50), ('C中庸', 50, 70), ('荒れ', 70, 201)]
BET_TYPES = ['単勝', '複勝', 'ワイド', '馬連', '馬単', '3連複', '3連単']

PAY_RANGES = {
    '3連単': [(0,5000,'低'),(5000,20000,'中'),(20000,100000,'高'),(100000,9e9,'超高')],
    '3連複': [(0,1000,'低'),(1000,5000,'中'),(5000,20000,'高'),(20000,9e9,'超高')],
    '馬連':  [(0,1000,'低'),(1000,5000,'中'),(5000,9e9,'高')],
    '馬単':  [(0,2000,'低'),(2000,10000,'中'),(10000,9e9,'高')],
    '単勝':  [(0,300,'低'),(300,1000,'中'),(1000,9e9,'高')],
    '複勝':  [(0,200,'低'),(200,500,'中'),(500,9e9,'高')],
    'ワイド': [(0,500,'低'),(500,2000,'中'),(2000,9e9,'高')],
}

STRAT3 = {'NNN':(0,0,0),'RRR':(1,1,1),'NNV':(0,0,2),'NRV':(0,1,2),'RRV':(1,1,2)}
SHAPES_TRF = [(2,4,7),(1,3,5),(1,4,7),(2,3,6),(1,3,7),(2,5,8)]
SHAPES_TRI = [(2,3,6),(1,4,7),(2,4,7),(2,5,8),(1,3,5)]

STRAT2 = {'NN':(0,0),'RR':(1,1),'NR':(0,1),'NV':(0,2),'RV':(1,2)}
SHAPES_2 = [(1,3),(1,4),(2,4),(2,5),(1,5),(2,6)]


def load_all_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    result = defaultdict(lambda: defaultdict(list))
    for rk, bt, combo, pay in con.execute(
            "SELECT race_key, bet_type, combo, payout FROM payouts"):
        c = str(combo).strip()
        if not c.isdigit():
            continue
        rk, pay = str(rk), float(pay)
        if bt in ('単勝', '複勝') and len(c) == 2:
            result[rk][bt].append((int(c), pay))
        elif bt in ('馬連', 'ワイド', '馬単', '枠連') and len(c) == 4:
            result[rk][bt].append(((int(c[:2]), int(c[2:])), pay))
        elif bt in ('3連複', '3連単') and len(c) == 6:
            result[rk][bt].append(((int(c[:2]), int(c[2:4]), int(c[4:])), pay))
    con.close()
    return result


def build_races():
    print('CSV読込...', file=sys.stderr)
    h = cd.load_horses(cols=['race_key','day','umaban','ninki','win_odds',
                             'chakujun','ability_score','vh2_score'])
    r = cd.load_races(cols=['race_key','field_size','kigo','is_handi1'])
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    print('レース構築...', file=sys.stderr)
    out = {}
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        odds_list = g['win_odds'].tolist()
        m = meta.get(rk)
        rv = vs.race_value_score(
            odds_list, {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                        'kigo': str(getattr(m, 'kigo', '') or '')},
            n_horses=len(g))
        if not rv:
            continue
        ninki_ord = g.sort_values('ninki', ascending=True)['umaban'].astype(int).tolist()
        rank_ord = g.sort_values('ability_score', ascending=True)['umaban'].astype(int).tolist()
        vh_ord = g.sort_values('vh2_score', ascending=False, na_position='last')['umaban'].astype(int).tolist()
        orders = [ninki_ord, rank_ord, vh_ord]

        fin = g.sort_values('chakujun')
        top3_ub = fin['umaban'].astype(int).tolist()[:3]
        if len(top3_ub) < 3:
            continue
        top3_ninki = fin['ninki'].astype(int).tolist()[:3]
        top3_odds = fin['win_odds'].tolist()[:3]
        top3_pos = [[orders[oi].index(ub)+1 for ub in top3_ub] for oi in range(3)]

        hp = np.array([[orders[oi].index(ub)+1 for oi in range(3)]
                       for ub in g['umaban'].astype(int).tolist()], dtype=np.int16)

        day_val = int(g['day'].iloc[0])
        yr = day_val // 10000
        period = 'train' if yr <= 2022 else ('val' if yr <= 2024 else ('holdout' if yr == 2025 else 'recent'))

        out[rk] = dict(vscore=rv['score'], top3=tuple(top3_ub), day=day_val, year=yr,
                       period=period, n=len(g), top3_pos=top3_pos, top3_ninki=top3_ninki,
                       top3_odds=top3_odds, orders=orders, horse_pos=hp, rk=rk)
    return out


def rep_payout(entries):
    return max(pay for _, pay in entries) if entries else None


def section_b(races, pall):
    print(f'\n{"="*78}')
    print('■ B: 妙味度ゾーン別 配当分布')
    print(f'{"="*78}')
    for zlbl, zlo, zhi in ZONES:
        zraces = [d for d in races if zlo <= d['vscore'] < zhi]
        print(f'\n{"─"*60}\n【{zlbl}】{len(zraces):,}R')
        for bt in BET_TYPES:
            vals = []
            for d in zraces:
                pl = pall.get(d['rk'], {}).get(bt)
                if pl:
                    vals.append(rep_payout(pl))
            if not vals:
                continue
            a = np.array(vals)
            print(f'\n  {bt}:')
            print(f'    中央値{np.median(a):>10,.0f}  平均{a.mean():>10,.0f}'
                  f'  25%{np.percentile(a,25):>8,.0f}  75%{np.percentile(a,75):>8,.0f}'
                  f'  90%{np.percentile(a,90):>8,.0f}')
            ranges = PAY_RANGES.get(bt, [])
            if ranges:
                parts = []
                for lo, hi, lbl in ranges:
                    cnt = ((a >= lo) & (a < hi)).sum()
                    parts.append(f'{lbl}{cnt/len(a)*100:.0f}%')
                print(f'    分布: {" / ".join(parts)}')


def section_c(races, pall):
    print(f'\n{"="*78}')
    print('■ C: ゾーン×3連単配当レンジ別 着順馬の特徴')
    print(f'{"="*78}')
    for zlbl, zlo, zhi in ZONES:
        zraces = [d for d in races if zlo <= d['vscore'] < zhi]
        for plo, phi, plbl in PAY_RANGES['3連単']:
            sub = []
            for d in zraces:
                pl = pall.get(d['rk'], {}).get('3連単')
                if pl:
                    p = rep_payout(pl)
                    if plo <= p < phi:
                        sub.append(d)
            if len(sub) < 50:
                continue
            print(f'\n  [{zlbl} / 3連単{plbl}配当] {len(sub):,}R')
            print(f'  {"着順":>6} {"人気中央":>8} {"Rank中央":>10} {"VH中央":>8} {"オッズ中央":>10}')
            for pi in range(3):
                nm = np.median([d['top3_ninki'][pi] for d in sub])
                rm = np.median([d['top3_pos'][1][pi] for d in sub])
                vm = np.median([d['top3_pos'][2][pi] for d in sub])
                om = np.median([d['top3_odds'][pi] for d in sub])
                print(f'  {pi+1}着: {nm:>6.0f}番 {rm:>8.0f}位 {vm:>6.0f}位 {om:>8.1f}倍')


def section_d(races):
    print(f'\n{"="*78}')
    print('■ D: 上位7頭の重なり分析')
    print(f'{"="*78}')
    TOP = 7
    for zlbl, zlo, zhi in ZONES:
        zraces = [d for d in races if zlo <= d['vscore'] < zhi]
        if not zraces:
            continue
        print(f'\n  【{zlbl}】{len(zraces):,}R')

        nr_ov, nv_ov, rv_ov = [], [], []
        vh_not_ninki, rank_not_ninki, vh_not_rank = [], [], []
        for d in zraces:
            nset = set(d['orders'][0][:TOP])
            rset = set(d['orders'][1][:TOP])
            vset = set(d['orders'][2][:TOP])
            nr_ov.append(len(nset & rset))
            nv_ov.append(len(nset & vset))
            rv_ov.append(len(rset & vset))
            vh_not_ninki.append(len(vset - nset))
            rank_not_ninki.append(len(rset - nset))
            vh_not_rank.append(len(vset - rset))

        print(f'    人気∩Rank: 平均{np.mean(nr_ov):.1f}頭  人気∩VH: {np.mean(nv_ov):.1f}頭'
              f'  Rank∩VH: {np.mean(rv_ov):.1f}頭  (/{TOP}頭)')
        print(f'    VH独自(人気外): {np.mean(vh_not_ninki):.1f}頭'
              f'  Rank独自(人気外): {np.mean(rank_not_ninki):.1f}頭'
              f'  VH独自(Rank外): {np.mean(vh_not_rank):.1f}頭')

        print(f'\n    馬のタイプ分類（{TOP}頭中の平均出現数）:')
        types = defaultdict(list)
        for d in zraces:
            nset = set(d['orders'][0][:TOP])
            rset = set(d['orders'][1][:TOP])
            vset = set(d['orders'][2][:TOP])
            for ub in set(d['orders'][0][:d['n']]):
                inn = ub in nset
                inr = ub in rset
                inv = ub in vset
                if inn and inr and inv:
                    types['全一致'].append(1)
                elif inv and not inn:
                    types['VH独自(人気外)'].append(1)
                elif inr and not inn:
                    types['Rank独自(人気外)'].append(1)
                elif inv and not inr:
                    types['VH独自(Rank外)'].append(1)
        for k in ['全一致', 'VH独自(人気外)', 'Rank独自(人気外)', 'VH独自(Rank外)']:
            v = types.get(k, [])
            avg = len(v) / len(zraces) if zraces else 0
            print(f'      {k}: {avg:.1f}頭/R')


def section_e(races):
    print(f'\n{"="*78}')
    print('■ E: 3着馬の捕捉率 (上位N頭にいる率)')
    print(f'{"="*78}')
    for zlbl, zlo, zhi in ZONES:
        zraces = [d for d in races if zlo <= d['vscore'] < zhi]
        if len(zraces) < 100:
            continue
        print(f'\n  【{zlbl}】{len(zraces):,}R')
        for N in [5, 7, 9]:
            n_cap = {0: 0, 1: 0, 2: 0}
            for d in zraces:
                for oi in range(3):
                    if d['top3_pos'][oi][2] <= N:
                        n_cap[oi] += 1
            tot = len(zraces)
            lbls = ['人気', 'Rank', 'VH']
            parts = [f'{lbls[oi]}={n_cap[oi]/tot*100:.1f}%' for oi in range(3)]
            print(f'    上位{N}頭: {" / ".join(parts)}')


# ── 戦略評価関数群 ──

def _find_pay(entries, key):
    for combo, pay in entries:
        if combo == key:
            return pay
    return 0

def _find_pay_sorted(entries, key):
    for combo, pay in entries:
        if tuple(sorted(combo)) == tuple(sorted(key)):
            return pay
    return 0


def eval_tansho(sel, pall, oi, top_n):
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('単勝')
        if not pl: continue
        n += 1; cost += top_n * 100
        if d['top3_pos'][oi][0] <= top_n:
            hit += 1
            ret += _find_pay(pl, d['top3'][0])
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0, pts=top_n)


def eval_fukusho(sel, pall, oi, top_n):
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('複勝')
        if not pl: continue
        n += 1; cost += top_n * 100
        fmap = {ub: pay for ub, pay in pl}
        rh = False
        for i in range(3):
            if d['top3_pos'][oi][i] <= top_n:
                p = fmap.get(d['top3'][i], 0)
                if p > 0:
                    ret += p; rh = True
        if rh: hit += 1
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0, pts=top_n)


def eval_quinella(sel, pall, strat, shape):
    o1, o2 = strat; a, b = shape
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('馬連')
        if not pl: continue
        A = set(d['orders'][o1][:a]); B = set(d['orders'][o2][:b])
        tc = len({tuple(sorted((x,y))) for x in A for y in B if x != y})
        if tc == 0: continue
        n += 1; cost += tc * 100
        key = tuple(sorted(d['top3'][:2]))
        ub1, ub2 = key
        if (ub1 in A and ub2 in B) or (ub2 in A and ub1 in B):
            hit += 1; ret += _find_pay_sorted(pl, key)
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0, pts=tc if sel else 0)


def eval_exacta(sel, pall, strat, shape):
    o1, o2 = strat; a, b = shape
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('馬単')
        if not pl: continue
        A = set(d['orders'][o1][:a]); B = set(d['orders'][o2][:b])
        tc = len({(x,y) for x in A for y in B if x != y})
        if tc == 0: continue
        n += 1; cost += tc * 100
        win = d['top3'][:2]
        if win[0] in A and win[1] in B:
            hit += 1; ret += _find_pay(pl, win)
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0, pts=tc if sel else 0)


def eval_wide(sel, pall, strat, shape):
    o1, o2 = strat; a, b = shape
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('ワイド')
        if not pl: continue
        A = set(d['orders'][o1][:a]); B = set(d['orders'][o2][:b])
        tickets = {tuple(sorted((x,y))) for x in A for y in B if x != y}
        if not tickets: continue
        n += 1; cost += len(tickets) * 100
        rh = False
        top3 = d['top3']
        for i, j in [(0,1),(0,2),(1,2)]:
            pair = tuple(sorted((top3[i], top3[j])))
            if pair in tickets:
                rh = True
                for combo, pay in pl:
                    if tuple(sorted(combo)) == pair:
                        ret += pay; break
        if rh: hit += 1
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0, pts=len(tickets) if sel else 0)


def eval_trio(sel, pall, strat, shape):
    o1, o2, o3 = strat; a, b, c = shape
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('3連複')
        if not pl: continue
        A = set(d['orders'][o1][:a]); B = set(d['orders'][o2][:b]); C = set(d['orders'][o3][:c])
        tickets = set()
        for x in A:
            for y in B:
                if y == x: continue
                for z in C:
                    if z == x or z == y: continue
                    tickets.add(tuple(sorted((x,y,z))))
        if not tickets: continue
        n += 1; cost += len(tickets) * 100
        key = tuple(sorted(d['top3']))
        if key in tickets:
            hit += 1; ret += _find_pay_sorted(pl, key)
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0,
                pts=len(tickets) if sel else 0)


def eval_trifecta(sel, pall, strat, shape):
    o1, o2, o3 = strat; a, b, c = shape
    cost, ret, hit, n = 0, 0.0, 0, 0
    for d in sel:
        pl = pall.get(d['rk'], {}).get('3連単')
        if not pl: continue
        hp = d['horse_pos']
        inA = hp[:, o1] <= a; inB = hp[:, o2] <= b; inC = hp[:, o3] <= c
        sA, sB, sC = int(inA.sum()), int(inB.sum()), int(inC.sum())
        sAB = int((inA & inB).sum()); sAC = int((inA & inC).sum()); sBC = int((inB & inC).sum())
        sABC = int((inA & inB & inC).sum())
        tc = max(0, sA*sB*sC - sAB*sC - sAC*sB - sBC*sA + 2*sABC)
        if tc == 0: continue
        n += 1; cost += tc * 100
        pos = d['top3_pos']
        if pos[o1][0] <= a and pos[o2][1] <= b and pos[o3][2] <= c:
            hit += 1; ret += _find_pay(pl, d['top3'])
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/cost*100 if cost else 0, pts=tc if sel else 0)


def section_f(races, pall):
    print(f'\n{"="*78}')
    print('■ F: 券種×戦略のゾーン別ROI比較')
    print(f'{"="*78}')

    PERIODS = [('train', 'train≤2022'), ('val', 'val 2023-24'), ('holdout', 'hold 2025')]
    all_rules = []

    for zlbl, zlo, zhi in ZONES:
        print(f'\n{"━"*78}\n▶ {zlbl}')

        for plbl, pdisp in PERIODS:
            sel = [d for d in races if zlo <= d['vscore'] < zhi and d['period'] == plbl]
            if len(sel) < 30:
                print(f'\n  [{pdisp}] {len(sel)}R（不足）')
                continue
            print(f'\n  [{pdisp}] {len(sel):,}R')

            results = []

            # ── 単勝 ──
            for olbl, oi in [('N',0),('R',1),('V',2)]:
                for tn in [1, 2]:
                    r = eval_tansho(sel, pall, oi, tn)
                    if r['n'] >= 30:
                        results.append(dict(券種='単勝', 戦略=f'{olbl}{tn}', **r))

            # ── 複勝 ──
            for olbl, oi in [('N',0),('R',1),('V',2)]:
                for tn in [1, 2, 3]:
                    r = eval_fukusho(sel, pall, oi, tn)
                    if r['n'] >= 30:
                        results.append(dict(券種='複勝', 戦略=f'{olbl}{tn}', **r))

            # ── 馬連 ──
            for slbl, st in STRAT2.items():
                for sh in SHAPES_2:
                    r = eval_quinella(sel, pall, st, sh)
                    if r['n'] >= 30:
                        results.append(dict(券種='馬連', 戦略=f'{slbl}{sh[0]}-{sh[1]}', **r))

            # ── 馬単 ──
            for slbl, st in STRAT2.items():
                for sh in SHAPES_2:
                    r = eval_exacta(sel, pall, st, sh)
                    if r['n'] >= 30:
                        results.append(dict(券種='馬単', 戦略=f'{slbl}{sh[0]}-{sh[1]}', **r))

            # ── ワイド ──
            for slbl, st in STRAT2.items():
                for sh in [(2,4),(2,5),(3,5)]:
                    r = eval_wide(sel, pall, st, sh)
                    if r['n'] >= 30:
                        results.append(dict(券種='ワイド', 戦略=f'{slbl}{sh[0]}-{sh[1]}', **r))

            # ── 3連複 ──
            for slbl, st in STRAT3.items():
                for sh in SHAPES_TRI:
                    r = eval_trio(sel, pall, st, sh)
                    if r['n'] >= 30:
                        results.append(dict(券種='3連複', 戦略=f'{slbl}{sh[0]}-{sh[1]}-{sh[2]}', **r))

            # ── 3連単 ──
            for slbl, st in STRAT3.items():
                for sh in SHAPES_TRF:
                    r = eval_trifecta(sel, pall, st, sh)
                    if r['n'] >= 30:
                        results.append(dict(券種='3連単', 戦略=f'{slbl}{sh[0]}-{sh[1]}-{sh[2]}', **r))

            if not results:
                continue

            df = pd.DataFrame(results)
            # 券種別ベスト
            print(f'\n    券種別ベスト (ROI順):')
            print(f'    {"券種":>6} {"戦略":>14} {"点数":>5} {"的中%":>7} {"ROI%":>6}')
            print(f'    {"-"*42}')
            for bt in BET_TYPES:
                sub = df[df['券種'] == bt]
                if sub.empty: continue
                best = sub.loc[sub['ROI'].idxmax()]
                results_summary = dict(zone=zlbl, period=plbl, bet=bt,
                                       strat=best['戦略'], pts=best['pts'],
                                       rate=best['rate'], roi=best['ROI'])
                all_rules.append(results_summary)
                print(f'    {bt:>6} {best["戦略"]:>14} {best["pts"]:>4.0f}'
                      f' {best["rate"]:>6.1f} {best["ROI"]:>5.0f}')

            # 全体Top5
            top5 = df.nlargest(5, 'ROI')
            print(f'\n    全券種Top5:')
            for _, r in top5.iterrows():
                print(f'      {r["券種"]}/{r["戦略"]} {r["pts"]:.0f}点'
                      f' 的中{r["rate"]:.1f}% ROI{r["ROI"]:.0f}%')

    # ── 最終ルール表 ──
    print(f'\n{"="*78}')
    print('■ 最終ルール表（各ゾーン×期間の券種別ベスト）')
    print(f'{"="*78}')
    if all_rules:
        rdf = pd.DataFrame(all_rules)
        for zlbl, _, _ in ZONES:
            zd = rdf[rdf['zone'] == zlbl]
            if zd.empty: continue
            print(f'\n  【{zlbl}】')
            for bt in BET_TYPES:
                bd = zd[zd['bet'] == bt]
                if bd.empty: continue
                parts = []
                for _, r in bd.iterrows():
                    parts.append(f'{r["period"]}:{r["strat"]} ROI{r["roi"]:.0f}%')
                print(f'    {bt:>6}: {" → ".join(parts)}')


def main():
    races_dict = build_races()
    races = list(races_dict.values())
    print('配当読込...', file=sys.stderr)
    pall = load_all_payouts()

    n_t = sum(1 for d in races if d['period'] == 'train')
    n_v = sum(1 for d in races if d['period'] == 'val')
    n_h = sum(1 for d in races if d['period'] == 'holdout')
    print(f'対象 {len(races):,}R (train≤2022: {n_t:,} / val2023-24: {n_v:,} / hold2025: {n_h:,})\n')

    section_b(races, pall)
    section_c(races, pall)
    section_d(races)
    section_e(races)
    print('戦略評価中...', file=sys.stderr)
    section_f(races, pall)

    print(f'\n※全ROIはtrain/val/holdoutの3期間で安定するものだけが信頼できる')
    print('※券種比較は同じ資金(100円×点数)での回収率。点数が違う券種間の比較は要注意')


if __name__ == '__main__':
    main()
