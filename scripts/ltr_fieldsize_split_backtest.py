# -*- coding: utf-8 -*-
"""頭数でLTRモデルを分割すべきか検証する（資料『少頭数/多頭数でモデル分割』の是非）。

主張(NotebookLM資料): 少頭数レース(8頭以下)と多頭数レース(13頭以上)は決まり方が
違うので、モデルを分けて重要特徴量に別々の重みを付けると穴馬を拾える。

検証設計:
  ・recall@7 の生値は頭数で自明に動く(7頭立てならtop7=全馬でrecall=1.0)ので比較に使えない。
    公平な指標は **モデル - 人気** の差分(=モデルが市場に上乗せした分)。
  ・まず現行の単一モデルで頭数帯別の上乗せを測る(分割の余地があるか)。
  ・余地があれば頭数帯別に学習した専用モデルと単一モデルを同じholdoutで比較する。
  ・学習/検証の窓は build_ltr_model.py の設定をそのまま流用(時系列分割・リーク無し)。

Usage:
  python scripts/ltr_fieldsize_split_backtest.py            # 診断のみ(学習しない)
  python scripts/ltr_fieldsize_split_backtest.py --train    # 分割モデルを学習して比較
"""
import os
import sys
import io
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd
import lightgbm as lgb

from scripts import build_ltr_model as B

# 頭数帯: 資料の主張(8頭以下/13頭以上)に合わせつつ中間帯も見る
BANDS = [('少頭数(〜9頭)', 5, 9), ('中間(10-12頭)', 10, 12), ('多頭数(13頭〜)', 13, 99)]


def _recall_gap(df, pred_col='pred'):
    """レース群に対する (モデルrecall@7, 人気recall@7, 上乗せpp, R数)。"""
    hit_m = hit_n = 0
    t3m, t3n = [], []
    total = 0
    for _, grp in df.groupby('race_key'):
        top3 = set(grp[grp['chakujun'] <= 3]['umaban'])
        winner = set(grp[grp['chakujun'] == 1]['umaban'])
        if not top3 or not winner:
            continue
        top7m = set(grp.nlargest(7, pred_col)['umaban'])
        top7n = set(grp.nsmallest(7, 'ninki')['umaban'])
        hit_m += int(bool(winner & top7m))
        hit_n += int(bool(winner & top7n))
        t3m.append(len(top3 & top7m) / len(top3))
        t3n.append(len(top3 & top7n) / len(top3))
        total += 1
    if not total:
        return None
    wm, wn = hit_m / total, hit_n / total
    return {'n': total, 'win_m': wm, 'win_n': wn, 'win_gap': (wm - wn) * 100,
            'top3_m': float(np.mean(t3m)), 'top3_n': float(np.mean(t3n)),
            'top3_gap': (float(np.mean(t3m)) - float(np.mean(t3n))) * 100}


def _prep(df):
    df = df.copy()
    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    cnt = df.groupby('race_key').size()
    df = df[df['race_key'].isin(cnt[cnt >= 5].index)]
    df['_field'] = df.groupby('race_key')['umaban'].transform('size')
    return df


