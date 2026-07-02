# -*- coding: utf-8 -*-
"""②Glickoレーティングを特徴量に足すと当たるか ―― 資料p6「レーティング系」の検証。

チェス式Glicko(強い馬を負かした馬は強い)を過去レースから逐次計算(リーク無し=各レースの
"事前"レーティングのみ特徴に使う)。既存 build_ltr_model の特徴量・学習・評価を再利用し、
ベースライン(現行26特徴) vs +Glicko でholdout recall@7を比較。
採用ゲート(auto_feature_searchの防護柵と同型): val2024とtest2025の両方でrecall@7が改善+マージン。
  超えれば本番LTRに追加、超えねば「馬の強さも人気に織込み済み」で却下(過去6候補と同じ運命の確認)。
"""
import os
import sys
import math
import time as _time

import numpy as np
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import scripts.build_ltr_model as J

Q = math.log(10) / 400.0
C2 = 34.0 ** 2   # レース間のRD(不確実性)増加
PI2 = math.pi ** 2


def build_glicko(df):
    """リーク無しGlicko-1: 各馬の"事前"レーティングを cand_glicko に。"""
    print('Computing Glicko ratings...', file=sys.stderr)
    df = df.sort_values(['day', 'race_num', 'race_key']).reset_index(drop=True)
    ket = df['ketto_num'].values
    chaku = df['chakujun'].values.astype(float)
    rk = df['race_key'].values
    n = len(df)
    pre = np.full(n, np.nan)
    R = {}   # ketto -> [rating, rd]
    i = 0
    while i < n:
        j = i
        cur_rk = rk[i]
        while j < n and rk[j] == cur_rk:
            j += 1
        rows = range(i, j)
        cur = []
        for k in rows:
            r, rd = R.get(ket[k], (1500.0, 350.0))
            rd = min(math.sqrt(rd * rd + C2), 350.0)   # 前走からの不確実性増
            R[ket[k]] = (r, rd)
            pre[k] = r
            cur.append((k, ket[k], chaku[k], r, rd))
        newv = {}
        for k, kt, ch, r, rd in cur:
            d2_inv = 0.0
            delta = 0.0
            for k2, kt2, ch2, r2, rd2 in cur:
                if k2 == k:
                    continue
                g = 1.0 / math.sqrt(1 + 3 * Q * Q * rd2 * rd2 / PI2)
                E = 1.0 / (1 + 10 ** (-g * (r - r2) / 400.0))
                s = 1.0 if ch < ch2 else (0.5 if ch == ch2 else 0.0)
                d2_inv += Q * Q * g * g * E * (1 - E)
                delta += g * (s - E)
            if d2_inv > 0:
                denom = 1.0 / (rd * rd) + d2_inv
                newv[kt] = (r + (Q / denom) * delta, math.sqrt(1.0 / denom))
        R.update(newv)
        i = j
    df['cand_glicko'] = pre
    df['cand_glicko_rank'] = df.groupby('race_key')['cand_glicko'].rank(method='min',
                                                                        na_option='bottom')
    print(f'  glicko computed (non-null {np.isfinite(pre).sum():,})', file=sys.stderr)
    return df


def train_eval(df, feats, tag):
    yi = df['year'].astype(int)
    tr = df[yi <= 2023].sort_values('race_key')
    va = df[yi == 2024].sort_values('race_key')
    te = df[yi >= 2025].sort_values('race_key')
    g_tr = tr.groupby('race_key', sort=False).size().values
    g_va = va.groupby('race_key', sort=False).size().values
    ds_tr = lgb.Dataset(tr[feats].values.astype(np.float64), label=tr['label'].values,
                        group=g_tr, feature_name=feats)
    ds_va = lgb.Dataset(va[feats].values.astype(np.float64), label=va['label'].values,
                        group=g_va, feature_name=feats, reference=ds_tr)
    params = {'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [3, 7],
              'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
              'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
              'verbose': -1, 'seed': 42}
    model = lgb.train(params, ds_tr, num_boost_round=1000, valid_sets=[ds_va],
                      callbacks=[lgb.early_stopping(50)])
    mv = J.evaluate(model, va, feats)
    mt = J.evaluate(model, te, feats)
    print(f'[{tag}] VAL win_r@7={mv["win_recall7"]:.4f} top3={mv["top3_recall7"]:.4f} | '
          f'TEST win_r@7={mt["win_recall7"]:.4f} top3={mt["top3_recall7"]:.4f}', file=sys.stderr)
    return mv, mt


def main():
    t0 = _time.time()
    df = J.load_data()
    df = df[(df['jyo'].astype(str).str.zfill(2) <= '10') &
            (df['jyo'].astype(str).str.zfill(2) >= '01')]
    df = df[df['year'].astype(int) >= 2015].copy()
    df = J.compute_corrected_time(df)
    df = J.compute_rolling_features(df)
    df = J.compute_trainer_course(df)
    df = J.compute_jockey_course(df)
    df = J.compute_jockey_dist(df)
    df = J.encode_features(df)
    df = J.compute_race_ranks(df)
    df = build_glicko(df)
    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    rc = df.groupby('race_key').size()
    df = df[df['race_key'].isin(rc[rc >= 5].index)]

    base = J.FEATURES
    plus = base + ['cand_glicko', 'cand_glicko_rank']
    print('\n=== ベースライン(26特徴) ===', file=sys.stderr)
    bv, bt = train_eval(df, base, 'base')
    print('\n=== +Glicko ===', file=sys.stderr)
    gv, gt = train_eval(df, plus, '+glicko')

    dv = (gv['win_recall7'] - bv['win_recall7']) * 100
    dt = (gt['win_recall7'] - bt['win_recall7']) * 100
    dv3 = (gv['top3_recall7'] - bv['top3_recall7']) * 100
    dt3 = (gt['top3_recall7'] - bt['top3_recall7']) * 100
    print(f'\n{"="*56}', file=sys.stderr)
    print(f'Glicko効果 win_r@7: VAL{dv:+.2f}pp / TEST{dt:+.2f}pp | '
          f'top3: VAL{dv3:+.2f}pp / TEST{dt3:+.2f}pp', file=sys.stderr)
    print('採用ゲート: val+test両方でwin or top3が+0.2pp以上改善', file=sys.stderr)
    win_ok = dv >= 0.2 and dt >= 0.2
    t3_ok = dv3 >= 0.2 and dt3 >= 0.2
    if win_ok or t3_ok:
        print('→ ✅ 採用候補(本番LTRに追加検討)', file=sys.stderr)
    else:
        print('→ ❌ 却下: 馬の強さも人気に織込み済み(過去6候補と同じ)', file=sys.stderr)
    print(f'\nDone in {_time.time()-t0:.0f}s', file=sys.stderr)


if __name__ == '__main__':
    main()
