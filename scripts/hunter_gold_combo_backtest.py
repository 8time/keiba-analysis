# -*- coding: utf-8 -*-
"""穴馬ハンター網 × 🥇(騎手×厩舎) / combo≥2 / 馬連携上位 の残差。

優先:
  ① VH網 × 🥇（35-40%）
  ② VH網 × combo≥2 × 🥇
  ③ VH網 × combo≥2 × 馬連携上位（USM≥115）
  ④ VH網 × 🥇 × 馬連携上位

判定: 6番人気以下、見る(〜2024)+確認(2025)で複残差>0 かつ z>=+2、n>=200。
VHスコアには足さない。ゲート通過なら表示印の候補。圏外の救済はしない。

🥇 = 騎手×調教師の直前連対 35-40%（騎乗10+）。🥇🥇(40%+)は織込み帯として対照。
馬連携 = 直近150騎乗の複勝USM。115以上=よく引き出す。J5係数への再加算はしない。

Usage: python scripts/hunter_gold_combo_backtest.py
"""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from scripts import csv_data as cd
from scripts.hunter_miss_complement import MIN_N, POP, add_light_score, fmt, stats

Z_GATE = 2.0
USM_HI = 115
USM_WINDOW = 150
GOLD_RIDES = jj.GOLD_MIN_RIDES


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def both_pos(train, hold):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return (train['z'] >= Z_GATE and hold['z'] >= Z_GATE
            and train['resid'] > 0 and hold['resid'] > 0)


def print_block(title, mask, periods, df, e3, base=None):
    print(f'--- {title} ---')
    row = {}
    for pname, pm in periods.items():
        st = stats(df[mask & pm], e3)
        row[pname] = st
        extra = ''
        if (base and pname in base and st and base[pname]
                and st['n'] >= MIN_N and base[pname]['n'] >= MIN_N):
            dpp = (st['resid'] - base[pname]['resid']) * 100
            extra = f'  vs網{dpp:+.2f}pp'
        print(f'  {pname:12s} {fmt(st)}{extra}')
    ok = both_pos(row.get('見る(〜2024)'), row.get('確認(2025)'))
    print('  → ' + ('★来ている（両窓 z>=+2）' if ok else 'ゲート未達'))
    return row, ok


