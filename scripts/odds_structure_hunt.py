# -*- coding: utf-8 -*-
"""オッズ構造から未検証の仮説をまとめて検証する(断層の続き)。

背景: 既に検証済み/実装済みなのは
  ・断層直上(odds_gap_anchors +3.9pp) ・断層直下(-5.1pp) ・エントロピー(荒れ予報)
  ・単複乖離(ガラス人気馬) ・1番人気オッズ水準 ・100倍超の構造的不利
オッズ変動(賢い金)は odds_history.db が91レース分しか無く現状は検証不能。
そこで**確定オッズの構造**から残っている仮説を一気に潰す。

測り方(重要): 自分のオッズ帯(20分位)で期待複勝率を作り、その残差を見る。
  こうすると「オッズ水準そのもの」の効果が抜け、**レース内での位置関係**だけが残る。
  train(≤2024)/holdout(2025+)の両窓で符号と有意性が揃うものだけ採用。

Usage:
  python scripts/odds_structure_hunt.py
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
        SELECT r.race_key, r.umaban, r.chakujun, r.ninki, r.win_odds, ra.year
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE CAST(ra.year AS INTEGER) >= 2016
          AND r.chakujun > 0 AND r.ninki > 0 AND r.win_odds > 0
    """, con)
    con.close()
    return df


def add_structure(df):
    """レース内のオッズ並びから位置関係の特徴を作る。"""
    df = df.sort_values(['race_key', 'win_odds'])
    g = df.groupby('race_key', sort=False)
    df['rank_o'] = g.cumcount() + 1          # オッズ昇順の順位
    df['field'] = g['win_odds'].transform('size')
    nxt = g['win_odds'].shift(-1)            # 1つ上のオッズ(=人気が1つ下)
    prv = g['win_odds'].shift(1)             # 1つ下のオッズ(=人気が1つ上)
    df['gap_below'] = nxt / df['win_odds']   # 自分の直下との開き(大=自分が断層の直上)
    df['gap_above'] = df['win_odds'] / prv   # 自分の直上との開き(大=自分が断層の直下)

    f = {}
    # ① 断層の直上(既存odds_gap_anchorsの一般化)。深さでグラデーションを付けられるか
    f['断層直上 1.3倍以上'] = df['gap_below'] >= 1.3
    f['断層直上 1.5倍以上'] = df['gap_below'] >= 1.5
    f['断層直上 2.0倍以上'] = df['gap_below'] >= 2.0
    # ② 断層の直下(既存: 市場が見放した側)
    f['断層直下 1.5倍以上'] = df['gap_above'] >= 1.5
    # ③ 横並び(自分の上下どちらとも僅差=集団の中に埋もれている)
    f['横並び(上下とも1.1未満)'] = (df['gap_below'] < 1.1) & (df['gap_above'] < 1.1)
    # ④ 心理的節目(1桁→2桁のまたぎ・9倍台と10倍台)
    f['9倍台'] = (df['win_odds'] >= 9.0) & (df['win_odds'] < 10.0)
    f['10倍台前半'] = (df['win_odds'] >= 10.0) & (df['win_odds'] < 11.0)
    # ⑤ 単勝1倍台(圧倒的本命)の直後にいる2番手
    _fav_odds = g['win_odds'].transform('first')
    f['1倍台本命の2番手'] = (df['rank_o'] == 2) & (_fav_odds < 2.0)
    # ⑥ 最下位人気から2番目(最低人気だけ極端に売れ残る現象の隣)
    f['ブービー人気'] = df['rank_o'] == (df['field'] - 1)
    for k, v in f.items():
        df[k] = v.fillna(False)
    return df, list(f.keys())


def resid(sub):
    n = len(sub)
    if n < 300:
        return None
    act = (sub['chakujun'] <= 3).mean()
    exp = sub['exp'].mean()
    r = (act - exp) * 100
    se = math.sqrt(max(exp * (1 - exp), 1e-9) / n) * 100
    return {'n': n, 'act': act * 100, 'r': r, 'z': r / se if se else 0}


def main():
    print('読込中...', file=sys.stderr)
    df = load()
    df, flags = add_structure(df)
    # 自分のオッズ帯で期待複勝率(=オッズ水準の効果を抜く)
    df['ob'] = pd.qcut(df['win_odds'], 20, labels=False, duplicates='drop')
    df['exp'] = df['ob'].map(df.groupby('ob')['chakujun'].apply(lambda s: (s <= 3).mean()))

    yi = df['year'].astype(int)
    tr, ho = df[yi <= 2024], df[yi >= 2025]
    print(f'全体 train {len(tr):,} / holdout {len(ho):,}\n')
    print('■ オッズ構造シグナル（オッズ水準を統制した複勝残差）')
    print(f'{"シグナル":24s}{"train n":>10}{"残差":>8}{"z":>7} │{"holdout n":>11}{"残差":>8}{"z":>7}  判定')
    print('-' * 96)
    keep = []
    for k in flags:
        a, b = resid(tr[tr[k]]), resid(ho[ho[k]])
        if not a or not b:
            print(f'{k:24s}{"標本不足":>10}')
            continue
        same = (a['r'] > 0) == (b['r'] > 0)
        strong = abs(a['z']) >= 2 and abs(b['z']) >= 2 and same
        v = '★両窓で有効' if strong else ('△片窓' if abs(a['z']) >= 2 or abs(b['z']) >= 2 else '✗なし')
        if strong:
            keep.append(k)
        print(f'{k:24s}{a["n"]:>10,}{a["r"]:>+8.2f}{a["z"]:>7.1f} │'
              f'{b["n"]:>11,}{b["r"]:>+8.2f}{b["z"]:>7.1f}  {v}')

    print(f'\n両窓で残ったもの: {keep if keep else "なし"}')

    # 断層直上は人気帯で効き方が違う可能性があるので分解する
    print('\n■ 断層直上(1.5倍以上)を人気帯で分解')
    print(f'{"人気帯":12s}{"train n":>10}{"残差":>8}{"z":>7} │{"holdout n":>11}{"残差":>8}{"z":>7}')
    print('-' * 66)
    for lbl, lo, hi in [('1-3番人気', 1, 3), ('4-7番人気', 4, 7),
                        ('8-12番人気', 8, 12), ('13番人気〜', 13, 99)]:
        m_tr = tr[(tr['断層直上 1.5倍以上']) & (tr['ninki'] >= lo) & (tr['ninki'] <= hi)]
        m_ho = ho[(ho['断層直上 1.5倍以上']) & (ho['ninki'] >= lo) & (ho['ninki'] <= hi)]
        a, b = resid(m_tr), resid(m_ho)
        if not a or not b:
            print(f'{lbl:12s}{"標本不足":>10}')
            continue
        print(f'{lbl:12s}{a["n"]:>10,}{a["r"]:>+8.2f}{a["z"]:>7.1f} │'
              f'{b["n"]:>11,}{b["r"]:>+8.2f}{b["z"]:>7.1f}')


if __name__ == '__main__':
    main()
