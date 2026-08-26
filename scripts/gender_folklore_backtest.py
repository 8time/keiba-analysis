# -*- coding: utf-8 -*-
"""性別俗説の残差検証 — 優先1から順に。

資料: 「夏は牝馬」は芝短距離限定・ダート例外 / 軽ハンデ牝は買い /
      性別×馬場×距離 / セン馬 / 牝×ローテ / 斤量比12.11% / 牝×馬体重

判定:
  穴馬ハンター = 6番人気以下・見る+確認で z>=+2 かつ n>=200 かつ残差>0
  危険ゲート   = 1-3番人気・見る+確認で z<=-2 かつ n>=200
  消去         = 危険ゲートに加え、確認の絶対複勝 < 20%
  既存フェードを狭める = 冬春のダート牝がゲート未達、かつ芝では両窓で負

残差 = 実複勝 − 同オッズ帯の期待複勝。
Usage: python scripts/gender_folklore_backtest.py
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
Z_FADE = -2.0
SPRINT = 1300
MILE_HI = 1600
MID_HI = 2000
STAY = 3000
LIGHT_LO = 495   # 49.5kg (futan は 0.1kg 単位)
LIGHT_HI = 510   # 51.0kg
SMALL_KG = 440
KIN_GOOD = 0.1120
KIN_WALL = 0.1211
KIN_OLD = 0.1260
REST9 = 63
REST180 = 180


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


def both_ok(train, hold, z_min=None, z_max=None):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    if z_min is not None and not (train['z'] >= z_min and hold['z'] >= z_min):
        return False
    if z_max is not None and not (train['z'] <= z_max and hold['z'] <= z_max):
        return False
    return True


def gate_label(train, hold, pop_name):
    hunter = pop_name == '6番人気以下' and both_ok(train, hold, z_min=Z_HUNTER)
    if hunter and train['resid'] > 0 and hold['resid'] > 0:
        return '★穴馬候補(6番以下 両窓 z>=+2)'
    danger = pop_name in ('1-3番人気', '1番人気') and both_ok(train, hold, z_max=Z_FADE)
    if danger:
        if hold['hit'] < 0.20:
            return '★危険+消去候補(両窓 z<=-2 かつ絶対複<20%)'
        return '★危険候補(1-3人気 両窓 z<=-2 / 絶対率は高いので単独では切らない)'
    return 'ゲート未達'


def run_block(title, conds, pops, periods, df, e3, collect):
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
            row['verdict'] = gate_label(row['見る(〜2024)'], row['確認(2025)'], pop_name)
            print('  → ' + row['verdict'])
            collect.append(row)


def overlay(label, a_train, a_hold, b_train, b_hold):
    """対象 − 対照 の残差差(pp)。両窓で同じ向きなら印。"""
    lines = []
    for tag, a, b in (('見る', a_train, b_train), ('確認', a_hold, b_hold)):
        if a is None or b is None or a['n'] < MIN_N or b['n'] < MIN_N:
            lines.append(f'  {tag} {label}: 標本不足')
            continue
        dpp = (a['resid'] - b['resid']) * 100
        mark = ''
        if dpp >= 0.5:
            mark = '  対象が対照より良い'
        elif dpp <= -0.5:
            mark = '  対象が対照より悪い'
        lines.append(
            f'  {tag} {label}: {dpp:+5.2f}pp'
            f'  (対象 {a["resid"]*100:+5.2f} / 対照 {b["resid"]*100:+5.2f}){mark}')
    return lines


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
        'race_key', 'day', 'ninki', 'win_odds', 'top3', 'win',
        'surface_code', 'kyori_int', 'sex_code', 'is_handi1', 'futan',
        'bataiju', 'zogen', 'waku_n', 'days_since', 'pos_ratio3', 'age',
    ])
    races = cd.load_races(cols=['race_key', 'fillies', 'baba_code'], with_period=False)
    df = df.merge(races, on='race_key', how='left')

    num_cols = [
        'ninki', 'win_odds', 'top3', 'win', 'surface_code', 'kyori_int',
        'sex_code', 'is_handi1', 'futan', 'bataiju', 'zogen', 'waku_n',
        'days_since', 'pos_ratio3', 'age', 'fillies', 'baba_code', 'day',
    ]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['sex_code'].notna()
            & df['kyori_int'].notna() & df['surface_code'].notna()].copy()
    df = df.reset_index(drop=True)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    month = (df['day'] // 100) % 100
    female = df['sex_code'] == 2
    male = df['sex_code'] == 1
    geld = df['sex_code'] == 3
    turf = df['surface_code'] == 0
    dirt = df['surface_code'] == 1
    sprint = df['kyori_int'] <= SPRINT
    mile = (df['kyori_int'] > SPRINT) & (df['kyori_int'] <= MILE_HI)
    mid = (df['kyori_int'] > MILE_HI) & (df['kyori_int'] <= MID_HI)
    longish = df['kyori_int'] > MID_HI
    stay = df['kyori_int'] >= STAY
    dash = (df['kyori_int'] >= 1000) & (df['kyori_int'] <= 1200)
    summer79 = month.isin([7, 8, 9])
    summer68 = month.isin([6, 7, 8])          # folk_signals の夏
    winter122 = month.isin([12, 1, 2])
    fade_ws = month.isin([12, 1, 2, 3])       # 既存 danger_gate
    mixed = df['fillies'].fillna(0) == 0
    fillies_r = df['fillies'] == 1
    wet = df['baba_code'].isin([3, 4])
    lhandi = (df['is_handi1'] == 1) & df['futan'].between(LIGHT_LO, LIGHT_HI)
    frontish = df['pos_ratio3'] <= 0.30
    end_draw = df['waku_n'].isin([1, 7, 8])
    kin = (df['futan'] / 10.0) / df['bataiju']
    small = df['bataiju'] < SMALL_KG
    rest9 = df['days_since'] >= REST9
    rest180 = df['days_since'] >= REST180
    tight = df['days_since'].between(1, 13)
    midrot = df['days_since'].between(35, 56)  # 中5-8週

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }
    pops = {
        '全体': pd.Series(True, index=df.index),
        '1-3番人気': df['ninki'] <= 3,
        '6番人気以下': df['ninki'] >= 6,
    }
    collect = []

    print(f'  {len(df):,}走')
    print('残差 = 実複勝 − 同オッズ帯期待。正=人気以上に来る / 負=人気の割に来ない。')
    print('★穴馬 = 6番以下 両窓 z>=+2  /  ★危険 = 1-3人気 両窓 z<=-2')

    # ------------------------------------------------------------------
    # 優先1  夏は牝馬 / 冬フェードの芝ダ・距離分解
    # ------------------------------------------------------------------
    conds1 = [
        ('牝×夏7-9 (資料の夏・未切り)', female & summer79),
        ('牝×夏6-8 (folkの夏・未切り)', female & summer68),
        ('牡×夏7-9 (対照)', male & summer79),
        ('牝×夏7-9×芝', female & summer79 & turf),
        ('牝×夏7-9×ダート', female & summer79 & dirt),
        ('牝×夏7-9×芝×1300m以下', female & summer79 & turf & sprint),
        ('牝×夏7-9×ダ×1300m以下', female & summer79 & dirt & sprint),
        ('牝×夏7-9×芝×1400-1600', female & summer79 & turf & mile),
        ('牝×夏7-9×芝×1700-2000', female & summer79 & turf & mid),
        ('牝×夏7-9×芝×2000m超', female & summer79 & turf & longish),
        ('牝×夏7-9×芝短×混合戦', female & summer79 & turf & sprint & mixed),
        ('牝×夏7-9×芝短×牝馬限定', female & summer79 & turf & sprint & fillies_r),
        ('牡×夏7-9×芝×1300m以下 (対照)', male & summer79 & turf & sprint),
        ('牡×夏7-9×ダ×1300m以下 (対照)', male & summer79 & dirt & sprint),
        ('牝×冬12-2 (資料の冬・未切り)', female & winter122),
        ('牝×冬春12-3 (既存フェード)', female & fade_ws),
        ('牝×冬春×芝', female & fade_ws & turf),
        ('牝×冬春×ダート', female & fade_ws & dirt),
        ('牝×冬春×芝×1300m以下', female & fade_ws & turf & sprint),
        ('牝×冬春×ダ×1300m以下', female & fade_ws & dirt & sprint),
        ('牝×冬春×芝×2000m超', female & fade_ws & turf & longish),
        ('牡×冬12-2 (対照)', male & winter122),
    ]
    run_block('優先1  夏は牝馬 / 冬フェードの芝ダ分解', conds1, pops, periods, df, e3, collect)

    print('\n---- 優先1 交互作用 ----')
    pairs1 = [
        ('全体', '牝×夏7-9×芝×1300m以下', '牝×夏7-9×ダート'),
        ('全体', '牝×夏7-9×芝×1300m以下', '牡×夏7-9×芝×1300m以下 (対照)'),
        ('6番人気以下', '牝×夏7-9×芝×1300m以下', '牡×夏7-9×芝×1300m以下 (対照)'),
        ('全体', '牝×夏7-9×芝短×混合戦', '牡×夏7-9×芝×1300m以下 (対照)'),
        ('1-3番人気', '牝×冬春×芝', '牝×冬春×ダート'),
        ('1-3番人気', '牝×冬春×芝×1300m以下', '牝×冬春×ダ×1300m以下'),
        ('全体', '牝×冬春×芝', '牝×冬春×ダート'),
    ]
    b1 = [r for r in collect if r['block'].startswith('優先1')]
    for pop, a, b in pairs1:
        ra, rb = pick(b1, pop, a), pick(b1, pop, b)
        if not ra or not rb:
            continue
        print(f'[{pop}] {a} vs {b}')
        for line in overlay(f'{a} − {b}',
                            ra['見る(〜2024)'], ra['確認(2025)'],
                            rb['見る(〜2024)'], rb['確認(2025)']):
            print(line)

    # ------------------------------------------------------------------
    # 優先2  軽ハンデ牝馬
    # ------------------------------------------------------------------
    conds2 = [
        ('軽ハンデ 49.5-51kg (現行消去)', lhandi),
        ('軽ハンデ×牝', lhandi & female),
        ('軽ハンデ×牡セ', lhandi & ~female),
        ('軽ハンデ×芝', lhandi & turf),
        ('軽ハンデ×ダート', lhandi & dirt),
        ('軽ハンデ×牝×芝', lhandi & female & turf),
        ('軽ハンデ×牝×ダート', lhandi & female & dirt),
        ('軽ハンデ×牝×芝1000-1200', lhandi & female & turf & dash),
        ('軽ハンデ×牝×芝3000+', lhandi & female & turf & stay),
        ('軽ハンデ×牝×芝短×逃げぐせ', lhandi & female & turf & dash & frontish),
        ('軽ハンデ×牝×芝短×1/7/8枠', lhandi & female & turf & dash & end_draw),
        ('軽ハンデ×牝×芝短×逃げ×両端枠',
         lhandi & female & turf & dash & frontish & end_draw),
        ('軽ハンデ×牝×芝1400-2000', lhandi & female & turf & (mile | mid)),
    ]
    run_block('優先2  軽ハンデ牝馬 (資料=買い / アプリ=消し)', conds2, pops, periods, df, e3, collect)

    print('\n---- 優先2 交互作用 ----')
    b2 = [r for r in collect if r['block'].startswith('優先2')]
    pairs2 = [
        ('全体', '軽ハンデ×牝×芝', '軽ハンデ 49.5-51kg (現行消去)'),
        ('6番人気以下', '軽ハンデ×牝×芝', '軽ハンデ 49.5-51kg (現行消去)'),
        ('全体', '軽ハンデ×牝×芝', '軽ハンデ×牡セ'),
        ('全体', '軽ハンデ×牝×芝1000-1200', '軽ハンデ 49.5-51kg (現行消去)'),
    ]
    for pop, a, b in pairs2:
        ra, rb = pick(b2, pop, a), pick(b2, pop, b)
        if not ra or not rb:
            continue
        print(f'[{pop}] {a} vs {b}')
        for line in overlay(f'{a} − {b}',
                            ra['見る(〜2024)'], ra['確認(2025)'],
                            rb['見る(〜2024)'], rb['確認(2025)']):
            print(line)

    # ------------------------------------------------------------------
    # 優先3  性別 × 馬場 × 距離
    # ------------------------------------------------------------------
    dist_slices = [
        ('1300m以下', sprint),
        ('1400-1600', mile),
        ('1700-2000', mid),
        ('2000m超', longish),
    ]
    conds3 = []
    for dname, dmask in dist_slices:
        conds3.append((f'牝×芝×{dname}', female & turf & dmask))
        conds3.append((f'牡×芝×{dname}', male & turf & dmask))
        conds3.append((f'牝×ダ×{dname}', female & dirt & dmask))
        conds3.append((f'牡×ダ×{dname}', male & dirt & dmask))
        conds3.append((f'牝×芝×{dname}×混合', female & turf & dmask & mixed))
    conds3.extend([
        ('牡×ダ×重不良', male & dirt & wet),
        ('牝×ダ×重不良', female & dirt & wet),
        ('牝×混合戦 全体', female & mixed),
        ('牝×牝馬限定 全体', female & fillies_r),
        ('牡×混合戦 全体', male & mixed),
    ])
    run_block('優先3  性別×馬場×距離グリッド', conds3, pops, periods, df, e3, collect)

    # ------------------------------------------------------------------
    # 次点  セン馬 / 牝×ローテ / 斤量比 / 馬体重
    # ------------------------------------------------------------------
    conds4 = [
        ('セン馬 全体', geld),
        ('セン馬×芝', geld & turf),
        ('セン馬×ダート', geld & dirt),
        ('セン馬×芝×1300m以下', geld & turf & sprint),
        ('セン馬×ダ×1700-2000', geld & dirt & mid),
        ('牝×中9週+休み明け', female & rest9),
        ('牡×中9週+休み明け (対照)', male & rest9),
        ('牝×半年休み', female & rest180),
        ('牝×連戦(中1-2週)', female & tight),
        ('牡×連戦(中1-2週) (対照)', male & tight),
        ('牝×中5-8週', female & midrot),
        ('牝×中9週+×芝短', female & rest9 & turf & sprint),
        (f'斤量比<{KIN_GOOD*100:.2f}%', kin < KIN_GOOD),
        (f'斤量比 {KIN_GOOD*100:.2f}-{KIN_WALL*100:.2f}%',
         kin.between(KIN_GOOD, KIN_WALL, inclusive='left')),
        (f'斤量比≥{KIN_WALL*100:.2f}% (資料の壁)', kin >= KIN_WALL),
        (f'斤量比≥{KIN_OLD*100:.1f}% (削除済み閾値)', kin >= KIN_OLD),
        ('牝×小柄×斤量比≥12.11%', female & small & (kin >= KIN_WALL)),
        ('牝×馬体重-6kg以下', female & (df['zogen'] <= -6)),
        ('牡×馬体重-6kg以下 (対照)', male & (df['zogen'] <= -6)),
        ('牝×小柄×馬体重-6kg', female & small & (df['zogen'] <= -6)),
        ('牝×馬体重+8kg以上', female & (df['zogen'] >= 8)),
    ]
    run_block('次点  セン馬 / 牝×ローテ / 斤量比 / 馬体重', conds4, pops, periods, df, e3, collect)

    # ------------------------------------------------------------------
    # まとめ
    # ------------------------------------------------------------------
    print('\n' + '=' * 72)
    print('まとめ — 両窓ゲートを満たした条件だけ')
    print('=' * 72)
    stars = [r for r in collect if r['verdict'].startswith('★')]
    if not stars:
        print('どのスライスも両窓ゲートに届かなかった。アプリは現状維持。')
        return

    for r in stars:
        t, h = r['見る(〜2024)'], r['確認(2025)']
        print(f"\n[{r['pop']}] {r['cond']}")
        print(f"  {r['verdict']}")
        print(f"  見る 複{t['hit']:.1%} 残差{t['resid']*100:+.2f}pp z={t['z']:+.2f} n={t['n']}")
        print(f"  確認 複{h['hit']:.1%} 残差{h['resid']*100:+.2f}pp z={h['z']:+.2f} n={h['n']}")

    print('\nスコアへは自動では入れない。穴馬は6番以下の正残差、危険は1-3の負残差だけ。')


if __name__ == '__main__':
    main()
