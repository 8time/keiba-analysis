# -*- coding: utf-8 -*-
"""B11–B25 の実行可能範囲。

ハイパーパラメータと edge 分位点はコードに固定。TEST 年では変えない。
2026 は選択に使わない。三連系は払戻パーサーをこの実行で再検証していないため対象外。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.experiment_store import append_experiment
from research.historical.feature_classes import HORSE, race_class
from research.metrics import max_drawdown

OUT = os.path.join(ROOT, 'data', 'research', 'advanced')
CK = os.path.join(ROOT, 'data', 'research', 'checkpoints')
UNIT = 100
SEED = 42
EDGE_Q = 0.90
FOLDS = [
    (2020, 20191231),
    (2021, 20201231),
    (2022, 20211231),
    (2023, 20221231),
    (2024, 20231231),
    (2025, 20241231),
]
FEATS_NO_ODDS = [
    'vh2_score', 'ability_score', 'h7_fig', 'spurt_mean3', 'prior_top3_rate',
    'trainer_jyo_t3', 'jockey_jyo_win', 'jockey_dist_win', 'elim_n',
    'field_size', 'surface_code', 'kyori_int', 'age', 'sex_code', 'vscore',
    'odds_entropy', 'mean_elim',
]
FEATS_ODDS = FEATS_NO_ODDS + ['log_odds', 'ninki']


def _ck(name, payload):
    os.makedirs(CK, exist_ok=True)
    with open(os.path.join(CK, name), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def feature_registry(df):
    rows = []
    for col, cls in HORSE.items():
        rows.append({
            'column': col, 'level': 'horse', 'klass': cls,
            'model_input': cls == 'SAFE_PRE_RACE',
            'note': 'combo is 2024+ longshot cache' if col == 'combo' else '',
        })
    head = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'races.csv'), nrows=0)
    for col in head.columns:
        cls = race_class(col)
        rows.append({'column': col, 'level': 'race', 'klass': cls, 'model_input': cls == 'SAFE_PRE_RACE'})
    rows.append({
        'column': 'win_odds',
        'level': 'horse',
        'klass': 'SAFE_PRE_RACE',
        'model_input': True,
        'timing': 'JV final win odds, not a proven bet-time quote',
    })
    return rows


def load():
    cols = [
        'race_key', 'day', 'umaban', 'ninki', 'win_odds', 'win', 'surface_code',
        'kyori_int', 'field_size', 'age', 'sex_code', 'vh2_score', 'ability_score',
        'h7_fig', 'spurt_mean3', 'prior_top3_rate', 'trainer_jyo_t3',
        'jockey_jyo_win', 'jockey_dist_win', 'elim_n',
    ]
    h = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'horse_races.csv'), usecols=cols)
    r = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'races.csv'),
                    usecols=['race_key', 'vscore', 'odds_entropy', 'mean_elim'])
    h = h[h['day'] <= 20251231].copy()
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    df = h.merge(r, on='race_key', how='left')
    df = df[df['win_odds'] > 0].copy()
    df['log_odds'] = np.log(df['win_odds'])
    inv = 1.0 / df['win_odds']
    df['p_market'] = inv / inv.groupby(df['race_key']).transform('sum')
    return df


def market_table(df):
    bands = pd.cut(df['win_odds'], [1, 2, 3, 5, 10, 20, 50, 999])
    rows = []
    for b, g in df.groupby(bands, observed=False):
        rows.append({
            'odds_band': str(b),
            'n': int(len(g)),
            'win_rate': float(g['win'].mean()),
            'mean_p_market': float(g['p_market'].mean()),
            'roi': float((g['win'] * g['win_odds']).mean() * 100),
        })
    return rows


def _xy(df, feats):
    x = df[feats].apply(pd.to_numeric, errors='coerce')
    y = df['win'].astype(int).to_numpy()
    return x, y


def fit_predict(train, test, feats):
    xtr, ytr = _xy(train, feats)
    xte, yte = _xy(test, feats)
    med = xtr.median()
    xtr = xtr.fillna(med)
    xte = xte.fillna(med)
    scaler = StandardScaler()
    ztr = scaler.fit_transform(xtr)
    zte = scaler.transform(xte)
    clf = LogisticRegression(C=1.0, max_iter=300, random_state=SEED)
    clf.fit(ztr, ytr)
    p = clf.predict_proba(zte)[:, 1]
    ptr = clf.predict_proba(ztr)[:, 1]
    return p, ptr, yte, clf, list(xtr.columns)


def metrics(y, p, p_mkt):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    p_mkt = np.clip(p_mkt, 1e-6, 1 - 1e-6)
    return {
        'logloss': float(log_loss(y, p)),
        'logloss_market': float(log_loss(y, p_mkt)),
        'brier': float(brier_score_loss(y, p)),
        'brier_market': float(brier_score_loss(y, p_mkt)),
        'auc': float(roc_auc_score(y, p)) if y.min() != y.max() else None,
        'auc_market': float(roc_auc_score(y, p_mkt)) if y.min() != y.max() else None,
    }


def value_bets(test, p, threshold):
    t = test.copy()
    t['p_model'] = p
    t['edge'] = t['p_model'] - t['p_market']
    bet = t[t['edge'] >= threshold]
    if bet.empty:
        return {'n': 0, 'roi': None, 'profit': 0, 'hit_rate': None, 'max_dd': 0}
    bet = bet.sort_values(['day', 'race_key'])
    stake = len(bet) * UNIT
    ret = float((bet['win'] * bet['win_odds'] * UNIT).sum())
    pl = np.where(bet['win'].to_numpy() == 1, bet['win_odds'].to_numpy() * UNIT - UNIT, -float(UNIT))
    tmp = bet[['day', 'race_key']].copy()
    tmp['pl'] = pl
    race_pl = tmp.groupby(['day', 'race_key'], sort=True)['pl'].sum().to_numpy()
    return {
        'n': int(len(bet)),
        'roi': 100.0 * ret / stake,
        'profit': ret - stake,
        'hit_rate': float(bet['win'].mean()),
        'max_dd': max_drawdown(list(race_pl)),
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load()
    reg = feature_registry(df)
    with open(os.path.join(OUT, 'feature_registry.json'), 'w', encoding='utf-8') as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    mkt = market_table(df)
    with open(os.path.join(OUT, 'market_baseline.json'), 'w', encoding='utf-8') as f:
        json.dump(mkt, f, ensure_ascii=False, indent=2)
    _ck('phase_b11.json', {'rows': len(reg), 'safe_horse': sum(1 for r in reg if r['klass'] == 'SAFE_PRE_RACE')})
    _ck('phase_b12.json', {'odds_bands': len(mkt)})

    fold_rows = []
    for year, train_end in FOLDS:
        train = df[df['day'] <= train_end]
        test = df[(df['day'] // 10000) == year]
        for name, feats in (('odds', FEATS_ODDS), ('no_odds', FEATS_NO_ODDS)):
            p, ptr, y, _clf, _cols = fit_predict(train, test, feats)
            met = metrics(y, p, test['p_market'].to_numpy())
            edge_tr = ptr - train['p_market'].to_numpy()
            thr = float(np.quantile(edge_tr, EDGE_Q))
            val = value_bets(test, p, thr) if name == 'odds' else {'n': 0, 'note': 'value uses odds model only'}
            rec = {
                'experiment_id': f'b15_{name}_{year}',
                'phase': 'B15',
                'hypothesis': f'logistic_{name}',
                'train_period': [20160101, train_end],
                'test_period': year,
                'features': feats,
                'parameters': {'C': 1.0, 'edge_q': EDGE_Q, 'threshold': thr},
                'metrics': met,
                'value': val,
                'status': 'tested',
            }
            append_experiment(rec)
            fold_rows.append({
                'year': year, 'model': name,
                'logloss': met['logloss'], 'logloss_market': met['logloss_market'],
                'auc': met['auc'], 'auc_market': met['auc_market'],
                'brier': met['brier'], 'brier_market': met['brier_market'],
                'value': val,
            })
            print(year, name, 'll', round(met['logloss'], 4), 'mkt', round(met['logloss_market'], 4),
                  'auc', None if met['auc'] is None else round(met['auc'], 3), file=sys.stderr)

    odds_rows = [r for r in fold_rows if r['model'] == 'odds']
    skill_years = sum(1 for r in odds_rows if r['logloss'] < r['logloss_market'] - 1e-4)
    value_years = [r['value'] for r in odds_rows if r['value'].get('n', 0) >= 80]
    roi_gt_100 = sum(1 for v in value_years if v.get('roi') and v['roi'] > 100)
    worst = min((v['roi'] for v in value_years), default=None)
    model_edge = skill_years >= 5 and roi_gt_100 >= 4 and worst is not None and worst >= 80
    exit_code = 'MODEL_EDGE' if model_edge else 'NO_MODEL_EDGE_FOUND'
    summary = {
        'exit': exit_code,
        'skill_years_logloss_beats_market': skill_years,
        'value_years_roi_gt_100': roi_gt_100,
        'worst_value_roi': worst,
        'folds': fold_rows,
        'edge_quantile_fixed': EDGE_Q,
        'notes': [
            'win_odds are JV final odds; ROI is not proven bet-time executable.',
            '2026 excluded from selection.',
            'Exotic bet types skipped: payout parser not re-verified in this run.',
            'VH_TOP2_POP6_WIN_V1 remains FAILED and was not reused.',
            'Simple-rule B5 result NO_HISTORICAL_EDGE_FOUND is unchanged.',
        ],
    }
    with open(os.path.join(OUT, 'b15_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    _ck('phase_b15.json', {'exit': exit_code, 'skill_years': skill_years})
    _ck('phase_b25.json', {'exit': exit_code, 'finalists': [] if not model_edge else ['logistic_odds_value']})
    digest = hashlib.sha256(json.dumps(FEATS_ODDS).encode()).hexdigest()[:12]
    print(json.dumps({'exit': exit_code, 'skill_years': skill_years, 'roi_gt_100': roi_gt_100,
                      'worst': worst, 'feat_hash': digest}, ensure_ascii=False))


if __name__ == '__main__':
    main()
