# -*- coding: utf-8 -*-
"""r=40モデル(簡略一般化モデル)で理論複勝確率を出し、実複勝オッズとの歪みを突けるか検証。

主張(伊藤耕介 2010・JRA-VAN 1995-2001の22,261R):
  単勝支持率から複勝的中確率θを数理的に逆算し、θ×実複勝オッズ>1.0 の馬を買う。
  **単勝支持率20%以上の本命に限定すると複勝回収率102.06%**(的中62.6%/3,267回)。

本スクリプトは 2016-2026 で追試する。元研究の窓(1995-2001)とは完全に別期間なので
純粋なout-of-sample。市場が適応していれば消えるはず。

モデル:
  π_i = 単勝支持率(控除率を戻して正規化)
  λ2=0.81, λ3=0.70  (Lo et al.1995 の r=40 対応値)
  θ_i = π_i
      + Σ_{j≠i} π_j·[π_i^λ2 / Σ_{n≠j} π_n^λ2]
      + Σ_{j≠i} Σ_{k≠i,j} π_j·[π_k^λ2/Σ_{n≠j}π_n^λ2]·[π_i^λ3/Σ_{m≠j,k}π_m^λ3]

⚠必ず置く対照群: 「EVフィルタ無しで単勝支持率20%+の複勝を全部買う」。
  人気馬の複勝はロングショットバイアスで元々ROIが高い可能性があり、
  それを超えなければ**モデルは何も足していない**ことになる。

Usage:
  python scripts/r40_place_model.py
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

LAM2, LAM3 = 0.81, 0.70      # r=40 に対応するパラメータ
TAKEOUT = 0.80               # 単勝払戻率

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def theta_r40(pi):
    """全馬の複勝的中確率θをO(n^2)で計算。pi は合計1に正規化済みの単勝確率。"""
    n = len(pi)
    if n < 4:
        return np.full(n, np.nan)
    a = pi ** LAM2
    b = pi ** LAM3
    Sa, Sb = a.sum(), b.sum()
    da = Sa - a                     # Σ_{n≠j} π_n^λ2  (jごと)
    # 2着項: Σ_{j≠i} π_j · a_i/da_j
    t2 = a * ((pi / da).sum() - pi / da)
    # 3着項: b_i · [ ΣΣ M[j,k] - Σ_j M[j,i] - Σ_k M[i,k] ]
    #   M[j,k] = π_j·a_k/da_j / (Sb - b_j - b_k)   (j≠k)
    denom = Sb - b[:, None] - b[None, :]
    with np.errstate(divide='ignore', invalid='ignore'):
        M = (pi[:, None] * a[None, :] / da[:, None]) / denom
    np.fill_diagonal(M, 0.0)
    M[~np.isfinite(M)] = 0.0
    total = M.sum()
    col = M.sum(axis=0)             # Σ_j M[j,i]
    row = M.sum(axis=1)             # Σ_k M[i,k]
    t3 = b * (total - col - row)
    return np.clip(pi + t2 + t3, 0, 1)


def load():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    po = pd.read_sql(
        "SELECT race_key, combo, odds AS pl_min, odds_max AS pl_max "
        "FROM odds WHERE bet_type='place'", con)
    pay = pd.read_sql(
        "SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'", con)
    con.close()
    po['umaban'] = pd.to_numeric(po['combo'], errors='coerce')
    po = po.drop(columns='combo').dropna(subset=['umaban'])
    pay['umaban'] = pd.to_numeric(pay['combo'], errors='coerce')
    pay = pay.drop(columns='combo').dropna(subset=['umaban'])
    pay = pay.rename(columns={'payout': 'pl_payout'})

    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki',
                             'win_odds', 'chakujun'])
    h['race_key'] = h['race_key'].astype(str)
    for x in (po, pay):
        x['race_key'] = x['race_key'].astype(str)
    h = h.merge(po, on=['race_key', 'umaban'], how='inner')
    h = h.merge(pay, on=['race_key', 'umaban'], how='left')
    h['pl_payout'] = h['pl_payout'].fillna(0.0)
    return h


def main():
    print('読込中...', file=sys.stderr)
    h = load()
    h = h[(h['win_odds'] > 0) & (h['pl_min'] > 0) & (h['chakujun'] > 0)]
    print(f'突合できた {len(h):,}頭 / {h["race_key"].nunique():,}レース', file=sys.stderr)

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        n = len(g)
        if n < 8:
            continue
        raw = TAKEOUT / g['win_odds'].to_numpy()
        pi = raw / raw.sum()                    # 正規化した単勝支持率
        th = theta_r40(pi)
        if not np.isfinite(th).all():
            continue
        out.append(pd.DataFrame({
            'race_key': rk, 'day': g['day'].to_numpy(),
            'umaban': g['umaban'].to_numpy(), 'ninki': g['ninki'].to_numpy(),
            'pi': pi, 'theta': th,
            'pl_min': g['pl_min'].to_numpy(), 'pl_max': g['pl_max'].to_numpy(),
            'pl_payout': g['pl_payout'].to_numpy(),
            'top3': (g['chakujun'].to_numpy() <= 3).astype(int),
        }))
    d = pd.concat(out, ignore_index=True)
    d['year'] = d['day'].astype(str).str[:4].astype(int)
    d['pl_mid'] = np.where(d['pl_max'].notna(),
                           (d['pl_min'] + d['pl_max']) / 2, d['pl_min'])
    d['ev_min'] = d['theta'] * d['pl_min']
    d['ev_mid'] = d['theta'] * d['pl_mid']

    print(f'\n対象 {len(d):,}頭 / {d["race_key"].nunique():,}レース '
          f'({d["year"].min()}〜{d["year"].max()})')

    # モデルの当てはまり(θの較正)を先に確認する
    print('\n■ まずモデルの精度: 理論θと実際の3着内率が合っているか')
    print(f'{"理論θ":14s}{"n":>9}{"実際の3着内率":>14}{"差":>9}')
    print('-' * 48)
    for lo in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        s = d[(d['theta'] >= lo) & (d['theta'] < lo + 0.1)]
        if len(s) < 500:
            continue
        act = s['top3'].mean() * 100
        print(f'{lo:.1f}-{lo+0.1:<10.1f}{len(s):>9,}{act:>13.1f}%'
              f'{act - s["theta"].mean()*100:>+9.1f}')

    def roi(sub, name):
        if len(sub) < 200:
            print(f'{name:42s}{"標本不足":>10}')
            return
        r = sub['pl_payout'].sum() / (len(sub) * 100) * 100
        print(f'{name:42s}{len(sub):>9,}{sub["top3"].mean()*100:>8.1f}%{r:>8.1f}%')

    print('\n■ 複勝の買い方別 実回収率（実配当ベース）')
    print(f'{"買い方":42s}{"n":>9}{"的中率":>8}{"回収率":>8}')
    print('-' * 70)
    roi(d, '【対照】全馬の複勝を買う')
    fav = d[d['pi'] >= 0.20]
    roi(fav, '【対照】単勝支持率20%以上を全部買う')
    roi(d[d['ninki'] == 1], '【対照】1番人気を全部買う')
    roi(fav[fav['ev_mid'] > 1.0], '★r40: 支持率20%+ かつ EV(中央値)>1.0')
    roi(fav[fav['ev_min'] > 1.0], '★r40: 支持率20%+ かつ EV(下限)>1.0')
    roi(d[d['ev_mid'] > 1.0], 'r40: 全帯で EV(中央値)>1.0')
    roi(d[(d['ev_min'] > 1.0)], 'r40: 全帯で EV(下限)>1.0')
    roi(fav[fav['ev_mid'] > 1.05], 'r40: 支持率20%+ かつ EV>1.05')
    roi(fav[fav['ev_mid'] > 1.10], 'r40: 支持率20%+ かつ EV>1.10')

    print('\n■ 期間を割って一貫性を見る（支持率20%+ かつ EV(中央値)>1.0）')
    for lo, hi in ((2016, 2019), (2020, 2023), (2024, 2026)):
        s = fav[(fav['ev_mid'] > 1.0) & (fav['year'] >= lo) & (fav['year'] <= hi)]
        if len(s) < 200:
            continue
        r = s['pl_payout'].sum() / (len(s) * 100) * 100
        print(f'  {lo}-{hi}: n={len(s):,}  的中{s["top3"].mean()*100:.1f}%  回収{r:.1f}%')


if __name__ == '__main__':
    main()
