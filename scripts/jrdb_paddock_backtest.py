# -*- coding: utf-8 -*-
"""JRDBのパドック評価（馬体コード/気配コード）に妙味があるか検証。

[[verified_paddock_weight]]で「主観項目(歩様/発汗)は履歴が無く検証不可」として
諦めていた領域。JRDB直前情報(TYB)に**充足率100%**で入っていたので初検証。

コード表(jrdb.com/program/jrdb_code.txt):
  馬体コード: 1太い 2余裕 3良い 4普通 5細い 6張り 7緩い
  気配コード: 1状態良 2平凡 3不安定 4イレ込 5気合良 6気不足 7チャカ 8イレチ

2025年の実測分布:
  馬体 3良い68% / 2余裕31% / 1太い0.6%
  気配 2平凡56% / 3不安定28% / 7チャカ15% / 8イレチ0.4%
  → 気配の「不安定」「チャカ」は発火率が十分あり検証に耐える。

⚠1年分しかないので train/holdout に割れない。ここでは
  ・オッズ帯統制の複勝率残差
  ・前半(1-6月)/後半(7-12月)で符号が一貫するか
  の2点で見る。有望なら年を足して追試する。

⚠既知の交絡: 馬体重増減は既に検証済み(大幅増減=危険)。
  パドック評価がそれと独立に効くのかを必ず分けて見る。

Usage:
  python scripts/jrdb_paddock_backtest.py
"""
import os
import sys
import math
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import jrdb_read          # これがstdoutをUTF-8に差し替える
from core import jockey_jv as jj

BATAI = {1: '太い', 2: '余裕', 3: '良い', 4: '普通', 5: '細い', 6: '張り', 7: '緩い'}
KEHAI = {1: '状態良', 2: '平凡', 3: '不安定', 4: 'イレ込', 5: '気合良',
         6: '気不足', 7: 'チャカ', 8: 'イレチ'}


def load():
    t = jrdb_read.load('TYB')
    t = t[t['取消フラグ'] != 1].copy()
    t['race_num'] = pd.to_numeric(t['Ｒ'], errors='coerce').astype('Int64')
    t['umaban'] = pd.to_numeric(t['馬番'], errors='coerce').astype('Int64')
    t['jyo'] = t['場コード'].astype(int).astype(str).str.zfill(2)

    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    races = pd.read_sql("SELECT race_key, year||monthday AS day, jyo, race_num "
                        "FROM races WHERE CAST(year AS INTEGER)=2025", con)
    res = pd.read_sql("SELECT race_key, umaban, ninki, win_odds, chakujun "
                      "FROM results WHERE chakujun>0", con)
    con.close()
    res['umaban'] = pd.to_numeric(res['umaban'], errors='coerce').astype('Int64')
    races['race_num'] = races['race_num'].astype('Int64')
    j = res.merge(races, on='race_key')

    d = t.merge(j, on=['day', 'jyo', 'race_num', 'umaban'], how='inner')
    d = d[(d['win_odds'] > 0)].copy()
    d['top3'] = (d['chakujun'] <= 3).astype(int)
    d['ob'] = pd.qcut(d['win_odds'], 20, labels=False, duplicates='drop')
    d['exp'] = d.groupby('ob')['top3'].transform('mean')
    d['resid'] = (d['top3'] - d['exp']) * 100
    d['h'] = np.where(d['day'].astype(str).str[4:6].astype(int) <= 6, 'H1', 'H2')
    # 馬体重増減（既知の交絡）を数値化
    d['wdiff'] = pd.to_numeric(
        d['馬体重増減'].astype(str).str.replace(' ', '', regex=False),
        errors='coerce')
    return d


