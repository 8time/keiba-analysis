# -*- coding: utf-8 -*-
"""VHが拾った穴の中から、combo / 血統 / 位置で危険な馬を落とせるか。

見逃し救済は不成立。こちらは逆方向＝誤選択の除去。
VHスコアの重みは触らず、広域網リストから条件付きで外すだけ。

判定（除去として採用）:
  広域網（6番以下・recall0.7以上）× シグナル が
  見る+確認で複残差 z<=-2、n>=200、残差<0。
  かつ 広域網全体より残差が 0.5pp 以上悪い（上乗せ）。

Usage: python scripts/hunter_vh_prune.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from scripts import csv_data as cd
from scripts.hunter_miss_complement import (
    BLOOD_HI, MIN_N, POP, add_light_score, fmt, stats,
)

Z_PRUNE = -2.0
PAD_PP = 0.5


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def prune_ok(train, hold, base_train=None, base_hold=None):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    if not (train['z'] <= Z_PRUNE and hold['z'] <= Z_PRUNE
            and train['resid'] < 0 and hold['resid'] < 0):
        return False
    if base_train is None or base_hold is None:
        return True
    if base_train['n'] < MIN_N or base_hold['n'] < MIN_N:
        return True
    d_tr = (train['resid'] - base_train['resid']) * 100
    d_ho = (hold['resid'] - base_hold['resid']) * 100
    return d_tr <= -PAD_PP and d_ho <= -PAD_PP


def print_block(title, mask, periods, df, e3, base=None):
    print(f'--- {title} ---')
    row = {}
    for pname, pm in periods.items():
        st = stats(df[mask & pm], e3)
        row[pname] = st
        extra = ''
        if base and pname in base and st and base[pname] and st['n'] >= MIN_N and base[pname]['n'] >= MIN_N:
            dpp = (st['resid'] - base[pname]['resid']) * 100
            extra = f'  vs網{dpp:+.2f}pp'
        print(f'  {pname:12s} {fmt(st)}{extra}')
    ok = prune_ok(row.get('見る(〜2024)'), row.get('確認(2025)'),
                  None if not base else base.get('見る(〜2024)'),
                  None if not base else base.get('確認(2025)'))
    print('  → ' + ('★除去候補(両窓 z<=-2 かつ網より0.5pp以上悪い)'
                    if ok else 'ゲート未達'))
    return row, ok


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    print('CSV...', flush=True)
    df = cd.load_horses(cols=[
        'race_key', 'day', 'ninki', 'win_odds', 'top3', 'win',
        'h7_fig', 'spurt_idx', 'blood_race_pct', 'combo', 'elim_n',
        'avg_pos3',
    ])
    for c in ('ninki', 'win_odds', 'top3', 'win', 'h7_fig', 'spurt_idx',
              'blood_race_pct', 'combo', 'elim_n', 'avg_pos3', 'day'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['race_key'].notna()].copy()
    df = df.reset_index(drop=True)

    print('VH軽量スコア...', flush=True)
    df = add_light_score(df)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }

    pool = df['ninki'] >= POP
    wide = pool & df['wide']
    elite = pool & df['elite']
    combo_known = df['combo'].notna()
    combo0 = combo_known & (df['combo'] == 0)
    combo1 = combo_known & (df['combo'] == 1)
    combo2 = combo_known & (df['combo'] >= 2)
    combo3 = combo_known & (df['combo'] >= 3)
    blood_hi = df['blood_pct'] >= BLOOD_HI
    blood_lo = df['blood_pct'] <= 0.30
    pos = df['pos_front'] == 1
    not_pos = df['pos_front'] == 0

    print(f'対象: {POP}番人気以下 × 広域網  {int(wide.sum()):,}走')
    print('除去 = 網の中で人気の割に来ない。VHスコアの重みは変えない。')
    print('残差 = 実複勝 − 同オッズ帯期待。マイナス=落とす候補。\n')

    print('======== 広域網の中 ========')
    base, _ = print_block('広域網 全体（対照）', wide, periods, df, e3)
    conds = [
        ('網 × combo=0', wide & combo0),
        ('網 × combo=1', wide & combo1),
        ('網 × combo≥2（濃い穴・対照）', wide & combo2),
        ('網 × combo≥3', wide & combo3),
        ('網 × 血統レース上位30%', wide & blood_hi),
        ('網 × 血統レース下位30%', wide & blood_lo),
        ('網 × 位置前寄り', wide & pos),
        ('網 × 位置前寄りでない', wide & not_pos),
        ('網 × combo=0 × 血統上位', wide & combo0 & blood_hi),
        ('網 × combo=0 × 位置前', wide & combo0 & pos),
        ('網 × 血統上位 × 位置前', wide & blood_hi & pos),
        ('網 × combo既知のみ', wide & combo_known),
    ]
    stars = []
    for name, mask in conds:
        _, ok = print_block(name, mask, periods, df, e3, base=base)
        if ok:
            stars.append(name)

    print('\n======== 精鋭の中（参考） ========')
    ebase, _ = print_block('精鋭 全体（対照）', elite, periods, df, e3)
    econds = [
        ('精鋭 × combo=0', elite & combo0),
        ('精鋭 × combo≥2', elite & combo2),
        ('精鋭 × 血統上位30%', elite & blood_hi),
        ('精鋭 × 位置前寄り', elite & pos),
    ]
    for name, mask in econds:
        _, ok = print_block(name, mask, periods, df, e3, base=ebase)
        if ok:
            stars.append(name)

    print('\n======== まとめ ========')
    if not stars:
        print('広域網の中で、combo / 血統 / 位置による除去は両窓ゲートに届かなかった。')
        print('VHリストからの条件付き落馬はしない。combo≥2 は絞りフィルターのまま。')
        return
    print('除去候補:')
    for s in stars:
        print(f'  {s}')
    print('VHスコアの重みは変えない。リストから外す条件としてだけ検討。')


if __name__ == '__main__':
    main()
