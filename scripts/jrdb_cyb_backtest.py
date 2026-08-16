# -*- coding: utf-8 -*-
"""CYB(調教分析データ)を検証する。「調教を強化できないか」への回答。

これまでの調教まわりの結論:
  ・調教**時計**(jravan.db training 50万件・自己相対) → 4.4万頭で完全にゼロ
    ([[verified_training_and_sire_popbucket]])
  ・KYIの**調教矢印コード** → 96%が同一値に集中し実質変動なし
    ([[verified_jrdb_kyi_fields]])
CYBには時計そのものではない「仕上り」系の指標があるので、そこだけ未検証だった。

実測の充足率(7日/2,581頭):
  仕上指数 100% / 調教量評価(A-D) 100% / 仕上指数変化 100% / 追切指数 95% /
  一週前追切指数 79.5%
  ⚠**調教コメント 0% / 調教評価(◎○△) 0%** ＝人力のC分類項目は空だった。

Usage:
  python scripts/jrdb_cyb_backtest.py
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

HDR = (f'{"区分":24s}{"n":>7}{"割合":>7}{"複勝率":>8}{"残差":>8}{"z":>7}{"複勝ROI":>8}')


def load():
    c = jrdb_read.load('CYB')
    c['race_num'] = pd.to_numeric(c['Ｒ'], errors='coerce').astype('Int64')
    c['umaban'] = pd.to_numeric(c['馬番'], errors='coerce').astype('Int64')
    c['jyo'] = c['場コード'].astype(int).astype(str).str.zfill(2)

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

    d = c.merge(j, on=['day', 'jyo', 'race_num', 'umaban'], how='inner')
    d = d[d['win_odds'] > 0].copy()
    d['top3'] = (d['chakujun'] <= 3).astype(int)
    d['ob'] = pd.qcut(d['win_odds'], 15, labels=False, duplicates='drop')
    d['exp'] = d.groupby('ob')['top3'].transform('mean')
    d['resid'] = (d['top3'] - d['exp']) * 100
    return d


def line(lbl, s, n_all):
    if len(s) < 120:
        return f'{lbl:24s}{len(s):>7,}{"標本不足":>34}'
    r = s['resid'].mean()
    se = s['resid'].std(ddof=0) / math.sqrt(len(s))
    z = r / se if se else 0
    return (f'{lbl:24s}{len(s):>7,}{len(s)/n_all*100:>6.1f}%'
            f'{s["top3"].mean()*100:>7.1f}%{r:>+8.2f}{z:>+7.2f}'
            f'{s["pl_pay"].mean():>8.1f}%  ' + ('★' if abs(z) >= 2 else ''))


def cat(d, col, title, order=None):
    print(f'\n■ {title}')
    print(HDR)
    print('-' * 76)
    v = d[col].astype(str).str.strip()
    for k in (order or sorted(x for x in v.unique() if x)):
        print(line(f'{col}={k}', d[v == k], len(d)))


def quart(d, col, title):
    s = pd.to_numeric(d[col], errors='coerce')
    if s.notna().sum() < 600 or s.nunique() < 4:
        print(f'\n■ {title}: 値が乏しく検証不可')
        return
    print(f'\n■ {title}')
    print(HDR)
    print('-' * 76)
    q = pd.qcut(s, 4, labels=False, duplicates='drop')
    for k in sorted(set(q.dropna())):
        rng = s[q == k]
        print(line(f'第{int(k)+1}四分位 ({rng.min():g}〜{rng.max():g})', d[q == k], len(d)))


def main():
    d = load()
    n = len(d)
    print(f'■ CYB×結果 突合 {n:,}頭 / {d["race_key"].nunique():,}レース'
          f'（{d["day"].min()}〜{d["day"].max()}）')

    quart(d, '仕上指数', '① 仕上指数（仕上り状態を指数化）※時計ではない')
    cat(d, '調教量評価', '② 調教量評価（A-D）', order=['A', 'B', 'C', 'D'])
    quart(d, '追切指数', '③ 追切指数（調教時計の指数化）')
    quart(d, '一週前追切指数', '④ 一週前追切指数')
    cat(d, '仕上指数変化', '⑤ 仕上指数変化')
    cat(d, '調教距離', '⑥ 調教距離（1長め/2普通/3短め/4:2本）')
    cat(d, '調教重点', '⑦ 調教重点（1テン/2中間/3終い/4平均）')

    # 仕上指数のレース内順位（頭数差を吸収）
    print('\n■ ⑧ 仕上指数のレース内順位')
    print(HDR)
    print('-' * 76)
    d['rk'] = d.groupby('race_key')['仕上指数'].rank(ascending=False, method='min')
    for lbl, lo, hi in (('1位', 1, 2), ('2-3位', 2, 4), ('4-6位', 4, 7),
                        ('7位以下', 7, 99)):
        print(line(lbl, d[d['rk'].between(lo, hi - 1)], n))

    print(f'\n※標本 {n:,}頭（7日）。方向性のみ。')
    print('※調教コメント・調教評価(◎○△)は充足率0%で検証対象にできなかった。')


if __name__ == '__main__':
    main()
