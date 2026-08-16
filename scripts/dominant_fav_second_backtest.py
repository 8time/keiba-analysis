# -*- coding: utf-8 -*-
"""『圧倒的1番人気がいる時の2番手』を詰めて検証する。

scripts/odds_structure_hunt.py で最大の残差(+7.5/+9.4pp・z+12.7/+6.5)が出た仮説。
実用に足るか(絶対複勝率・ROI・本命の強さ別・頭数別)を確かめ、
『買える』のか『軸信頼度の表示止まり』なのかを決める。

⚠単勝は市場効率的(全条件でプラス圏なし)と検証済みなので、
  ROIが100%を超えないなら"買い"ではなく"相手の質"の情報として扱う。

Usage:
  python scripts/dominant_fav_second_backtest.py
"""
import os
import sys
import io
import math
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from core import jockey_jv as jj


def load():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    df = pd.read_sql("""
        SELECT r.race_key, r.umaban, r.chakujun, r.ninki, r.win_odds, ra.year, ra.shusso_tosu
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE CAST(ra.year AS INTEGER) >= 2016
          AND r.chakujun > 0 AND r.ninki > 0 AND r.win_odds > 0
    """, con)
    con.close()
    df = df.sort_values(['race_key', 'win_odds'])
    g = df.groupby('race_key', sort=False)
    df['rank_o'] = g.cumcount() + 1
    df['fav_odds'] = g['win_odds'].transform('first')
    df['field'] = g['win_odds'].transform('size')
    df['ob'] = pd.qcut(df['win_odds'], 20, labels=False, duplicates='drop')
    df['exp'] = df['ob'].map(df.groupby('ob')['chakujun'].apply(lambda s: (s <= 3).mean()))
    return df


def stat(sub):
    n = len(sub)
    if n < 200:
        return None
    act = (sub['chakujun'] <= 3).mean()
    exp = sub['exp'].mean()
    r = (act - exp) * 100
    se = math.sqrt(max(exp * (1 - exp), 1e-9) / n) * 100
    roi = sub.loc[sub['chakujun'] == 1, 'win_odds'].sum() / n * 100
    return {'n': n, 'act': act * 100, 'r': r, 'z': r / se if se else 0,
            'roi': roi, 'odds': sub['win_odds'].median()}


def show(title, rows):
    print(f'\n■ {title}')
    print(f'{"条件":18s}{"n":>8}{"複勝率":>8}{"残差":>8}{"z":>7}{"単ROI":>8}{"中央オッズ":>9}')
    print('-' * 68)
    for lbl, s in rows:
        if not s:
            print(f'{lbl:18s}{"標本不足":>8}')
            continue
        print(f'{lbl:18s}{s["n"]:>8,}{s["act"]:>7.1f}%{s["r"]:>+8.2f}{s["z"]:>7.1f}'
              f'{s["roi"]:>7.0f}%{s["odds"]:>9.1f}')


def main():
    print('読込中...', file=sys.stderr)
    df = load()
    yi = df['year'].astype(int)
    tr, ho = df[yi <= 2024], df[yi >= 2025]

    sec = df[df['rank_o'] == 2]
    sec_tr, sec_ho = sec[sec['year'].astype(int) <= 2024], sec[sec['year'].astype(int) >= 2025]

    # 本命の強さ別
    bands = [('本命 〜1.5倍', 0, 1.5), ('本命 1.5-2.0倍', 1.5, 2.0),
             ('本命 2.0-2.5倍', 2.0, 2.5), ('本命 2.5-3.5倍', 2.5, 3.5),
             ('本命 3.5倍〜', 3.5, 999)]
    show('2番手の成績を「本命の強さ」で分ける（train ≤2024）',
         [(l, stat(sec_tr[(sec_tr['fav_odds'] >= lo) & (sec_tr['fav_odds'] < hi)]))
          for l, lo, hi in bands])
    show('同（holdout 2025+）',
         [(l, stat(sec_ho[(sec_ho['fav_odds'] >= lo) & (sec_ho['fav_odds'] < hi)]))
          for l, lo, hi in bands])

    # 1倍台本命に限定して頭数別
    d_tr = sec_tr[sec_tr['fav_odds'] < 2.0]
    d_ho = sec_ho[sec_ho['fav_odds'] < 2.0]
    fb = [('〜9頭', 5, 9), ('10-13頭', 10, 13), ('14頭〜', 14, 99)]
    show('1倍台本命×2番手を頭数で分ける（train）',
         [(l, stat(d_tr[(d_tr['field'] >= lo) & (d_tr['field'] <= hi)])) for l, lo, hi in fb])
    show('同（holdout）',
         [(l, stat(d_ho[(d_ho['field'] >= lo) & (d_ho['field'] <= hi)])) for l, lo, hi in fb])

    # 3番手以降にも同じ現象があるか(＝2番手固有か)
    show('1倍台本命がいる時の各順位（holdout）',
         [(f'{k}番手', stat(ho[(ho['rank_o'] == k) & (ho['fav_odds'] < 2.0)]))
          for k in (2, 3, 4, 5)])

    # 本命自身はどうか(圧倒的本命は買えるのか)
    show('圧倒的本命(1倍台)自身（holdout）',
         [('本命1倍台', stat(ho[(ho['rank_o'] == 1) & (ho['fav_odds'] < 2.0)])),
          ('本命2倍台', stat(ho[(ho['rank_o'] == 1) & (ho['fav_odds'] >= 2.0)
                             & (ho['fav_odds'] < 3.0)]))])

    print('\n※単ROIが100%未満なら「買い」ではなく相手の質/軸信頼度の情報として使うこと。')


if __name__ == '__main__':
    main()
