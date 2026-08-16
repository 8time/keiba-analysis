# -*- coding: utf-8 -*-
"""「回収率116%」等の自己申告を、統計的にどこまで信じられるかを計算する。

問い: 実力ゼロ(真のROI=控除率どおり)の人が、N回買って「回収率100%超」に
      **偶然**なる確率はどれくらいか。これが高いなら、公開実績の数字だけでは
      実力の証拠にならない。

方法: 実際の単勝/複勝の払戻分布からブートストラップし、
      真のROIを75-80%(控除率どおり=実力ゼロ)に固定した上で、
      N回の試行でROIが100%を超える確率を数える。

券種で分散が全く違うので、単勝(中穴)・単勝(人気)・複勝(人気)の3つで測る。

Usage:
  python scripts/roi_claim_credibility.py
"""
import os
import sys
import io
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

N_SIM = 20000


def load():
    h = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win_odds', 'chakujun'])
    h = h[(h['win_odds'] > 0) & (h['chakujun'] > 0)].copy()
    # 単勝の払戻(円/100円): 1着ならオッズ×100、それ以外0
    h['win_ret'] = np.where(h['chakujun'] == 1, h['win_odds'] * 100, 0.0)
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    pay = pd.read_sql(
        "SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'", con)
    con.close()
    pay['umaban'] = pd.to_numeric(pay['combo'], errors='coerce')
    pay = pay.drop(columns='combo').dropna(subset=['umaban'])
    h['race_key'] = h['race_key'].astype(str)
    pay['race_key'] = pay['race_key'].astype(str)
    h = h.merge(pay.rename(columns={'payout': 'pl_ret'}),
                on=['race_key', 'umaban'], how='left')
    h['pl_ret'] = h['pl_ret'].fillna(0.0)
    return h


def sim(ret, n_bets, n_sim=N_SIM, seed=1):
    """払戻列からn_bets回ブートストラップし、ROI分布を返す。"""
    rng = np.random.default_rng(seed)
    r = np.asarray(ret, dtype=float)
    idx = rng.integers(0, len(r), size=(n_sim, n_bets))
    return r[idx].mean(axis=1)


def main():
    print('読込中...', file=sys.stderr)
    h = load()

    groups = [
        ('単勝・中穴(6-12番人気)', h[(h['ninki'] >= 6) & (h['ninki'] <= 12)]['win_ret']),
        ('単勝・人気(1-3番人気)', h[h['ninki'] <= 3]['win_ret']),
        ('複勝・人気(1-3番人気)', h[h['ninki'] <= 3]['pl_ret']),
    ]

    print('■ 実力ゼロ（＝控除率どおり）の人が、偶然「回収率100%超」に見える確率')
    print('   ※実際の払戻分布からブートストラップ。真のROIは下段の「真値」欄。')
    print(f'{"券種/帯":26s}{"真値":>7}{"賭け数":>8}{"100%超確率":>11}'
          f'{"ROIの90%範囲":>18}')
    print('-' * 74)
    for name, ret in groups:
        true_roi = float(np.mean(ret))
        for n in (200, 500, 1000, 3000, 10000):
            r = sim(ret, n)
            p = (r >= 100).mean() * 100
            lo, hi = np.percentile(r, 5), np.percentile(r, 95)
            lbl = name if n == 200 else ''
            print(f'{lbl:26s}{true_roi:>6.0f}%{n:>8,}{p:>10.1f}%'
                  f'{f"{lo:.0f}〜{hi:.0f}%":>18}')
        print()

    print('■ 逆に「本当に実力がある人」を見分けるには何回必要か')
    print('   真のROI=105%の人と、真のROI=80%の人を取り違えない賭け数')
    base = h[h['ninki'] <= 3]['pl_ret'].to_numpy()      # 分散が最も小さい複勝で計算
    scaled = base * (105.0 / base.mean())              # 真値105%になるよう調整
    print(f'{"賭け数":>10}{"真105%が100%超を示す率":>24}{"真80%が100%超に見える率":>26}')
    print('-' * 62)
    for n in (200, 500, 1000, 3000, 10000):
        a = (sim(scaled, n, seed=2) >= 100).mean() * 100
        b = (sim(base, n, seed=3) >= 100).mean() * 100
        print(f'{n:>10,}{a:>23.1f}%{b:>25.1f}%')

    print('\n■ 参考: 高配当1本がROIをどれだけ動かすか（単勝・中穴で1,000回買った場合）')
    mid = h[(h['ninki'] >= 6) & (h['ninki'] <= 12)]
    for q in (0.999, 0.9999):
        big = mid['win_ret'].quantile(q)
        print(f'  上位{(1-q)*100:.2f}%の払戻({big:,.0f}円)を1本引くだけで '
              f'ROIが{big/1000/100*100:+.1f}pp動く')


if __name__ == '__main__':
    main()
