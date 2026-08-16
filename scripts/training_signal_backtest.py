# -*- coding: utf-8 -*-
"""調教(追い切り時計)は人気を超えるエッジになるか。jravan.db の training を初検証。

発見: jravan.db に training テーブルが505,512件あった(過去メモの「DBに過去調教なし」は誤り)。
      ただし cho_date は 2025-06〜2026-06 の**1年分**のみ。

設計上の壁と対処:
  ・t4fの分布は二峰性(52-60秒帯と60-70秒帯)＝坂路とウッドが混在。施設を示す列が無い。
    生の時計を横比較すると「どの施設で追ったか」を測るだけになる。
  → **その馬自身の過去の追い切りと比べて速いか**(self-relative)で正規化する。
    同じ馬は同じ施設を使い続ける傾向があるので施設差が相殺され、かつリークが無い
    (今走より前の追い切りだけを使う)。

指標:
  tr_z   … 直前追い切りの t4f が、その馬の過去追い切り平均から何σ速いか(速い=正)
  tr_best… その馬の過去最速を更新したか

Usage:
  python scripts/training_signal_backtest.py
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

MIN_HIST = 3      # 自己比較に必要な過去追い切り本数


def load():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    res = pd.read_sql("""
        SELECT r.race_key, r.ketto_num, r.umaban, r.chakujun, r.ninki, r.win_odds,
               ra.year, ra.monthday
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE r.chakujun > 0 AND r.ninki > 0 AND r.win_odds > 0
          AND CAST(ra.year AS INTEGER) >= 2025
    """, con)
    tr = pd.read_sql("""
        SELECT ketto_num, cho_date, t4f, t3f, lap_20
        FROM training WHERE t4f > 0
    """, con)
    con.close()
    res['day'] = res['year'].astype(str) + res['monthday'].astype(str).str.zfill(4)
    return res, tr


def build(res, tr):
    """各出走に『直前の追い切り』と『それ以前の自己履歴』を紐づける(リーク無し)。"""
    tr = tr.sort_values(['ketto_num', 'cho_date'])
    by_horse = {k: g for k, g in tr.groupby('ketto_num', sort=False)}
    rows = []
    for rec in res.itertuples(index=False):
        g = by_horse.get(rec.ketto_num)
        if g is None:
            continue
        past = g[g['cho_date'] < rec.day]
        if len(past) < MIN_HIST + 1:
            continue
        last = past.iloc[-1]
        hist = past.iloc[:-1]          # 直前追い切りより前＝比較用の自己履歴
        mu, sd = hist['t4f'].mean(), hist['t4f'].std(ddof=0)
        if not sd or sd <= 0 or np.isnan(sd):
            continue
        rows.append({
            'race_key': rec.race_key, 'chakujun': rec.chakujun,
            'ninki': rec.ninki, 'win_odds': rec.win_odds, 'day': rec.day,
            # 時計は小さいほど速い → 符号反転して「速い=正」に揃える
            'tr_z': (mu - last['t4f']) / sd,
            'tr_best': 1 if last['t4f'] <= hist['t4f'].min() else 0,
            'n_hist': len(hist),
        })
    return pd.DataFrame(rows)


def resid(sub):
    n = len(sub)
    if n < 200:
        return None
    act = (sub['chakujun'] <= 3).mean()
    exp = sub['exp'].mean()
    r = (act - exp) * 100
    se = math.sqrt(max(exp * (1 - exp), 1e-9) / n) * 100
    roi = sub.loc[sub['chakujun'] == 1, 'win_odds'].sum() / n * 100
    return {'n': n, 'act': act * 100, 'r': r, 'z': r / se if se else 0, 'roi': roi}


def show(title, rows):
    print(f'\n■ {title}')
    print(f'{"区分":18s}{"n":>8}{"複勝率":>8}{"残差":>9}{"z":>7}{"単ROI":>8}')
    print('-' * 60)
    for lbl, s in rows:
        if not s:
            print(f'{lbl:18s}{"標本不足":>8}')
            continue
        print(f'{lbl:18s}{s["n"]:>8,}{s["act"]:>7.1f}%{s["r"]:>+9.2f}{s["z"]:>7.2f}{s["roi"]:>7.0f}%')


def main():
    print('読込中...', file=sys.stderr)
    res, tr = load()
    print(f'出走 {len(res):,} / 追い切り {len(tr):,}', file=sys.stderr)
    df = build(res, tr)
    if df.empty:
        print('紐づく出走がありません（調教データの期間が短すぎます）。')
        return
    df['ob'] = pd.qcut(df['win_odds'], 20, labels=False, duplicates='drop')
    df['exp'] = df['ob'].map(df.groupby('ob')['chakujun'].apply(lambda s: (s <= 3).mean()))
    print(f'\n自己履歴{MIN_HIST}本以上で照合できた出走: {len(df):,}頭'
          f'（{df["day"].min()}〜{df["day"].max()}）')

    # レース内で相対化(同じ日・同じ条件の比較にする)
    df['tr_rank'] = df.groupby('race_key')['tr_z'].rank(ascending=False, method='min')
    df['field'] = df.groupby('race_key')['tr_z'].transform('size')

    show('追い切りが自己平均より速いか（σ）',
         [('速い +1.0σ以上', resid(df[df['tr_z'] >= 1.0])),
          ('やや速い +0.5〜1.0', resid(df[(df['tr_z'] >= 0.5) & (df['tr_z'] < 1.0)])),
          ('ふつう -0.5〜+0.5', resid(df[(df['tr_z'] > -0.5) & (df['tr_z'] < 0.5)])),
          ('遅い -1.0σ以下', resid(df[df['tr_z'] <= -1.0]))])

    show('レース内で追い切りが最も良い馬',
         [('レース内1位', resid(df[df['tr_rank'] == 1])),
          ('レース内2-3位', resid(df[(df['tr_rank'] >= 2) & (df['tr_rank'] <= 3)])),
          ('レース内下位半分', resid(df[df['tr_rank'] > df['field'] / 2]))])

    show('自己ベスト更新',
         [('自己ベスト更新', resid(df[df['tr_best'] == 1])),
          ('更新せず', resid(df[df['tr_best'] == 0]))])

    show('人気薄(6番人気以下)に限定',
         [('速い+1.0σ以上×人気薄', resid(df[(df['tr_z'] >= 1.0) & (df['ninki'] >= 6)])),
          ('レース内1位×人気薄', resid(df[(df['tr_rank'] == 1) & (df['ninki'] >= 6)])),
          ('自己ベスト×人気薄', resid(df[(df['tr_best'] == 1) & (df['ninki'] >= 6)]))])

    print('\n※データは2025-06〜2026-06の1年分のみ。train/holdoutに割れないため、'
          'ここで有望でも「候補」止まり。期間が延びてから追試すること。')


if __name__ == '__main__':
    main()
