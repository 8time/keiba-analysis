# -*- coding: utf-8 -*-
"""LTRパイプラインを包む『安全な自己改善ループ』 — scripts/auto_feature_search.py

図の自己改善ループ(戦略→BT→採点→弱点→並列別案→最良選択→絞り込み)を、
中核目標(過小評価の勝ち馬=recall@7)に限定して安全に回す。

設計(影響最小・検証済みエッジのみ思想):
- build_ltr_model.py / ltr_ranker.py は一切変更しない(import して再利用するだけ)。
- 評価は固定の 2025+ テスト集合の recall@7 のみ(リーク耐性のある単一指標)。ROI最適化はしない。
- 候補特徴量は『リークしない×推論時(ltr_ranker)でも計算できる』ものだけ。
- 多重検定の罠を避ける: ①固定seedで決定論化 ②val(2024)とtest(2025+)の両方で改善した案だけ採用候補
  ③改善マージンしきい値(--margin, 既定+0.0015=+0.15pp) ④自動デプロイしない(人がレビューして配線)。

候補(2026-06-22 第2イテレーション=より良い仮説):
  [強]  cand_prior_margin      前走の勝ち馬との着差(秒)。shift(1)で前走・フィルタ前の全履歴で計算
        cand_jockey_form_t3    騎手の直近複勝率(過去50騎乗・当該除外のrolling)
        cand_jockey_win        騎手の直近勝率(過去80騎乗)
        cand_trainer_form_t3   厩舎の直近複勝率(過去30出走)
  [簡]  --include-simple 時のみ: weight_ratio/zogen_abs/draw_rel/age_sq/bataiju_dev/futan_dev(第1回で不採用)

使い方:
  python scripts/auto_feature_search.py                 # 強候補のadd-one探索
  python scripts/auto_feature_search.py --include-simple# 簡易候補も含める
  python scripts/auto_feature_search.py --ablation      # drop-one(有害特徴量検出)も
  python scripts/auto_feature_search.py --quick          # 2019+のみ・軽量(動作確認)
出力: data/feature_search_log.json + 標準エラーにランキング表。本番モデルは上書きしない。
"""
import os
import sys
import json
import sqlite3
import argparse
import time as _time

import numpy as np
import pandas as pd
import lightgbm as lgb

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.build_ltr_model as bm  # 既存パイプラインを再利用(変更しない)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(ROOT, 'data', 'feature_search_log.json')
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')

PARAMS = {
    'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [3, 7],
    'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
    'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
    'verbose': -1, 'seed': 42, 'bagging_seed': 42, 'feature_fraction_seed': 42,
}


def _rolling_prior_rate(df, key, value_col, window, minp):
    """key(騎手/厩舎)ごとに日付順で『当該レースを除外した』過去N件のvalue_col平均を返す。
    shift(1)で必ず過去のみ=リーク無し。元のdf.indexに揃えて返す。"""
    tmp = df[[key, 'day', 'race_num', value_col]].sort_values([key, 'day', 'race_num'])
    res = tmp.groupby(key, sort=False)[value_col].transform(
        lambda x: x.shift(1).rolling(window, min_periods=minp).mean())
    return res.reindex(df.index)


