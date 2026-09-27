# -*- coding: utf-8 -*-
"""影響率ランクの研究。ROI は目的関数に入れない。本番ウェイトは変えない。"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.experiment_store import append_experiment

OUT = os.path.join(ROOT, 'data', 'research', 'influence_rank')
FOLDS = [(2020, 20191231), (2021, 20201231), (2022, 20211231),
         (2023, 20221231), (2024, 20231231), (2025, 20241231)]
INDEP = ['vh2_score', 'ability_inv', 'h7_fig', 'spurt_mean3', 'prior_top3_rate',
         'jockey_jyo_win', 'trainer_jyo_t3', 'elim_inv']
AWARE = INDEP + ['ninki_inv']


def load():
    cols = ['race_key', 'day', 'chakujun', 'ninki', 'vh2_score', 'ability_score', 'h7_fig',
            'spurt_mean3', 'prior_top3_rate', 'jockey_jyo_win', 'trainer_jyo_t3', 'elim_n']
    df = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'horse_races.csv'), usecols=cols)
    df = df[(df['day'] <= 20251231) & df['chakujun'].notna() & (df['chakujun'] > 0)].copy()
    df['race_key'] = df['race_key'].astype(str)
    df['ability_inv'] = -pd.to_numeric(df['ability_score'], errors='coerce')
    df['elim_inv'] = -pd.to_numeric(df['elim_n'], errors='coerce')
    df['ninki_inv'] = -pd.to_numeric(df['ninki'], errors='coerce')
    df['rel_win'] = (df['chakujun'] == 1).astype(int)
    df['rel_top3'] = (df['chakujun'] <= 3).astype(int)
    df['gain'] = np.where(df['chakujun'] == 1, 3, np.where(df['chakujun'] == 2, 2, np.where(df['chakujun'] == 3, 1, 0)))
    return df


def ndcg_at3(df, score_col):
    total = 0.0
    n = 0
    discounts = 1.0 / np.log2(np.arange(2, 5))
    for _, g in df.groupby('race_key', sort=False):
        if len(g) < 3:
            continue
        pred = g.sort_values(score_col, ascending=False).head(3)['gain'].to_numpy()
        ideal = np.sort(g['gain'].to_numpy())[::-1][:3]
        dcg = float((pred * discounts).sum())
        idcg = float((ideal * discounts).sum())
        total += dcg / idcg if idcg else 0.0
        n += 1
    return total / n if n else 0.0


def rank_stats(df, score_col):
    g = df.copy()
    g['rk'] = g.groupby('race_key')[score_col].rank(ascending=False, method='min')
    out = {}
    r1 = g[g['rk'] == 1]
    top3_cap = []
    for _, race in g.groupby('race_key', sort=False):
        truth = set(race.loc[race['chakujun'] <= 3, 'rk'])  # wrong
    # coverage: fraction of actual top3 horses that our top3 contains, averaged
    hit = 0
    races = 0
    for _, race in g.groupby('race_key', sort=False):
        if race['chakujun'].le(3).sum() < 3:
            continue
        ours = set(race.nsmallest(3, 'rk').index) if False else set(race.loc[race['rk'] <= 3].index)
        truth_idx = set(race.loc[race['chakujun'] <= 3].index)
        hit += len(ours & truth_idx) / 3.0
        races += 1
    buckets = {}
    for k in range(1, 6):
        part = g[g['rk'] == k]
        if part.empty:
            continue
        buckets[str(k)] = {
            'n': int(len(part)),
            'win': float((part['chakujun'] == 1).mean()),
            'top3': float((part['chakujun'] <= 3).mean()),
        }
    return {
        'rank1_win': float((r1['chakujun'] == 1).mean()) if len(r1) else None,
        'rank1_top3': float((r1['chakujun'] <= 3).mean()) if len(r1) else None,
        'top3_capture': hit / races if races else None,
        'ndcg3': ndcg_at3(g, score_col),
        'buckets': buckets,
    }


def fit_scores(train, test, feats):
    xtr = train[feats].apply(pd.to_numeric, errors='coerce')
    xte = test[feats].apply(pd.to_numeric, errors='coerce')
    med = xtr.median()
    xtr = xtr.fillna(med)
    xte = xte.fillna(med)
    scaler = StandardScaler().fit(xtr)
    clf = LogisticRegression(C=1.0, max_iter=200, random_state=42)
    clf.fit(scaler.transform(xtr), train['rel_win'].to_numpy())
    test = test.copy()
    test['opt_score'] = clf.predict_proba(scaler.transform(xte))[:, 1]
    coef = {f: float(c) for f, c in zip(feats, clf.coef_[0])}
    return test, coef


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load()
    # baselines use native columns: higher score = better rank
    df['pop_score'] = df['ninki_inv']
    df['vh_score'] = pd.to_numeric(df['vh2_score'], errors='coerce')
    df['ab_score'] = df['ability_inv']
    rows = []
    coefs = []
    for year, end in FOLDS:
        train = df[df['day'] <= end]
        test = df[df['day'] // 10000 == year]
        scored, coef = fit_scores(train, test, INDEP)
        aware, coef_a = fit_scores(train, test, AWARE)
        coefs.append({'year': year, 'independent': coef, 'aware': coef_a})
        for name, frame, col in (
            ('popularity', test, 'pop_score'),
            ('vh', test, 'vh_score'),
            ('ability', test, 'ab_score'),
            ('influence_independent', scored, 'opt_score'),
            ('influence_market_aware', aware, 'opt_score'),
        ):
            met = rank_stats(frame, col)
            rows.append({'year': year, 'model': name, **{k: met[k] for k in ('rank1_win', 'rank1_top3', 'top3_capture', 'ndcg3')}, 'buckets': met['buckets']})
            append_experiment({
                'experiment_id': f'ir_{name}_{year}',
                'phase': 'INFLUENCE_RANK',
                'hypothesis': name,
                'test_period': year,
                'ndcg3': met['ndcg3'],
                'rank1_win': met['rank1_win'],
                'status': 'tested',
                'objective': 'win-label logistic on standardized SAFE columns; ROI excluded',
            })
        print(year, 'done', file=sys.stderr)
    # signs of independent coefs
    signs = {}
    for feat in INDEP:
        s = [np.sign(c['independent'][feat]) for c in coefs]
        signs[feat] = {'signs': s, 'stable': len(set(s)) == 1}
    # promotion: independent ndcg > max(vh, ability) in >=4 years AND rank1 win > bucket3 win in >=4
    beats = 0
    mono = 0
    for year, _ in FOLDS:
        ind = next(r for r in rows if r['year'] == year and r['model'] == 'influence_independent')
        vh = next(r for r in rows if r['year'] == year and r['model'] == 'vh')
        ab = next(r for r in rows if r['year'] == year and r['model'] == 'ability')
        pop = next(r for r in rows if r['year'] == year and r['model'] == 'popularity')
        if ind['ndcg3'] > max(vh['ndcg3'], ab['ndcg3']) + 1e-4:
            beats += 1
        b1 = ind['buckets'].get('1', {}).get('win', 0)
        b3 = ind['buckets'].get('3', {}).get('win', 1)
        if b1 > b3:
            mono += 1
        ind['beats_popularity_ndcg'] = ind['ndcg3'] > pop['ndcg3']
    exit_code = 'INFLUENCE_RANK_CANDIDATE' if beats >= 4 and mono >= 4 and all(v['stable'] for v in signs.values()) else 'NO_STABLE_INFLUENCE_RANK'
    summary = {
        'exit': exit_code,
        'years_ndcg_beats_vh_and_ability': beats,
        'years_rank1_win_above_rank3': mono,
        'coef_signs': signs,
        'folds': rows,
        'coefs': coefs,
        'betting_test': False,
        'production_weights_changed': False,
        'excluded': ['ScoringSignal', 'Projected Score', 'BattleScore', 'JPower', 'Lap33'],
    }
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    ck = os.path.join(ROOT, 'data', 'research', 'checkpoints', 'influence_rank.json')
    with open(ck, 'w', encoding='utf-8') as f:
        json.dump({'exit': exit_code, 'beats': beats, 'mono': mono}, f, indent=2)
    print(json.dumps({'exit': exit_code, 'beats': beats, 'mono': mono}, ensure_ascii=False))


if __name__ == '__main__':
    main()
