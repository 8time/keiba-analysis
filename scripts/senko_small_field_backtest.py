# -*- coding: utf-8 -*-
"""少頭数×先行 1セル — 実装しない。定義は repo/brief_senko_small_field.md。

CELL: pos_ratio3<=0.28 かつ field_size<=11
採否は B_cell（少頭数の中の人気ベース）の残差。
頭数閾値は動かさない。2セル目を足さない。

Usage: python scripts/senko_small_field_backtest.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import csv_data as cd

MIN_N = 200
ADOPT_PP = 0.03  # +3.0pp。後から下げない
SENKO_RATIO = 0.28
SMALL_MAX = 11
BIG_MIN = 15
Z_SE_P = 0.22
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, 'data', 'senko_small_field_summary.json')


def stats(resid, top3, win, odds):
    n = len(resid)
    if n == 0:
        return None
    r = np.asarray(resid, dtype=float)
    t3 = np.asarray(top3, dtype=float)
    w = np.asarray(win, dtype=float)
    o = np.asarray(odds, dtype=float)
    se = (Z_SE_P * (1 - Z_SE_P) / n) ** 0.5
    pay = np.where(w == 1, np.nan_to_num(o, nan=0.0), 0.0).sum()
    mean = float(r.mean())
    return {
        'n': int(n),
        'hit': float(t3.mean()),
        'win': float(w.mean()),
        'roi': float(pay / n),
        'resid': mean,
        'z': float(mean / se) if se > 0 else 0.0,
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 勝{s['win']:5.1%} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def ninki_base(df):
    g = df.groupby(df['ninki'].astype(int))['top3'].mean()
    return g.to_dict()


def apply_resid(h, base, fallback=None):
    nk = h['ninki'].astype(int)
    exp = nk.map(base).astype(float)
    if fallback is not None:
        exp = exp.fillna(nk.map(fallback).astype(float))
    return h['top3'] - exp


def slice_stats(h, mask, resid_col):
    sub = h.loc[mask]
    if sub.empty:
        return None
    return stats(sub[resid_col], sub['top3'], sub['win'], sub['win_odds'])


def main():
    print('CSV読み込み...', flush=True)
    cols = [
        'race_key', 'day', 'ninki', 'win_odds', 'pos_ratio3',
        'field_size', 'top3', 'win',
    ]
    h = cd.load_horses(cols=cols, with_period=True)
    h['year'] = (pd.to_numeric(h['day'], errors='coerce') // 10000).astype(int)
    h['win_odds'] = pd.to_numeric(h['win_odds'], errors='coerce')
    h['top3'] = pd.to_numeric(h['top3'], errors='coerce').fillna(0)
    h['win'] = pd.to_numeric(h['win'], errors='coerce').fillna(0)
    h['field_size'] = pd.to_numeric(h['field_size'], errors='coerce')
    ratio = pd.to_numeric(h['pos_ratio3'], errors='coerce')
    h['senko'] = ratio <= SENKO_RATIO
    h['small'] = h['field_size'] <= SMALL_MAX
    h['big'] = h['field_size'] >= BIG_MIN
    h['cell'] = h['senko'] & h['small']
    h['comp'] = (~h['senko']) & h['small']
    h['big_s'] = h['senko'] & h['big']

    train = h[h['period'] == 'train']
    b_global = ninki_base(train)
    b_cell = ninki_base(train[train['small']])
    h = h.copy()
    h['resid_g'] = apply_resid(h, b_global)
    h['resid_c'] = apply_resid(h, b_cell, fallback=b_global)

    groups = [
        ('CELL  先行×頭数≤11', 'cell', True),
        ('COMP  非先行×頭数≤11', 'comp', True),
        ('BIG   先行×頭数≥15', 'big_s', False),
        ('ALL_S 先行（頭数不問）', 'senko', False),
        ('ALL_F 頭数≤11（脚質不問）', 'small', True),
    ]

    print('\n定義固定: 先行=pos_ratio3≤0.28  少頭数=field_size≤11')
    print('B_global = train全体の人気別ベース（少頭数インフレが乗る）')
    print('B_cell   = trainの頭数≤11だけの人気別ベース（採否はこっち）')
    print('覗き見あり: 前回holdout探索で CELL が B_global +5.55pp だった。\n')

    out = {'groups': {}}
    for title, col, use_bcell in groups:
        print(f'--- {title} ---')
        out['groups'][col] = {}
        for per in ('train', 'holdout', 'recent'):
            sub = h[h['period'] == per]
            sg = slice_stats(sub, sub[col], 'resid_g')
            sc = slice_stats(sub, sub[col], 'resid_c') if use_bcell else None
            raw = None
            if sub[col].any():
                raw = float(sub.loc[sub[col], 'top3'].mean() - sub['top3'].mean())
            out['groups'][col][per] = {
                'b_global': sg, 'b_cell': sc, 'raw_diff': raw,
            }
            raw_s = f"  生差{raw*100:+.2f}pt" if raw is not None else ''
            print(f'  {per:8s} B_global {fmt(sg)}{raw_s}')
            if use_bcell:
                print(f'           B_cell   {fmt(sc)}')

    print('\n========== 主判定用: CELL − COMP（B_cell） ==========')
    gaps = {}
    for per in ('train', 'holdout', 'recent'):
        cell = out['groups']['cell'][per]['b_cell']
        comp = out['groups']['comp'][per]['b_cell']
        if cell is None or comp is None:
            print(f'  {per:8s} 欠損')
            gaps[per] = None
            continue
        gap = cell['resid'] - comp['resid']
        gaps[per] = gap
        print(f'  {per:8s} CELL {cell["resid"]*100:+.2f}pp − COMP {comp["resid"]*100:+.2f}pp'
              f' = {gap*100:+.2f}pp'
              f'  (CELL n={cell["n"]} / COMP n={comp["n"]})')

    print('\n補助: 少頭数レース内の 先行平均残差 − 非先行平均残差（B_cell、採否に使わない）')
    small_h = h[h['small']].copy()
    for per in ('train', 'holdout', 'recent'):
        sub = small_h[small_h['period'] == per]
        rows = []
        for _, g in sub.groupby('race_key', sort=False):
            a = g[g['senko']]
            b = g[~g['senko']]
            if a.empty or b.empty:
                continue
            rows.append(float(a['resid_c'].mean() - b['resid_c'].mean()))
        if len(rows) < 80:
            print(f'  {per:8s} レース数不足 nR={len(rows)}')
            continue
        print(f'  {per:8s} nR={len(rows):5d}  レース内差 {np.mean(rows)*100:+.2f}pp')

    print('\n説明用: CELL の人気帯（B_cell、ここで切って採用しない）')
    hold = h[h['period'] == 'holdout']
    cell_h = hold[hold['cell']]

    def nband(n):
        n = int(n)
        if n <= 3:
            return '1-3'
        if n <= 5:
            return '4-5'
        return '6+'

    for band, idx in cell_h.groupby(cell_h['ninki'].map(nband)).groups.items():
        st = slice_stats(hold, hold.index.isin(idx), 'resid_c')
        print(f'  holdout 人気{band}: {fmt(st)}')

    print('\ntrain 年別 CELL（B_cell、符号確認用）')
    years = []
    tr_cell = h[(h['period'] == 'train') & h['cell']]
    for y, g in tr_cell.groupby('year'):
        st = stats(g['resid_c'], g['top3'], g['win'], g['win_odds'])
        if st and st['n'] >= MIN_N:
            years.append((int(y), st['resid'] > 0, st['resid'], st['n']))
            print(f'  {int(y)}: {st["resid"]*100:+.2f}pp n={st["n"]}')
    if years:
        pos = sum(1 for _, p, _, _ in years if p)
        print(f'  年プラス {pos}/{len(years)}')

    cell_h_tr = out['groups']['cell']['train']['b_cell']
    cell_h_ho = out['groups']['cell']['holdout']['b_cell']
    gap_ho = gaps.get('holdout')
    ok_n = bool(cell_h_ho and cell_h_ho['n'] >= MIN_N)
    ok_cell = bool(cell_h_ho and cell_h_ho['resid'] >= ADOPT_PP)
    ok_gap = bool(gap_ho is not None and gap_ho >= ADOPT_PP)
    ok_train = bool(cell_h_tr and cell_h_tr['resid'] > 0)
    adopt = ok_n and ok_cell and ok_gap and ok_train

    print('\n========== 判定（閾値は指示書どおり +3.0pp） ==========')
    print(f'  holdout CELL n≥200: {ok_n}  (n={cell_h_ho["n"] if cell_h_ho else 0})')
    print(f'  holdout CELL B_cell ≥+3.0pp: {ok_cell}'
          f'  ({(cell_h_ho["resid"]*100 if cell_h_ho else 0):+.2f}pp)')
    print(f'  holdout CELL−COMP ≥+3.0pp: {ok_gap}'
          f'  ({(gap_ho*100 if gap_ho is not None else 0):+.2f}pp)')
    print(f'  train CELL B_cell がプラス: {ok_train}'
          f'  ({(cell_h_tr["resid"]*100 if cell_h_tr else 0):+.2f}pp)')
    print(f'\n総合: {"続ける" if adopt else "打ち切り"}')
    if adopt:
        print('  → 条件付き俗説の研究を続けてよい。有効度0〜100は作らない。エンジンには足さない。')
    else:
        print('  → 俗説系の条件探しは一旦止める。2セル目を探さない。有効度もバイアスも復活させない。')

    summary = {
        'adopt': bool(adopt),
        'ok_n': ok_n,
        'ok_cell': ok_cell,
        'ok_gap': ok_gap,
        'ok_train': ok_train,
        'holdout_cell_b_cell': cell_h_ho,
        'holdout_gap_pp': gap_ho,
        'train_cell_b_cell': cell_h_tr,
        'groups': {
            k: {
                per: {
                    'raw_diff': v[per]['raw_diff'],
                    'b_cell_resid': (v[per]['b_cell'] or {}).get('resid') if v[per]['b_cell'] else None,
                    'b_global_resid': (v[per]['b_global'] or {}).get('resid') if v[per]['b_global'] else None,
                    'n': (v[per]['b_cell'] or {}).get('n') if v[per]['b_cell'] else None,
                } for per in ('train', 'holdout', 'recent')
            } for k, v in out['groups'].items()
        },
    }
    try:
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f'\n要約: {OUT_JSON}')
    except Exception as e:
        print(f'JSON保存スキップ: {e}')


if __name__ == '__main__':
    main()
