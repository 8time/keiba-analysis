# -*- coding: utf-8 -*-
"""LTRモデルの鮮度更新（学習窓を1年前進）と、現行モデルとの公平な比較。

背景: data/ltr_model.lgb は train≤2023 / val2024 / test2025+ で学習されている。
      jravan.dbは2026-06-21まであるので、**2024年の1年分が学習に使われていない**。
      窓を1年前進(train≤2024 / val2025)すれば学習データが増えるが、
      その代わり2025年が「きれいなholdout」でなくなる＝再検証可能性を1年分失う。
      この取引が割に合うかを、**両モデルにとって未知の2026年**だけで判定する。

比較の設計(ここが肝):
  現行モデル  … train≤2023 / val2024   → 2026年は未知
  候補モデル  … train≤2024 / val2025   → 2026年は未知
  よって 2026年(1-6月)は両者にとって公平な土俵。ここでのrecall@7で勝った方を採る。
  ※2025年で比較してはいけない(候補にとってvalであり、現行にとってのみ未知＝不公平)。

安全策:
  - 本番の data/ltr_model.lgb は**上書きしない**。候補は data/ltr_model_candidate.lgb に出す。
  - 採否は人が判断して差し替える(--promote で明示的に昇格。バックアップを取る)。
  - build_ltr_model.py は一切変更せず import して再利用する(auto_feature_search.py と同じ流儀)。

Usage:
  python scripts/refresh_ltr_model.py            # 候補を作って2026で比較(本番は触らない)
  python scripts/refresh_ltr_model.py --promote  # 比較後、候補を本番に昇格(バックアップ付き)
"""
import os
import sys
import json
import shutil
import time as _time

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

import scripts.build_ltr_model as bm  # 既存パイプラインを再利用(変更しない)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR_MODEL = os.path.join(ROOT, 'data', 'ltr_model.lgb')
CUR_META = os.path.join(ROOT, 'data', 'ltr_meta.json')
CAND_MODEL = os.path.join(ROOT, 'data', 'ltr_model_candidate.lgb')
CAND_META = os.path.join(ROOT, 'data', 'ltr_meta_candidate.json')

NEW_TRAIN_END = 2024   # 現行は2023
NEW_VAL_YEAR = 2025    # 現行は2024
JUDGE_YEAR = 2026      # 両モデルにとって未知＝公平な比較窓


def recall_at7(model, df, features):
    """勝ち馬/3着内馬を予測上位7頭に入れられた率。人気順ベースラインも併記。"""
    d = df.copy()
    d['pred'] = model.predict(d[features].values.astype(np.float64))
    win_m = win_n = 0
    t3_m, t3_n = [], []
    tot = 0
    for _, g in d.groupby('race_key'):
        top3 = set(g[g['chakujun'] <= 3]['umaban'])
        winner = set(g[g['chakujun'] == 1]['umaban'])
        if not top3 or not winner:
            continue
        m7 = set(g.nlargest(7, 'pred')['umaban'])
        n7 = set(g.nsmallest(7, 'ninki')['umaban'])
        win_m += int(bool(winner & m7))
        win_n += int(bool(winner & n7))
        t3_m.append(len(top3 & m7) / len(top3))
        t3_n.append(len(top3 & n7) / len(top3))
        tot += 1
    return {'races': tot,
            'win_recall7': win_m / tot if tot else 0.0,
            'top3_recall7': float(np.mean(t3_m)) if t3_m else 0.0,
            'win_recall7_ninki': win_n / tot if tot else 0.0,
            'top3_recall7_ninki': float(np.mean(t3_n)) if t3_n else 0.0}


def build_frame():
    """build_ltr_model と同一手順で特徴量フレームを作る(定義のズレを防ぐため関数を再利用)。"""
    df = bm.load_data()
    df = bm.compute_corrected_time(df)
    df = bm.compute_rolling_features(df)
    df = bm.compute_trainer_course(df)
    df = bm.compute_jockey_course(df)
    df = bm.compute_jockey_dist(df)
    df = df[df['year'].astype(int) >= 2016].copy()
    df = bm.encode_features(df)
    df = bm.compute_race_ranks(df)
    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    cnt = df.groupby('race_key').size()
    return df[df['race_key'].isin(cnt[cnt >= 5].index)]


