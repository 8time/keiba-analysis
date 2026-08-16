# -*- coding: utf-8 -*-
"""VH3列目の追加検証。

仮説: フォーメーション3列目(最も広い列)をRank→VHに変えると改善する。
  D鉄板 3連複: NNN(2-3-6) → NNV(2-3-6)
  C中庸 3連単: RRR(2-4-7) → RRV(2-4-7)

検証:
  ① 重複度: VH上位c頭とRank上位c頭が何頭入れ替わるか
  ② ペア比較: 同じレースでbase/VH版の的中をMcNemar検定
  ③ 年別安定性: 毎年VH版が勝つか
  ④ VH独自ヒットの3着馬の正体
  ⑤ 3着馬の捕捉率: Rank上位c vs VH上位c vs ランダム

Usage: python scripts/vh_leg3_verify.py
"""
import os, sys, io, sqlite3
from collections import defaultdict

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

CONFIGS = [
    dict(zone='D鉄板', zlo=0, zhi=50, kind='trio',
         base_lbl='NNN(2-3-6)', test_lbl='NNV(2-3-6)',
         base_o3=0, test_o3=2,       # 3列目: 0=ninki, 2=vh
         o1=0, o2=0, shape=(2, 3, 6)),
    dict(zone='C中庸', zlo=50, zhi=70, kind='trifecta',
         base_lbl='RRR(2-4-7)', test_lbl='RRV(2-4-7)',
         base_o3=1, test_o3=2,       # 3列目: 1=rank, 2=vh
         o1=1, o2=1, shape=(2, 4, 7)),
]


def load_payouts(bet_type):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?", (bet_type,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[rk].append(((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay)))
    con.close()
    return out


def build_races():
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score', 'vh2_score'])
    r = cd.load_races(cols=['race_key', 'field_size', 'kigo', 'is_handi1'])
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

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

        top3_pos = [[orders[oi].index(ub) + 1 for ub in top3_ub] for oi in range(3)]

        horses = g['umaban'].astype(int).tolist()
        horse_pos = np.array([[orders[oi].index(ub) + 1 for oi in range(3)] for ub in horses],
                             dtype=np.int16)

        day_val = int(g['day'].iloc[0])
        out[rk] = dict(vscore=rv['score'], top3=tuple(top3_ub), day=day_val,
                       year=day_val // 10000, n=len(g), top3_pos=top3_pos,
                       top3_ninki=top3_ninki, orders=orders, horse_pos=horse_pos, rk=rk)
    return out


def check_hit(top3_pos, strat, shape, kind):
    o1i, o2i, o3i = strat
    a, b, c = shape
    if kind == 'trifecta':
        return top3_pos[o1i][0] <= a and top3_pos[o2i][1] <= b and top3_pos[o3i][2] <= c
    for p0, p1, p2 in [(0,1,2),(0,2,1),(1,0,2),(1,2,0),(2,0,1),(2,1,0)]:
        if top3_pos[o1i][p0] <= a and top3_pos[o2i][p1] <= b and top3_pos[o3i][p2] <= c:
            return True
    return False


def ticket_count_trifecta(hp, strat, shape):
    o1i, o2i, o3i = strat
    a, b, c = shape
    in_a = hp[:, o1i] <= a
    in_b = hp[:, o2i] <= b
    in_c = hp[:, o3i] <= c
    sA, sB, sC = int(in_a.sum()), int(in_b.sum()), int(in_c.sum())
    sAB, sAC, sBC = int((in_a & in_b).sum()), int((in_a & in_c).sum()), int((in_b & in_c).sum())
    sABC = int((in_a & in_b & in_c).sum())
    return max(0, sA*sB*sC - sAB*sC - sAC*sB - sBC*sA + 2*sABC)


def ticket_count_trio(hp, strat, shape):
    o1i, o2i, o3i = strat
    a, b, c = shape
    A = set(np.where(hp[:, o1i] <= a)[0])
    B = set(np.where(hp[:, o2i] <= b)[0])
    C = set(np.where(hp[:, o3i] <= c)[0])
    out = set()
    for x in A:
        for y in B:
            if y == x: continue
            for z in C:
                if z == x or z == y: continue
                out.add(tuple(sorted((x, y, z))))
    return len(out)