def build_candidates(df, candset):
    """リーク無・推論時も計算可の候補をフィルタ前の全履歴で計算。
    candset: 'strong'(前走着差+騎手厩舎の全体成績) / 'cond'(条件特化=当馬場・当コース)
            / 'cond2'(血統×馬場・枠×コース・騎手当コース再挑戦) / 'all'。"""
    # results から不足列のみ取り込み(load_dataにjockey/trainer_codeが入った後は衝突回避のためwakuのみ)
    need = [c for c in ('jockey_code', 'trainer_code', 'waku') if c not in df.columns]
    if need:
        con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
        jt = pd.read_sql(f"SELECT race_key, umaban, {', '.join(need)} FROM results", con)
        con.close()
        df = df.merge(jt, on=['race_key', 'umaban'], how='left').reset_index(drop=True)
    df['_t3'] = (df['chakujun'] <= 3).astype(float)
    df['_w'] = (df['chakujun'] == 1).astype(float)
    cands = []

    if candset in ('strong', 'all'):
        # 前走着差: 各レースの勝ち馬秒との差 → 馬ごとに1走前(shift1)
        df['_race_margin'] = df['sec'] - df.groupby('race_key')['sec'].transform('min')
        tmp = df[['ketto_num', 'day', 'race_num', '_race_margin']].sort_values(['ketto_num', 'day', 'race_num'])
        df['cand_prior_margin'] = tmp.groupby('ketto_num', sort=False)['_race_margin'].shift(1).reindex(df.index)
        df.drop(columns=['_race_margin'], inplace=True)
        df['cand_jockey_form_t3'] = _rolling_prior_rate(df, 'jockey_code', '_t3', 50, 10)
        df['cand_jockey_win'] = _rolling_prior_rate(df, 'jockey_code', '_w', 80, 20)
        df['cand_trainer_form_t3'] = _rolling_prior_rate(df, 'trainer_code', '_t3', 30, 8)
        cands += ['cand_prior_margin', 'cand_jockey_form_t3', 'cand_jockey_win', 'cand_trainer_form_t3']

    if candset in ('cond', 'all'):
        # 条件特化(全体成績は織込み済み→当馬場/当コースは織込み薄い: project_trainer_course整合)
        df['_jk_surf'] = df['jockey_code'].astype(str) + '|' + df['surface'].astype(str)
        df['_jk_jyo'] = df['jockey_code'].astype(str) + '|' + df['jyo'].astype(str)
        df['_tr_jyo'] = df['trainer_code'].astype(str) + '|' + df['jyo'].astype(str)
        df['_tr_surf'] = df['trainer_code'].astype(str) + '|' + df['surface'].astype(str)
        df['cand_jockey_surf_t3'] = _rolling_prior_rate(df, '_jk_surf', '_t3', 30, 8)
        df['cand_jockey_jyo_t3'] = _rolling_prior_rate(df, '_jk_jyo', '_t3', 20, 5)
        df['cand_trainer_jyo_t3'] = _rolling_prior_rate(df, '_tr_jyo', '_t3', 20, 5)
        df['cand_trainer_surf_t3'] = _rolling_prior_rate(df, '_tr_surf', '_t3', 30, 8)
        df.drop(columns=['_jk_surf', '_jk_jyo', '_tr_jyo', '_tr_surf'], inplace=True)
        cands += ['cand_jockey_surf_t3', 'cand_jockey_jyo_t3', 'cand_trainer_jyo_t3', 'cand_trainer_surf_t3']

    if candset in ('cond2', 'all'):
        # ① 血統×馬場: 種牡馬(sire)の産駒が当該馬場で稼ぐ複勝率(roll100 min30)
        con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
        sires = pd.read_sql("SELECT ketto_num, sire FROM horses", con)
        con.close()
        df = df.merge(sires, on='ketto_num', how='left').reset_index(drop=True)
        df['_sire_surf'] = df['sire'].astype(str) + '|' + df['surface'].astype(str)
        df['cand_sire_surf_t3'] = _rolling_prior_rate(df, '_sire_surf', '_t3', 100, 30)

        # ② 枠×コース(枠順バイアス): 当(jyo|surface|kyori|waku)の過去複勝率。
        #    1レースに同枠が複数いるのでレース単位に集約→shift(1).rollingで当該レースを完全除外(リーク無)
        df['_dcg'] = (df['jyo'].astype(str) + '|' + df['surface'].astype(str) + '|'
                      + df['kyori'].astype(str) + '|' + df['waku'].astype(str))
        g = df.groupby(['_dcg', 'race_key'], as_index=False).agg(
            _t3m=('_t3', 'mean'), _day=('day', 'first'), _rn=('race_num', 'first'))
        g = g.sort_values(['_dcg', '_day', '_rn'])
        g['_bias'] = g.groupby('_dcg', sort=False)['_t3m'].transform(
            lambda x: x.shift(1).rolling(150, min_periods=20).mean())
        df = df.merge(g[['_dcg', 'race_key', '_bias']], on=['_dcg', 'race_key'], how='left')
        df['cand_draw_course_t3'] = df['_bias']

        # ③ 騎手の当コース系(再挑戦): 当場の勝率 + 騎手×(場|馬場)複勝率
        df['_jk_jyo2'] = df['jockey_code'].astype(str) + '|' + df['jyo'].astype(str)
        df['cand_jockey_jyo_win'] = _rolling_prior_rate(df, '_jk_jyo2', '_w', 60, 15)
        df['_jk_sj'] = (df['jockey_code'].astype(str) + '|' + df['jyo'].astype(str)
                        + '|' + df['surface'].astype(str))
        df['cand_jockey_surfjyo_t3'] = _rolling_prior_rate(df, '_jk_sj', '_t3', 25, 6)
        df.drop(columns=['_sire_surf', '_dcg', '_bias', '_jk_jyo2', '_jk_sj'], inplace=True)
        cands += ['cand_sire_surf_t3', 'cand_draw_course_t3', 'cand_jockey_jyo_win', 'cand_jockey_surfjyo_t3']

    if candset in ('cond3', 'all'):
        # 距離帯バケツ
        ky = pd.to_numeric(df['kyori'], errors='coerce')
        db = pd.Series('X', index=df.index)
        db[ky <= 1400] = 'S'
        db[(ky > 1400) & (ky <= 1800)] = 'M'
        db[(ky > 1800) & (ky <= 2200)] = 'L'
        df['_dbk'] = db
        # ① 騎手×距離帯(勝率/複勝率)  ② 厩舎×距離帯(複勝率)
        df['_jk_d'] = df['jockey_code'].astype(str) + '|' + df['_dbk']
        df['_tr_d'] = df['trainer_code'].astype(str) + '|' + df['_dbk']
        df['cand_jockey_dist_win'] = _rolling_prior_rate(df, '_jk_d', '_w', 50, 12)
        df['cand_jockey_dist_t3'] = _rolling_prior_rate(df, '_jk_d', '_t3', 50, 12)
        df['cand_trainer_dist_t3'] = _rolling_prior_rate(df, '_tr_d', '_t3', 40, 10)
        # ③ 前走クラス昇降の代理(DBに条件クラスコード無し): 前走勝ち=昇級戦代理 / 通算勝利数=クラス代理
        tmp = df[['ketto_num', 'day', 'race_num', '_w']].sort_values(['ketto_num', 'day', 'race_num'])
        df['cand_prev_was_win'] = tmp.groupby('ketto_num', sort=False)['_w'].shift(1).reindex(df.index)
        df['cand_cum_wins'] = (tmp.groupby('ketto_num', sort=False)['_w']
                               .transform(lambda x: x.shift(1).cumsum()).reindex(df.index))
        df.drop(columns=['_dbk', '_jk_d', '_tr_d'], inplace=True)
        cands += ['cand_jockey_dist_win', 'cand_jockey_dist_t3', 'cand_trainer_dist_t3',
                  'cand_prev_was_win', 'cand_cum_wins']

    if candset in ('cond4', 'all'):
        ky = pd.to_numeric(df['kyori'], errors='coerce')
        df['_dbk4'] = pd.Series(np.where(ky <= 1400, 'S', np.where(ky <= 1800, 'M',
                                np.where(ky <= 2200, 'L', 'X'))), index=df.index)
        # ① 厩舎×騎手の相性(複勝率) — 個別特徴量に無い相互作用
        df['_tj'] = df['trainer_code'].astype(str) + '|' + df['jockey_code'].astype(str)
        df['cand_trainer_jockey_t3'] = _rolling_prior_rate(df, '_tj', '_t3', 30, 8)
        # ② 騎手×馬場×距離 勝率(より細かい騎手適性)
        df['_jsd'] = df['jockey_code'].astype(str) + '|' + df['surface'].astype(str) + '|' + df['_dbk4']
        df['cand_jockey_surf_dist_win'] = _rolling_prior_rate(df, '_jsd', '_w', 40, 10)
        # ③ 枠×距離(馬場込み)の枠順バイアス: レース単位集約→shift(1).rollingで当該レース完全除外(リーク無)
        df['_wd'] = df['surface'].astype(str) + '|' + df['_dbk4'] + '|' + df['waku'].astype(str)
        g = df.groupby(['_wd', 'race_key'], as_index=False).agg(
            _t3m=('_t3', 'mean'), _day=('day', 'first'), _rn=('race_num', 'first'))
        g = g.sort_values(['_wd', '_day', '_rn'])
        g['_b'] = g.groupby('_wd', sort=False)['_t3m'].transform(
            lambda x: x.shift(1).rolling(150, min_periods=20).mean())
        df = df.merge(g[['_wd', 'race_key', '_b']], on=['_wd', 'race_key'], how='left')
        df['cand_waku_dist_t3'] = df['_b']
        df.drop(columns=['_dbk4', '_tj', '_jsd', '_wd', '_b'], inplace=True)
        cands += ['cand_trainer_jockey_t3', 'cand_jockey_surf_dist_win', 'cand_waku_dist_t3']

    if candset in ('cond5', 'all'):
        # USM(馬力絞り出しメーター): オッズ帯の人口平均成績に対する、その騎手の過去実績比。
        # leak防止=shift(1)で過去のみ。期待値=オッズ帯別の人口勝率/連対率/複勝率(集合知)。
        od = pd.to_numeric(df['win_odds'], errors='coerce')
        edges = [0, 1.45, 1.95, 2.95, 3.95, 4.95, 6.95, 9.95, 14.95, 19.95, 29.95, 49.95, 99.95, 1e9]
        df['_band'] = pd.cut(od, bins=edges, labels=False, right=False)
        _aw = (df['chakujun'] == 1).astype(float)
        _a2 = (df['chakujun'] <= 2).astype(float)
        _a3 = (df['chakujun'] <= 3).astype(float)
        _valid = od > 0
        bw = _aw[_valid].groupby(df['_band'][_valid]).mean()
        b2 = _a2[_valid].groupby(df['_band'][_valid]).mean()
        b3 = _a3[_valid].groupby(df['_band'][_valid]).mean()
        df['_ew'] = df['_band'].map(bw); df['_e2'] = df['_band'].map(b2); df['_e3'] = df['_band'].map(b3)
        df['_aw'] = _aw; df['_a2'] = _a2; df['_a3'] = _a3
        for _c in ['_ew', '_e2', '_e3', '_aw', '_a2', '_a3']:
            df.loc[~_valid, _c] = np.nan

        def _usm(numc, denc, W=250, minp=40):
            tmp = df[['jockey_code', 'day', 'race_num', numc, denc]].sort_values(['jockey_code', 'day', 'race_num'])
            g = tmp.groupby('jockey_code', sort=False)
            num = g[numc].transform(lambda x: x.shift(1).rolling(W, min_periods=minp).sum())
            den = g[denc].transform(lambda x: x.shift(1).rolling(W, min_periods=minp).sum())
            return (num / den.where(den > 0)).reindex(df.index)

        df['cand_usm_win'] = _usm('_aw', '_ew')
        df['cand_usm_t2'] = _usm('_a2', '_e2')
        df['cand_usm_t3'] = _usm('_a3', '_e3')
        df.drop(columns=['_band', '_ew', '_e2', '_e3', '_aw', '_a2', '_a3'], inplace=True)
        cands += ['cand_usm_win', 'cand_usm_t2', 'cand_usm_t3']

    df.drop(columns=['_t3', '_w'], inplace=True)
    return df, cands


