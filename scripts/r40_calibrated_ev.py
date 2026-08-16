# -*- coding: utf-8 -*-
"""複勝EVを「実際の着地位置」で較正し直して、r40フィルタが本物か決着させる。

前段の発見(scripts/place_range_landing.py):
  複勝の実配当はレンジの**平均0.22の位置**にしか着地しない(中央値0.03)。
  なのに EV を中央値(=位置0.5)で計算していた＝**EVを体系的に過大評価**していた。
  → EV>1.10 で選ばれていたのは「レンジが広い(上限が高い)馬」で、
     モデルの実力ではなく較正ミスを拾っていただけの可能性がある。

そこで期待複勝オッズを
    exp_odds = pl_min + POS × (pl_max - pl_min)
として、POS を実測値(全体0.318 / 支持率20%+では0.305)に置き換えた
**較正済みEV**で選び直し、ROIが維持されるかを見る。

較正版の方が良ければ「モデルが効いている」。
較正すると崩れるなら「元の結果は較正ミスの副産物」＝棄却。

Usage:
  python scripts/r40_calibrated_ev.py
"""
import os
import sys
import io
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

import scripts.r40_place_model as R

# 実測の平均着地位置。学習窓(2016-2021)だけで決めて、評価窓(2022-2026)に適用する
FIT_END = 2021


def build():
    h = R.load()
    h = h[(h['win_odds'] > 0) & (h['pl_min'] > 0) & (h['chakujun'] > 0)]
    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < 8:
            continue
        raw = R.TAKEOUT / g['win_odds'].to_numpy()
        pi = raw / raw.sum()
        th = R.theta_r40(pi)
        if not np.isfinite(th).all():
            continue
        out.append(pd.DataFrame({
            'day': g['day'].to_numpy(), 'ninki': g['ninki'].to_numpy(),
            'pi': pi, 'theta': th,
            'pl_min': g['pl_min'].to_numpy(), 'pl_max': g['pl_max'].to_numpy(),
            'pl_payout': g['pl_payout'].to_numpy(),
            'top3': (g['chakujun'].to_numpy() <= 3).astype(int),
        }))
    d = pd.concat(out, ignore_index=True)
    d['year'] = d['day'].astype(str).str[:4].astype(int)
    d['pl_max'] = d['pl_max'].fillna(d['pl_min'])
    d['rng'] = (d['pl_max'] - d['pl_min']).clip(lower=0)
    d['pl_mid'] = (d['pl_min'] + d['pl_max']) / 2
    return d


def boot(s, n_boot=4000, seed=9):
    rng = np.random.default_rng(seed)
    p = s['pl_payout'].to_numpy()
    if len(p) < 100:
        return (np.nan, np.nan)
    idx = rng.integers(0, len(p), size=(n_boot, len(p)))
    r = p[idx].mean(axis=1)
    return float(np.percentile(r, 5)), float(np.percentile(r, 95))


def main():
    print('読込中...', file=sys.stderr)
    d = build()
    fav = d[d['pi'] >= 0.20].copy()

    # ── 着地位置を学習窓だけで推定（評価窓に情報を漏らさない）──
    tr = fav[(fav['year'] <= FIT_END) & (fav['top3'] == 1) & (fav['rng'] > 0)]
    POS = float(((tr['pl_payout'] / 100 - tr['pl_min']) / tr['rng']).clip(0, 1).mean())
    print(f'学習窓(〜{FIT_END})で推定した平均着地位置: {POS:.3f}')
    print(f'（中央値を使う＝0.500 と仮定していたのが過大評価の正体）\n')

    fav['exp_odds'] = fav['pl_min'] + POS * fav['rng']
    fav['ev_cal'] = fav['theta'] * fav['exp_odds']       # 較正済みEV
    fav['ev_mid'] = fav['theta'] * fav['pl_mid']         # 元のEV
    fav['ev_min'] = fav['theta'] * fav['pl_min']         # 最保守EV

    ev_win = fav[fav['year'] > FIT_END]                  # 評価窓のみ

    def line(name, s):
        if len(s) < 150:
            print(f'{name:38s}{len(s):>8,}{"標本不足":>28}')
            return
        lo, hi = boot(s)
        print(f'{name:38s}{len(s):>8,}{s["top3"].mean()*100:>8.1f}%'
              f'{s["pl_payout"].mean():>9.1f}%{f"{lo:.0f}〜{hi:.0f}%":>16}')

    print(f'■ 評価窓 {FIT_END+1}-2026 のみ（着地位置は学習窓で決定済み）')
    print(f'{"買い方":38s}{"n":>8}{"的中率":>8}{"回収率":>9}{"90%CI":>16}')
    print('-' * 82)
    line('【対照】支持率20%+ 全部', ev_win)
    for t in (1.00, 1.05, 1.10, 1.20):
        line(f'元のEV(中央値) > {t:.2f}', ev_win[ev_win['ev_mid'] > t])
    print()
    for t in (0.95, 1.00, 1.02, 1.05):
        line(f'★較正EV(位置{POS:.2f}) > {t:.2f}', ev_win[ev_win['ev_cal'] > t])
    print()
    for t in (0.90, 1.00):
        line(f'最保守EV(下限) > {t:.2f}', ev_win[ev_win['ev_min'] > t])

    print('\n■ 較正EVで選んだ馬の着地位置は偏っていないか')
    w = ev_win[(ev_win['top3'] == 1) & (ev_win['rng'] > 0)].copy()
    w['pos'] = ((w['pl_payout'] / 100 - w['pl_min']) / w['rng']).clip(0, 1)
    for nm, s in (('較正EV>1.00', w[w['ev_cal'] > 1.00]),
                  ('元のEV>1.10', w[w['ev_mid'] > 1.10]),
                  ('対照(支持率20%+全部)', w)):
        if len(s) >= 100:
            print(f'  {nm:24s} n={len(s):>6,}  平均位置 {s["pos"].mean():.3f}')

    print('\n■ 較正EVでの年別（閾値1.00）')
    s0 = ev_win[ev_win['ev_cal'] > 1.00]
    for y in sorted(s0['year'].unique()):
        s = s0[s0['year'] == y]
        if len(s) < 30:
            continue
        print(f'  {y}: n={len(s):>4,}  的中{s["top3"].mean()*100:>5.1f}%  '
              f'回収{s["pl_payout"].mean():>6.1f}%')


if __name__ == '__main__':
    main()