def get_payout(rk, pm, kind, top3):
    pl = pm.get(rk)
    if not pl:
        return None
    for combo, pay in pl:
        if kind == 'trifecta':
            if combo == top3:
                return pay
        else:
            if tuple(sorted(combo)) == tuple(sorted(top3)):
                return pay
    return None


def eval_roi(sel, pm, strat, shape, kind):
    hit, spend, ret, n = 0, 0, 0.0, 0
    tc_fn = ticket_count_trifecta if kind == 'trifecta' else ticket_count_trio
    for d in sel:
        tc = tc_fn(d['horse_pos'], strat, shape)
        if tc <= 0:
            continue
        pay = get_payout(d['rk'], pm, kind, d['top3'])
        if pay is None:
            continue
        n += 1
        spend += tc * 100
        if check_hit(d['top3_pos'], strat, shape, kind):
            hit += 1
            ret += pay
    return dict(n=n, hit=hit, rate=hit/n*100 if n else 0, ROI=ret/spend*100 if spend else 0)


def main():
    print('読込中...', file=sys.stderr)
    races = build_races()
    all_races = list(races.values())
    pm_trio = load_payouts('3連複')
    pm_trf = load_payouts('3連単')
    print(f'対象 {len(races):,}R\n')

    for cfg in CONFIGS:
        pm = pm_trio if cfg['kind'] == 'trio' else pm_trf
        o1, o2, shape, kind = cfg['o1'], cfg['o2'], cfg['shape'], cfg['kind']
        a, b, c = shape
        base_strat = (o1, o2, cfg['base_o3'])
        test_strat = (o1, o2, cfg['test_o3'])

        sel = [d for d in all_races
               if cfg['zlo'] <= d['vscore'] < cfg['zhi']
               and get_payout(d['rk'], pm, kind, d['top3']) is not None]

        lbl_k = '3連複' if kind == 'trio' else '3連単'
        print(f'{"="*72}')
        print(f'■ {cfg["zone"]} {lbl_k}: {cfg["base_lbl"]} vs {cfg["test_lbl"]}')
        print(f'  対象 {len(sel):,}R')
        print(f'{"="*72}')

        # ── ① 重複度 ──
        print(f'\n● ① 重複度: 3列目上位{c}頭がbase基準とVHでどれだけ重なるか')
        overlaps = []
        for d in sel:
            base_set = set(d['orders'][cfg['base_o3']][:c])
            vh_set = set(d['orders'][2][:c])
            overlaps.append(len(base_set & vh_set))
        ov = np.array(overlaps)
        print(f'  重複: 平均{ov.mean():.1f}頭 / 中央値{np.median(ov):.0f}頭（{c}頭中）')
        for n_ov in sorted(set(ov)):
            pct = (ov == n_ov).sum() / len(ov) * 100
            if pct >= 2:
                print(f'    {n_ov}頭一致: {pct:.0f}%')
        print(f'  → 平均{c - ov.mean():.1f}頭がVH固有（入れ替わり）')

        # ── ② ペア比較(McNemar) ──
        print(f'\n● ② ペア比較: 同じレースでの的中を比較（McNemar検定）')
        both, base_only, test_only, neither = 0, 0, 0, 0
        test_only_3rd = []
        base_only_3rd = []
        for d in sel:
            bh = check_hit(d['top3_pos'], base_strat, shape, kind)
            th = check_hit(d['top3_pos'], test_strat, shape, kind)
            if bh and th:
                both += 1
            elif bh:
                base_only += 1
                base_only_3rd.append(d['top3_ninki'][2])
            elif th:
                test_only += 1
                test_only_3rd.append(d['top3_ninki'][2])
            else:
                neither += 1

        total = len(sel)
        print(f'  両方的中:     {both:>5} ({both/total*100:.1f}%)')
        print(f'  base版のみ:   {base_only:>5} ({base_only/total*100:.1f}%)')
        print(f'  VH版のみ:     {test_only:>5} ({test_only/total*100:.1f}%)')
        print(f'  両方外れ:     {neither:>5} ({neither/total*100:.1f}%)')
        net = test_only - base_only
        print(f'  純増 = {net:+d}件')
        if base_only + test_only > 0:
            z = (test_only - base_only) / (base_only + test_only) ** 0.5
            print(f'  McNemar z = {z:+.2f}（±1.96で有意）')

        # ── ③ 年別安定性 ──
        print(f'\n● ③ 年別安定性')
        years = sorted(set(d['year'] for d in sel))
        print(f'  {"年":>6} {"base的中%":>10} {"VH的中%":>10} {"差":>8}'
              f' {"base_ROI":>10} {"VH_ROI":>10} {"差":>8} {"R数":>6}')
        print(f'  {"-"*70}')
        wins_rate, wins_roi, n_yrs = 0, 0, 0
        for yr in years:
            yr_sel = [d for d in sel if d['year'] == yr]
            if len(yr_sel) < 30:
                continue
            n_yrs += 1
            br = eval_roi(yr_sel, pm, base_strat, shape, kind)
            tr = eval_roi(yr_sel, pm, test_strat, shape, kind)
            rd = tr['rate'] - br['rate']
            roid = tr['ROI'] - br['ROI']
            mr = '◎' if rd > 0 else ('△' if abs(rd) < 0.5 else '×')
            mroi = '◎' if roid > 0 else ('△' if abs(roid) < 1 else '×')
            print(f'  {yr:>6} {br["rate"]:>9.1f}% {tr["rate"]:>9.1f}% {rd:>+6.1f}{mr}'
                  f'  {br["ROI"]:>9.0f}% {tr["ROI"]:>9.0f}% {roid:>+6.0f}{mroi}'
                  f'  {br["n"]:>6}')
            if rd > 0: wins_rate += 1
            if roid > 0: wins_roi += 1
        print(f'  VH勝ち年: 的中率{wins_rate}/{n_yrs}  ROI{wins_roi}/{n_yrs}')

        # ── ④ VH独自ヒットの3着馬 ──
        print(f'\n● ④ VH独自ヒット({test_only}件)の3着馬')
        if test_only_3rd:
            arr = np.array(test_only_3rd)
            bins = {'1-3番': ((arr <= 3)).sum(), '4-6番': ((arr >= 4) & (arr <= 6)).sum(),
                    '7-9番': ((arr >= 7) & (arr <= 9)).sum(), '10番+': (arr >= 10).sum()}
            dist = ' / '.join(f'{k}={v/len(arr)*100:.0f}%' for k, v in bins.items())
            print(f'  人気中央値: {np.median(arr):.0f}番人気')
            print(f'  分布: {dist}')
        if base_only_3rd:
            arr2 = np.array(base_only_3rd)
            print(f'  (参考: base独自ヒットの3着馬は中央値{np.median(arr2):.0f}番人気)')

        # ── ⑤ 3着馬の捕捉率 ──
        print(f'\n● ⑤ 3着馬の捕捉率: 各基準の上位{c}頭に3着馬が入っている率')
        base_cap, vh_cap, rand_exp = 0, 0, 0.0
        ninki_cap = 0
        for d in sel:
            ub3 = d['top3'][2]
            base_cap += 1 if d['orders'][cfg['base_o3']].index(ub3) < c else 0
            vh_cap += 1 if d['orders'][2].index(ub3) < c else 0
            ninki_cap += 1 if d['orders'][0].index(ub3) < c else 0
            rand_exp += c / d['n']
        n = len(sel)
        print(f'  人気上位{c}:  {ninki_cap/n*100:.1f}%')
        if cfg['base_o3'] != 0:
            print(f'  Rank上位{c}:  {base_cap/n*100:.1f}%')
        print(f'  VH上位{c}:   {vh_cap/n*100:.1f}%')
        print(f'  ランダム{c}: {rand_exp/n*100:.1f}%（期待値 = {c}/頭数）')
        diff = vh_cap - base_cap
        z_cap = diff / (n * base_cap/n * (1 - base_cap/n)) ** 0.5 if base_cap > 0 else 0
        print(f'  VH - base差: {diff:+d}件 ({diff/n*100:+.1f}pp)  z={z_cap:+.2f}')

    print(f'\n※VH=穴馬ハンター(vh2_score)。3列目に使う=「3着に来そうな穴馬」をVHで探す。')


if __name__ == '__main__':
    main()
