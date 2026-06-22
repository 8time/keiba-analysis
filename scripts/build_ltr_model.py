# -*- coding: utf-8 -*-
"""
LightGBM LambdaRank 妙味ランキングモデルの学習 — scripts/build_ltr_model.py

検証済みエッジのみを特徴量に使用。recall@7(勝ち馬を上位7頭に入れる)を最適化。
補正タイム: リーク防止のため各レース時点での過去走のみからH7を再計算。
禁止: kyakushitsu(事後リーク), PCI乖離(織込済), 展開恩恵(織込済), 巻き返し(過剰人気)。

Usage: python scripts/build_ltr_model.py
Output: data/ltr_model.lgb, data/ltr_meta.json
"""
import os
import sys
import sqlite3
import json
import time as _time

import numpy as np
import pandas as pd
import lightgbm as lgb

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
OUT_MODEL = os.path.join(ROOT, 'data', 'ltr_model.lgb')
OUT_META = os.path.join(ROOT, 'data', 'ltr_meta.json')

FEATURES = [
    'ninki', 'log_odds', 'umaban', 'futan',
    'bataiju', 'zogen', 'sex_code', 'age',
    'field_size', 'is_handicap', 'surface_code', 'kyori', 'baba_code',
    'h7_fig', 'h7_rank', 'spurt_mean3', 'spurt_rank',
    'prior_top3_rate', 'avg_chaku5',
    'jyo_code', 'race_num_code', 'cushion', 'dirt_moisture',
    'trainer_jyo_t3', 'jockey_jyo_win', 'jockey_dist_win',
]

BASELINE_FROM = 1990
TRAIN_END = 2023
VAL_YEAR = 2024
TEST_FROM = 2025


def _connect_ro(path):
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit('DB locked')


def _to_sec(t):
    if not t or len(t) != 4 or not t.isdigit() or t == '0000':
        return np.nan
    return int(t[0]) * 60 + int(t[1:3]) + int(t[3]) / 10.0


def load_data():
    con = _connect_ro(JV_DB)
    print('Loading race results...', file=sys.stderr)
    df = pd.read_sql("""
        SELECT r.race_key, r.ketto_num, r.umaban, r.chakujun, r.ninki, r.win_odds,
               r.bataiju, r.zogen, r.ato3f AS horse_ato3f, r.sex, r.age, r.futan, r.time,
               r.trainer_code, r.jockey_code,
               ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori, ra.shusso_tosu,
               ra.juryo, ra.baba_shiba, ra.baba_dirt, ra.race_num,
               tc.cushion, tc.dirt_moisture
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        LEFT JOIN track_cond tc ON ra.year = tc.year AND ra.monthday = tc.monthday AND ra.jyo = tc.jyo
        WHERE ra.surface IN ('芝','ダート')
          AND CAST(ra.year AS INTEGER) >= {base}
          AND r.chakujun > 0 AND r.chakujun <= 28
    """.format(base=BASELINE_FROM), con)
    con.close()
    print(f'  loaded {len(df):,} rows', file=sys.stderr)
    return df


def compute_corrected_time(df):
    print('Computing corrected times...', file=sys.stderr)
    df['sec'] = df['time'].apply(_to_sec)
    df['day'] = df['year'].astype(int) * 10000 + df['monthday'].astype(int)
    df['kyori_int'] = df['kyori'].astype(int)

    bl = (df.dropna(subset=['sec'])
          .groupby(['surface', 'kyori_int'])['sec']
          .agg(bl_med='median', bl_n='count')
          .reset_index())
    bl = bl[bl['bl_n'] >= 30][['surface', 'kyori_int', 'bl_med']]
    df = df.merge(bl, on=['surface', 'kyori_int'], how='left')
    df['raw_dev'] = df['sec'] - df['bl_med']

    tb = (df.dropna(subset=['raw_dev'])
          .groupby(['day', 'jyo', 'surface'])['raw_dev']
          .agg(tb_med='median', tb_n='count')
          .reset_index())
    tb = tb[tb['tb_n'] >= 4][['day', 'jyo', 'surface', 'tb_med']]
    df = df.merge(tb, on=['day', 'jyo', 'surface'], how='left')
    df['corrected'] = df['raw_dev'] - df['tb_med']
    df.drop(columns=['bl_med', 'raw_dev', 'tb_med', 'bl_n', 'tb_n'],
            errors='ignore', inplace=True)
    valid_ct = df['corrected'].notna().sum()
    print(f'  valid corrected: {valid_ct:,}', file=sys.stderr)
    return df