def train_candidate(df):
    yi = df['year'].astype(int)
    tr = df[yi <= NEW_TRAIN_END].sort_values('race_key')
    va = df[yi == NEW_VAL_YEAR].sort_values('race_key')
    print(f'候補モデル: train {len(tr):,}行(≤{NEW_TRAIN_END}) / val {len(va):,}行({NEW_VAL_YEAR})',
          file=sys.stderr)
    ds_tr = lgb.Dataset(tr[bm.FEATURES].values.astype(np.float64), label=tr['label'].values,
                        group=tr.groupby('race_key', sort=False).size().values,
                        feature_name=bm.FEATURES)
    ds_va = lgb.Dataset(va[bm.FEATURES].values.astype(np.float64), label=va['label'].values,
                        group=va.groupby('race_key', sort=False).size().values,
                        feature_name=bm.FEATURES, reference=ds_tr)
    params = {
        'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [3, 7],
        'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5, 'verbose': -1,
    }
    model = lgb.train(params, ds_tr, num_boost_round=1000, valid_sets=[ds_va],
                      callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)])
    model.save_model(CAND_MODEL)
    return model, len(tr), len(va)


def main():
    t0 = _time.time()
    promote = '--promote' in sys.argv
    df = build_frame()
    judge = df[df['year'].astype(int) == JUDGE_YEAR]
    if len(judge) == 0:
        raise SystemExit(f'{JUDGE_YEAR}年のデータが無い。比較不能。')

    cand, n_tr, n_va = train_candidate(df)
    cur = lgb.Booster(model_file=CUR_MODEL)

    a = recall_at7(cur, judge, bm.FEATURES)
    b = recall_at7(cand, judge, bm.FEATURES)
    print('\n' + '=' * 78)
    print(f'公平比較: {JUDGE_YEAR}年 {a["races"]:,}レース (両モデルにとって未知)')
    print('=' * 78)
    print(f"{'モデル':34s} {'勝ち馬recall@7':>13s} {'3着内recall@7':>13s}")
    print(f"{'人気順(ベースライン)':34s} {a['win_recall7_ninki']:12.4f} "
          f"{a['top3_recall7_ninki']:12.4f}")
    print(f"{'現行 train≤2023/val2024':34s} {a['win_recall7']:12.4f} {a['top3_recall7']:12.4f}")
    print(f"{'候補 train≤2024/val2025':34s} {b['win_recall7']:12.4f} {b['top3_recall7']:12.4f}")
    dw = (b['win_recall7'] - a['win_recall7']) * 100
    dt = (b['top3_recall7'] - a['top3_recall7']) * 100
    print(f"\n  差分(候補 − 現行): 勝ち馬 {dw:+.2f}pp / 3着内 {dt:+.2f}pp")
    better = dw > 0 and dt > 0
    print(f"  判定: {'✅候補が両指標で上回る' if better else '❌候補は上回らない(現行維持を推奨)'}")
    print(f"  ※採用すると2025年がholdoutでなくなる(再検証可能性を1年失う)。"
          f"差分が誤差なら現行維持が正解。")

    meta = {'train_end': NEW_TRAIN_END, 'val_year': NEW_VAL_YEAR,
            'judge_year': JUDGE_YEAR, 'features': bm.FEATURES,
            'n_train': n_tr, 'n_val': n_va,
            'best_iteration': cand.best_iteration,
            'built_at': _time.strftime('%Y-%m-%d %H:%M:%S'),
            f'judge{JUDGE_YEAR}_current': a, f'judge{JUDGE_YEAR}_candidate': b,
            'delta_win_pp': dw, 'delta_top3_pp': dt, 'candidate_better': bool(better)}
    with open(CAND_META, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f'\n候補モデル → {CAND_MODEL}\n候補meta   → {CAND_META}')

    if promote:
        if not better:
            print('\n⚠ 候補が上回っていないため昇格しない(--promoteは無視)。')
        else:
            ts = _time.strftime('%Y%m%d_%H%M%S')
            shutil.copy2(CUR_MODEL, CUR_MODEL + f'.bak_{ts}')
            shutil.copy2(CUR_META, CUR_META + f'.bak_{ts}')
            shutil.copy2(CAND_MODEL, CUR_MODEL)
            with open(CUR_META, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            print(f'\n✅ 昇格した(バックアップ: *.bak_{ts})。Streamlitは完全再起動が必要。')
    print(f'done in {_time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
