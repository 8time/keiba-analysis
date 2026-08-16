# -*- coding: utf-8 -*-
"""高解像度フォーメーション分析：各列に人気/Rank/VHのどれを使うかのゾーン別最適化。

既存分析(Rank2-4-7 ROI92%等)の深掘り:
  Q1 各列(1着/2着/3着)に別々の基準(人気/Rank/VH)を割り当てる「混合戦略」は純粋戦略に勝てるか
  Q2 2-4-7以外にもっと良い形はあるか
  Q3 勝馬券の各位置にはどういう馬が来ているか(役割分析)

Usage: python scripts/formation_hires_backtest.py
"""
import os
import sys
import io
import sqlite3
from collections import defaultdict, Counter

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

TRIFECTA_SHAPES = [
    (1, 2, 5), (1, 2, 6), (1, 2, 7), (1, 2, 8),
    (1, 3, 5), (1, 3, 6), (1, 3, 7), (1, 3, 8),
    (1, 4, 6), (1, 4, 7), (1, 4, 8), (1, 4, 9),
    (1, 5, 7), (1, 5, 8), (1, 5, 9),
    (2, 3, 5), (2, 3, 6), (2, 3, 7), (2, 3, 8),
    (2, 4, 6), (2, 4, 7), (2, 4, 8), (2, 4, 9),
    (2, 5, 7), (2, 5, 8), (2, 5, 9),
    (2, 6, 8), (2, 6, 9),
    (3, 4, 7), (3, 4, 8),
    (3, 5, 7), (3, 5, 8), (3, 5, 9),
    (3, 6, 8), (3, 6, 9),
    (4, 5, 8), (4, 6, 8), (4, 6, 9),
]

TRIO_SHAPES = [
    (1, 3, 5), (1, 3, 6), (1, 3, 7), (1, 3, 8),
    (1, 4, 6), (1, 4, 7), (1, 4, 8),
    (1, 5, 7), (1, 5, 8), (1, 5, 9),
    (2, 3, 6), (2, 3, 7),
    (2, 4, 6), (2, 4, 7), (2, 4, 8),
    (2, 5, 7), (2, 5, 8), (2, 5, 9),
    (2, 6, 8), (2, 6, 9),
    (3, 5, 7), (3, 5, 8), (3, 5, 9),
    (3, 6, 8), (3, 6, 9),
    (4, 6, 8), (4, 6, 9),
]

# N=人気, R=Rank(ability_score), V=VH(vh2_score)
# 表記: 列1基準_列2基準_列3基準
STRATEGIES = {
    'NNN': ('ninki', 'ninki', 'ninki'),
    'RRR': ('rank', 'rank', 'rank'),
    'NNR': ('ninki', 'ninki', 'rank'),
    'NRR': ('ninki', 'rank', 'rank'),
    'RRN': ('rank', 'rank', 'ninki'),
    'NNV': ('ninki', 'ninki', 'vh'),
    'RRV': ('rank', 'rank', 'vh'),
    'NRV': ('ninki', 'rank', 'vh'),
}


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

        fin = g.sort_values('chakujun')
        top3_ub = fin['umaban'].astype(int).tolist()[:3]
        if len(top3_ub) < 3:
            continue
        top3_ninki = fin['ninki'].astype(int).tolist()[:3]
        top3_rank_pos = [rank_ord.index(ub) + 1 for ub in top3_ub]
        top3_vh_pos = [vh_ord.index(ub) + 1 for ub in top3_ub]

        day_val = int(g['day'].iloc[0])
        yr = day_val // 10000
        period = 'train' if yr <= 2024 else ('holdout' if yr == 2025 else 'recent')

        out[rk] = {
            'vscore': rv['score'],
            'orders': {'ninki': ninki_ord, 'rank': rank_ord, 'vh': vh_ord},
            'top3': tuple(top3_ub), 'day': day_val, 'period': period, 'n': len(g),
            'top3_ninki': top3_ninki, 'top3_rank': top3_rank_pos, 'top3_vh': top3_vh_pos,
        }
    return out


def make_tickets(orders, strat, a, b, c, kind):
    o1, o2, o3 = strat
    A = set(orders[o1][:a])
    B = set(orders[o2][:b])
    C = set(orders[o3][:c])
    if kind == 'trifecta':
        return {(x, y, z) for x in A for y in B for z in C if len({x, y, z}) == 3}
    out = set()
    for x in A:
        for y in B:
            for z in C:
                if len({x, y, z}) == 3:
                    out.add(tuple(sorted((x, y, z))))
    return out


