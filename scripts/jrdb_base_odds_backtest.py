# -*- coding: utf-8 -*-
"""JRDBの「基準複勝オッズ」と市場オッズの乖離に妙味があるか検証。

なぜ有望に見えたか:
  [[verified_r40_place_ev]]は「オッズから作った推定値をオッズと比べる」構造だったので、
  確定オッズを知らないと成立せず実装不可になった。
  JRDBの**基準オッズは前日19:00に確定する独立した推定値**なので、
  「基準 vs 直前の市場オッズ」なら**買える時点で成立する**。

データ:
  JO(情報データ) … 基準オッズ / 基準複勝オッズ（前日確定・充足率100%）
  TYB(直前情報)  … 発走約17分前の実オッズ（単勝・複勝下限）
  jravan.db      … 着順・複勝配当

⚠懸念: 基準オッズはJRDB会員全員に配布されている。全員が同じ「割安判定」を
  見て買うので織り込まれている可能性が高い（[[project_dbkeiba_jcombo]]と同型）。

⚠標本: いまは7日分(2,581頭)しかない。方向性を見るだけ。
  有望なら日数を足して追試する。

Usage:
  python scripts/jrdb_base_odds_backtest.py
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

from scripts import jrdb_read
from core import jockey_jv as jj


def load():
    jo = jrdb_read.load('JOA', spec_key='Jodata')
    jo['race_num'] = pd.to_numeric(jo['Ｒ'], errors='coerce').astype('Int64')
    jo['umaban'] = pd.to_numeric(jo['馬番'], errors='coerce').astype('Int64')
    jo['jyo'] = jo['場コード'].astype(int).astype(str).str.zfill(2)
    jo = jo[['day', 'jyo', 'race_num', 'umaban', '基準オッズ', '基準複勝オッズ',
             'CID', 'LS指数', 'CID素点']]

    ty = jrdb_read.load('TYB')
    ty = ty[ty['取消フラグ'] != 1]
    ty['race_num'] = pd.to_numeric(ty['Ｒ'], errors='coerce').astype('Int64')
    ty['umaban'] = pd.to_numeric(ty['馬番'], errors='coerce').astype('Int64')
    ty['jyo'] = ty['場コード'].astype(int).astype(str).str.zfill(2)
    ty = ty[['day', 'jyo', 'race_num', 'umaban', '単勝オッズ', '複勝オッズ']]
    ty = ty.rename(columns={'単勝オッズ': 'live_win', '複勝オッズ': 'live_place'})

    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    races = pd.read_sql("SELECT race_key, year||monthday AS day, jyo, race_num "
                        "FROM races WHERE CAST(year AS INTEGER)=2025", con)
    res = pd.read_sql("SELECT race_key, umaban, ninki, win_odds, chakujun "
                      "FROM results WHERE chakujun>0", con)
    pay = pd.read_sql("SELECT race_key, combo, payout FROM payouts "
                      "WHERE bet_type='複勝'", con)
    con.close()
    pay['umaban'] = pd.to_numeric(pay['combo'], errors='coerce').astype('Int64')
    pay = pay.drop(columns='combo').rename(columns={'payout': 'pl_pay'})
    res['umaban'] = pd.to_numeric(res['umaban'], errors='coerce').astype('Int64')
    races['race_num'] = races['race_num'].astype('Int64')
    j = res.merge(races, on='race_key').merge(pay, on=['race_key', 'umaban'],
                                              how='left')
    j['pl_pay'] = j['pl_pay'].fillna(0.0)

    d = (jo.merge(ty, on=['day', 'jyo', 'race_num', 'umaban'])
           .merge(j, on=['day', 'jyo', 'race_num', 'umaban']))
    d = d[(d['基準複勝オッズ'] > 0) & (d['live_place'] > 0) & (d['win_odds'] > 0)].copy()
    d['top3'] = (d['chakujun'] <= 3).astype(int)
    d['ob'] = pd.qcut(d['win_odds'], 15, labels=False, duplicates='drop')
    d['exp'] = d.groupby('ob')['top3'].transform('mean')
    d['resid'] = (d['top3'] - d['exp']) * 100
    # 市場が基準より何倍高く付けているか（>1 = 市場が過小評価＝買い候補）
    d['gap'] = d['live_place'] / d['基準複勝オッズ']
    return d


def line(lbl, s, n_all):
    if len(s) < 100:
        return f'{lbl:20s}{len(s):>7,}{"標本不足":>40}'
    r = s['resid'].mean()
    se = s['resid'].std(ddof=0) / math.sqrt(len(s))
    z = r / se if se else 0
    roi = s['pl_pay'].mean()
    return (f'{lbl:20s}{len(s):>7,}{len(s)/n_all*100:>6.1f}%'
            f'{s["top3"].mean()*100:>7.1f}%{r:>+8.2f}{z:>+7.2f}{roi:>8.1f}%')


def main():
    d = load()
    n = len(d)
    print(f'■ JO×TYB×結果 突合 {n:,}頭 / {d["race_key"].nunique():,}レース'
          f'（{d["day"].min()}〜{d["day"].max()}）\n')

    print('■ ① 基準複勝オッズは市場とどれくらいズレているか')
    g = d['gap'].replace([np.inf, -np.inf], np.nan).dropna()
    print(f'  市場(17分前) / 基準 の比: 中央 {g.median():.3f} / 平均 {g.mean():.3f}')
    print(f'  ±10%以内に収まる割合: {((g-1).abs()<=0.10).mean()*100:.1f}%')
    print(f'  基準の方が高い(市場が買われている): {(g<1).mean()*100:.1f}%')

    hdr = (f'{"区分":20s}{"n":>7}{"割合":>7}{"複勝率":>8}{"残差":>8}{"z":>7}{"複勝ROI":>8}')
    print(f'\n■ ② 乖離帯別（gap = 市場複勝 ÷ 基準複勝）')
    print(hdr)
    print('-' * 66)
    for lbl, lo, hi in (('〜0.85 (市場が安い)', 0, 0.85), ('0.85-0.95', 0.85, 0.95),
                        ('0.95-1.05 (一致)', 0.95, 1.05), ('1.05-1.20', 1.05, 1.20),
                        ('1.20-1.50', 1.20, 1.50), ('1.50〜 (市場が高い)', 1.50, 99)):
        print(line(lbl, d[(d['gap'] >= lo) & (d['gap'] < hi)], n))

    print(f'\n■ ③ 人気上位に限定（r40と同じ土俵: 単勝支持率20%相当=単勝4倍以下）')
    print(hdr)
    print('-' * 66)
    fav = d[d['win_odds'] <= 4.0]
    for lbl, lo, hi in (('〜0.95', 0, 0.95), ('0.95-1.05', 0.95, 1.05),
                        ('1.05-1.20', 1.05, 1.20), ('1.20〜', 1.20, 99)):
        print(line(lbl, fav[(fav['gap'] >= lo) & (fav['gap'] < hi)], len(fav)))

    print(f'\n■ ④ ついでにCID / LS指数')
    print(hdr)
    print('-' * 66)
    for col in ('CID', 'LS指数'):
        v = d[col]
        if v.notna().sum() < 500 or v.nunique() < 3:
            print(f'{col:20s}{"値が乏しく検証不可":>30}')
            continue
        q = pd.qcut(v, 4, labels=False, duplicates='drop')
        for k in sorted(set(q.dropna())):
            print(line(f'{col} 第{int(k)+1}四分位', d[q == k], n))

    print(f'\n※標本 {n:,}頭（7日）。方向性のみ。'
          '|z|>=2かつROI>100%が出たら日数を足して追試する。')


if __name__ == '__main__':
    main()
