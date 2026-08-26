# -*- coding: utf-8 -*-
"""事前リストの計算式だけを、回収率・的中(複勝残差)で測るループ。

「あらゆる組合せ」は当たり年を拾うのでやらない。下の FORMULAS だけ。
判定: 見る期間(〜2024)と確認期間(2025)の両方で 複残差z>=+2、確認n>=200。
単勝ROI>100%は必須にしない(単勝は市場が効率的)。確認期間の単ROIが
母集団より明らかに悪い式は★にしない。自動でスコアへは入れない。

使い方: python scripts/formula_residual_loop.py
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
Z_GATE = 2.0


def _rank_desc(s, g):
    return s.groupby(g).rank(ascending=False, method='min')


def formulas(df):
    """リーク無し列だけから、事前に決めた旗。"""
    ninki = df['ninki']
    h7r = df['h7_rank']
    h7p = df['h7_pct']
    sp = df['spurt_race_pct']
    bl = df['blood_race_pct']
    tr = df['trainer_jyo_t3']
    jk = df['jockey_jyo_win']
    jd = df['jockey_dist_win']
    days = df['days_since']
    dist = df['dist_change']
    zg = df['zogen']
    pos = df['pos_ratio3']
    combo = df['combo']
    lap = df['lap_fit_bin']
    age = df['age']
    waku = df['waku_n']
    ky = df['kyori_int']
    dirt = df['surface_code'] == 1
    turf = df['surface_code'] == 0
    female = df['sex_code'] == 2
    month = (df['day'] // 100) % 100
    odds = df['win_odds']
    ability = df['ability_score']
    field = df['field_size'].replace(0, np.nan)

    sp_rank = _rank_desc(sp, df['race_key'])
    gap_h7 = ninki - h7r
    gap_sp = ninki - sp_rank
    val_ratio = (h7p.fillna(0) + 0.01) / (ninki / field)
    race_val_rank = _rank_desc(val_ratio, df['race_key'])
    ab_odds = ability / np.log1p(odds)
    ab_rank = _rank_desc(ab_odds, df['race_key'])
    jk_tr = jk * tr
    h7_sp = (h7p + sp) / 2.0
    mix_rank = _rank_desc(h7_sp, df['race_key'])

    out = {
        '図指数が人気より上(差4+)': (gap_h7 >= 4) & h7r.notna(),
        '末脚が人気より上(差4+)': (gap_sp >= 4) & sp.notna(),
        '図の割安比 レース上位20%': (race_val_rank <= df.groupby('race_key')['umaban'].transform('size') * 0.20) & h7p.notna(),
        '能力÷単オッズ レース上位20%': (ab_rank <= df.groupby('race_key')['umaban'].transform('size') * 0.20) & ability.notna(),
        '血統上位×5番人気以下': (bl >= 0.70) & (ninki >= 5),
        '厩舎当コース複25%+×6番〜': (tr >= 0.25) & (ninki >= 6),
        '騎手当場勝率15%+×6番〜': (jk >= 0.15) & (ninki >= 6),
        '騎手場×距離の積 高×6番〜': (jk_tr >= 0.04) & (ninki >= 6),
        '間隔2〜6週×図上位': days.between(14, 42) & (h7p >= 0.60),
        '若駒距離延長200m+×6番〜': (dist >= 200) & (age <= 4) & (ninki >= 6),
        '距離短縮200m+×6番〜': (dist <= -200) & (ninki >= 6),
        '減量8kg+休み4週+×6番〜': (zg <= -8) & (days >= 28) & (ninki >= 6),
        '後方×末脚上位×6番〜': (pos >= 0.65) & (sp >= 0.70) & (ninki >= 6),
        '図+末脚ミックス レース上位3': (mix_rank <= 3) & h7p.notna() & sp.notna(),
        '33ラップ適合×6番〜': (lap == 1) & (ninki >= 6),
        'シグナル2重+×6番〜': (combo >= 2) & (ninki >= 6),
        'ダ短内枠×6番〜': dirt & (ky <= 1400) & (waku <= 2) & (ninki >= 6),
        '芝マイル外枠×6番〜': turf & ky.between(1400, 1800) & (waku >= 7) & (ninki >= 6),
        '牝ダ冬春の人気馬(1-3)': female & dirt & month.between(1, 4) & ninki.between(1, 3),
        '近走複勝率50%+×6番〜': (df['prior_top3_rate'] >= 0.50) & (ninki >= 6),
    }
    return out


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def period_stats(sub, e3):
    n = len(sub)
    if n == 0:
        return None
    t3 = sub['top3'].to_numpy()
    win = sub['win'].to_numpy()
    odds = sub['win_odds'].to_numpy()
    resid = t3 - e3[sub.index].to_numpy()
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
    return (f"n={s['n']:6d} 複的中{s['hit']:5.1%} 勝{s['win']:5.1%} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']:+.3f}(z={s['z']:+.2f})")


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    print('CSV...', flush=True)
    df = cd.load_horses()
    for c in ('h7_rank', 'h7_pct', 'spurt_race_pct', 'blood_race_pct',
              'trainer_jyo_t3', 'jockey_jyo_win', 'jockey_dist_win',
              'days_since', 'dist_change', 'zogen', 'pos_ratio3', 'combo',
              'lap_fit_bin', 'age', 'waku_n', 'kyori_int', 'surface_code',
              'sex_code', 'win_odds', 'ability_score', 'field_size',
              'prior_top3_rate', 'umaban', 'top3', 'win', 'ninki', 'day'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0) & df['ninki'].notna()]
    df = df.reset_index(drop=True)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)
    print(f'  {len(df):,}走', flush=True)

    masks = formulas(df)
    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }
    base = {name: period_stats(df[m], e3) for name, m in periods.items()}
    pop6 = df['ninki'] >= 6
    base6 = {name: period_stats(df[m & pop6], e3) for name, m in periods.items()}

    print('\n======== 母集団 ========')
    for name, s in base.items():
        print(f'  全体 {name:12s} {fmt(s)}')
    for name, s in base6.items():
        print(f'  6番〜 {name:12s} {fmt(s)}')

    print('\n======== 事前リストの式 ========')
    print('★ = 見る期間・確認期間の両方で複残差z>=+2 かつ 確認n>=200')
    print('    かつ 確認の単ROIが同じ母集団(全体 or 6番〜)より悪くない\n')

    rows = []
    for fname, mask in masks.items():
        mask = mask.fillna(False)
        uses_long = '6番' in fname or '5番' in fname
        print(f'--- {fname} ---')
        rec = {'name': fname}
        ok_train = ok_hold = False
        roi_ok = False
        for pname, pm in periods.items():
            sub = df[mask & pm]
            st = period_stats(sub, e3)
            rec[pname] = st
            print(f'  {pname:12s} {fmt(st)}')
            if st is None:
                continue
            if pname == '見る(〜2024)' and st['z'] >= Z_GATE:
                ok_train = True
            if pname == '確認(2025)' and st['z'] >= Z_GATE and st['n'] >= MIN_N:
                ok_hold = True
                ref = base6['確認(2025)'] if uses_long else base['確認(2025)']
                roi_ok = (ref is None) or (st['roi'] >= ref['roi'] - 0.02)
        star = ok_train and ok_hold and roi_ok
        rec['star'] = star
        print('  → ' + ('★ 採用候補(配線はしない・人のレビュー待ち)' if star else '不採用'))
        rows.append(rec)

    stars = [r['name'] for r in rows if r['star']]
    print('\n======== まとめ ========')
    if stars:
        print('通過: ' + ' / '.join(stars))
        print('スコア・買い目には入れない。残差が持続するか種を変えて再確認してから。')
    else:
        print('通過ゼロ。このCSVの列の組み合わせでは、新しい回収・的中の数字は出ていない。')


if __name__ == '__main__':
    main()