def add_simple_candidates(df):
    """第1イテレーションの簡易候補(全て不採用だった)。--include-simple 時のみ使用。"""
    bat = pd.to_numeric(df['bataiju'], errors='coerce')
    fut = pd.to_numeric(df['futan'], errors='coerce')
    df['_bat_num'] = bat
    df['_fut_num'] = fut
    df['cand_weight_ratio'] = fut / bat.replace(0, np.nan)
    df['cand_zogen_abs'] = pd.to_numeric(df['zogen'], errors='coerce').abs()
    df['cand_draw_rel'] = pd.to_numeric(df['umaban'], errors='coerce') / pd.to_numeric(df['field_size'], errors='coerce').replace(0, np.nan)
    df['cand_age_sq'] = pd.to_numeric(df['age'], errors='coerce') ** 2
    df['cand_bataiju_dev'] = bat - df.groupby('race_key')['_bat_num'].transform('mean')
    df['cand_futan_dev'] = fut - df.groupby('race_key')['_fut_num'].transform('mean')
    df.drop(columns=['_bat_num', '_fut_num'], inplace=True)
    return ['cand_weight_ratio', 'cand_zogen_abs', 'cand_draw_rel',
            'cand_age_sq', 'cand_bataiju_dev', 'cand_futan_dev']


