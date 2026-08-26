# -*- coding: utf-8 -*-
"""性別 × 年齢 × 芝ダ × 距離 — 穴馬ハンター候補の残差検証。

俗説の「牝馬だから」は、年齢・完成度・距離適性に吸収されている可能性がある。
6番人気以下で見る+確認の両方 z>=+2 かつ n>=200 かつ残差>0 だけを VH 候補にする。

Usage: python scripts/gender_age_surface_backtest.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from scripts import csv_data as cd

MIN_N = 200
Z_HUNTER = 2.0
SPRINT = 1300
MILE_HI = 1600
MID_HI = 2000
STAY = 2400   # 長距離の目安（2000は中距離寄り）


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def stats(sub, e3):
    n = len(sub)
    if n == 0:
        return None
    t3 = sub['top3'].to_numpy()
    win = sub['win'].to_numpy()
    odds = sub['win_odds'].to_numpy()
    resid = t3 - e3.loc[sub.index].to_numpy()
    se = (0.22 * 0.78 / n) ** 0.5
    z = (resid.mean() / se) if se > 0 else 0.0
    pay = np.where(win == 1, odds, 0.0).sum()
    return {
        'n': n,
        'hit': float(t3.mean()),
        'win': float(win.mean()),
        'roi': float(pay / n),
        'z': float(z),
        'resid': float(resid.mean()),
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 勝{s['win']:5.1%} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def hunter_ok(train, hold):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return (train['z'] >= Z_HUNTER and hold['z'] >= Z_HUNTER
            and train['resid'] > 0 and hold['resid'] > 0)


def verdict(train, hold):
    if hunter_ok(train, hold):
        return '★VH候補(6番以下 両窓 z>=+2)'
    return 'ゲート未達'


def run_conds(title, conds, pops, periods, df, e3, collect):
    print(f'\n{"=" * 72}')
    print(title)
    print('=' * 72)
    for pop_name, pop in pops.items():
        print(f'\n-------- {pop_name} --------')
        for cname, cmask in conds:
            print(f'--- {cname} ---')
            row = {'block': title, 'pop': pop_name, 'cond': cname}
            for pname, pm in periods.items():
                st = stats(df[pop & cmask & pm], e3)
                row[pname] = st
                print(f'  {pname:12s} {fmt(st)}')
            row['verdict'] = verdict(row['見る(〜2024)'], row['確認(2025)'])
            if pop_name != '6番人気以下':
                row['verdict'] = '（参考・穴ゲート対象外）'
            print('  → ' + row['verdict'])
            collect.append(row)


def overlay_line(tag, a, b):
    if a is None or b is None or a['n'] < MIN_N or b['n'] < MIN_N:
        return f'  {tag}: 標本不足'
    dpp = (a['resid'] - b['resid']) * 100
    mark = ''
    if dpp >= 0.5:
        mark = '  牝が牡より良い'
    elif dpp <= -0.5:
        mark = '  牝が牡より悪い'
    return (f'  {tag}: {dpp:+5.2f}pp'
            f'  (牝 {a["resid"]*100:+5.2f} / 牡 {b["resid"]*100:+5.2f}){mark}')


def pick(rows, pop, cond):
    for r in rows:
        if r['pop'] == pop and r['cond'] == cond:
            return r
    return None


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    print('CSV...', flush=True)
    df = cd.load_horses(cols=[
        'day', 'ninki', 'win_odds', 'top3', 'win',
        'surface_code', 'kyori_int', 'sex_code', 'age',
    ])
    for c in ('ninki', 'win_odds', 'top3', 'win', 'surface_code',
              'kyori_int', 'sex_code', 'age', 'day'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['sex_code'].notna()
            & df['kyori_int'].notna() & df['surface_code'].notna()
            & df['age'].notna()].copy()
    df = df.reset_index(drop=True)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    female = df['sex_code'] == 2
    male = df['sex_code'] == 1
    turf = df['surface_code'] == 0
    dirt = df['surface_code'] == 1
    sprint = df['kyori_int'] <= SPRINT
    mile = (df['kyori_int'] > SPRINT) & (df['kyori_int'] <= MILE_HI)
    mid = (df['kyori_int'] > MILE_HI) & (df['kyori_int'] <= MID_HI)
    longish = df['kyori_int'] > MID_HI
    stay = df['kyori_int'] >= STAY
    a2 = df['age'] == 2
    a3 = df['age'] == 3
    a23 = df['age'].between(2, 3)
    a34 = df['age'].between(3, 4)
    a45 = df['age'].between(4, 5)
    a4 = df['age'] >= 4          # 古馬
    a5p = df['age'] >= 5
    a6p = df['age'] >= 6

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }
    pops_all = {
        '6番人気以下': df['ninki'] >= 6,
        '全体': pd.Series(True, index=df.index),
    }
    pops_ls = {'6番人気以下': df['ninki'] >= 6}
    collect = []

    print(f'  {len(df):,}走')
    print('残差 = 実複勝 − 同オッズ帯期待。★VH = 6番以下 両窓 z>=+2')

    # ------------------------------------------------------------------
    # 指名スライス（ユーザー指定 + 同条件の牡対照 + 2歳/3歳の分解）
    # ------------------------------------------------------------------
    named = [
        ('2-3歳牝 × 芝短距離', female & a23 & turf & sprint),
        ('2-3歳牡 × 芝短距離 (対照)', male & a23 & turf & sprint),
        ('2歳牝 × 芝短距離', female & a2 & turf & sprint),
        ('3歳牝 × 芝短距離', female & a3 & turf & sprint),
        ('4-5歳牝 × 芝短距離', female & a45 & turf & sprint),
        ('4-5歳牡 × 芝短距離 (対照)', male & a45 & turf & sprint),
        ('6歳以上牝 × 芝短距離', female & a6p & turf & sprint),
        ('6歳以上牡 × 芝短距離 (対照)', male & a6p & turf & sprint),
        ('3-4歳牝 × ダート短距離', female & a34 & dirt & sprint),
        ('3-4歳牡 × ダート短距離 (対照)', male & a34 & dirt & sprint),
        ('5歳以上牝 × ダート', female & a5p & dirt),
        ('5歳以上牡 × ダート (対照)', male & a5p & dirt),
        ('牡 × 古馬4歳+ × ダート', male & a4 & dirt),
        ('牝 × 古馬4歳+ × ダート (対照)', female & a4 & dirt),
        ('牝 × 古馬4歳+ × 芝長距離2400+', female & a4 & turf & stay),
        ('牡 × 古馬4歳+ × 芝長距離2400+ (対照)', male & a4 & turf & stay),
        ('牝 × 古馬4歳+ × 芝2000超', female & a4 & turf & longish),
        ('牡 × 古馬4歳+ × 芝2000超 (対照)', male & a4 & turf & longish),
    ]
    run_conds('指名スライス（年齢×馬場×距離）', named, pops_all, periods, df, e3, collect)

    print('\n---- 指名スライス 牝−牡（6番以下） ----')
    pairs = [
        ('2-3歳牝 × 芝短距離', '2-3歳牡 × 芝短距離 (対照)'),
        ('4-5歳牝 × 芝短距離', '4-5歳牡 × 芝短距離 (対照)'),
        ('6歳以上牝 × 芝短距離', '6歳以上牡 × 芝短距離 (対照)'),
        ('3-4歳牝 × ダート短距離', '3-4歳牡 × ダート短距離 (対照)'),
        ('5歳以上牝 × ダート', '5歳以上牡 × ダート (対照)'),
        ('牝 × 古馬4歳+ × ダート (対照)', '牡 × 古馬4歳+ × ダート'),
        ('牝 × 古馬4歳+ × 芝長距離2400+', '牡 × 古馬4歳+ × 芝長距離2400+ (対照)'),
        ('牝 × 古馬4歳+ × 芝2000超', '牡 × 古馬4歳+ × 芝2000超 (対照)'),
    ]
    named_rows = [r for r in collect if r['block'].startswith('指名') and r['pop'] == '6番人気以下']
    for a, b in pairs:
        ra, rb = pick(named_rows, '6番人気以下', a), pick(named_rows, '6番人気以下', b)
        if not ra or not rb:
            continue
        print(f'{a} vs {b}')
        print(overlay_line('見る', ra['見る(〜2024)'], rb['見る(〜2024)']))
        print(overlay_line('確認', ra['確認(2025)'], rb['確認(2025)']))

    # ------------------------------------------------------------------
    # 系統グリッド（6番以下のみ）
    # ------------------------------------------------------------------
    ages = [
        ('2-3歳', a23),
        ('4-5歳', a45),
        ('6歳以上', a6p),
    ]
    surfs = [('芝', turf), ('ダ', dirt)]
    dists = [
        ('1300m以下', sprint),
        ('1400-1600', mile),
        ('1700-2000', mid),
        ('2000m超', longish),
    ]
    grid = []
    for aname, amask in ages:
        for sname, smask in surfs:
            for dname, dmask in dists:
                grid.append((f'牝×{aname}×{sname}×{dname}',
                             female & amask & smask & dmask))
                grid.append((f'牡×{aname}×{sname}×{dname}',
                             male & amask & smask & dmask))
    run_conds('系統グリッド 性別×年齢×馬場×距離（6番以下）',
              grid, pops_ls, periods, df, e3, collect)

    print('\n---- グリッド 牝−牡（6番以下・標本足りるセル） ----')
    grid_rows = [r for r in collect if r['block'].startswith('系統')]
    for aname, _ in ages:
        for sname, _ in surfs:
            for dname, _ in dists:
                fa = pick(grid_rows, '6番人気以下', f'牝×{aname}×{sname}×{dname}')
                ma = pick(grid_rows, '6番人気以下', f'牡×{aname}×{sname}×{dname}')
                if not fa or not ma:
                    continue
                t, h = fa['見る(〜2024)'], fa['確認(2025)']
                if t is None or h is None or t['n'] < MIN_N or h['n'] < MIN_N:
                    continue
                print(f'牝×{aname}×{sname}×{dname}')
                print(overlay_line('見る', t, ma['見る(〜2024)']))
                print(overlay_line('確認', h, ma['確認(2025)']))

    # ------------------------------------------------------------------
    print('\n' + '=' * 72)
    print('まとめ — 6番以下で両窓 z>=+2 の VH 候補だけ')
    print('=' * 72)
    stars = [r for r in collect
             if r['pop'] == '6番人気以下' and r['verdict'].startswith('★')]
    if not stars:
        print('該当なし。性別×年齢×馬場×距離でも、新しい VH 条件にはならなかった。')
        print('スコアには入れない。')
        return
    for r in stars:
        t, h = r['見る(〜2024)'], r['確認(2025)']
        print(f"\n{r['cond']}")
        print(f"  見る 複{t['hit']:.1%} 残差{t['resid']*100:+.2f}pp z={t['z']:+.2f} n={t['n']}")
        print(f"  確認 複{h['hit']:.1%} 残差{h['resid']*100:+.2f}pp z={h['z']:+.2f} n={h['n']}")
    print('\n候補止まり。強適スコアへは自動では入れない。')


if __name__ == '__main__':
    main()