def compute_rolling_features(df):
    """H7(ループ) + spurt/prior_top3/avg_chaku(pandas transform)"""
    print('Computing rolling features (H7 loop)...', file=sys.stderr)
    df = df.sort_values(['ketto_num', 'day', 'race_num']).reset_index(drop=True)
    n = len(df)

    kettos = df['ketto_num'].values
    corr = df['corrected'].values.astype(np.float64)
    surfs = df['surface'].values

    h7 = np.full(n, np.nan)
    prev_k = None
    hist = []  # [(corrected, surface)]
    for i in range(n):
        k = kettos[i]
        if k != prev_k:
            hist = []
            prev_k = k
        prior7 = hist[-7:]
        same = [c for c, s in prior7 if s == surfs[i] and c == c]
        if same:
            h7[i] = min(same)
        c = corr[i]
        if c == c:
            hist.append((c, surfs[i]))
    df['h7_fig'] = h7

    print('Computing rolling features (pandas)...', file=sys.stderr)
    df['ato3f_v'] = df['horse_ato3f'].where(df['horse_ato3f'] > 0)
    df['is_top3'] = (df['chakujun'] <= 3).astype(float)
    df['chaku_f'] = df['chakujun'].astype(float)

    df['spurt_mean3'] = (df.groupby('ketto_num')['ato3f_v']
                         .transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean()))
    df['prior_top3_rate'] = (df.groupby('ketto_num')['is_top3']
                             .transform(lambda x: x.shift(1).rolling(7, min_periods=1).mean()))
    df['avg_chaku5'] = (df.groupby('ketto_num')['chaku_f']
                        .transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean()))
    df.drop(columns=['ato3f_v', 'is_top3', 'chaku_f'], inplace=True)
    return df


def encode_features(df):
    # jravan.db: sex='1'(牡)/'2'(牝)/'3'(セ), juryo='3'(ハンデ),
    #            baba='1'(良)/'2'(稍重)/'3'(重)/'4'(不良)/'0'(不明)
    df['sex_code'] = pd.to_numeric(df['sex'], errors='coerce').fillna(0).astype(int)
    df['surface_code'] = df['surface'].str.contains('ダ', na=False).astype(int)
    _bs = pd.to_numeric(df['baba_shiba'], errors='coerce').fillna(0)
    _bd = pd.to_numeric(df['baba_dirt'], errors='coerce').fillna(0)
    df['baba_code'] = np.where(df['surface_code'] == 0, _bs, _bd).astype(int)
    df['is_handicap'] = (df['juryo'].astype(str) == '3').astype(int)
    df['field_size'] = df['shusso_tosu'].astype(int)
    df['log_odds'] = np.log1p(pd.to_numeric(df['win_odds'], errors='coerce').fillna(0))
    df['jyo_code'] = pd.to_numeric(df['jyo'], errors='coerce').fillna(0).astype(int)
    df['race_num_code'] = pd.to_numeric(df['race_num'], errors='coerce').fillna(0).astype(int)
    # cushion/dirt_moisture are from track_cond LEFT JOIN (2021+ only, NaN for older)
    df['cushion'] = pd.to_numeric(df['cushion'], errors='coerce')
    df['dirt_moisture'] = pd.to_numeric(df['dirt_moisture'], errors='coerce')
    return df