def row(lbl, s, base_n):
    if len(s) < 150:
        return f'{lbl:14s}{len(s):>7,}{"標本不足":>34}'
    r = s['resid'].mean()
    se = s['resid'].std(ddof=0) / math.sqrt(len(s))
    z = r / se if se else 0
    h1 = s[s['h'] == 'H1']['resid'].mean() if (s['h'] == 'H1').sum() >= 80 else np.nan
    h2 = s[s['h'] == 'H2']['resid'].mean() if (s['h'] == 'H2').sum() >= 80 else np.nan
    cons = '一致' if (np.isfinite(h1) and np.isfinite(h2)
                      and np.sign(h1) == np.sign(h2)) else '不一致'
    star = '★' if abs(z) >= 2 and cons == '一致' else ''
    return (f'{lbl:14s}{len(s):>7,}{len(s)/base_n*100:>6.1f}%'
            f'{s["top3"].mean()*100:>7.1f}%{r:>+8.2f}{z:>+7.2f}'
            f'{h1:>+7.2f}{h2:>+7.2f}  {cons}{star}')


def main():
    d = load()
    n = len(d)
    print(f'■ TYB×結果 突合 {n:,}頭 / {d["race_key"].nunique():,}レース（2025年）\n')
    hdr = (f'{"区分":14s}{"n":>7}{"割合":>7}{"複勝率":>8}{"残差":>8}{"z":>7}'
           f'{"前半":>7}{"後半":>7}  一貫性')
    print('■ ① 気配コード（パドックで見た馬気配）')
    print(hdr)
    print('-' * 84)
    for k in sorted(KEHAI):
        s = d[pd.to_numeric(d['気配コード'], errors='coerce') == k]
        if len(s) >= 150:
            print(row(f'{k} {KEHAI[k]}', s, n))

    print('\n■ ② 馬体コード（パドックで見た馬体）')
    print(hdr)
    print('-' * 84)
    for k in sorted(BATAI):
        s = d[pd.to_numeric(d['馬体コード'], errors='coerce') == k]
        if len(s) >= 150:
            print(row(f'{k} {BATAI[k]}', s, n))

    print('\n■ ③ 馬体重増減と独立か（既知の交絡を分離）')
    print(f'{"区分":26s}{"n":>8}{"残差":>9}{"z":>7}')
    print('-' * 52)
    ke = pd.to_numeric(d['気配コード'], errors='coerce')
    bad = ke.isin([3, 7, 8])          # 不安定/チャカ/イレチ
    for wlbl, wm in (('増減が小さい(|Δ|<=6)', d['wdiff'].abs() <= 6),
                     ('増減が大きい(|Δ|>6)', d['wdiff'].abs() > 6)):
        for klbl, km in (('気配 平凡/良', ~bad), ('気配 不安定系', bad)):
            s = d[wm & km]
            if len(s) < 200:
                continue
            r = s['resid'].mean()
            se = s['resid'].std(ddof=0) / math.sqrt(len(s))
            print(f'{wlbl+" × "+klbl:26s}{len(s):>8,}{r:>+8.2f}{r/se if se else 0:>+7.2f}')

    print('\n■ ④ 人気帯別（気配 不安定系）')
    print(f'{"人気帯":14s}{"n":>8}{"複勝率":>8}{"残差":>9}{"z":>7}')
    print('-' * 48)
    for lbl, m in (('1-3番人気', d['ninki'] <= 3), ('4-5番人気', d['ninki'].between(4, 5)),
                   ('6-9番人気', d['ninki'].between(6, 9)),
                   ('10番人気以下', d['ninki'] >= 10)):
        s = d[m & bad]
        if len(s) < 200:
            continue
        r = s['resid'].mean()
        se = s['resid'].std(ddof=0) / math.sqrt(len(s))
        print(f'{lbl:14s}{len(s):>8,}{s["top3"].mean()*100:>7.1f}%'
              f'{r:>+8.2f}{r/se if se else 0:>+7.2f}')

    print('\n※1年分のみ。前半/後半で符号が一致し|z|>=2のものだけ★＝追試候補。')


if __name__ == '__main__':
    main()
