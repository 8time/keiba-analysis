# -*- coding: utf-8 -*-
"""Benter較正バックテスト — Qiita記事の手法を自プロジェクトで検証。

仮説: オッズ無しLTRの出力をBenter較正(P_model^α × P_market^β)で
      市場オッズと事後合成すれば、オッズを特徴量に直接食わせた現行LTRより
      recall@7が上がるか？

設計:
  現行LTR     = 26特徴量(ninki, log_odds含む), train≤2023/val2024
  オッズ無しLTR = 24特徴量(ninki, log_odds除外), 同split
  Benter較正   = オッズ無しLTRの出力 × 市場確率 を α/βでブレンド

  α/β推定: val(2024)で勝ち馬のlog-likelihoodを最大化するMLE
  評価:     test(2025+)でrecall@7を3モデル比較

参考: Benter (1994) "Computer Based Horse Race Handicapping and Wagering Systems"
      P_final(i) ∝ P_model(i)^α × P_public(i)^β

Usage: python scripts/benter_calibration_backtest.py
"""
import os
import sys
import time as _time

import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

import scripts.build_ltr_model as bm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR_MODEL = os.path.join(ROOT, 'data', 'ltr_model.lgb')

FEATURES_NO_ODDS = [f for f in bm.FEATURES if f not in ('ninki', 'log_odds')]


# ── helpers ──────────────────────────────────────────────

def softmax_by_race(df, score_col):
    """レース内softmaxで生スコアを確率に変換。"""
    probs = np.zeros(len(df))
    for idx in df.groupby('race_key').indices.values():
        s = df.iloc[idx][score_col].values.astype(np.float64)
        s = s - s.max()
        e = np.exp(s)
        probs[idx] = e / e.sum()
    return probs


def market_prob(df):
    """市場オッズからレース内正規化した暗黙確率を算出。"""
    odds = pd.to_numeric(df['win_odds'], errors='coerce').fillna(100).values.astype(np.float64)
    odds = np.clip(odds, 1.0, 9999.0)
    inv = 1.0 / odds
    probs = np.zeros(len(df))
    for idx in df.groupby('race_key').indices.values():
        total = inv[idx].sum()
        if total > 0:
            probs[idx] = inv[idx] / total
        else:
            probs[idx] = 1.0 / len(idx)
    return probs


def benter_blend(p_model, p_market, alpha, beta):
    """Benter較正: P_final ∝ P_model^α × P_market^β (レース内正規化)。"""
    raw = (p_model ** alpha) * (p_market ** beta)
    return raw  # 正規化はNLLやrecall計算側でやる


def neg_log_likelihood(params, p_model, p_market, winner_mask, race_indices):
    """Benter α/βの負対数尤度(最小化対象)。"""
    alpha, beta = params
    if alpha < 0 or beta < 0:
        return 1e12
    raw = benter_blend(p_model, p_market, alpha, beta)
    nll = 0.0
    n_races = 0
    for idx in race_indices:
        r = raw[idx]
        total = r.sum()
        if total <= 0:
            continue
        p_norm = r / total
        w = winner_mask[idx]
        winner_idx = np.where(w)[0]
        if len(winner_idx) == 0:
            continue
        p_win = p_norm[winner_idx[0]]
        if p_win > 0:
            nll -= np.log(p_win)
        else:
            nll += 30.0
        n_races += 1
    return nll / max(n_races, 1)


def recall_at7_from_scores(df, score_col):
    """score_col(高い方が良い)でrecall@7を計算。"""
    win_hit, tot = 0, 0
    t3_recall = []
    for _, g in df.groupby('race_key'):
        top3 = set(g[g['chakujun'] <= 3]['umaban'])
        winner = set(g[g['chakujun'] == 1]['umaban'])
        if not top3 or not winner:
            continue
        top7 = set(g.nlargest(7, score_col)['umaban'])
        win_hit += int(bool(winner & top7))
        t3_recall.append(len(top3 & top7) / len(top3))
        tot += 1
    if tot == 0:
        return 0.0, 0.0, 0
    return win_hit / tot, float(np.mean(t3_recall)), tot


# ── main ─────────────────────────────────────────────────

