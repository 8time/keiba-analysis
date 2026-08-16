# -*- coding: utf-8 -*-
"""『戦闘力2』の到達可能ラインを測る: 上位N頭で"5着以内の馬"を何%捕まえられるか。

問い(ユーザー): 手持ちの全項目を組み合わせて「5着以内に入る馬を80%くらい当てる」
数値は作れるか。

測り方:
  ・各レースで実際に5着以内だった馬(最大5頭)を正解とする。
  ・スコア上位N頭を選び、正解を何頭カバーできたか(recall)を測る。
  ・比較対象: 現行LTR / 人気(市場) / BattleScore相当(オッズ抜きの素の能力)。
  ・Nを変えて「80%に届くのは何頭選んだ時か」を出す。
  ・学習/検証窓は build_ltr_model.py のまま(時系列分割・リーク無し)。

これで「80%は可能か」ではなく「80%に何頭必要か」という答えの出る形にする。

Usage:
  python scripts/top5_capture_ceiling.py
"""
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd
import lightgbm as lgb

from scripts import build_ltr_model as B

NS = [3, 4, 5, 6, 7, 8, 9, 10]


def _fit(train_df, val_df, features):
    tr = train_df.sort_values('race_key')
    va = val_df.sort_values('race_key')
    ds_tr = lgb.Dataset(tr[features].values.astype(np.float64), label=tr['label'].values,
                        group=tr.groupby('race_key', sort=False).size().values,
                        feature_name=features)
    ds_va = lgb.Dataset(va[features].values.astype(np.float64), label=va['label'].values,
                        group=va.groupby('race_key', sort=False).size().values,
                        feature_name=features, reference=ds_tr)
    params = {'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [5],
              'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
              'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
              'verbose': -1}
    return lgb.train(params, ds_tr, num_boost_round=600, valid_sets=[ds_va],
                     callbacks=[lgb.early_stopping(50, verbose=False)])


def capture(test_df, col, ascending=False):
    """上位N頭で『5着以内の馬』を何%カバーできるか。Nごとのrecallを返す。"""
    out = {n: [] for n in NS}
    perfect = {n: 0 for n in NS}
    total = 0
    for _, g in test_df.groupby('race_key'):
        truth = set(g[g['chakujun'] <= 5]['umaban'])
        if not truth:
            continue
        total += 1
        for n in NS:
            if n > len(g):
                sel = set(g['umaban'])
            else:
                sel = set(g.nsmallest(n, col)['umaban'] if ascending
                          else g.nlargest(n, col)['umaban'])
            hit = len(truth & sel)
            out[n].append(hit / len(truth))
            if hit == len(truth):
                perfect[n] += 1
    return ({n: float(np.mean(v)) for n, v in out.items() if v},
            {n: perfect[n] / total for n in NS} if total else {}, total)


def main():
    print('データ読込＋特徴量生成中...', file=sys.stderr)
    df = B.load_data()
    df = B.compute_corrected_time(df)
    df = B.compute_rolling_features(df)
    df = B.compute_trainer_course(df)
    df = B.compute_jockey_course(df)
    df = B.compute_jockey_dist(df)
    df = df[df['year'].astype(int) >= 2016].copy()
    df = B.encode_features(df)
    df = B.compute_race_ranks(df)

    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    cnt = df.groupby('race_key').size()
    df = df[df['race_key'].isin(cnt[cnt >= 5].index)]

    yi = df['year'].astype(int)
    train_df, val_df = df[yi <= B.TRAIN_END], df[yi == B.VAL_YEAR]
    test_df = df[yi >= B.TEST_FROM].copy()

    # ① 現行LTR(全特徴量=オッズ込み)
    m_all = _fit(train_df, val_df, B.FEATURES)
    test_df['ltr'] = m_all.predict(test_df[B.FEATURES].values.astype(np.float64))

    # ② オッズ・人気を除いた『純粋な能力』モデル(＝BattleScore的な立ち位置)
    feats_noodds = [f for f in B.FEATURES if f not in ('log_odds', 'ninki')]
    m_ab = _fit(train_df, val_df, feats_noodds)
    test_df['ability'] = m_ab.predict(test_df[feats_noodds].values.astype(np.float64))

    r_ltr, p_ltr, n_races = capture(test_df, 'ltr')
    r_nin, p_nin, _ = capture(test_df, 'ninki', ascending=True)
    r_ab, p_ab, _ = capture(test_df, 'ability')

    print(f'\nテスト対象: {n_races:,}レース（{B.TEST_FROM}年以降・学習に未使用）\n')
    print('■ 上位N頭で「5着以内の馬」を何%カバーできるか')
    print(f'{"N":>3} {"現行LTR":>9} {"人気":>9} {"能力のみ":>9}   LTRの上乗せ')
    print('-' * 52)
    for n in NS:
        if n not in r_ltr:
            continue
        print(f'{n:>3} {r_ltr[n]*100:>8.1f}% {r_nin[n]*100:>8.1f}% {r_ab[n]*100:>8.1f}%'
              f'   {(r_ltr[n]-r_nin[n])*100:>+6.2f}pp')

    print('\n■ 5着以内の馬を「全頭」捕まえられたレースの割合')
    print(f'{"N":>3} {"現行LTR":>9} {"人気":>9}')
    print('-' * 26)
    for n in NS:
        if n not in p_ltr:
            continue
        print(f'{n:>3} {p_ltr[n]*100:>8.1f}% {p_nin[n]*100:>8.1f}%')

    hit80 = [n for n in NS if r_ltr.get(n, 0) >= 0.80]
    print(f'\n→ カバー率80%に到達するのは上位 {hit80[0] if hit80 else "—"} 頭を選んだ時')
    hit90 = [n for n in NS if r_ltr.get(n, 0) >= 0.90]
    print(f'→ カバー率90%に到達するのは上位 {hit90[0] if hit90 else "—"} 頭を選んだ時')


if __name__ == '__main__':
    main()