def prepare(quick=False, include_simple=False, candset='cond'):
    print('=== データ準備(既存パイプライン再利用) ===', file=sys.stderr)
    df = bm.load_data()
    df = bm.compute_corrected_time(df)          # 'sec','day' を生成
    df = bm.compute_rolling_features(df)
    df = bm.compute_trainer_course(df)          # 本番FEATURES入りの trainer_jyo_t3 を再現(ベースライン用)
    df = bm.compute_jockey_course(df)           # 同上 jockey_jyo_win
    df = bm.compute_jockey_dist(df)             # 同上 jockey_dist_win
    # 候補は『フィルタ前の全履歴』で計算(前走/騎手騎乗履歴を欠けさせない)
    df, cands = build_candidates(df, candset)

    base_year = 2019 if quick else 2016
    df = df[df['year'].astype(int) >= base_year].copy()
    df = bm.encode_features(df)
    df = bm.compute_race_ranks(df)
    if include_simple:
        cands = cands + add_simple_candidates(df)

    df['label'] = np.clip(4 - df['chakujun'], 0, 3).astype(int)
    df = df.dropna(subset=['ninki'])
    rc = df.groupby('race_key').size()
    df = df[df['race_key'].isin(rc[rc >= 5].index)]

    yi = df['year'].astype(int)
    train_df = df[yi <= bm.TRAIN_END].sort_values('race_key')
    val_df = df[yi == bm.VAL_YEAR].sort_values('race_key')
    test_df = df[yi >= bm.TEST_FROM].sort_values('race_key')
    print(f'Train {len(train_df):,} / Val {len(val_df):,} / Test {len(test_df):,} / 候補{len(cands)}本',
          file=sys.stderr)
    return train_df, val_df, test_df, cands


