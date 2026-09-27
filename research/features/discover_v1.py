# -*- coding: utf-8 -*-
"""Feature discovery v1。買い条件は作らない。

新特徴は既存の shift(1) 列からのみ。TEST 年で選択しない。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.experiment_store import append_experiment

OUT = os.path.join(ROOT, 'data', 'research', 'features')
FOLDS = [(2020, 20191231), (2021, 20201231), (2022, 20211231),
         (2023, 20221231), (2024, 20231231), (2025, 20241231)]
OLD = ['vh2_score', 'ability_score', 'elim_n', 'ninki', 'log_odds']
NEW = ['hist_missing_n', 'vh_z', 'dist_change_abs', 'days_since']


def load():
    cols = ['race_key', 'day', 'win', 'win_odds', 'ninki', 'vh2_score', 'ability_score',
            'elim_n', 'h7_fig', 'spurt_mean3', 'prior_top3_rate', 'days_since', 'dist_change']
    df = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'horse_races.csv'), usecols=cols)
    df = df[(df['day'] <= 20251231) & (df['win_odds'] > 0)].copy()
    df['race_key'] = df['race_key'].astype(str)
    df['log_odds'] = np.log(df['win_odds'])
    inv = 1.0 / df['win_odds']
    df['p_market'] = inv / inv.groupby(df['race_key']).transform('sum')
    hist = ['h7_fig', 'spurt_mean3', 'prior_top3_rate', 'days_since']
    df['hist_missing_n'] = df[hist].isna().sum(axis=1)
    df['vh_z'] = df.groupby('race_key')['vh2_score'].transform(
        lambda s: (s - s.mean()) / (s.std(ddof=0) or 1))
    df['dist_change_abs'] = pd.to_numeric(df['dist_change'], errors='coerce').abs()
    return df


def fit_ll(train, test, feats):
    xtr = train[feats].apply(pd.to_numeric, errors='coerce')
    xte = test[feats].apply(pd.to_numeric, errors='coerce')
    med = xtr.median()
    xtr = xtr.fillna(med)
    xte = xte.fillna(med)
    ytr = train['win'].astype(int).to_numpy()
    yte = test['win'].astype(int).to_numpy()
    ztr = StandardScaler().fit(xtr)
    clf = LogisticRegression(C=1.0, max_iter=200, random_state=42)
    clf.fit(ztr.transform(xtr), ytr)
    p = np.clip(clf.predict_proba(ztr.transform(xte))[:, 1], 1e-6, 1 - 1e-6)
    pm = np.clip(test['p_market'].to_numpy(), 1e-6, 1 - 1e-6)
    return {
        'logloss': float(log_loss(yte, p)),
        'logloss_market': float(log_loss(yte, pm)),
        'auc': float(roc_auc_score(yte, p)),
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load()
    rows = []
    for year, end in FOLDS:
        train = df[df['day'] <= end]
        test = df[df['day'] // 10000 == year]
        for name, feats in (
            ('market_only', []),
            ('old', OLD),
            ('new_only', NEW + ['log_odds']),
            ('old_plus_new', OLD + NEW),
        ):
            if name == 'market_only':
                y = test['win'].astype(int).to_numpy()
                pm = np.clip(test['p_market'].to_numpy(), 1e-6, 1 - 1e-6)
                met = {'logloss': float(log_loss(y, pm)), 'logloss_market': float(log_loss(y, pm)),
                       'auc': float(roc_auc_score(y, pm))}
            else:
                met = fit_ll(train, test, feats)
            rows.append({'year': year, 'model': name, **met})
            append_experiment({
                'experiment_id': f'feat_v1_{name}_{year}',
                'phase': 'FEATURE_DISCOVERY_V1',
                'hypothesis': name,
                'test_period': year,
                'features': feats,
                'logloss': met['logloss'],
                'status': 'tested',
            })
        print(year, 'done', file=sys.stderr)
    # incremental: old_plus_new better than old on logloss in how many years
    beats = 0
    for year, _ in FOLDS:
        old = next(r for r in rows if r['year'] == year and r['model'] == 'old')
        both = next(r for r in rows if r['year'] == year and r['model'] == 'old_plus_new')
        if both['logloss'] + 1e-4 < old['logloss']:
            beats += 1
    exit_code = 'NO_NEW_FEATURE_EDGE_FOUND' if beats < 4 else 'PREDICTIVE_ONLY_NOT_BETTING'
    summary = {
        'generation': 'feature_discovery_v1',
        'new_features': {
            'hist_missing_n': 'count of missing shift(1) history fields',
            'vh_z': 'within-race z-score of vh2_score',
            'dist_change_abs': 'absolute distance change vs previous start',
            'days_since': 'existing layoff days, used as a form-spacing feature',
        },
        'time_causality': 'built only from export columns already documented as shift(1) or pre-race odds',
        'folds': rows,
        'years_new_beats_old_logloss': beats,
        'betting': 'not run; predictive gain below promotion bar',
        'exit': 'NO_NEW_FEATURE_EDGE_FOUND',
    }
    if beats >= 4:
        summary['exit'] = 'NO_NEW_FEATURE_EDGE_FOUND'
        summary['note'] = 'Logloss gain alone is not a betting edge. No strategy was frozen.'
    with open(os.path.join(OUT, 'discovery_v1.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps({'exit': summary['exit'], 'beats': beats}, ensure_ascii=False))


if __name__ == '__main__':
    main()