def evaluate_all(sel, pay_map, shapes, kind):
    """全戦略×全形をまとめて評価し、DataFrameで返す。"""
    rows = []
    for sk, strat in STRATEGIES.items():
        for (a, b, c) in shapes:
            hit, spend, ret, pts_list, n = 0, 0, 0.0, [], 0
            for d in sel:
                tk = make_tickets(d['orders'], strat, a, b, c, kind)
                if not tk:
                    continue
                pl = pay_map.get(d['_rk'])
                if not pl:
                    continue
                n += 1
                pts_list.append(len(tk))
                spend += len(tk) * 100
                for combo, pay in pl:
                    key = combo if kind == 'trifecta' else tuple(sorted(combo))
                    if key in tk:
                        hit += 1
                        ret += pay
                        break
            if n < 50:
                continue
            rows.append({
                '戦略': sk, '形': f'{a}-{b}-{c}',
                '点': np.mean(pts_list), 'R数': n,
                '的中%': hit / n * 100,
                'ROI': ret / spend * 100 if spend else 0,
            })
    return pd.DataFrame(rows)


def role_analysis(sel, zone_label):
    """勝馬券内の各着順の馬は何番人気/何位だったか。"""
    print(f'\n  ● 勝馬券の各列の馬の正体（{len(sel):,}R）')
    print(f'  {"位置":>6} {"人気":>8} {"Rank":>8} {"VH順":>8} ← 中央値')
    print(f'  {"-"*36}')
    for pos in range(3):
        lbl = f'{pos+1}着'
        n_med = np.median([d['top3_ninki'][pos] for d in sel])
        r_med = np.median([d['top3_rank'][pos] for d in sel])
        v_med = np.median([d['top3_vh'][pos] for d in sel])
        print(f'  {lbl:>6} {n_med:>6.0f}番 {r_med:>6.0f}位 {v_med:>6.0f}位')

    print(f'\n  ● 各着順の人気帯分布:')
    for pos in range(3):
        lbl = f'{pos+1}着'
        vals = [d['top3_ninki'][pos] for d in sel]
        total = len(vals)
        bins = {'1-3': sum(1 for v in vals if v <= 3),
                '4-6': sum(1 for v in vals if 4 <= v <= 6),
                '7-9': sum(1 for v in vals if 7 <= v <= 9),
                '10+': sum(1 for v in vals if v >= 10)}
        dist = ' / '.join(f'{k}={bins[k]/total*100:.0f}%' for k in bins)
        print(f'    {lbl}: {dist}')

    print(f'\n  ● 各着順のRank帯分布:')
    for pos in range(3):
        lbl = f'{pos+1}着'
        vals = [d['top3_rank'][pos] for d in sel]
        total = len(vals)
        bins = {'1-3': sum(1 for v in vals if v <= 3),
                '4-6': sum(1 for v in vals if 4 <= v <= 6),
                '7-9': sum(1 for v in vals if 7 <= v <= 9),
                '10+': sum(1 for v in vals if v >= 10)}
        dist = ' / '.join(f'{k}={bins[k]/total*100:.0f}%' for k in bins)
        print(f'    {lbl}: {dist}')


def print_section(title):
    print(f'\n{"="*78}')
    print(f'■ {title}')
    print(f'{"="*78}')


