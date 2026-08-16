# -*- coding: utf-8 -*-
"""ガラス人気馬(fade・検証済z-8.5)とr40複勝EV(買い・ROI105%)の矛盾を解く。

両者は同じ「人気馬なのに複勝オッズが高い馬」を見ている疑いが濃い:
  ガラス人気馬 : 1-5番人気 × 単勝<10倍 × 実複勝/帯中央値 >= 1.25 → **複勝率残差 z-8.5(fade)**
  r40 EV      : 単勝支持率>=20% × θ×複勝オッズ > 1.10        → **複勝ROI 105.7%(買い)**
  r40が選ぶ馬の複勝中央は1.90倍(対照1.45倍)＝比1.31でガラス閾値1.25を超える。

仮説: **両方とも正しい**。
  「複勝率が市場の単勝評価より低い」(ガラスの主張)ことと、
  「複勝オッズがその低さを上回って高い」(r40の主張)ことは両立する。
  つまり複勝プールが**下げすぎ**ている。
  →ガラス人気馬は『軸から外す』は正しいが『複勝馬券を買わない』は誤りになる。

これを重なりとROIの直接測定で決着させる。

Usage:
  python scripts/glass_vs_r40_overlap.py
"""
import os
import sys
import io
import math
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

import scripts.r40_place_model as R
from core import value_scanner as vs


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
            'race_key': rk, 'day': g['day'].to_numpy(), 'ninki': g['ninki'].to_numpy(),
            'win_odds': g['win_odds'].to_numpy(), 'pi': pi, 'theta': th,
            'pl_min': g['pl_min'].to_numpy(), 'pl_max': g['pl_max'].to_numpy(),
            'pl_payout': g['pl_payout'].to_numpy(),
            'top3': (g['chakujun'].to_numpy() <= 3).astype(int),
        }))
    d = pd.concat(out, ignore_index=True)
    d['year'] = d['day'].astype(str).str[:4].astype(int)
    d['pl_mid'] = np.where(d['pl_max'].notna(),
                           (d['pl_min'] + d['pl_max']) / 2, d['pl_min'])
    d['ev_mid'] = d['theta'] * d['pl_mid']
    # ガラス判定を実装そのままで付与
    gl, gr = [], []
    for w, p, n in zip(d['win_odds'], d['pl_mid'], d['ninki']):
        f, r = vs.glass_favorite_fade(w, p, n)
        gl.append(bool(f))
        gr.append(r if r is not None else np.nan)
    d['glass'] = gl
    d['glass_ratio'] = gr
    return d


def line(name, s):
    if len(s) < 200:
        print(f'{name:38s}{"標本不足":>10}')
        return
    roi = s['pl_payout'].mean()
    hit = s['top3'].mean() * 100
    se = math.sqrt(0.2 * 0.8 / len(s)) * 100
    print(f'{name:38s}{len(s):>9,}{hit:>8.1f}%{roi:>9.1f}%')


def main():
    print('読込中...', file=sys.stderr)
    d = build()
    print(f'対象 {len(d):,}頭\n')

    sel = d[(d['pi'] >= 0.20) & (d['ev_mid'] > 1.10)]
    print('■ ① 重なり: r40が選んだ馬のうちガラス人気馬は何%か')
    print(f'  r40選抜 {len(sel):,}頭 中 ガラス判定 {sel["glass"].sum():,}頭 '
          f'= **{sel["glass"].mean()*100:.1f}%**')
    print(f'  ガラス比の中央値: r40選抜 {sel["glass_ratio"].median():.2f} '
          f'/ 全体 {d["glass_ratio"].median():.2f}  （ガラス閾値=1.25）')

    print('\n■ ② ガラス人気馬そのものの複勝成績（fadeなのか買いなのか）')
    print(f'{"群":38s}{"n":>9}{"的中率":>8}{"複勝ROI":>9}')
    print('-' * 66)
    up = d[(d['ninki'] <= 5) & (d['win_odds'] < 10)]
    line('1-5番人気×単勝10倍未満（母集団）', up)
    line('  └ ガラス該当', up[up['glass']])
    line('  └ ガラス非該当', up[~up['glass']])
    for lo, hi in ((1.25, 1.4), (1.4, 1.6), (1.6, 99)):
        line(f'  └ ガラス比 {lo:.2f}〜{hi if hi<99 else "∞"}',
             up[(up['glass_ratio'] >= lo) & (up['glass_ratio'] < hi)])

    print('\n■ ③ r40の選抜をガラスで割る（どちらが効いているか）')
    print(f'{"群":38s}{"n":>9}{"的中率":>8}{"複勝ROI":>9}')
    print('-' * 66)
    fav = d[d['pi'] >= 0.20]
    line('支持率20%+ 全部', fav)
    line('支持率20%+ × ガラス該当', fav[fav['glass']])
    line('支持率20%+ × EV>1.10', fav[fav['ev_mid'] > 1.10])
    line('支持率20%+ × EV>1.10 × ガラス該当', fav[(fav['ev_mid'] > 1.10) & fav['glass']])
    line('支持率20%+ × EV>1.10 × ガラス非該当',
         fav[(fav['ev_mid'] > 1.10) & ~fav['glass']])
    line('支持率20%+ × ガラス該当 × EV<=1.10',
         fav[fav['glass'] & (fav['ev_mid'] <= 1.10)])

    print('\n■ ④ 複勝率(ガラスの主張)と複勝ROI(r40の主張)は両立するか')
    print('   同じ群で「オッズ統制した複勝率残差」と「ROI」を並べる')
    up = up.copy()
    up['ob'] = pd.qcut(up['win_odds'], 20, labels=False, duplicates='drop')
    exp = up.groupby('ob')['top3'].transform('mean')
    up['resid'] = (up['top3'] - exp) * 100
    print(f'{"群":38s}{"n":>9}{"複勝率残差":>11}{"複勝ROI":>9}')
    print('-' * 68)
    for nm, s in (('ガラス該当', up[up['glass']]),
                  ('ガラス非該当', up[~up['glass']])):
        print(f'{nm:38s}{len(s):>9,}{s["resid"].mean():>+10.2f}pp'
              f'{s["pl_payout"].mean():>9.1f}%')
    print('\n  → 残差がマイナスなのにROIが100%超なら「複勝プールが下げすぎ」が正解。')
    print('    その場合ガラス人気馬は『軸から外す』は正しく『複勝を買わない』は誤り。')


if __name__ == '__main__':
    main()
