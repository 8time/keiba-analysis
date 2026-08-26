# -*- coding: utf-8 -*-
"""ダート／短距離 × 休み明け — 消去フラグ候補の検証。

資料主張:
  ダート休み明け 複勝16.9%(10-25週) / 14.3%(半年+) → 大幅割引
  1300m以下休み明け 複勝15.3% / 13.6%(長期) → 大幅マイナス
  芝・2500m以上は休み明けでも割引不要

既存との関係:
  半年休み(>=180日)は elim_cross に既にある。中9週+(>=63日)は人気馬のソフト減点のみ。
  ここでは『芝ダ・距離を分けたときに、休み明け単独より悪いか』=交互作用を見る。
  交互作用が無ければ新フラグは不要(既存の休み明けで足りる)。

判定(消去として採用):
  見る期間(〜2024) と 確認期間(2025) の両方で 複残差 z<=-2 かつ n>=200
  かつ 同じ休養帯の芝(または中長距離)より残差が明確に悪い
  1-3番人気で絶対複勝率が高い帯は単独危険表示にしない(半年休みの教訓)

母集団スライス: 全体 / 1-3番人気 / 6番人気以下

Usage: python scripts/layoff_dirt_sprint_backtest.py
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
Z_GATE = -2.0
LAYOFF_MID = 63    # 中9週+(アプリ既存)
LAYOFF_LONG = 180  # 半年+(elim_cross既存)
SPRINT = 1300
STAY = 2500


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


def mark_elim(train, hold):
    """両窓で残差z<=-2 かつ確認n>=200なら消去候補。"""
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return train['z'] <= Z_GATE and hold['z'] <= Z_GATE


def worse_than(a, b, pad_pp=0.5):
    """a の残差が b より pad_pp 以上悪い(交互作用の目安)。"""
    if a is None or b is None:
        return False
    if a['n'] < MIN_N or b['n'] < MIN_N:
        return False
    return (a['resid'] * 100) <= (b['resid'] * 100) - pad_pp


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    print('CSV...', flush=True)
    df = cd.load_horses(cols=[
        'day', 'ninki', 'win_odds', 'top3', 'win',
        'days_since', 'surface_code', 'kyori_int',
    ])
    for c in ('ninki', 'win_odds', 'top3', 'win', 'days_since',
              'surface_code', 'kyori_int', 'day'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['days_since'].notna()
            & (df['days_since'] > 0) & df['kyori_int'].notna()
            & df['surface_code'].notna()].copy()
    df = df.reset_index(drop=True)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    dirt = df['surface_code'] == 1
    turf = df['surface_code'] == 0
    sprint = df['kyori_int'] <= SPRINT
    stay = df['kyori_int'] >= STAY
    mid = (df['kyori_int'] > SPRINT) & (df['kyori_int'] < STAY)
    rest9 = df['days_since'] >= LAYOFF_MID
    rest_mid = (df['days_since'] >= LAYOFF_MID) & (df['days_since'] < LAYOFF_LONG)
    rest180 = df['days_since'] >= LAYOFF_LONG
    fresh = df['days_since'] < LAYOFF_MID

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }
    pops = {
        '全体': pd.Series(True, index=df.index),
        '1-3番人気': df['ninki'] <= 3,
        '1番人気': df['ninki'] == 1,
        '6番人気以下': df['ninki'] >= 6,
    }

    conds = [
        ('休み明け中9週+ (対照・全条件)', rest9),
        ('中9-25週 (63-179日)', rest_mid),
        ('半年休み (180日+)', rest180),
        ('中8週以内 (対照・使われている)', fresh),
        ('ダート×中9週+', dirt & rest9),
        ('芝×中9週+ (対照)', turf & rest9),
        ('ダート×中9-25週', dirt & rest_mid),
        ('芝×中9-25週 (対照)', turf & rest_mid),
        ('ダート×半年休み', dirt & rest180),
        ('芝×半年休み (対照)', turf & rest180),
        ('ダート×中8週以内 (対照)', dirt & fresh),
        ('芝×中8週以内 (対照)', turf & fresh),
        ('1300m以下×中9週+', sprint & rest9),
        ('1400-2400×中9週+ (対照)', mid & rest9),
        ('2500m以上×中9週+ (対照)', stay & rest9),
        ('1300m以下×中9-25週', sprint & rest_mid),
        ('1300m以下×半年休み', sprint & rest180),
        ('1300m以下×中8週以内 (対照)', sprint & fresh),
        ('ダート1300m以下×中9週+', dirt & sprint & rest9),
        ('芝1300m以下×中9週+ (対照)', turf & sprint & rest9),
        ('ダート2500m以上×中9週+', dirt & stay & rest9),
        ('芝2500m以上×中9週+ (対照)', turf & stay & rest9),
    ]

    print(f'  {len(df):,}走 (days_sinceあり)')
    print('残差 = 実複勝 − 同オッズ帯の期待複勝。マイナス=人気の割に来ない。')
    print('★消去候補 = 見る+確認の両方で z<=-2 かつ n>=200')
    print('交互作用 = 同じ休養帯の対照(芝 or 中長距離)より残差が0.5pp以上悪い\n')

    verdicts = []
    for pop_name, pop in pops.items():
        print(f'\n======== {pop_name} ========')
        for cname, cmask in conds:
            print(f'--- {cname} ---')
            row = {'pop': pop_name, 'cond': cname}
            st_by = {}
            for pname, pm in periods.items():
                st = stats(df[pop & cmask & pm], e3)
                st_by[pname] = st
                print(f'  {pname:12s} {fmt(st)}')
            row['train'] = st_by['見る(〜2024)']
            row['hold'] = st_by['確認(2025)']
            row['elim'] = mark_elim(row['train'], row['hold'])
            print('  → ' + ('★ 消去候補(両窓 z<=-2)' if row['elim'] else 'ゲート未達'))
            verdicts.append(row)

    # 交互作用: 同じpop・同じ休養帯で 対象 vs 対照
    pairs = [
        ('ダート×中9週+', '芝×中9週+ (対照)'),
        ('ダート×中9-25週', '芝×中9-25週 (対照)'),
        ('ダート×半年休み', '芝×半年休み (対照)'),
        ('1300m以下×中9週+', '1400-2400×中9週+ (対照)'),
        ('1300m以下×中9週+', '2500m以上×中9週+ (対照)'),
        ('ダート1300m以下×中9週+', '芝1300m以下×中9週+ (対照)'),
        ('芝2500m以上×中9週+ (対照)', '休み明け中9週+ (対照・全条件)'),
    ]

    print('\n======== 交互作用 (確認期間) ========')
    print('対象の残差が対照より 0.5pp 以上悪いか。見る期間も同じ向きなら「条件の上乗せ」.')
    for pop_name in pops:
        print(f'\n--- {pop_name} ---')
        by_cond = {r['cond']: r for r in verdicts if r['pop'] == pop_name}
        for a, b in pairs:
            ra, rb = by_cond.get(a), by_cond.get(b)
            if not ra or not rb:
                continue
            for tag, key in (('見る', 'train'), ('確認', 'hold')):
                sa, sb = ra[key], rb[key]
                if sa is None or sb is None or sa['n'] < MIN_N or sb['n'] < MIN_N:
                    print(f'  {tag} {a} vs {b}: 標本不足')
                    continue
                dpp = (sa['resid'] - sb['resid']) * 100
                flag = ' 上乗せ' if dpp <= -0.5 else ''
                print(f'  {tag} {a} − {b}: {dpp:+5.2f}pp'
                      f'  (対象 {sa["resid"]*100:+5.2f} / 対照 {sb["resid"]*100:+5.2f}){flag}')

    print('\n======== まとめ ========')
    stars = [r for r in verdicts if r['elim'] and '対照' not in r['cond']]
    if not stars:
        print('資料の『ダート／短距離×休み明け』は、両窓ゲートを満たす新フラグにならなかった。')
        print('既存の半年休み(180日+)と人気馬×中9週+ソフト減点のままで足りる。')
        return
    print('両窓で z<=-2 になった条件(対照を除く):')
    for r in stars:
        t, h = r['train'], r['hold']
        print(f"  [{r['pop']}] {r['cond']}")
        print(f"    見る 複{t['hit']:.1%} 残差{t['resid']*100:+.2f}pp z={t['z']:+.2f} n={t['n']}")
        print(f"    確認 複{h['hit']:.1%} 残差{h['resid']*100:+.2f}pp z={h['z']:+.2f} n={h['n']}")
        abs_hi = h['hit'] >= 0.35
        note = '絶対率が高い → 単独危険表示はしない(半年休みと同じ)' if abs_hi else \
               '絶対率も低い → 消去クロスの条件付きフラグ候補'
        print(f'    {note}')
    print('スコア・買い目には自動では入れない。交互作用が無いなら既存フラグで足りる。')


if __name__ == '__main__':
    main()