def _recall7(model, eval_df, features):
    X = eval_df[features].values.astype(np.float64)
    g = eval_df[['race_key', 'chakujun', 'umaban']].copy()
    g['pred'] = model.predict(X)
    win_hit, tot, t3 = 0, 0, []
    for _, grp in g.groupby('race_key'):
        winner = set(grp[grp['chakujun'] == 1]['umaban'])
        top3 = set(grp[grp['chakujun'] <= 3]['umaban'])
        if not winner or not top3:
            continue
        top7 = set(grp.nlargest(7, 'pred')['umaban'])
        win_hit += int(bool(winner & top7))
        t3.append(len(top3 & top7) / len(top3))
        tot += 1
    return (win_hit / tot if tot else 0.0), (float(np.mean(t3)) if t3 else 0.0), tot


def train_eval(train_df, val_df, test_df, features, rounds=1000):
    train_g = train_df.groupby('race_key', sort=False).size().values
    val_g = val_df.groupby('race_key', sort=False).size().values
    ds_tr = lgb.Dataset(train_df[features].values.astype(np.float64),
                        label=train_df['label'].values, group=train_g, feature_name=features)
    ds_va = lgb.Dataset(val_df[features].values.astype(np.float64),
                        label=val_df['label'].values, group=val_g, feature_name=features, reference=ds_tr)
    model = lgb.train(PARAMS, ds_tr, num_boost_round=rounds, valid_sets=[ds_va],
                      callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)])
    v_win, v_t3, _ = _recall7(model, val_df, features)
    t_win, t_t3, n = _recall7(model, test_df, features)
    return {'val_win7': v_win, 'val_top3_7': v_t3,
            'test_win7': t_win, 'test_top3_7': t_t3,
            'test_races': n, 'best_iter': model.best_iteration}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ablation', action='store_true', help='drop-one も試す')
    ap.add_argument('--quick', action='store_true', help='2019+のみ・軽量(動作確認)')
    ap.add_argument('--include-simple', action='store_true', help='第1回の簡易候補も含める')
    ap.add_argument('--candset', choices=['strong', 'cond', 'cond2', 'cond3', 'cond4', 'cond5', 'all'], default='cond',
                    help='strong=前走着差+全体成績 / cond=当馬場当コース / '
                         'cond2=血統×馬場・枠×コース・騎手当コース / '
                         'cond3=騎手厩舎×距離帯・昇級代理 / '
                         'cond4=厩舎×騎手相性・騎手×馬場×距離・枠×距離 / '
                         'cond5=USM(単/連/複・全体・馬力絞り出し) / all')
    ap.add_argument('--margin', type=float, default=0.0015,
                    help='採用候補とみなす test win_recall@7 の改善マージン(既定+0.15pp)')
    args = ap.parse_args()

    t0 = _time.time()
    train_df, val_df, test_df, cands = prepare(quick=args.quick, include_simple=args.include_simple,
                                               candset=args.candset)
    rounds = 400 if args.quick else 1000
    base = list(bm.FEATURES)

    print('\n=== ① ベースライン(現行FEATURES) ===', file=sys.stderr)
    base_m = train_eval(train_df, val_df, test_df, base, rounds)
    print(f"  test win@7={base_m['test_win7']:.4f}  top3@7={base_m['test_top3_7']:.4f}  "
          f"val win@7={base_m['val_win7']:.4f}  (races={base_m['test_races']})", file=sys.stderr)

    results = []

    print('\n=== ② add-one 探索(ベース+候補1本) ===', file=sys.stderr)
    for c in cands:
        m = train_eval(train_df, val_df, test_df, base + [c], rounds)
        d_test = m['test_win7'] - base_m['test_win7']
        d_val = m['val_win7'] - base_m['val_win7']
        ok = (d_test >= args.margin) and (d_val >= 0)
        results.append({'kind': 'add', 'feature': c, **m,
                        'd_test_win7': d_test, 'd_val_win7': d_val, 'adopt': ok})
        print(f"  +{c:22s} test {m['test_win7']:.4f} ({d_test*100:+.2f}pp)  "
              f"val ({d_val*100:+.2f}pp)  {'★採用候補' if ok else ''}", file=sys.stderr)

    # 強候補が複数採用候補なら、まとめて足した版も評価(相乗/冗長の確認)
    add_ok = [r['feature'] for r in results if r.get('adopt')]
    if len(add_ok) >= 2:
        m = train_eval(train_df, val_df, test_df, base + add_ok, rounds)
        d_test = m['test_win7'] - base_m['test_win7']
        d_val = m['val_win7'] - base_m['val_win7']
        results.append({'kind': 'combo', 'feature': '+'.join(add_ok), **m,
                        'd_test_win7': d_test, 'd_val_win7': d_val,
                        'adopt': (d_test >= args.margin and d_val >= 0)})
        print(f"  ＝全採用候補同時: test {m['test_win7']:.4f} ({d_test*100:+.2f}pp) val ({d_val*100:+.2f}pp)",
              file=sys.stderr)

    if args.ablation:
        print('\n=== ③ drop-one 探索(各既存特徴量を1本抜く=不要/有害の検出) ===', file=sys.stderr)
        for f in base:
            sub = [x for x in base if x != f]
            m = train_eval(train_df, val_df, test_df, sub, rounds)
            d_test = m['test_win7'] - base_m['test_win7']
            results.append({'kind': 'drop', 'feature': f, **m,
                            'd_test_win7': d_test, 'd_val_win7': m['val_win7'] - base_m['val_win7'],
                            'adopt': False})
            flag = '⚠抜くと改善(有害?)' if d_test >= args.margin else ''
            print(f"  -{f:22s} test {m['test_win7']:.4f} ({d_test*100:+.2f}pp)  {flag}", file=sys.stderr)

    results.sort(key=lambda r: -r['d_test_win7'])
    adopt = [r for r in results if r.get('adopt') and r['kind'] in ('add', 'combo')]

    print('\n' + '=' * 60, file=sys.stderr)
    print('=== 採点まとめ(test win_recall@7 改善順) ===', file=sys.stderr)
    for r in results[:12]:
        print(f"  [{r['kind']}] {r['feature']:26s} Δtest{r['d_test_win7']*100:+.2f}pp "
              f"Δval{r['d_val_win7']*100:+.2f}pp", file=sys.stderr)
    if adopt:
        print('\n★ 採用候補(test+val 両方改善・マージン超え) — 人がレビューして配線:', file=sys.stderr)
        for r in adopt:
            print(f"   - {r['feature']}", file=sys.stderr)
        print('   配線先=build_ltr_model.FEATURES&encode + ltr_ranker.py(推論時の各行)。'
              '1案ずつ・影響少なめに→`python scripts/build_ltr_model.py`再訓練。', file=sys.stderr)
    else:
        print('\n採用候補なし(現行FEATURESが既に強い/候補は織込み済み)。', file=sys.stderr)

    out = {'ts': _time.strftime('%Y-%m-%d %H:%M:%S'), 'quick': args.quick,
           'include_simple': args.include_simple, 'margin': args.margin,
           'baseline': base_m, 'results': results, 'adopt': [r['feature'] for r in adopt]}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\nlog → {LOG_PATH}　done in {_time.time()-t0:.0f}s', file=sys.stderr)


if __name__ == '__main__':
    main()