def compute_trainer_course(df):
    """厩舎×競馬場(jyo)の直近複勝率(shift(1).rolling20,min5)=リーク無。
    『当コース成績』は検証エッジ(全体勝率は織込み済み・auto_feature_searchで採用)。"""
    print('Computing trainer-course form...', file=sys.stderr)
    df['_t3'] = (df['chakujun'] <= 3).astype(float)
    df['_tcj'] = df['trainer_code'].astype(str) + '|' + df['jyo'].astype(str)
    tmp = df[['_tcj', 'day', 'race_num', '_t3']].sort_values(['_tcj', 'day', 'race_num'])
    df['trainer_jyo_t3'] = (tmp.groupby('_tcj', sort=False)['_t3']
                            .transform(lambda x: x.shift(1).rolling(20, min_periods=5).mean())
                            .reindex(df.index))
    df.drop(columns=['_t3', '_tcj'], inplace=True)
    return df


def compute_jockey_course(df):
    """騎手×競馬場(jyo)の直近勝率(shift(1).rolling60,min15)=リーク無。
    当場勝率はauto_feature_searchのseed頑健性で採用(複勝でなく勝率がrecall@7に効く)。"""
    print('Computing jockey-course form...', file=sys.stderr)
    df['_w'] = (df['chakujun'] == 1).astype(float)
    df['_jcj'] = df['jockey_code'].astype(str) + '|' + df['jyo'].astype(str)
    tmp = df[['_jcj', 'day', 'race_num', '_w']].sort_values(['_jcj', 'day', 'race_num'])
    df['jockey_jyo_win'] = (tmp.groupby('_jcj', sort=False)['_w']
                            .transform(lambda x: x.shift(1).rolling(60, min_periods=15).mean())
                            .reindex(df.index))
    df.drop(columns=['_w', '_jcj'], inplace=True)
    return df


def compute_jockey_dist(df):
    """騎手×距離帯の直近勝率(shift(1).rolling50,min12)=リーク無。auto_feature_searchで採用。
    距離帯: S<=1400 / M1401-1800 / L1801-2200 / X2201+。"""
    print('Computing jockey-distance form...', file=sys.stderr)
    ky = pd.to_numeric(df['kyori'], errors='coerce')
    db = np.where(ky <= 1400, 'S', np.where(ky <= 1800, 'M', np.where(ky <= 2200, 'L', 'X')))
    df['_w'] = (df['chakujun'] == 1).astype(float)
    df['_jkd'] = df['jockey_code'].astype(str) + '|' + pd.Series(db, index=df.index)
    tmp = df[['_jkd', 'day', 'race_num', '_w']].sort_values(['_jkd', 'day', 'race_num'])
    df['jockey_dist_win'] = (tmp.groupby('_jkd', sort=False)['_w']
                             .transform(lambda x: x.shift(1).rolling(50, min_periods=12).mean())
                             .reindex(df.index))
    df.drop(columns=['_w', '_jkd'], inplace=True)
    return df


def compute_race_ranks(df):
    df['h7_rank'] = df.groupby('race_key')['h7_fig'].rank(method='min', na_option='bottom')
    df['spurt_rank'] = df.groupby('race_key')['spurt_mean3'].rank(method='min', na_option='bottom')
    return df