def main():
    print('読込中...', file=sys.stderr)
    races = build_races()
    for rk in races:
        races[rk]['_rk'] = rk
    all_races = list(races.values())
    n_train = sum(1 for d in all_races if d['period'] == 'train')
    n_hold = sum(1 for d in all_races if d['period'] == 'holdout')
    print(f'対象 {len(races):,}R（train {n_train:,} / holdout {n_hold:,}）\n')

    # ── ① 役割分析: 勝馬券の各位置にはどういう馬が来ているか ──
    print_section('① 役割分析：勝馬券の各位置にはどういう馬が来ているか')
    for zlbl, zlo, zhi in ZONES:
        sel = [d for d in all_races if zlo <= d['vscore'] < zhi]
        if len(sel) < 100:
            continue
        print(f'\n{"─"*50}')
        print(f'【{zlbl}】')
        role_analysis(sel, zlbl)

    # ── ② ゾーン別 戦略×形の全評価 ──
    for kind, lbl_k, pay_key in [('trio', '3連複', '3連複'), ('trifecta', '3連単', '3連単')]:
        pm = load_payouts(pay_key)
        shapes = TRIO_SHAPES if kind == 'trio' else TRIFECTA_SHAPES

        print_section(f'② {lbl_k}：戦略×形の最適化')

        for zlbl, zlo, zhi in ZONES:
            print(f'\n{"─"*78}')
            print(f'【{zlbl}】')

            for period_lbl, pf in [('train≤2024', 'train'), ('holdout2025', 'holdout')]:
                sel = [d for d in all_races if zlo <= d['vscore'] < zhi and d['period'] == pf]
                if len(sel) < 50:
                    print(f'\n  [{period_lbl}] {len(sel)}R（不足）')
                    continue

                df = evaluate_all(sel, pm, shapes, kind)
                if df.empty:
                    print(f'\n  [{period_lbl}] 結果なし')
                    continue

                # (a) 戦略別ベスト: 各戦略の最良形を1つずつ
                print(f'\n  [{period_lbl}] {len(sel):,}R')
                print(f'  ● 戦略別ベスト (ROI順):')
                best_idx = df.groupby('戦略')['ROI'].idxmax()
                sb = df.loc[best_idx].sort_values('ROI', ascending=False)
                print(f'    {"戦略":>5} {"形":>7} {"点数":>5} {"的中%":>6} {"ROI%":>6}')
                print(f'    {"-"*34}')
                for _, r in sb.iterrows():
                    print(f'    {r["戦略"]:>5} {r["形"]:>7} {r["点"]:>4.0f} '
                          f'{r["的中%"]:>5.1f} {r["ROI"]:>5.0f}')

                # (b) 同一形での戦略比較 (代表2形)
                ref_shapes = ['2-4-7', '1-4-7'] if kind == 'trifecta' else ['2-5-8', '1-4-7']
                for rs in ref_shapes:
                    ref = df[df['形'] == rs].sort_values('ROI', ascending=False)
                    if ref.empty:
                        continue
                    print(f'\n  ● 形={rs} 固定で戦略比較:')
                    for _, r in ref.iterrows():
                        print(f'    {r["戦略"]:>5}: {r["点"]:.0f}点 '
                              f'的中{r["的中%"]:.1f}% ROI{r["ROI"]:.0f}%')

                # (c) 全体Top10
                top = df.nlargest(10, 'ROI')
                print(f'\n  ● 全組合せROI Top10:')
                print(f'    {"戦略":>5} {"形":>7} {"点数":>5} {"的中%":>6} {"ROI%":>6}')
                print(f'    {"-"*34}')
                for _, r in top.iterrows():
                    print(f'    {r["戦略"]:>5} {r["形"]:>7} {r["点"]:>4.0f} '
                          f'{r["的中%"]:>5.1f} {r["ROI"]:>5.0f}')

    # ── ③ 点数とROIの関係 ──
    print_section('③ 点数とROIの相関（全ゾーン全戦略）')
    for kind, lbl_k, pay_key in [('trio', '3連複', '3連複'), ('trifecta', '3連単', '3連単')]:
        pm = load_payouts(pay_key)
        shapes = TRIO_SHAPES if kind == 'trio' else TRIFECTA_SHAPES
        sel = [d for d in all_races if d['period'] == 'train']
        df = evaluate_all(sel, pm, shapes, kind)
        if df.empty:
            continue
        corr = df['点'].corr(df['ROI'])
        print(f'  {lbl_k}: 点数×ROI相関 = {corr:+.3f}')
        for lo, hi, lbl in [(0, 10, '～10点'), (10, 30, '10-30点'), (30, 60, '30-60点'), (60, 999, '60点+')]:
            s = df[(df['点'] >= lo) & (df['点'] < hi)]
            if len(s) >= 3:
                print(f'    {lbl}: 平均ROI {s["ROI"].mean():.0f}% (n={len(s)})')

    print(f'\n※控除率25%が壁。ROI100%超はまず出ない前提で「同点数ならどれがマシか」を見る。')
    print('※VH=vh2_score(穴馬ハンター)順。列3(最も広い列)にVHを使う=穴馬を探す用途。')


if __name__ == '__main__':
    main()