def _fit(train_df, val_df):
    tr = train_df.sort_values('race_key')
    va = val_df.sort_values('race_key')
    ds_tr = lgb.Dataset(tr[B.FEATURES].values.astype(np.float64),
                        label=tr['label'].values,
                        group=tr.groupby('race_key', sort=False).size().values,
                        feature_name=B.FEATURES)
    ds_va = lgb.Dataset(va[B.FEATURES].values.astype(np.float64),
                        label=va['label'].values,
                        group=va.groupby('race_key', sort=False).size().values,
                        feature_name=B.FEATURES, reference=ds_tr)
    params = {'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [3, 7],
              'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
              'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
              'verbose': -1}
    return lgb.train(params, ds_tr, num_boost_round=600, valid_sets=[ds_va],
                     callbacks=[lgb.early_stopping(50, verbose=False)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train', action='store_true', help='頭数帯別モデルを学習して比較する')
    args = ap.parse_args()

    print('データ読込＋特徴量生成中...', file=sys.stderr)
    # build_ltr_model.main() と同じ前処理パイプラインをそのまま踏襲する
    # (自前で作ると特徴量定義がズレて比較にならない)
    df = B.load_data()
    df = B.compute_corrected_time(df)
    df = B.compute_rolling_features(df)
    df = B.compute_trainer_course(df)
    df = B.compute_jockey_course(df)
    df = B.compute_jockey_dist(df)
    df = df[df['year'].astype(int) >= 2016].copy()
    df = B.encode_features(df)
    df = B.compute_race_ranks(df)
    df = _prep(df)
    yi = df['year'].astype(int)
    train_df = df[yi <= B.TRAIN_END]
    val_df = df[yi == B.VAL_YEAR]
    test_df = df[yi >= B.TEST_FROM]
    print(f'train {len(train_df):,} / val {len(val_df):,} / test {len(test_df):,}\n')

    print('=== ① 現行の単一モデルは頭数帯でムラがあるか ===')
    print('（recall@7の生値でなく「モデル−人気」の上乗せppで比較）\n')
    base = _fit(train_df, val_df)
    test_df = test_df.copy()
    test_df['pred'] = base.predict(test_df[B.FEATURES].values.astype(np.float64))

    rows = []
    for lbl, lo, hi in BANDS:
        sub = test_df[(test_df['_field'] >= lo) & (test_df['_field'] <= hi)]
        r = _recall_gap(sub)
        if not r:
            continue
        rows.append((lbl, r))
        print(f"  {lbl:14s} {r['n']:>6,}R  勝ち馬: モデル{r['win_m']:.3f} 人気{r['win_n']:.3f} "
              f"上乗せ{r['win_gap']:+.2f}pp / 3着内 上乗せ{r['top3_gap']:+.2f}pp")

    gaps = [r['win_gap'] for _, r in rows]
    spread = max(gaps) - min(gaps)
    print(f"\n  帯間の上乗せ差(最大-最小): {spread:.2f}pp")
    if spread < 0.5:
        print('  → ムラが小さい。頭数で分けても得るものは無さそう。')
    else:
        print('  → ムラあり。分割で改善する余地がありうる。')

    if not args.train:
        print('\n(--train を付けると頭数帯別モデルを学習して単一モデルと比較します)')
        return

    print('\n=== ② 頭数帯別モデル vs 単一モデル(同じholdoutで比較) ===')
    tot_s = tot_b = tot_n = 0
    for lbl, lo, hi in BANDS:
        tr = train_df[(train_df['_field'] >= lo) & (train_df['_field'] <= hi)]
        va = val_df[(val_df['_field'] >= lo) & (val_df['_field'] <= hi)]
        te = test_df[(test_df['_field'] >= lo) & (test_df['_field'] <= hi)]
        if len(tr) < 5000 or te.empty:
            print(f'  {lbl}: 標本不足でスキップ')
            continue
        m = _fit(tr, va)
        te = te.copy()
        te['pred_split'] = m.predict(te[B.FEATURES].values.astype(np.float64))
        r_b = _recall_gap(te, 'pred')
        r_s = _recall_gap(te, 'pred_split')
        print(f"  {lbl:14s} {r_b['n']:>6,}R  単一{r_b['win_m']:.4f} → 分割{r_s['win_m']:.4f}"
              f"  ({(r_s['win_m']-r_b['win_m'])*100:+.2f}pp)")
        tot_s += r_s['win_m'] * r_b['n']
        tot_b += r_b['win_m'] * r_b['n']
        tot_n += r_b['n']
    if tot_n:
        print(f"\n  全体加重: 単一{tot_b/tot_n:.4f} → 分割{tot_s/tot_n:.4f} "
              f"({(tot_s-tot_b)/tot_n*100:+.2f}pp)")
        print('  ※ +0.3pp未満なら運用コスト(モデル2倍)に見合わない＝不採用が妥当')


if __name__ == '__main__':
    main()
