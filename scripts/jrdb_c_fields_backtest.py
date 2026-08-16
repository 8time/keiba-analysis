# -*- coding: utf-8 -*-
"""JRDBの「C分類」=人力・独自ルートで収集した情報を検証する。

他サービス(JRA-VAN/netkeiba)に**存在しない**のはこの層だけ。
指数系(B分類)は全て検証済みでゼロだった
([[verified_jrdb_kyi_fields]] [[verified_jrdb_base_odds]] [[verified_jrdb_paddock_codes]])。

手元のKYI/TYB(7日)にあるC項目と充足率:
  特定情報◎○▲△  100% … **専門情報紙 関東約9紙150人/関西約8紙100人の印を人力集計**
  総合情報◎○▲△  100% … 同上(範囲違い)
  蹄コード        87%  … パドックで蹄を目視分類(大中小細×立/標準/ベタ)
  体型            87%  … 16桁の部位別コード(目視観察)
  脚元情報(TYB)   100% … 直前パドックで 0平行線/1良化(!)/2疑問(?)/3悪化(X)
  馬具変更情報(TYB)100% … 0なし/1変更/2特注
  走法             0%  … 仕様書に「採取休止中」と明記＝使えない

**専門紙の印が一番面白い**: 市場オッズとは別の"プロの集合知"なので、
両者がズレたときに妙味が出る可能性がある。オッズ統制後の残差で見る。

⚠標本7日(2,568頭)。方向性のみ。|z|>=2が出たら日数を足して追試。

Usage:
  python scripts/jrdb_c_fields_backtest.py
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

HDR = (f'{"区分":26s}{"n":>7}{"割合":>7}{"複勝率":>8}{"残差":>8}{"z":>7}{"複勝ROI":>8}')


def _key(df):
    df = df.copy()
    df['race_num'] = pd.to_numeric(df['Ｒ'], errors='coerce').astype('Int64')
    df['umaban'] = pd.to_numeric(df['馬番'], errors='coerce').astype('Int64')
    df['jyo'] = df['場コード'].astype(int).astype(str).str.zfill(2)
    return df


def load():
    k = _key(jrdb_read.load('KYI'))
    t = _key(jrdb_read.load('TYB'))[['day', 'jyo', 'race_num', 'umaban',
                                     '脚元情報', '馬具変更情報']]
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

    d = (k.merge(t, on=['day', 'jyo', 'race_num', 'umaban'], how='left')
          .merge(j, on=['day', 'jyo', 'race_num', 'umaban'], how='inner'))
    d = d[d['win_odds'] > 0].copy()
    d['top3'] = (d['chakujun'] <= 3).astype(int)
    d['ob'] = pd.qcut(d['win_odds'], 15, labels=False, duplicates='drop')
    d['exp'] = d.groupby('ob')['top3'].transform('mean')
    d['resid'] = (d['top3'] - d['exp']) * 100

    # 専門紙の印を重み付き合計にする（◎3/○2/▲1/△0.5）
    for pre in ('特定情報', '総合情報'):
        w = np.zeros(len(d))
        for mark, wt in (('◎', 3.0), ('○', 2.0), ('▲', 1.0), ('△', 0.5)):
            c = f'{pre}{mark}'
            if c in d.columns:
                w = w + pd.to_numeric(d[c], errors='coerce').fillna(0).to_numpy() * wt
        d[f'{pre}_score'] = w
        # レース内順位（頭数差を吸収）
        d[f'{pre}_rank'] = d.groupby('race_key')[f'{pre}_score'] \
                            .rank(ascending=False, method='min')
    return d


def line(lbl, s, n_all):
    if len(s) < 120:
        return f'{lbl:26s}{len(s):>7,}{"標本不足":>34}'
    r = s['resid'].mean()
    se = s['resid'].std(ddof=0) / math.sqrt(len(s))
    z = r / se if se else 0
    star = '★' if abs(z) >= 2 else ''
    return (f'{lbl:26s}{len(s):>7,}{len(s)/n_all*100:>6.1f}%'
            f'{s["top3"].mean()*100:>7.1f}%{r:>+8.2f}{z:>+7.2f}'
            f'{s["pl_pay"].mean():>8.1f}%  {star}')


def main():
    d = load()
    n = len(d)
    print(f'■ KYI×TYB×結果 突合 {n:,}頭 / {d["race_key"].nunique():,}レース'
          f'（{d["day"].min()}〜{d["day"].max()}）')

    for pre in ('特定情報', '総合情報'):
        print(f'\n■ {pre}（専門紙の印を人力集計・◎3○2▲1△0.5で加重）')
        print(HDR)
        print('-' * 78)
        for lbl, lo, hi in (('レース内1位', 1, 2), ('2位', 2, 3), ('3位', 3, 4),
                            ('4-6位', 4, 7), ('7位以下', 7, 99)):
            m = d[f'{pre}_rank'].between(lo, hi - 1)
            print(line(lbl, d[m], n))
        # 印ゼロ（誰も推していない）
        print(line('印ゼロ(誰も推さず)', d[d[f'{pre}_score'] == 0], n))

    print('\n■ 専門紙1位 × 人気帯（プロと市場のズレ）')
    print(HDR)
    print('-' * 78)
    top1 = d['総合情報_rank'] == 1
    for lbl, m in (('専門1位×1番人気', d['ninki'] == 1),
                   ('専門1位×2-3番人気', d['ninki'].between(2, 3)),
                   ('専門1位×4-6番人気', d['ninki'].between(4, 6)),
                   ('専門1位×7番人気以下', d['ninki'] >= 7)):
        print(line(lbl, d[top1 & m], n))

    print('\n■ 蹄コード（パドックで蹄を目視分類）')
    print(HDR)
    print('-' * 78)
    hv = pd.to_numeric(d['蹄コード'], errors='coerce')
    for k in sorted(x for x in hv.dropna().unique() if x > 0):
        s = d[hv == k]
        if len(s) >= 150:
            print(line(f'蹄コード={int(k)}', s, n))

    print('\n■ 脚元情報（直前パドックの脚元判定）')
    print(HDR)
    print('-' * 78)
    av = pd.to_numeric(d['脚元情報'], errors='coerce')
    for k, lbl in ((0, '0 平行線'), (1, '1 良化(!)'), (2, '2 疑問(?)'), (3, '3 悪化(X)')):
        print(line(lbl, d[av == k], n))

    print('\n■ 馬具変更情報')
    print(HDR)
    print('-' * 78)
    bv = pd.to_numeric(d['馬具変更情報'], errors='coerce')
    for k, lbl in ((0, '0 変更なし'), (1, '1 変更(通常)'), (2, '2 変更(特注)')):
        print(line(lbl, d[bv == k], n))

    print(f'\n※標本 {n:,}頭（7日）。★は|z|>=2＝追試候補どまり。')


if __name__ == '__main__':
    main()