def load_gold_usm(exp):
    """全騎乗のリーク無し 🥇マークと馬連携USM。race_key×umaban でCSVに結合する。"""
    print('騎手×厩舎・馬連携（jravan・リーク無し）...', flush=True)
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True, timeout=30)
    res = pd.read_sql_query(
        """SELECT race_key, umaban, jockey_name, trainer_code, chakujun, win_odds
           FROM results
           WHERE chakujun>0 AND jockey_name IS NOT NULL AND jockey_name<>''""",
        con)
    con.close()
    res['chakujun'] = pd.to_numeric(res['chakujun'], errors='coerce')
    res['umaban'] = pd.to_numeric(res['umaban'], errors='coerce')
    res['win_odds'] = pd.to_numeric(res['win_odds'], errors='coerce')
    res = res[res['chakujun'].notna() & res['umaban'].notna()].copy()
    res['race_key'] = res['race_key'].astype(str)
    res['jockey_name'] = res['jockey_name'].map(jj._norm)
    res['trainer_code'] = res['trainer_code'].fillna('').astype(str)
    res['top2'] = (res['chakujun'] <= 2).astype(int)
    res['a3'] = (res['chakujun'] <= 3).astype(float)
    res['e3'] = _band_exp(res['win_odds'], exp, 'top3', 0.22)
    res = res.sort_values('race_key').reset_index(drop=True)

    g = res.groupby(['jockey_name', 'trainer_code'], sort=False)
    res['c_rides'] = g.cumcount()
    res['c_top2'] = g['top2'].cumsum() - res['top2']
    res['combo_rate'] = res['c_top2'] / res['c_rides'].where(res['c_rides'] > 0)
    unknown = res['trainer_code'].isin(('', '00000', 'None'))
    enough = (~unknown) & (res['c_rides'] >= GOLD_RIDES) & res['combo_rate'].notna()
    rate = res['combo_rate']
    res['gold1'] = enough & (rate >= jj.GOLD_TOP2_GATE) & (rate < jj.GOLD_TOP2_STRONG)
    res['gold2'] = enough & (rate >= jj.GOLD_TOP2_STRONG)
    res['gold_any'] = res['gold1'] | res['gold2']
    res['gold_tri'] = enough & (rate >= jj.GOLD_TOP2_WEAK) & (rate < jj.GOLD_TOP2_GATE)

    jk = res.groupby('jockey_name', sort=False)
    res['usm_a3'] = jk['a3'].transform(
        lambda s: s.shift(1).rolling(USM_WINDOW, min_periods=USM_WINDOW).sum())
    res['usm_e3'] = jk['e3'].transform(
        lambda s: s.shift(1).rolling(USM_WINDOW, min_periods=USM_WINDOW).sum())
    res['usm'] = np.where(
        res['usm_e3'] > 0, res['usm_a3'] / res['usm_e3'] * 100.0, np.nan)
    res['usm_hi'] = res['usm'] >= USM_HI

    print(f'  🥇 {int(res["gold1"].sum()):,}  🥇🥇 {int(res["gold2"].sum()):,}  '
          f'馬連携上位 {int(res["usm_hi"].sum()):,} / {len(res):,}騎乗', flush=True)
    return res[['race_key', 'umaban', 'gold1', 'gold2', 'gold_any',
                'gold_tri', 'usm', 'usm_hi', 'c_rides', 'combo_rate']]


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    print('CSV...', flush=True)
    df = cd.load_horses(cols=[
        'race_key', 'day', 'ninki', 'win_odds', 'top3', 'win', 'umaban',
        'h7_fig', 'spurt_idx', 'blood_race_pct', 'combo', 'elim_n', 'avg_pos3',
    ])
    for c in ('ninki', 'win_odds', 'top3', 'win', 'umaban', 'h7_fig',
              'spurt_idx', 'blood_race_pct', 'combo', 'elim_n', 'avg_pos3',
              'day'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['race_key'].notna()].copy()
    df = df.reset_index(drop=True)

    print('VH軽量スコア...', flush=True)
    df = add_light_score(df)
    flags = load_gold_usm(exp)
    df['race_key'] = df['race_key'].astype(str)
    df = df.merge(flags, on=['race_key', 'umaban'], how='left')
    for c in ('gold1', 'gold2', 'gold_any', 'gold_tri', 'usm_hi'):
        df[c] = df[c].fillna(False).astype(bool)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    shown = df['ninki'] >= POP
    elite = shown & df['elite']
    wide = shown & df['wide'] & ~df['elite']
    other = shown & ~df['wide'] & ~df['elite']
    net = shown & (df['elite'] | df['wide'])
    combo2 = df['combo'].notna() & (df['combo'] >= 2)
    gold1 = df['gold1']
    gold2 = df['gold2']
    gold_any = df['gold_any']
    usm_hi = df['usm_hi']

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }

    print(f'\n表示= {POP}番人気以下 {int(shown.sum()):,}走')
    print(f'精鋭+広域(VH網) {int(net.sum()):,} / 圏外 {int(other.sum()):,}')
    print('残差 = 実複勝 − 同オッズ帯期待。★ = 両窓 z>=+2 かつ残差>0\n')

    print('======== 対照 ========')
    print_block('6番以下 全体', shown, periods, df, e3)
    print_block('6番以下 × 🥇（35-40%・網の内外）', shown & gold1, periods, df, e3)
    print_block('6番以下 × 🥇🥇（40%+）', shown & gold2, periods, df, e3)
    base, _ = print_block('VH網（精鋭+広域・対照）', net, periods, df, e3)
    print_block('VH網 × combo≥2（濃い穴・対照）', net & combo2, periods, df, e3, base=base)

    print('\n======== ① VH × 🥇 ========')
    conds = [
        ('VH網 × 🥇（35-40%）', net & gold1),
        ('精鋭 × 🥇', elite & gold1),
        ('広域網 × 🥇', wide & gold1),
        ('VH網 × 🥇🥇（40%+・対照）', net & gold2),
        ('VH網 × 🥇または🥇🥇', net & gold_any),
        ('圏外 × 🥇（救済しない）', other & gold1),
        ('圏外 × 🥇または🥇🥇', other & gold_any),
    ]
    stars = []
    for name, mask in conds:
        _, ok = print_block(name, mask, periods, df, e3, base=base)
        if ok:
            stars.append(name)

    print('\n======== ② VH × combo≥2 × 🥇 ========')
    conds2 = [
        ('VH網 × combo≥2 × 🥇', net & combo2 & gold1),
        ('VH網 × combo≥2 × 🥇🥇', net & combo2 & gold2),
        ('VH網 × combo≥2 × 🥇または🥇🥇', net & combo2 & gold_any),
        ('精鋭 × combo≥2 × 🥇', elite & combo2 & gold1),
        ('広域網 × combo≥2 × 🥇', wide & combo2 & gold1),
        ('圏外 × combo≥2 × 🥇', other & combo2 & gold1),
    ]
    for name, mask in conds2:
        _, ok = print_block(name, mask, periods, df, e3, base=base)
        if ok:
            stars.append(name)

    print('\n======== ③ VH × combo≥2 × 馬連携上位 ========')
    conds3 = [
        ('VH網 × 馬連携上位（USM≥115）', net & usm_hi),
        ('VH網 × combo≥2 × 馬連携上位', net & combo2 & usm_hi),
        ('精鋭 × combo≥2 × 馬連携上位', elite & combo2 & usm_hi),
        ('広域網 × combo≥2 × 馬連携上位', wide & combo2 & usm_hi),
        ('圏外 × combo≥2 × 馬連携上位', other & combo2 & usm_hi),
    ]
    for name, mask in conds3:
        _, ok = print_block(name, mask, periods, df, e3, base=base)
        if ok:
            stars.append(name)

    print('\n======== ④ VH × 🥇 × 馬連携上位 ========')
    conds4 = [
        ('VH網 × 🥇 × 馬連携上位', net & gold1 & usm_hi),
        ('VH網 × combo≥2 × 🥇 × 馬連携上位', net & combo2 & gold1 & usm_hi),
        ('VH網 × 🥇または🥇🥇 × 馬連携上位', net & gold_any & usm_hi),
    ]
    for name, mask in conds4:
        _, ok = print_block(name, mask, periods, df, e3, base=base)
        if ok:
            stars.append(name)

    print('\n======== まとめ ========')
    if not stars:
        print('VH網に🥇／馬連携を掛けても、両窓 z>=+2 の追加残差には届かない。')
        print('🥇はJ5表のまま。ハンター印には昇格しない。点数にも足さない。')
        return
    print('両窓で来ている:')
    for s in stars:
        print(f'  {s}')
    print()
    print('来た組み合わせだけ表示印の候補。全部付いたから最強、にはしない。')
    print('点数・並び・馬連携のJ5再加算はしない。')


if __name__ == '__main__':
    main()
