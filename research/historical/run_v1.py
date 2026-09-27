# -*- coding: utf-8 -*-
"""historical_research_v1

単勝100円。TRAINで候補を凍結し、VALIDATIONは一度だけ。
day>=20250101 は読み込んだ直後に捨て、集計に入れない。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.experiment_store import append_experiment
from research.historical import VERSION
from research.historical.feature_classes import HORSE, race_class
from research.metrics import max_drawdown
from research.parity_gate import assert_split_day_allowed
from research.splits import split_for_day

OUT = os.path.join(ROOT, 'data', 'research', 'historical_v1')
HOLDOUT_FROM = 20250101
UNIT = 100
MIN_N = 500
BOOT_N = 400
RNG = np.random.default_rng(42)

# 事前定義。VALIDATION 後に増やさない。
RULES = [
    'fav',
    'vh_top',
    'ability_top',
    'h7_top',
    'spurt_top',
    'jockey_top',
    'trainer_top',
    'elim_le1_ninki_le3',
    'vh_rank2_ninki_ge6',
    'fav_odds_ge3',
    'fav_field_le12',
    'fav_fillies',
    'fav_dirt',
    'fav_turf',
    'fav_vscore_lt50',
    'vh_vscore_50_70',
    'fav_entropy_hi',
    'fav_mean_elim_hi',
]


def _drop_holdout(df: pd.DataFrame) -> pd.DataFrame:
    day = pd.to_numeric(df['day'], errors='coerce')
    keep = day < HOLDOUT_FROM
    # guard: remaining days must not be holdout
    for d in pd.unique(day[keep].dropna().astype(int))[:3]:
        assert_split_day_allowed(int(d))
    return df.loc[keep].copy()


def load_frames():
    hcols = list(HORSE)
    horses = pd.read_csv(
        os.path.join(ROOT, 'data', 'export', 'horse_races.csv'), usecols=hcols)
    horses = _drop_holdout(horses)
    rcols_all = pd.read_csv(
        os.path.join(ROOT, 'data', 'export', 'races.csv'), nrows=0).columns.tolist()
    safe_r = [c for c in rcols_all if race_class(c) == 'SAFE_PRE_RACE']
    races = pd.read_csv(
        os.path.join(ROOT, 'data', 'export', 'races.csv'), usecols=safe_r)
    races = _drop_holdout(races)
    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)
    horses['split'] = horses['day'].map(lambda d: split_for_day(int(d)))
    return horses, races


def registry(horses, races):
    rows = []
    for col, cls in HORSE.items():
        s = horses[col]
        rows.append({
            'column': col, 'level': 'horse', 'klass': cls,
            'na_rate': float(s.isna().mean()) if s.dtype != object else float(s.isna().mean()),
            'usable_as_input': cls == 'SAFE_PRE_RACE',
        })
    # race file classes for columns not loaded
    head = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'races.csv'), nrows=0)
    for col in head.columns:
        cls = race_class(col)
        na = None
        if col in races.columns:
            na = float(races[col].isna().mean())
        rows.append({
            'column': col, 'level': 'race', 'klass': cls,
            'na_rate': na, 'usable_as_input': cls == 'SAFE_PRE_RACE',
        })
    return rows


def _prepare(horses, races):
    m = races.set_index('race_key')
    df = horses.merge(
        m[['vscore', 'odds_entropy', 'mean_elim', 'fillies', 'fav1']].reset_index(),
        on='race_key', how='left', suffixes=('', '_r'))
    df['vh_rank'] = df.groupby('race_key')['vh2_score'].rank(ascending=False, method='min')
    df['ab_rank'] = df.groupby('race_key')['ability_score'].rank(ascending=True, method='min')
    df['spurt_rank'] = df.groupby('race_key')['spurt_idx'].rank(ascending=False, method='min')
    df['jk_rank'] = df.groupby('race_key')['jockey_jyo_win'].rank(ascending=False, method='min')
    df['tr_rank'] = df.groupby('race_key')['trainer_jyo_t3'].rank(ascending=False, method='min')
    return df


def mask_for(rule, df, frozen):
    ninki = df['ninki']
    base = {
        'fav': ninki == 1,
        'vh_top': df['vh_rank'] == 1,
        'ability_top': df['ab_rank'] == 1,
        'h7_top': df['h7_rank'] == 1,
        'spurt_top': df['spurt_rank'] == 1,
        'jockey_top': df['jk_rank'] == 1,
        'trainer_top': df['tr_rank'] == 1,
        'elim_le1_ninki_le3': (df['elim_n'] <= 1) & (ninki <= 3),
        'vh_rank2_ninki_ge6': (df['vh_rank'] <= 2) & (ninki >= 6),
        'fav_odds_ge3': (ninki == 1) & (df['win_odds'] >= 3),
        'fav_field_le12': (ninki == 1) & (df['field_size'] <= 12),
        'fav_fillies': (ninki == 1) & (df['fillies'] == 1),
        'fav_dirt': (ninki == 1) & (df['surface_code'] == 1),
        'fav_turf': (ninki == 1) & (df['surface_code'] != 1),
        'fav_vscore_lt50': (ninki == 1) & (df['vscore'] < 50),
        'vh_vscore_50_70': (df['vh_rank'] == 1) & (df['vscore'] >= 50) & (df['vscore'] < 70),
        'fav_entropy_hi': (ninki == 1) & (df['odds_entropy'] >= frozen['entropy_p75']),
        'fav_mean_elim_hi': (ninki == 1) & (df['mean_elim'] >= frozen['elim_p75']),
    }
    return base[rule].fillna(False)


def score_bets(df):
    """1行=1点の単勝。戻りはレース順の profit。"""
    if df.empty:
        return _empty()
    sub = df.sort_values(['day', 'race_key', 'umaban'])
    stake = len(sub) * UNIT
    ret = float((sub['win'].astype(float) * sub['win_odds'].astype(float) * UNIT).sum())
    profit_row = np.where(sub['win'].to_numpy() == 1, sub['win_odds'].to_numpy() * UNIT - UNIT, -UNIT)
    # race-level for DD: sum within race
    tmp = sub[['day', 'race_key']].copy()
    tmp['pl'] = profit_row
    race_pl = tmp.groupby(['day', 'race_key'], sort=True)['pl'].sum().to_numpy()
    hits = int(sub['win'].sum())
    years = {}
    for y, g in sub.groupby(sub['day'] // 10000):
        st = len(g) * UNIT
        rt = float((g['win'] * g['win_odds'] * UNIT).sum())
        years[int(y)] = {'n': int(len(g)), 'roi': 100.0 * rt / st if st else 0.0}
    boot = []
    if len(race_pl) >= 30:
        for _ in range(BOOT_N):
            sample = RNG.choice(race_pl, size=len(race_pl), replace=True)
            boot.append(100.0 * (sample.sum() + len(sample) * 0) / (len(sub) * UNIT) * (len(race_pl) / max(len(race_pl), 1)))
        # ROI bootstrap on race profits / original stake scale
        stake_per = stake / len(race_pl)
        rois = []
        for _ in range(BOOT_N):
            sample = RNG.choice(race_pl, size=len(race_pl), replace=True)
            rois.append(100.0 * (sample.sum() + len(race_pl) * stake_per) / (len(race_pl) * stake_per))
        boot = rois
    lo, hi = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))) if boot else (None, None)
    return {
        'n_bets': int(len(sub)),
        'n_races': int(sub['race_key'].nunique()),
        'stake': stake,
        'payout': ret,
        'profit': ret - stake,
        'roi': 100.0 * ret / stake if stake else 0.0,
        'hit_rate': hits / len(sub) if len(sub) else 0.0,
        'avg_odds': float(sub['win_odds'].mean()),
        'median_odds': float(sub['win_odds'].median()),
        'max_drawdown': max_drawdown(list(race_pl)),
        'years': years,
        'roi_ci95': [lo, hi],
        'years_roi_gt_90': sum(1 for v in years.values() if v['roi'] >= 90),
    }


def _empty():
    return {'n_bets': 0, 'n_races': 0, 'stake': 0, 'payout': 0, 'profit': 0, 'roi': 0,
            'hit_rate': 0, 'avg_odds': 0, 'median_odds': 0, 'max_drawdown': 0,
            'years': {}, 'roi_ci95': [None, None], 'years_roi_gt_90': 0}


def univariate(train):
    cols = [
        'ninki', 'win_odds', 'vh2_score', 'ability_score', 'elim_n', 'h7_fig',
        'spurt_idx', 'jockey_jyo_win', 'trainer_jyo_t3', 'field_size', 'vscore',
        'odds_entropy', 'mean_elim',
    ]
    out = []
    for col in cols:
        s = pd.to_numeric(train[col], errors='coerce')
        ok = s.notna()
        if ok.sum() < 1000:
            continue
        try:
            bins = pd.qcut(s[ok], 5, duplicates='drop')
        except ValueError:
            continue
        part = train.loc[ok].copy()
        part['_bin'] = bins.astype(str)
        for b, g in part.groupby('_bin'):
            met = score_bets(g)
            met.update({'feature': col, 'bin': b, 'warn_small': met['n_bets'] < MIN_N})
            out.append(met)
    return out


def eligible(m):
    if m['n_bets'] < MIN_N:
        return False
    if m['years_roi_gt_90'] < 4:
        return False
    lo = m['roi_ci95'][0]
    return m['roi'] >= 100 or (lo is not None and lo >= 95)


def main():
    os.makedirs(OUT, exist_ok=True)
    horses, races = load_frames()
    reg = registry(horses, races)
    with open(os.path.join(OUT, 'feature_registry.json'), 'w', encoding='utf-8') as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    df = _prepare(horses, races)
    train = df[df['split'] == 'train']
    val = df[df['split'] == 'validation']
    frozen_thr = {
        'entropy_p75': float(train['odds_entropy'].quantile(0.75)),
        'elim_p75': float(train['mean_elim'].quantile(0.75)),
    }
    uni = univariate(train)
    with open(os.path.join(OUT, 'stage1_univariate.json'), 'w', encoding='utf-8') as f:
        json.dump(uni, f, ensure_ascii=False)

    train_metrics = {}
    for rule in RULES:
        m = score_bets(train[mask_for(rule, train, frozen_thr)])
        train_metrics[rule] = m
        append_experiment({
            'experiment_id': f'{VERSION}_{rule}_train',
            'baseline_version': VERSION,
            'hypothesis': rule,
            'changed_variable': rule,
            'split': 'train',
            'metrics': m,
            'thresholds': frozen_thr,
            'verdict': 'eligible' if eligible(m) else 'fail_screen',
        })

    ranked = [r for r in RULES if eligible(train_metrics[r])]
    ranked.sort(key=lambda r: (train_metrics[r]['profit'], train_metrics[r]['roi']), reverse=True)
    picked = ranked[:10]
    freeze = {'version': VERSION, 'thresholds': frozen_thr, 'rules': picked, 'ticket': 'win_100yen'}
    with open(os.path.join(OUT, 'freeze.json'), 'w', encoding='utf-8') as f:
        json.dump(freeze, f, ensure_ascii=False, indent=2)

    val_metrics = {}
    survived = []
    for rule in picked:
        m = score_bets(val[mask_for(rule, val, frozen_thr)])
        val_metrics[rule] = m
        tr = train_metrics[rule]
        ok = m['n_bets'] >= 80 and m['roi'] >= 95 and m['profit'] > tr['profit'] * 0
        # 再現: VALIDATION ROI が TRAIN の方向（100超なら VAL も 95以上）
        reproduce = m['n_bets'] >= 80 and ((tr['roi'] >= 100 and m['roi'] >= 95) or (m['roi'] >= tr['roi'] - 15 and m['roi'] >= 90))
        append_experiment({
            'experiment_id': f'{VERSION}_{rule}_validation',
            'baseline_version': VERSION,
            'hypothesis': rule,
            'split': 'validation',
            'metrics': m,
            'verdict': 'reproduced' if reproduce else 'not_reproduced',
        })
        if reproduce:
            survived.append(rule)

    summary = {
        'version': VERSION,
        'train_rules': {k: train_metrics[k] for k in RULES},
        'frozen': picked,
        'validation': val_metrics,
        'survived': survived[:5],
        'holdout': 'not_run',
    }
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps({
        'frozen': picked,
        'survived': survived[:5],
        'n_train_rows': int(len(train)),
        'n_val_rows': int(len(val)),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