def evaluate(model, test_df, features):
    X = test_df[features].values.astype(np.float64)
    test_df = test_df.copy()
    test_df['pred'] = model.predict(X)

    win_hit_m, win_hit_n, top3_r_m, top3_r_n, total = 0, 0, [], [], 0
    for _, grp in test_df.groupby('race_key'):
        top3 = set(grp[grp['chakujun'] <= 3]['umaban'])
        winner = set(grp[grp['chakujun'] == 1]['umaban'])
        if not top3 or not winner:
            continue
        top7m = set(grp.nlargest(7, 'pred')['umaban'])
        top7n = set(grp.nsmallest(7, 'ninki')['umaban'])
        win_hit_m += int(bool(winner & top7m))
        win_hit_n += int(bool(winner & top7n))
        top3_r_m.append(len(top3 & top7m) / len(top3))
        top3_r_n.append(len(top3 & top7n) / len(top3))
        total += 1

    print(f'\n{"="*50}', file=sys.stderr)
    print(f'Test races: {total:,}', file=sys.stderr)
    wr_m = win_hit_m / total if total else 0
    wr_n = win_hit_n / total if total else 0
    t3_m = np.mean(top3_r_m) if top3_r_m else 0
    t3_n = np.mean(top3_r_n) if top3_r_n else 0
    print(f'Win recall@7  Model: {wr_m:.4f}  Ninki: {wr_n:.4f}  diff: {(wr_m-wr_n)*100:+.2f}pp',
          file=sys.stderr)
    print(f'Top3 recall@7 Model: {t3_m:.4f}  Ninki: {t3_n:.4f}  diff: {(t3_m-t3_n)*100:+.2f}pp',
          file=sys.stderr)

    imp = model.feature_importance(importance_type='gain')
    fi = sorted(zip(features, imp), key=lambda x: -x[1])
    print(f'\nFeature importance (gain):', file=sys.stderr)
    for name, gain in fi:
        print(f'  {name:20s} {gain:>10.0f}', file=sys.stderr)

    return {'win_recall7': wr_m, 'top3_recall7': t3_m,
            'win_recall7_ninki': wr_n, 'top3_recall7_ninki': t3_n}


def train_and_evaluate(df):
    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    race_cnt = df.groupby('race_key').size()
    df = df[df['race_key'].isin(race_cnt[race_cnt >= 5].index)]

    yi = df['year'].astype(int)
    train_df = df[yi <= TRAIN_END].sort_values('race_key')
    val_df = df[yi == VAL_YEAR].sort_values('race_key')
    test_df = df[yi >= TEST_FROM].sort_values('race_key')
    print(f'Train {len(train_df):,} / Val {len(val_df):,} / Test {len(test_df):,}', file=sys.stderr)

    train_g = train_df.groupby('race_key', sort=False).size().values
    val_g = val_df.groupby('race_key', sort=False).size().values

    X_tr = train_df[FEATURES].values.astype(np.float64)
    X_va = val_df[FEATURES].values.astype(np.float64)

    ds_tr = lgb.Dataset(X_tr, label=train_df['label'].values,
                        group=train_g, feature_name=FEATURES)
    ds_va = lgb.Dataset(X_va, label=val_df['label'].values,
                        group=val_g, feature_name=FEATURES, reference=ds_tr)

    params = {
        'objective': 'lambdarank',
        'metric': 'ndcg',
        'ndcg_eval_at': [3, 7],
        'learning_rate': 0.05,
        'num_leaves': 31,
        'min_data_in_leaf': 50,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
    }

    model = lgb.train(params, ds_tr, num_boost_round=1000, valid_sets=[ds_va],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)])

    os.makedirs(os.path.dirname(OUT_MODEL), exist_ok=True)
    model.save_model(OUT_MODEL)

    metrics = evaluate(model, test_df, FEATURES)
    meta = {
        'features': FEATURES,
        'train_end': TRAIN_END, 'val_year': VAL_YEAR,
        'n_train': len(train_df), 'n_val': len(val_df), 'n_test': len(test_df),
        'best_iteration': model.best_iteration,
        'metrics': metrics,
    }
    with open(OUT_META, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return model


def main():
    t0 = _time.time()
    df = load_data()
    df = compute_corrected_time(df)
    df = compute_rolling_features(df)
    df = compute_trainer_course(df)
    df = compute_jockey_course(df)
    df = compute_jockey_dist(df)
    df = df[df['year'].astype(int) >= 2016].copy()
    df = encode_features(df)
    df = compute_race_ranks(df)
    train_and_evaluate(df)
    print(f'\nDone in {_time.time()-t0:.0f}s — model saved to {OUT_MODEL}', file=sys.stderr)


if __name__ == '__main__':
    main()
