# -*- coding: utf-8 -*-
"""r40複勝EVの最後の未検証点を潰す: 締切前オッズでも成立するか。

背景([[verified_r40_place_ev]]):
  複勝EVの検証は jravan.db の**確定オッズ**で行った(ROI 104-111%)。
  しかしライブで見えるのは締切前のオッズ。そのズレは未知だった。

JRDB直前情報(TYB)には **発走約17分前の単勝オッズ・複勝オッズ(下限)** が入っている。
これで「実際に買える時点のオッズ」でr40を回し直す。

測るもの:
  ① 直前オッズ vs 確定オッズ のズレ（単勝・複勝下限）
  ② 直前オッズでθとEVを計算し直した場合のROI（=これが本番の数字）

⚠TYBの複勝は**下限のみ**。上限は確定側(jravan.db odds表)の
  「同じ馬の max/min 比」を使って推定する。ライブのnetkeiba APIは
  min/max両方返す(fetch_place_odds_api)ので、実運用では推定不要。

Usage:
  python scripts/r40_live_odds_check.py
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

from scripts import jrdb_tyb
from core import jockey_jv as jj
from core import r40_place as r4

# ⚠jrdb_tyb がインポート時に sys.stdout を差し替える。
#   ここで再度包むと元のラッパが閉じられて以降書けなくなるので何もしない。


def load_jv():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    races = pd.read_sql(
        "SELECT race_key, year||monthday AS day, jyo, race_num "
        "FROM races WHERE CAST(year AS INTEGER)=2025", con)
    res = pd.read_sql(
        "SELECT race_key, umaban, ninki, win_odds, chakujun FROM results "
        "WHERE chakujun>0", con)
    po = pd.read_sql(
        "SELECT race_key, combo, odds AS f_pmin, odds_max AS f_pmax "
        "FROM odds WHERE bet_type='place'", con)
    pay = pd.read_sql(
        "SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'", con)
    con.close()
    for x in (po, pay):
        x['umaban'] = pd.to_numeric(x['combo'], errors='coerce')
        x.drop(columns='combo', inplace=True)
    pay.rename(columns={'payout': 'pl_payout'}, inplace=True)
    res['umaban'] = pd.to_numeric(res['umaban'], errors='coerce')
    d = (res.merge(races, on='race_key')
            .merge(po, on=['race_key', 'umaban'], how='left')
            .merge(pay, on=['race_key', 'umaban'], how='left'))
    d['pl_payout'] = d['pl_payout'].fillna(0.0)
    return d


def main():
    print('TYB読込中...', file=sys.stderr)
    t = jrdb_tyb.load_all()
    t = t[(t['cancel'] != '1') & t['win_odds'].notna()].copy()
    t['race_num'] = t['r'].astype('Int64')
    t['umaban'] = t['umaban'].astype('Int64')
    print(f'TYB {len(t):,}行', file=sys.stderr)

    print('jravan読込中...', file=sys.stderr)
    j = load_jv()
    j['race_num'] = j['race_num'].astype('Int64')
    j['umaban'] = j['umaban'].astype('Int64')

    m = t.merge(j, on=['day', 'jyo', 'race_num', 'umaban'], how='inner',
                suffixes=('_live', '_final'))
    print(f'\n突合 {len(m):,}頭 / {m["race_key"].nunique():,}レース')
    print(f'（TYB {len(t):,}行のうち {len(m)/len(t)*100:.1f}% が確定データと一致）\n')

    ok = m[(m['win_odds_live'] > 0) & (m['win_odds_final'] > 0) &
           (m['place_odds_min'] > 0) & m['f_pmin'].notna()].copy()

    # ── ① オッズのズレ ──
    ok['w_ratio'] = ok['win_odds_final'] / ok['win_odds_live']
    ok['p_ratio'] = ok['f_pmin'] / ok['place_odds_min']
    print('■ ① 直前(約17分前) → 確定 のオッズ変化')
    print(f'{"":22s}{"中央値":>9}{"平均":>9}{"±5%内":>9}{"±10%内":>9}')
    print('-' * 60)
    for lbl, c in (('単勝オッズ 確定/直前', 'w_ratio'),
                   ('複勝下限  確定/直前', 'p_ratio')):
        s = ok[c].replace([np.inf, -np.inf], np.nan).dropna()
        print(f'{lbl:22s}{s.median():>9.3f}{s.mean():>9.3f}'
              f'{((s-1).abs()<=0.05).mean()*100:>8.1f}%'
              f'{((s-1).abs()<=0.10).mean()*100:>8.1f}%')

    fav = ok[ok['ninki'] <= 3]
    print('\n  人気上位(1-3番人気)に限ると:')
    for lbl, c in (('単勝', 'w_ratio'), ('複勝下限', 'p_ratio')):
        s = fav[c].replace([np.inf, -np.inf], np.nan).dropna()
        print(f'    {lbl:10s} 中央{s.median():.3f} / ±5%内 {((s-1).abs()<=0.05).mean()*100:.1f}%'
              f' / ±10%内 {((s-1).abs()<=0.10).mean()*100:.1f}%')

    # ── ② 直前オッズでr40を回し直す ──
    print('\n■ ② 直前オッズでθとEVを計算し直した場合のROI')
    # 複勝上限の推定: 確定側の max/min 比の中央値を下限帯ごとに使う
    ok['pmax_ratio'] = ok['f_pmax'] / ok['f_pmin']
    ok['pb'] = pd.cut(ok['place_odds_min'], [0, 1.2, 1.5, 2, 3, 5, 10, 1e9],
                      labels=False)
    rmap = ok.groupby('pb')['pmax_ratio'].median()
    ok['est_pmax'] = ok['place_odds_min'] * ok['pb'].map(rmap)

    rows = []
    for rk, g in ok.groupby('race_key', sort=False):
        if len(g) < 8:
            continue
        # 3つ目は切り分け用: 単勝だけ直前・複勝は確定
        # → 崩れるなら「単勝の変動」が原因、崩れないなら「複勝の変動」が原因
        for src, wcol, pmin_col, pmax_col in (
                ('確定', 'win_odds_final', 'f_pmin', 'f_pmax'),
                ('直前', 'win_odds_live', 'place_odds_min', 'est_pmax'),
                ('単直前+複確定', 'win_odds_live', 'f_pmin', 'f_pmax'),
                ('単確定+複直前', 'win_odds_final', 'place_odds_min', 'est_pmax')):
            th, pi = r4.theta_r40(g[wcol].tolist())
            if th is None:
                continue
            eo = [r4.expected_place_odds(a, b)
                  for a, b in zip(g[pmin_col], g[pmax_col])]
            for i, (_, row) in enumerate(g.iterrows()):
                if eo[i] is None:
                    continue
                rows.append({'src': src, 'pi': pi[i], 'theta': th[i],
                             'ev': th[i] * eo[i], 'pay': row['pl_payout'],
                             'top3': int(row['chakujun'] <= 3)})
    d = pd.DataFrame(rows)

    print(f'{"オッズ源":10s}{"閾値":>8}{"n":>8}{"的中率":>8}{"回収率":>9}')
    print('-' * 48)
    for src in ('確定', '直前', '単直前+複確定', '単確定+複直前'):
        s0 = d[(d['src'] == src) & (d['pi'] >= r4.PI_MIN)]
        for th in (1.00, 1.02, 1.05):
            s = s0[s0['ev'] > th]
            if len(s) < 30:
                continue
            print(f'{src:10s}{th:>8.2f}{len(s):>8,}{s["top3"].mean()*100:>7.1f}%'
                  f'{s["pay"].mean():>8.1f}%')
        print()

    print('※2025年の1年分のみ。母数が小さいので水準より「確定と直前で大きく変わらないか」を見る。')


if __name__ == '__main__':
    main()
