# -*- coding: utf-8 -*-
"""「人気1-3の馬がRank10位以下に出る」現象を監査する。バグか仕様かの切り分け。

ユーザー報告: SRAで人気1-3番の馬がRank10位以下に表示されることがある。

切り分けの考え方:
  もしアプリが**何かを見抜いている**なら、その馬の実際の複勝率は
  普段の人気1-3番より**大きく落ちる**はず。
  もし**単なる欠損や誤差**なら、複勝率は普段どおりのはず。
  → 実測でどちらか分かる。

Rankはability_score(LTR代理・**小さいほど強い**)の昇順で近似する。
アプリの既定はBattleScore/予測スコアだが、LTRも選択肢にあり
どちらも「実力順」で市場と独立という点は同じ。

Usage:
  python scripts/rank_disagree_audit.py
"""
import os
import sys
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd

sys.stdout.reconfigure(encoding='utf-8')


def main():
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score'])
    h = h[(h['ninki'] > 0) & (h['chakujun'] > 0) & h['ability_score'].notna()].copy()
    # ⚠ability_scoreは小さいほど強い
    h['rank'] = h.groupby('race_key')['ability_score'].rank(method='min')
    h['top3'] = (h['chakujun'] <= 3).astype(int)
    h['field'] = h.groupby('race_key')['umaban'].transform('size')
    h = h[h['field'] >= 10]
    n = len(h)
    print(f'■ 対象 {n:,}頭 / {h["race_key"].nunique():,}レース（10頭立て以上）\n')

    print('■ ① 人気1-3番の馬は、Rankで何位に置かれているか')
    print(f'{"人気":>6}{"n":>9}{"Rank中央":>10}{"Rank10位以下":>13}{"Rank7位以下":>12}')
    print('-' * 52)
    for p in (1, 2, 3):
        s = h[h['ninki'] == p]
        print(f'{p:>6}{len(s):>9,}{s["rank"].median():>10.0f}'
              f'{(s["rank"] >= 10).mean()*100:>12.1f}%'
              f'{(s["rank"] >= 7).mean()*100:>11.1f}%')

    print('\n■ ② その馬は実際どうだったか（アプリが正しいのか市場が正しいのか）')
    print(f'{"区分":30s}{"n":>8}{"複勝率":>9}{"差":>9}')
    print('-' * 58)
    for p in (1, 2, 3):
        base = h[h['ninki'] == p]['top3'].mean() * 100
        print(f'{f"人気{p}番 全体":30s}{len(h[h.ninki==p]):>8,}{base:>8.1f}%{"":>9}')
        for lbl, m in (('  └ Rank 1-3位に置かれた', h['rank'] <= 3),
                       ('  └ Rank 4-6位', h['rank'].between(4, 6)),
                       ('  └ Rank 7-9位', h['rank'].between(7, 9)),
                       ('  └ Rank 10位以下', h['rank'] >= 10)):
            s = h[(h['ninki'] == p) & m]
            if len(s) < 120:
                print(f'{lbl:30s}{len(s):>8,}{"標本不足":>18}')
                continue
            v = s['top3'].mean() * 100
            print(f'{lbl:30s}{len(s):>8,}{v:>8.1f}%{v-base:>+8.1f}')
        print()

    print('■ ③ 逆側: Rank1位なのに人気が低い馬（アプリが推す穴）')
    print(f'{"区分":30s}{"n":>8}{"複勝率":>9}{"単勝ROI":>10}')
    print('-' * 58)
    h['ret'] = np.where(h['chakujun'] == 1, h['win_odds'] * 100, 0.0)
    for lbl, m in (('Rank1位 × 人気1-3番', (h['rank'] == 1) & (h['ninki'] <= 3)),
                   ('Rank1位 × 人気4-6番', (h['rank'] == 1) & h['ninki'].between(4, 6)),
                   ('Rank1位 × 人気7番以下', (h['rank'] == 1) & (h['ninki'] >= 7))):
        s = h[m]
        if len(s) < 120:
            continue
        print(f'{lbl:30s}{len(s):>8,}{s["top3"].mean()*100:>8.1f}%'
              f'{s["ret"].mean():>9.1f}%')

    print('\n■ ④ 大きく食い違った時、どちらが正しいか（オッズ統制の残差）')
    h['ob'] = pd.qcut(h['win_odds'], 20, labels=False, duplicates='drop')
    h['exp'] = h.groupby('ob')['top3'].transform('mean')
    h['resid'] = (h['top3'] - h['exp']) * 100
    print(f'{"区分":34s}{"n":>8}{"残差":>9}{"z":>8}')
    print('-' * 60)
    for lbl, m in (('人気1-3 かつ Rank10位以下', (h['ninki'] <= 3) & (h['rank'] >= 10)),
                   ('人気1-3 かつ Rank7-9位', (h['ninki'] <= 3) & h['rank'].between(7, 9)),
                   ('人気1-3 かつ Rank1-3位', (h['ninki'] <= 3) & (h['rank'] <= 3)),
                   ('人気7以下 かつ Rank1-3位', (h['ninki'] >= 7) & (h['rank'] <= 3))):
        s = h[m]
        if len(s) < 120:
            continue
        r = s['resid'].mean()
        se = s['resid'].std(ddof=0) / math.sqrt(len(s))
        z = r / se if se else 0
        print(f'{lbl:34s}{len(s):>8,}{r:>+8.2f}{z:>+8.2f}  '
              + ('★' if abs(z) >= 2 else ''))

    print('\n※残差が負＝オッズが示す以上に走らない（アプリの降格が正しい）')
    print('※残差が0付近＝アプリの降格に意味が無い（表示だけの問題）')


if __name__ == '__main__':
    main()
