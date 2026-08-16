# -*- coding: utf-8 -*-
"""KYI(競走馬データ)の主要項目に妙味があるか検証。外厩(放牧先ランク)が本命。

KYIは128項目・レコード長1024。充足率100%の項目が多い:
  放牧先 / 放牧先ランク(A-E) … **外厩**。台帳に全く無い新情報
  調教矢印コード / 厩舎評価コード … 調教の「評価」（[[verified_training_and_sire_popbucket]]で
      調教**時計**は4.4万頭で完全にゼロだったが、評価は別物として未検証）
  激走指数 / 万券指数 … JRDB独自の穴指数
  厩舎ランク / 厩舎指数
  入厩何走目 / 入厩何日前 … 放牧明けの度合い

⚠標本は7日(2,581頭)。方向性を見るだけ。有望なら日数を足す。
⚠他社の加工済み指数は織り込まれている前提で見る
  （[[project_dbkeiba_jcombo]]・[[verified_jrdb_base_odds]]と同型）。

Usage:
  python scripts/jrdb_kyi_backtest.py
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
    k = jrdb_read.load('KYI')
    k['race_num'] = pd.to_numeric(k['Ｒ'], errors='coerce').astype('Int64')
    k['umaban'] = pd.to_numeric(k['馬番'], errors='coerce').astype('Int64')
    k['jyo'] = k['場コード'].astype(int).astype(str).str.zfill(2)

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
    j = (res.merge(races, on='race_key')
            .merge(pay, on=['race_key', 'umaban'], how='left'))
    j['pl_pay'] = j['pl_pay'].fillna(0.0)

    d = k.merge(j, on=['day', 'jyo', 'race_num', 'umaban'], how='inner')
    d = d[d['win_odds'] > 0].copy()
    d['top3'] = (d['chakujun'] <= 3).astype(int)
    d['ob'] = pd.qcut(d['win_odds'], 15, labels=False, duplicates='drop')
    d['exp'] = d.groupby('ob')['top3'].transform('mean')
    d['resid'] = (d['top3'] - d['exp']) * 100
    return d


def line(lbl, s, n_all):
    if len(s) < 120:
        return f'{lbl:22s}{len(s):>7,}{"標本不足":>38}'
    r = s['resid'].mean()
    se = s['resid'].std(ddof=0) / math.sqrt(len(s))
    z = r / se if se else 0
    star = '★' if abs(z) >= 2 else ''
    return (f'{lbl:22s}{len(s):>7,}{len(s)/n_all*100:>6.1f}%'
            f'{s["top3"].mean()*100:>7.1f}%{r:>+8.2f}{z:>+7.2f}'
            f'{s["pl_pay"].mean():>8.1f}%  {star}')


HDR = (f'{"区分":22s}{"n":>7}{"割合":>7}{"複勝率":>8}{"残差":>8}{"z":>7}{"複勝ROI":>8}')


def by_cat(d, col, title, order=None):
    print(f'\n■ {title}')
    print(HDR)
    print('-' * 74)
    v = d[col].astype(str).str.strip()
    keys = order or sorted(x for x in v.unique() if x)
    for k in keys:
        print(line(f'{col}={k}', d[v == k], len(d)))


def by_quartile(d, col, title, q=4):
    s = pd.to_numeric(d[col], errors='coerce')
    if s.notna().sum() < 600 or s.nunique() < 4:
        print(f'\n■ {title}: 値が乏しく検証不可')
        return
    print(f'\n■ {title}')
    print(HDR)
    print('-' * 74)
    qq = pd.qcut(s, q, labels=False, duplicates='drop')
    for kk in sorted(set(qq.dropna())):
        rng = s[qq == kk]
        print(line(f'第{int(kk)+1}四分位 ({rng.min():g}〜{rng.max():g})',
                   d[qq == kk], len(d)))


def main():
    d = load()
    n = len(d)
    print(f'■ KYI×結果 突合 {n:,}頭 / {d["race_key"].nunique():,}レース'
          f'（{d["day"].min()}〜{d["day"].max()}）')

    by_cat(d, '放牧先ランク', '① 外厩（放牧先ランク A-E）',
           order=['A', 'B', 'C', 'D', 'E'])

    # 放牧先の実名トップ（どこが多いか＋成績）
    print('\n■ ①-2 放牧先（多い順トップ8）')
    print(HDR)
    print('-' * 74)
    top = d['放牧先'].astype(str).str.strip().value_counts().head(8)
    for name, _c in top.items():
        if name:
            print(line(name[:20], d[d['放牧先'].astype(str).str.strip() == name], n))

    by_quartile(d, '調教矢印コード', '② 調教矢印コード（調教の評価）')
    by_quartile(d, '厩舎評価コード', '③ 厩舎評価コード')
    by_quartile(d, '激走指数', '④ 激走指数（JRDB独自の穴指数）')
    by_quartile(d, '万券指数', '⑤ 万券指数')
    by_quartile(d, '厩舎ランク', '⑥ 厩舎ランク')

    # 入厩何日前（放牧明けの度合い）
    print('\n■ ⑦ 入厩何日前（放牧明けの度合い）')
    print(HDR)
    print('-' * 74)
    v = pd.to_numeric(d['入厩何日前'], errors='coerce')
    for lbl, lo, hi in (('〜20日', 0, 21), ('21-40日', 21, 41),
                        ('41-70日', 41, 71), ('71日〜', 71, 9999)):
        print(line(lbl, d[(v >= lo) & (v < hi)], n))

    print(f'\n※標本 {n:,}頭（7日）。★は|z|>=2だが1年窓ですらないので候補どまり。')
    print('※他社の加工済み指数は会員全員が見るため織り込まれやすい点に注意。')


if __name__ == '__main__':
    main()