def main():
    t0 = _time.time()
    print('='*70)
    print('Benter較正バックテスト: オッズ無しLTR + 市場ブレンド vs 現行LTR')
    print('='*70)

    # 1) データ構築(build_ltr_modelと同一パイプライン)
    print('\n[1/5] データ構築...')
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
    df = df[df['race_key'].isin(cnt[cnt >= 5].index)]

    yi = df['year'].astype(int)
    train_df = df[yi <= bm.TRAIN_END].sort_values('race_key')
    val_df = df[yi == bm.VAL_YEAR].sort_values('race_key')
    test_df = df[yi >= bm.TEST_FROM].sort_values('race_key')
    print(f'  Train {len(train_df):,} / Val {len(val_df):,} / Test {len(test_df):,}')

    # 2) オッズ無しLTRを学習
    print('\n[2/5] オッズ無しLTR学習(24特徴量)...')
    print(f'  除外: ninki, log_odds')
    print(f'  使用: {len(FEATURES_NO_ODDS)}特徴量')

    tr_g = train_df.groupby('race_key', sort=False).size().values
    va_g = val_df.groupby('race_key', sort=False).size().values

    ds_tr = lgb.Dataset(train_df[FEATURES_NO_ODDS].values.astype(np.float64),
                        label=train_df['label'].values,
                        group=tr_g, feature_name=FEATURES_NO_ODDS)
    ds_va = lgb.Dataset(val_df[FEATURES_NO_ODDS].values.astype(np.float64),
                        label=val_df['label'].values,
                        group=va_g, feature_name=FEATURES_NO_ODDS, reference=ds_tr)

    params = {
        'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [3, 7],
        'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 50,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
        'verbose': -1,
    }
    no_odds_model = lgb.train(params, ds_tr, num_boost_round=1000,
                              valid_sets=[ds_va],
                              callbacks=[lgb.early_stopping(50, verbose=False),
                                         lgb.log_evaluation(0)])
    print(f'  best_iteration: {no_odds_model.best_iteration}')

    # 3) val(2024)でBenter α/β MLE
    print('\n[3/5] Benter α/β MLE推定(val=2024年)...')
    val_df = val_df.copy()
    val_df['pred_no_odds'] = no_odds_model.predict(
        val_df[FEATURES_NO_ODDS].values.astype(np.float64))
    val_df['p_model'] = softmax_by_race(val_df, 'pred_no_odds')
    val_df['p_market'] = market_prob(val_df)
    val_df['is_winner'] = (val_df['chakujun'] == 1).astype(int)

    val_race_idx = list(val_df.groupby('race_key').indices.values())
    p_model_v = val_df['p_model'].values
    p_market_v = val_df['p_market'].values
    winner_v = val_df['is_winner'].values

    best_result = None
    for a0, b0 in [(0.3, 0.8), (0.5, 0.5), (0.8, 0.3), (1.0, 1.0), (0.2, 0.9)]:
        res = minimize(neg_log_likelihood, x0=[a0, b0],
                       args=(p_model_v, p_market_v, winner_v, val_race_idx),
                       method='Nelder-Mead',
                       options={'maxiter': 2000, 'xatol': 1e-4, 'fatol': 1e-6})
        if best_result is None or res.fun < best_result.fun:
            best_result = res

    alpha_mle, beta_mle = best_result.x
    print(f'  α = {alpha_mle:.4f}, β = {beta_mle:.4f}  (NLL = {best_result.fun:.6f})')
    print(f'  解釈: モデル信頼度 {alpha_mle:.2f} / 市場信頼度 {beta_mle:.2f}')

    # NLL比較(val上)
    nll_model_only = neg_log_likelihood(
        [1.0, 0.0], p_model_v, p_market_v, winner_v, val_race_idx)
    nll_market_only = neg_log_likelihood(
        [0.0, 1.0], p_model_v, p_market_v, winner_v, val_race_idx)
    nll_equal = neg_log_likelihood(
        [1.0, 1.0], p_model_v, p_market_v, winner_v, val_race_idx)
    print(f'\n  NLL比較(val):')
    print(f'    モデルのみ(α=1,β=0): {nll_model_only:.6f}')
    print(f'    市場のみ(α=0,β=1):   {nll_market_only:.6f}')
    print(f'    等価(α=1,β=1):        {nll_equal:.6f}')
    print(f'    MLE(α={alpha_mle:.3f},β={beta_mle:.3f}): {best_result.fun:.6f}')

    # 4) test(2025+)で3モデル比較
    print('\n[4/5] test(2025+)でrecall@7比較...')
    test_df = test_df.copy()

    # A) 現行LTR
    cur_model = lgb.Booster(model_file=CUR_MODEL)
    test_df['pred_current'] = cur_model.predict(
        test_df[bm.FEATURES].values.astype(np.float64))

    # B) オッズ無しLTR
    test_df['pred_no_odds'] = no_odds_model.predict(
        test_df[FEATURES_NO_ODDS].values.astype(np.float64))

    # C) オッズ無しLTR + Benter較正
    test_df['p_model'] = softmax_by_race(test_df, 'pred_no_odds')
    test_df['p_market'] = market_prob(test_df)
    test_df['pred_benter'] = benter_blend(
        test_df['p_model'].values, test_df['p_market'].values,
        alpha_mle, beta_mle)

    # D) 人気順ベースライン
    test_df['pred_ninki'] = -test_df['ninki'].astype(float)

    wr_cur, t3_cur, n_cur = recall_at7_from_scores(test_df, 'pred_current')
    wr_no, t3_no, n_no = recall_at7_from_scores(test_df, 'pred_no_odds')
    wr_ben, t3_ben, n_ben = recall_at7_from_scores(test_df, 'pred_benter')
    wr_nin, t3_nin, n_nin = recall_at7_from_scores(test_df, 'pred_ninki')

    # 5) 結果表示
    print('\n[5/5] 結果')
    print('='*70)
    print(f'Test期間: {bm.TEST_FROM}年～ / {n_cur:,}レース')
    print(f'{"モデル":32s} {"勝ちrecall@7":>14s} {"3着内recall@7":>14s}')
    print('-'*70)
    print(f'{"人気順(ベースライン)":32s} {wr_nin:13.4f} {t3_nin:13.4f}')
    print(f'{"現行LTR(26feat, odds込み)":32s} {wr_cur:13.4f} {t3_cur:13.4f}')
    print(f'{"オッズ無しLTR(24feat)":32s} {wr_no:13.4f} {t3_no:13.4f}')
    print(f'{"オッズ無し+Benter較正":32s} {wr_ben:13.4f} {t3_ben:13.4f}')
    print('-'*70)

    d_ben_vs_cur_w = (wr_ben - wr_cur) * 100
    d_ben_vs_cur_t = (t3_ben - t3_cur) * 100
    d_no_vs_cur_w = (wr_no - wr_cur) * 100
    d_no_vs_cur_t = (t3_no - t3_cur) * 100
    d_ben_vs_no_w = (wr_ben - wr_no) * 100
    d_ben_vs_no_t = (t3_ben - t3_no) * 100

    print(f'\n差分(pp):')
    print(f'  Benter vs 現行LTR:      勝ち {d_ben_vs_cur_w:+.2f}pp / 3着内 {d_ben_vs_cur_t:+.2f}pp')
    print(f'  オッズ無し vs 現行LTR:  勝ち {d_no_vs_cur_w:+.2f}pp / 3着内 {d_no_vs_cur_t:+.2f}pp')
    print(f'  Benter vs オッズ無し:   勝ち {d_ben_vs_no_w:+.2f}pp / 3着内 {d_ben_vs_no_t:+.2f}pp')

    print(f'\nBenter較正のα/β: α={alpha_mle:.4f}, β={beta_mle:.4f}')
    if alpha_mle < beta_mle:
        print('  → 市場(オッズ)をモデルより強く信頼する較正')
    elif alpha_mle > beta_mle:
        print('  → モデルを市場より強く信頼する較正')
    else:
        print('  → モデルと市場をほぼ等価に扱う較正')

    if d_ben_vs_cur_w > 0 and d_ben_vs_cur_t > 0:
        print('\n★ Benter較正が現行LTRを両指標で上回った → 追検証の価値あり')
    elif d_ben_vs_cur_w > 0 or d_ben_vs_cur_t > 0:
        print('\n△ Benter較正が片方の指標で上回った → 微妙、年別分析が必要')
    else:
        print('\n✗ Benter較正は現行LTRを超えない → LTRのオッズ内包が正解')

    # 年別内訳
    print('\n年別内訳:')
    print(f'{"年":>6s} {"現行LTR勝ち":>12s} {"Benter勝ち":>12s} '
          f'{"現行LTR 3着":>12s} {"Benter 3着":>12s} {"レース数":>8s}')
    for y in sorted(test_df['year'].astype(int).unique()):
        yd = test_df[test_df['year'].astype(int) == y]
        if len(yd) == 0:
            continue
        wr_c, t3_c, nc = recall_at7_from_scores(yd, 'pred_current')
        wr_b, t3_b, nb = recall_at7_from_scores(yd, 'pred_benter')
        print(f'{y:6d} {wr_c:12.4f} {wr_b:12.4f} {t3_c:12.4f} {t3_b:12.4f} {nc:8d}')

    # feature importance(オッズ無しモデル)
    imp = no_odds_model.feature_importance(importance_type='gain')
    fi = sorted(zip(FEATURES_NO_ODDS, imp), key=lambda x: -x[1])
    print(f'\nオッズ無しLTR feature importance (gain):')
    for name, gain in fi[:10]:
        print(f'  {name:20s} {gain:>10.0f}')

    elapsed = _time.time() - t0
    print(f'\n完了: {elapsed:.0f}秒')


if __name__ == '__main__':
    main()
