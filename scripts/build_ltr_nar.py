# -*- coding: utf-8 -*-
"""NAR(南関)専用LTRモデル ―― 資料p5「9セグメント」の実践。

今日、JRA学習のLTRはNAR分布外として抑制した(app.py)。その"空白"を、
NAR(南関42-45)データだけで学習した専用LightGBM LambdaRankで埋められるかを検証。
既存 scripts/build_ltr_model.py の特徴量計算を再利用し、NARで無効な特徴
(log_odds=NAR win_odds全null / cushion・dirt_moisture=track_cond無 / surface_code=ほぼダ固定)
は外したNAR専用特徴で学習。

採用ゲート: holdout2025でモデルのrecall@7が人気ベースを上回る(win or top3どちらか+マージン)。
  超えれば ltr_ranker にNAR分岐を配線(今日の抑制を"専用モデル"に置換)。
  超えねば「NARは人気較正(POP_FUKU_NAR)で十分」と決着(それも正しい答え)。
"""
import os
import sys
import json
import sqlite3
import time as _time

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import scripts.build_ltr_model as J  # 特徴量計算を再利用

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
OUT_MODEL = os.path.join(ROOT, 'data', 'ltr_nar_model.lgb')
OUT_META = os.path.join(ROOT, 'data', 'ltr_nar_meta.json')

# NAR専用特徴(JRA版からlog_odds/surface_code/is_handicap/cushion/dirt_moistureを除外)
FEATURES_NAR = [
    'ninki', 'umaban', 'futan', 'bataiju', 'zogen', 'sex_code', 'age',
    'field_size', 'kyori', 'baba_code',
    'h7_fig', 'h7_rank', 'spurt_mean3', 'spurt_rank',
    'prior_top3_rate', 'avg_chaku5',
    'jyo_code', 'race_num_code',
    'trainer_jyo_t3', 'jockey_jyo_win', 'jockey_dist_win',
]
NAR_VENUES = ('42', '43', '44', '45')  # 浦和/船橋/大井/川崎
TRAIN_END, VAL_YEAR, TEST_FROM = 2023, 2024, 2025


def load_nar():
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
    ph = ','.join('?' * len(NAR_VENUES))
    df = pd.read_sql(f"""
        SELECT r.race_key, r.ketto_num, r.umaban, r.chakujun, r.ninki, r.win_odds,
               r.bataiju, r.zogen, r.ato3f AS horse_ato3f, r.sex, r.age, r.futan, r.time,
               r.trainer_code, r.jockey_code,
               ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori, ra.shusso_tosu,
               ra.juryo, ra.baba_shiba, ra.baba_dirt, ra.race_num,
               NULL AS cushion, NULL AS dirt_moisture
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE ra.jyo IN ({ph}) AND CAST(ra.year AS INTEGER) >= 2017
          AND r.chakujun > 0 AND r.chakujun <= 28
    """, con, params=NAR_VENUES)
    con.close()
    print(f'  NAR(南関) loaded {len(df):,} rows', file=sys.stderr)
    return df


def main():
    t0 = _time.time()
    df = load_nar()
    df = J.compute_corrected_time(df)
    df = J.compute_rolling_features(df)
    df = J.compute_trainer_course(df)
    df = J.compute_jockey_course(df)
    df = J.compute_jockey_dist(df)
    df = J.encode_features(df)
    df = J.compute_race_ranks(df)

    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    rc = df.groupby('race_key').size()
    df = df[df['race_key'].isin(rc[rc >= 5].index)]
    yi = df['year'].astype(int)
    tr, va, te = df[yi <= TRAIN_END].sort_values('race_key'), \
        df[yi == VAL_YEAR].sort_values('race_key'), df[yi >= TEST_FROM].sort_values('race_key')
    print(f'Train {len(tr):,} / Val {len(va):,} / Test {len(te):,}', file=sys.stderr)
    if len(te) < 2000 or len(tr) < 10000:
        print('⚠ データ不足の可能性', file=sys.stderr)

    g_tr = tr.groupby('race_key', sort=False).size().values
    g_va = va.groupby('race_key', sort=False).size().values
    ds_tr = lgb.Dataset(tr[FEATURES_NAR].values.astype(np.float64), label=tr['label'].values,
                        group=g_tr, feature_name=FEATURES_NAR)
    ds_va = lgb.Dataset(va[FEATURES_NAR].values.astype(np.float64), label=va['label'].values,
                        group=g_va, feature_name=FEATURES_NAR, reference=ds_tr)
    params = {'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [3, 7],
              'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
              'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5, 'verbose': -1}
    model = lgb.train(params, ds_tr, num_boost_round=1000, valid_sets=[ds_va],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)])

    m = J.evaluate(model, te, FEATURES_NAR)
    win_edge = (m['win_recall7'] - m['win_recall7_ninki']) * 100
    top3_edge = (m['top3_recall7'] - m['top3_recall7_ninki']) * 100
    print(f'\n{"="*50}', file=sys.stderr)
    print(f'採用ゲート: recall@7が人気を+0.5pp超で上回るか', file=sys.stderr)
    passed = win_edge >= 0.5 or top3_edge >= 0.5
    print(f'win_edge={win_edge:+.2f}pp / top3_edge={top3_edge:+.2f}pp → '
          + ('✅ 採用(NAR専用モデルを配線)' if passed else '❌ 却下(NARは人気較正で十分)'),
          file=sys.stderr)

    if passed:
        model.save_model(OUT_MODEL)
        with open(OUT_META, 'w', encoding='utf-8') as f:
            json.dump({'features': FEATURES_NAR, 'venues': list(NAR_VENUES),
                       'train_end': TRAIN_END, 'val_year': VAL_YEAR,
                       'n_train': len(tr), 'n_test': len(te), 'metrics': m,
                       'best_iteration': model.best_iteration}, f, ensure_ascii=False, indent=2)
        print(f'saved: {OUT_MODEL}', file=sys.stderr)
    print(f'\nDone in {_time.time()-t0:.0f}s', file=sys.stderr)


if __name__ == '__main__':
    main()
