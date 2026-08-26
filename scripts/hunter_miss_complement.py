# -*- coding: utf-8 -*-
"""穴馬ハンターが見逃した6番以下3着内を、combo / 血統 / 位置が補完できるか。

ライブの VH 軽量スコアは係数が オッズ 0.88 + 補正T 0.41 で、
combo / 血統 / 位置はほぼ 0（位置はわずかに負）。
だから「圏外に落ちた穴」に、これらがまだ残差を残すなら補完候補。
残差がゼロなら、すでにオッズ・補正Tに吸収されている。

判定（補完として足す）:
  圏外（広域網しきい値未満）× シグナル の 6番以下が、
  見る+確認で複残差 z>=+2、n>=200。

Usage: python scripts/hunter_miss_complement.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from core import value_hunter as vh
from scripts import csv_data as cd

MIN_N = 200
Z_GATE = 2.0
POP = 6
BLOOD_HI = 0.70
POS_FRONT = 3.0


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
        'hits': int(t3.sum()),
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 捕捉{s['hits']:5d} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def add_light_score(df):
    """value_hunter と同じ7特徴ロジスティック。パーセンタイルはレース全頭。"""
    g = df.groupby('race_key', sort=False)

    def _pct(col, higher_better):
        if higher_better:
            rnk = g[col].rank(ascending=False, method='min')
        else:
            rnk = g[col].rank(ascending=True, method='min')
        n = df[col].notna().groupby(df['race_key']).transform('sum')
        denom = (n - 1).clip(lower=1)
        out = 1.0 - (rnk - 1) / denom
        return out.where(df[col].notna(), np.nan)

    df = df.copy()
    df['ct_pct'] = _pct('h7_fig', False)
    df['spurt_pct'] = _pct('spurt_idx', True)
    df['blood_pct'] = _pct('blood_race_pct', True)
    df['neg_log_odds'] = -np.log(df['win_odds'].astype(float))
    df['combo_n'] = pd.to_numeric(df['combo'], errors='coerce').fillna(0.0)
    df['low_elim'] = (pd.to_numeric(df['elim_n'], errors='coerce').fillna(9) <= 1).astype(float)
    df['pos_front'] = (pd.to_numeric(df['avg_pos3'], errors='coerce') <= POS_FRONT).astype(float)

    p = vh.load_params()
    mu, sd, w, b = np.array(p['mu']), np.array(p['sd']), np.array(p['w']), p['b']
    feats = {
        'neg_log_odds': df['neg_log_odds'],
        'ct_pct': df['ct_pct'].fillna(0.5),
        'spurt_pct': df['spurt_pct'].fillna(0.5),
        'blood_pct': df['blood_pct'].fillna(0.5),
        'combo': df['combo_n'],
        'low_elim': df['low_elim'],
        'pos_front': df['pos_front'],
    }
    z = np.full(len(df), b, dtype=float)
    for i, name in enumerate(vh.FEATS):
        sdi = sd[i] if sd[i] else 1.0
        z += w[i] * ((feats[name].to_numpy(dtype=float) - mu[i]) / sdi)
    df['vh_p'] = 1.0 / (1.0 + np.exp(-z))
    ops = p['ops']
    df['elite'] = df['vh_p'] >= ops['recall0.5']
    df['wide'] = df['vh_p'] >= ops['recall0.7']
    return df


def both_star(train, hold):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return (train['z'] >= Z_GATE and hold['z'] >= Z_GATE
            and train['resid'] > 0 and hold['resid'] > 0)


def print_block(title, mask, periods, df, e3):
    print(f'--- {title} ---')
    row = {}
    for pname, pm in periods.items():
        st = stats(df[mask & pm], e3)
        row[pname] = st
        print(f'  {pname:12s} {fmt(st)}')
    ok = both_star(row.get('見る(〜2024)'), row.get('確認(2025)'))
    print('  → ' + ('★補完候補(圏外で両窓 z>=+2)' if ok else 'ゲート未達'))
    return row, ok


def coverage(hits_miss, label, flag):
    sub = hits_miss[flag]
    n = len(hits_miss)
    if n == 0:
        return
    k = int(flag.sum()) if hasattr(flag, 'sum') else int(sub)
    # flag aligned
    k = int(flag.reindex(hits_miss.index).fillna(False).sum())
    print(f'  見逃し3着内のうち {label}: {k}/{n} ({k/n:5.1%})')


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    print('CSV...', flush=True)
    df = cd.load_horses(cols=[
        'race_key', 'day', 'ninki', 'win_odds', 'top3', 'win',
        'h7_fig', 'spurt_idx', 'blood_race_pct', 'combo', 'elim_n',
        'avg_pos3', 'sire_winroi',
    ])
    for c in ('ninki', 'win_odds', 'top3', 'win', 'h7_fig', 'spurt_idx',
              'blood_race_pct', 'combo', 'elim_n', 'avg_pos3', 'sire_winroi',
              'day'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['race_key'].notna()].copy()
    df = df.reset_index(drop=True)

    print('VH軽量スコア...', flush=True)
    df = add_light_score(df)
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    p = vh.load_params()
    print(f"  係数: オッズ{p['w'][0]:+.3f} 補正T{p['w'][1]:+.3f} "
          f"末脚{p['w'][2]:+.3f} 血統{p['w'][3]:+.3f} "
          f"combo{p['w'][4]:+.3f} 消去少{p['w'][5]:+.3f} 位置{p['w'][6]:+.3f}")

    pool = df['ninki'] >= POP
    combo_known = df['combo'].notna()
    blood_hi = df['blood_pct'] >= BLOOD_HI
    pos = df['pos_front'] == 1
    combo2 = combo_known & (df['combo'] >= 2)
    sire_roi = df['sire_winroi'] >= 0.80   # 血統回収の粗い代理（CSVにある列）

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }

    print(f'\n対象: {POP}番人気以下  {int(pool.sum()):,}走')
    print('広域網 = VH確率 ≥ recall0.7 しきい値。圏外 = それを下回る穴馬。')
    print('残差 = 実複勝 − 同オッズ帯期待。正=人気以上に来る。\n')

    # 再現率
    print('======== ハンターの捕捉（参考） ========')
    for pname, pm in periods.items():
        sub = df[pool & pm]
        hits = sub['top3'] == 1
        n_hit = int(hits.sum())
        if n_hit == 0:
            print(f'  {pname}: 3着内なし')
            continue
        rec_w = ((hits) & sub['wide']).sum() / n_hit
        rec_e = ((hits) & sub['elite']).sum() / n_hit
        n_w = int(sub['wide'].sum())
        prec_w = sub.loc[sub['wide'], 'top3'].mean() if n_w else 0
        print(f'  {pname}: 3着内{n_hit}頭  広域再現{rec_w:.1%} 精鋭再現{rec_e:.1%}'
              f'  広域n={n_w:,} 広域複{prec_w:.1%}')

    missed = pool & ~df['wide']
    caught = pool & df['wide']

    print('\n======== 圏外に落ちた穴を、combo / 血統 / 位置が拾えるか ========')
    conds = [
        ('圏外 全体（対照）', missed),
        ('広域網に入った穴（対照）', caught),
        ('圏外 × combo≥2', missed & combo2),
        ('圏外 × 血統レース上位30%', missed & blood_hi),
        ('圏外 × 位置前寄り(平均4角≤3)', missed & pos),
        ('圏外 × 血統回収ROI≥80%', missed & sire_roi.fillna(False)),
        ('圏外 × (combo≥2 または 血統上位 または 位置前)',
         missed & (combo2 | blood_hi | pos)),
        ('圏外 × combo既知のみ（2024+・7番以下）', missed & combo_known),
        ('圏外 × combo=0（既知）', missed & combo_known & (df['combo'] == 0)),
        ('圏外 × combo=1（既知）', missed & combo_known & (df['combo'] == 1)),
    ]
    stars = []
    for name, mask in conds:
        row, ok = print_block(name, mask, periods, df, e3)
        if ok and '対照' not in name:
            stars.append(name)

    print('\n======== 見逃し3着内の内訳（確認期間） ========')
    hold = df['period'] == 'holdout'
    miss_hits = df[pool & hold & (df['top3'] == 1) & ~df['wide']]
    print(f'  確認期間の見逃し3着内: {len(miss_hits)}頭')
    if len(miss_hits):
        coverage(miss_hits, 'combo≥2', miss_hits['combo'].ge(2) & miss_hits['combo'].notna())
        coverage(miss_hits, 'combo欠損（測れない）', miss_hits['combo'].isna())
        coverage(miss_hits, '血統レース上位30%', miss_hits['blood_pct'] >= BLOOD_HI)
        coverage(miss_hits, '位置前寄り', miss_hits['pos_front'] == 1)
        any_sig = (
            (miss_hits['combo'].ge(2) & miss_hits['combo'].notna())
            | (miss_hits['blood_pct'] >= BLOOD_HI)
            | (miss_hits['pos_front'] == 1)
        )
        coverage(miss_hits, 'combo/血統/位置のいずれか', any_sig)
        none = ~any_sig
        coverage(miss_hits, '3つとも無し', none)

    print('\n======== まとめ ========')
    if not stars:
        print('圏外に残った combo / 血統 / 位置は、両窓の正残差に届かない。')
        print('ハンターが見逃す穴を、この3つで救済する根拠は今回は出なかった。')
        print('係数がほぼ0なのは「足していない」のではなく、市場・補正Tに吸収済み、に近い。')
    else:
        print('補完候補:')
        for s in stars:
            print(f'  {s}')
        print('スコアの重みはまだ変えない。圏外の救済表示だけ検討。')


if __name__ == '__main__':
    main()
