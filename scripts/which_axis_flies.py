# -*- coding: utf-8 -*-
"""「軸2頭のうちどちらが飛ぶか」をガラス人気馬/消去クロスで当てられるか。

背景: ◎〇固定4点の天井は「人気1・2が**両方**3着内」=32%。
      片方だけ飛ぶケースが多いので、**どちらが飛ぶか**が事前に分かれば
      飛ぶ側を軸から外して1頭軸にでき、命中率が上がるはず。

検証の的を絞る:
  人気1と人気2のうち**ちょうど1頭だけ**が3着内に入ったレースに限定し、
  「飛んだのはどちらか」を50%より高い精度で当てられる指標があるかを見る。
  ここが50%なら、どんな買い方の工夫も効かない(情報が無い)。

指標:
  glass   … ガラス人気馬 = 単勝人気が上位なのに複勝オッズが割高
            (core/value_scanner.glass_favorite_fade と同じ発想を過去odds表で再現)
            比率 = 実複勝オッズ中央値 / 単勝オッズから期待される複勝オッズ
  p_gap   … 単勝オッズ差(人気1と2の開き)
  ability … アプリのRank(ability_score・小さいほど強い)

⚠複勝オッズはjravan.dbのodds表(bet_type='place')に11.4万レース分ある。
  odds=下限/odds_max=上限なので中央値を使う。**確定オッズ**なので当日の
  最終オッズ相当(ライブの締切前オッズとは厳密には別物)。

Usage:
  python scripts/which_axis_flies.py
"""
import os
import sys
import io
import sqlite3
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def load_place_odds():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    df = pd.read_sql(
        "SELECT race_key, combo, odds, odds_max FROM odds WHERE bet_type='place'", con)
    con.close()
    df['umaban'] = pd.to_numeric(df['combo'], errors='coerce')
    df['place_mid'] = np.where(df['odds_max'].notna(),
                               (df['odds'] + df['odds_max']) / 2, df['odds'])
    return df[['race_key', 'umaban', 'place_mid']].dropna()


def main():
    print('読込中...', file=sys.stderr)
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score'])
    h['race_key'] = h['race_key'].astype(str)
    po = load_place_odds()
    po['race_key'] = po['race_key'].astype(str)
    h = h.merge(po, on=['race_key', 'umaban'], how='left')
    cov = h['place_mid'].notna().mean() * 100
    print(f'複勝オッズの被覆率: {cov:.1f}%')

    # 単勝オッズから期待される複勝オッズの基準線(帯ごとの中央値)を作る
    ok = h[h['place_mid'].notna() & (h['win_odds'] > 0)].copy()
    ok['ob'] = pd.qcut(ok['win_odds'], 40, labels=False, duplicates='drop')
    base = ok.groupby('ob')['place_mid'].median()
    ok['exp_place'] = ok['ob'].map(base)
    # glass比 >1 = 単勝の人気に対して複勝が割高(=買われていない)＝ガラス
    ok['glass'] = ok['place_mid'] / ok['exp_place']

    rows = []
    for rk, g in ok.groupby('race_key', sort=False):
        if len(g) < 8:
            continue
        try:
            a = g[g['ninki'] == 1].iloc[0]
            b = g[g['ninki'] == 2].iloc[0]
        except Exception:
            continue
        ia, ib = int(a['chakujun']) <= 3, int(b['chakujun']) <= 3
        if ia == ib:
            continue                       # 両方来た/両方飛んだ は対象外
        rows.append({
            'rk': rk, 'year': int(str(g['day'].iloc[0])[:4]),
            'flew_is_fav1': int(not ia),   # 飛んだのが人気1か
            'glass_1': a['glass'], 'glass_2': b['glass'],
            'odds_1': a['win_odds'], 'odds_2': b['win_odds'],
            'ab_1': a['ability_score'], 'ab_2': b['ability_score'],
        })
    d = pd.DataFrame(rows)
    print(f'\n「人気1・2のうちちょうど1頭だけ3着内」= {len(d):,}レース')
    print(f'  そのうち飛んだのが人気1: {d["flew_is_fav1"].mean()*100:.1f}%'
          f' / 人気2: {(1-d["flew_is_fav1"]).mean()*100:.1f}%')
    print('  ← ここが基準。指標がこれを超えなければ「どちらが飛ぶか」は当てられない。\n')

    # ⚠基準は50%ではない。「常に人気2が飛ぶ」と言うだけで62.2%当たる。
    #   指標はこの素朴な基準を**同じ母集団で**超えて初めて価値がある。
    NAIVE = (1 - d['flew_is_fav1']).mean()

    def rule(name, pred, sub=None):
        """pred: 1なら『人気1が飛ぶ』と予想。NaNは判定を出さない(見送り)。"""
        s = d if sub is None else sub
        p = pd.Series(np.asarray(pred(s), dtype=float), index=s.index)
        use = p.notna()
        if use.sum() < 200:
            print(f'{name:34s}{"標本不足":>10}')
            return
        ss = s.loc[use]
        acc = (p[use] == ss['flew_is_fav1']).mean() * 100
        # 同じ部分集合での素朴基準(常に人気2が飛ぶ)
        nv = (1 - ss['flew_is_fav1']).mean() * 100
        n = int(use.sum())
        se = math.sqrt(0.25 / n) * 100
        z = (acc - nv) / se
        star = '★' if z >= 2 else ''
        print(f'{name:34s}{n:>9,}{acc:>9.1f}%{nv:>9.1f}%{z:>+8.2f}  {star}')

    print(f'{"判定ルール":34s}{"n":>9}{"的中率":>9}{"素朴基準":>9}{"z(差)":>8}')
    print('-' * 74)
    rule('ガラス比が高い方が飛ぶ', lambda s: (s['glass_1'] > s['glass_2']).astype(float))
    rule('ガラス比の差が10%以上ある時だけ',
         lambda s: np.where((s['glass_1'] / s['glass_2'] > 1.10), 1.0,
                            np.where((s['glass_2'] / s['glass_1'] > 1.10), 0.0, np.nan)))
    rule('ガラス比の差が20%以上ある時だけ',
         lambda s: np.where((s['glass_1'] / s['glass_2'] > 1.20), 1.0,
                            np.where((s['glass_2'] / s['glass_1'] > 1.20), 0.0, np.nan)))
    rule('【比較】アプリRankが下の方が飛ぶ',
         lambda s: (s['ab_1'] > s['ab_2']).astype(float))
    rule("【比較】常に人気2が飛ぶと言う",
         lambda s: pd.Series(0.0, index=s.index))
    rule('【比較】オッズ差2倍以上なら人気2が飛ぶ',
         lambda s: np.where(s['odds_2'] / s['odds_1'] >= 2.0, 0.0, np.nan))

    print('\n■ 年窓を分けて一貫性を見る（ガラス比が高い方が飛ぶ）')
    for lo, hi in ((2016, 2020), (2021, 2024), (2025, 2026)):
        sub = d[(d['year'] >= lo) & (d['year'] <= hi)]
        if len(sub) < 500:
            continue
        acc = ((sub['glass_1'] > sub['glass_2']).astype(float)
               == sub['flew_is_fav1']).mean() * 100
        se = math.sqrt(0.25 / len(sub)) * 100
        print(f'  {lo}-{hi}: n={len(sub):,}  的中{acc:.1f}%  z={(acc-50)/se:+.2f}')


if __name__ == '__main__':
    main()
