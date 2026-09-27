# -*- coding: utf-8 -*-
"""Phase B5 walk-forward。各 TRAIN で screen し、翌年だけを1回評価する。"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.experiment_store import append_experiment
from research.metrics import max_drawdown
from research.walkforward.catalog import (
    BH_Q, FAILED_REFERENCE, FOLDS, MIN_TEST_N, MIN_TEST_YEARS,
    MIN_YEARS_ROI_100, RULES, SELECT_MAX_DAY, WORST_ROI_FLOOR,
)

UNIT = 100
BOOT = 1000
RNG = np.random.default_rng(42)
OUT = os.path.join(ROOT, 'data', 'research', 'walkforward')
CACHE = os.path.join(ROOT, 'data', 'research', 'cache', 'b5_frame.pkl')


def load_frame():
    if os.path.exists(CACHE):
        return pd.read_pickle(CACHE)
    from research.historical.feature_classes import HORSE
    cols = [c for c in HORSE if c != 'combo']
    extra = ['win']
    horses = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'horse_races.csv'),
                         usecols=list(dict.fromkeys(cols + extra)))
    races = pd.read_csv(
        os.path.join(ROOT, 'data', 'export', 'races.csv'),
        usecols=['race_key', 'day', 'vscore', 'odds_entropy', 'mean_elim', 'fillies', 'fav1'])
    horses = horses[horses['day'] <= SELECT_MAX_DAY]
    races = races[races['day'] <= SELECT_MAX_DAY]
    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)
    df = horses.merge(races.drop(columns=['day']), on='race_key', how='left')
    df['vh_rank'] = df.groupby('race_key')['vh2_score'].rank(ascending=False, method='min')
    df['ab_rank'] = df.groupby('race_key')['ability_score'].rank(ascending=True, method='min')
    df['spurt_rank'] = df.groupby('race_key')['spurt_idx'].rank(ascending=False, method='min')
    df['jk_rank'] = df.groupby('race_key')['jockey_jyo_win'].rank(ascending=False, method='min')
    df['tr_rank'] = df.groupby('race_key')['trainer_jyo_t3'].rank(ascending=False, method='min')
    df['pt3_rank'] = df.groupby('race_key')['prior_top3_rate'].rank(ascending=False, method='min')
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    df.to_pickle(CACHE)
    return df


def mask(rule, df, thr):
    n = df['ninki']
    table = {
        'fav': n == 1,
        'vh_top': df['vh_rank'] == 1,
        'ability_top': df['ab_rank'] == 1,
        'h7_top': df['h7_rank'] == 1,
        'spurt_top': df['spurt_rank'] == 1,
        'jockey_top': df['jk_rank'] == 1,
        'trainer_top': df['tr_rank'] == 1,
        'prior_top3_top': df['pt3_rank'] == 1,
        'elim_le1_ninki_le3': (df['elim_n'] <= 1) & (n <= 3),
        'vh_rank2_ninki_ge6': (df['vh_rank'] <= 2) & (n >= 6),
        'fav_odds_ge3': (n == 1) & (df['win_odds'] >= 3),
        'fav_field_le12': (n == 1) & (df['field_size'] <= 12),
        'fav_fillies': (n == 1) & (df['fillies'] == 1),
        'fav_dirt': (n == 1) & (df['surface_code'] == 1),
        'fav_turf': (n == 1) & (df['surface_code'] != 1),
        'fav_sprint': (n == 1) & (df['kyori_int'] <= 1400),
        'fav_vscore_lt50': (n == 1) & (df['vscore'] < 50),
        'fav_vscore_50_70': (n == 1) & (df['vscore'] >= 50) & (df['vscore'] < 70),
        'fav_entropy_hi': (n == 1) & (df['odds_entropy'] >= thr['entropy_p75']),
        'fav_mean_elim_hi': (n == 1) & (df['mean_elim'] >= thr['elim_p75']),
        'fav_age_le3': (n == 1) & (df['age'] <= 3),
    }
    return table[rule].fillna(False)


def score(df):
    if df.empty:
        return {'n': 0, 'hit_rate': 0.0, 'roi': 0.0, 'profit': 0.0, 'max_dd': 0.0, 'stake': 0.0}
    sub = df.sort_values(['day', 'race_key'])
    stake = len(sub) * UNIT
    ret = float((sub['win'] * sub['win_odds'] * UNIT).sum())
    pl = np.where(sub['win'].to_numpy() == 1, sub['win_odds'].to_numpy() * UNIT - UNIT, -UNIT)
    tmp = sub[['day', 'race_key']].copy()
    tmp['pl'] = pl
    race_pl = tmp.groupby(['day', 'race_key'], sort=True)['pl'].sum().to_numpy()
    return {
        'n': int(len(sub)),
        'hit_rate': float(sub['win'].mean()),
        'roi': 100.0 * ret / stake,
        'profit': ret - stake,
        'max_dd': max_drawdown(list(race_pl)),
        'stake': float(stake),
        'payout': ret,
    }


def train_pass(m, n_years):
    return m['n'] >= 400 and m['roi'] > 0


def bh(pvals):
    """Benjamini-Hochberg. returns reject mask."""
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    thresh = BH_Q * (np.arange(1, m + 1) / m)
    ranked = np.array(pvals)[order]
    below = ranked <= thresh
    cutoff = below.nonzero()[0].max() if below.any() else -1
    reject = np.zeros(m, dtype=bool)
    if cutoff >= 0:
        reject[order[:cutoff + 1]] = True
    return reject.tolist()


def pooled_p(bets_list):
    """One-sided bootstrap P(ROI <= 100) under resampling of pooled bets."""
    if not bets_list:
        return 1.0
    df = pd.concat(bets_list, ignore_index=True)
    if len(df) < 50:
        return 1.0
    win = df['win'].to_numpy()
    odds = df['win_odds'].to_numpy()
    n = len(df)
    hits = 0
    idx = np.arange(n)
    for _ in range(BOOT):
        take = RNG.choice(idx, size=n, replace=True)
        ret = float((win[take] * odds[take] * UNIT).sum())
        if 100.0 * ret / (n * UNIT) <= 100.0:
            hits += 1
    return (hits + 1) / (BOOT + 1)


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load_frame()
    tests = {rid: [] for rid, _ in RULES}
    pooled_bets = {rid: [] for rid, _ in RULES}
    n_exp = 0
    for fold, tr0, tr1, te0, te1 in FOLDS:
        train = df[(df['day'] >= tr0) & (df['day'] <= tr1)]
        test = df[(df['day'] >= te0) & (df['day'] <= te1)]
        thr = {
            'entropy_p75': float(train['odds_entropy'].quantile(0.75)),
            'elim_p75': float(train['mean_elim'].quantile(0.75)),
        }
        n_years = train['day'].astype(int).floordiv(10000).nunique()
        for rid, family in RULES:
            tm = score(train[mask(rid, train, thr)])
            passed = train_pass(tm, n_years) and rid != 'skip'
            status = 'train_fail' if not passed else 'frozen_for_test'
            rec = {
                'experiment_id': f'b5_{fold}_{rid}',
                'phase': 'B5',
                'hypothesis': rid,
                'family': family,
                'train_period': [tr0, tr1],
                'test_period': [te0, te1] if passed else None,
                'rules': rid,
                'sample_size': tm['n'],
                'stake': tm['stake'],
                'hit_rate': tm['hit_rate'],
                'ROI': tm['roi'],
                'profit': tm['profit'],
                'max_DD': tm['max_dd'],
                'status': status,
                'reason': 'screen_on_train_only',
                'failed_reference': rid == FAILED_REFERENCE,
            }
            if passed:
                sm = score(test[mask(rid, test, thr)])
                rec['test'] = sm
                rec['status'] = 'tested'
                tests[rid].append({'fold': fold, 'year': te0 // 10000, **sm})
                part = test[mask(rid, test, thr)][['win', 'win_odds']]
                if len(part):
                    pooled_bets[rid].append(part)
            append_experiment(rec)
            n_exp += 1
        print(fold, 'done', file=sys.stderr)

    rows = []
    pvals = []
    ids = []
    for rid, family in RULES:
        ys = tests[rid]
        if rid == FAILED_REFERENCE:
            rows.append({'rule': rid, 'family': family, 'blocked': True, 'n_tests': len(ys)})
            continue
        if len(ys) < MIN_TEST_YEARS:
            rows.append({'rule': rid, 'family': family, 'blocked': False, 'n_tests': len(ys),
                         'promote': False, 'reason': 'too_few_test_years'})
            continue
        rois = [y['roi'] for y in ys if y['n'] >= MIN_TEST_N]
        profits = sum(y['profit'] for y in ys)
        p = pooled_p(pooled_bets[rid])
        ids.append(rid)
        pvals.append(p)
        rows.append({
            'rule': rid, 'family': family, 'blocked': False,
            'n_tests': len(ys),
            'years_roi_gt_100': sum(1 for r in rois if r > 100),
            'years_roi_gt_90': sum(1 for r in rois if r > 90),
            'median_roi': float(np.median(rois)) if rois else None,
            'worst_roi': float(min(rois)) if rois else None,
            'combined_profit': profits,
            'p_roi_le_100': p,
            'tests': ys,
        })
    reject = bh(pvals) if pvals else []
    survivors = []
    j = 0
    for row in rows:
        if row.get('blocked') or 'p_roi_le_100' not in row:
            row['promote'] = False
            continue
        row['bh_reject'] = reject[j] if j < len(reject) else False
        j += 1
        ok = (
            row['years_roi_gt_100'] >= MIN_YEARS_ROI_100
            and row['worst_roi'] is not None and row['worst_roi'] >= WORST_ROI_FLOOR
            and row['bh_reject']
        )
        row['promote'] = bool(ok)
        if ok:
            survivors.append(row['rule'])

    summary = {
        'phase': 'B5',
        'n_rules': len(RULES),
        'n_experiments': n_exp,
        'survivors': survivors,
        'exit': 'to_b6' if survivors else 'NO_HISTORICAL_EDGE_FOUND',
        'rows': rows,
        'note': '2026 excluded from selection. Failed v1 rule not promotable.',
    }
    with open(os.path.join(OUT, 'b5_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    ck = os.path.join(ROOT, 'data', 'research', 'checkpoints')
    os.makedirs(ck, exist_ok=True)
    with open(os.path.join(ck, 'phase_b5.json'), 'w', encoding='utf-8') as f:
        json.dump({'exit': summary['exit'], 'survivors': survivors, 'n_experiments': n_exp}, f, indent=2)
    print(json.dumps({'exit': summary['exit'], 'survivors': survivors, 'n_exp': n_exp}, ensure_ascii=False))


if __name__ == '__main__':
    main()
