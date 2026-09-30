# -*- coding: utf-8 -*-
"""Descriptive stats for high-eff_n cohorts (research only)."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'data', 'research')

HOLDOUT_DAY = 20240101
TRAIN_END_DAY = 20231231

# Target: within high market-mix races, who becomes "big upset" vs "ordinary mix"
BIG_UPSET = 'big_upset_mix'
ORDINARY_MIX = 'ordinary_mix'

PRE_FEATURES = [
    'fav1', 'r21', 'r31', 'spread31', 'odds_entropy', 'eff_n', 'syn3', 'arare_prob',
    'field_size', 'live10', 'live30', 'mid515',
    'n_front', 'n_hana', 'mean_elim', 'n_elim3', 'h7_top2gap', 'vh2_top2gap',
    'mkt_ability_corr',
]


def eff_n_cohort_mask(df: pd.DataFrame, top_frac: float) -> pd.Series:
    """Top fraction by eff_n (higher = more mixed market)."""
    thr = df['eff_n'].quantile(1.0 - top_frac)
    return df['eff_n'] >= thr


def classify_mix_outcome(row) -> str | None:
    """Within high-eff_n: big upset vs ordinary (descriptive, not for training leak)."""
    if pd.isna(row.get('eff_n')):
        return None
    fav_out = row.get('favorite_failure', 0) == 1
    top2_out = row.get('top2_failure', 0) == 1
    multi = row.get('multi_longshot_7', 0) == 1 or row.get('multi_longshot_5', 0) == 1
    high_pay = row.get('payout_class_train_q', np.nan)
    high_pay = (pd.notna(high_pay) and float(high_pay) >= 3)
    if fav_out and (multi or high_pay or top2_out):
        return BIG_UPSET
    if row.get('honsen', 0) == 1:
        return ORDINARY_MIX
    if not fav_out and not multi:
        return ORDINARY_MIX
    return ORDINARY_MIX if not fav_out else BIG_UPSET


def cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float('nan')
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = np.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    if pooled <= 0:
        return 0.0
    return float((a.mean() - b.mean()) / pooled)


def bootstrap_mean_diff(a, b, n_boot=400, seed=42):
    rng = np.random.default_rng(seed)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return None
    diffs = []
    for _ in range(n_boot):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs.append(sa.mean() - sb.mean())
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {'mean_diff': float(a.mean() - b.mean()), 'ci_lo': float(lo), 'ci_hi': float(hi)}


def compare_groups(df: pd.DataFrame, top_frac: float = 0.2) -> dict:
    sub = df[eff_n_cohort_mask(df, top_frac)].copy()
    sub['mix_class'] = sub.apply(classify_mix_outcome, axis=1)
    big = sub[sub['mix_class'] == BIG_UPSET]
    ord_ = sub[sub['mix_class'] == ORDINARY_MIX]
    feats = [c for c in PRE_FEATURES if c in sub.columns]
    rows = []
    for c in feats:
        x = big[c].astype(float).values
        y = ord_[c].astype(float).values
        rows.append({
            'feature': c,
            'n_big': int(np.sum(~np.isnan(x))),
            'n_ordinary': int(np.sum(~np.isnan(y))),
            'mean_big': float(np.nanmean(x)) if len(x) else None,
            'mean_ordinary': float(np.nanmean(y)) if len(y) else None,
            'median_big': float(np.nanmedian(x)) if len(x) else None,
            'median_ordinary': float(np.nanmedian(y)) if len(y) else None,
            'cohen_d': cohen_d(x, y),
            'bootstrap': bootstrap_mean_diff(x, y),
        })
    rows.sort(key=lambda r: abs(r['cohen_d']) if r['cohen_d'] == r['cohen_d'] else 0, reverse=True)
    return {
        'top_frac': top_frac,
        'cohort_n': len(sub),
        'big_upset_n': len(big),
        'ordinary_n': len(ord_),
        'features': rows,
    }


def baseline_arare_holdout(df: pd.DataFrame) -> dict:
    """Holdout metrics for frozen arare_prob vs longshot_place_7 (same as scanner target)."""
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

    h = df[df['day'] >= HOLDOUT_DAY].dropna(subset=['arare_prob', 'longshot_place_7'])
    if len(h) < 50:
        return {'note': '件数不足', 'n': len(h)}
    y = h['longshot_place_7'].astype(int).values
    p = h['arare_prob'].astype(float).values
    out = {
        'n': len(h),
        'period': f'day>={HOLDOUT_DAY}',
        'label': 'longshot_place_7',
        'auc': float(roc_auc_score(y, p)),
        'pr_auc': float(average_precision_score(y, p)),
        'brier': float(brier_score_loss(y, p)),
    }
    for pct in (0.1, 0.2, 0.3):
        k = max(1, int(len(h) * pct))
        top = h.nlargest(k, 'arare_prob')
        out[f'precision_top_{int(pct*100)}pct'] = float(top['longshot_place_7'].mean())
    return out


def run_analysis(df: pd.DataFrame) -> dict:
    rep = {
        'n_races': len(df),
        'day_min': int(df['day'].min()),
        'day_max': int(df['day'].max()),
        'missing_rates': {c: float(df[c].isna().mean()) for c in df.columns if df[c].isna().any()},
        'label_rates': {},
        'eff_n_quantiles': df['eff_n'].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).to_dict(),
        'cohorts': {},
        'baseline_holdout': baseline_arare_holdout(df),
    }
    for col in ('favorite_failure', 'top2_failure', 'longshot_place_7', 'longshot_place_6',
                'multi_longshot_5', 'multi_longshot_7', 'honsen', 'arareB'):
        if col in df.columns:
            rep['label_rates'][col] = float(df[col].mean())
    for frac in (0.5, 0.3, 0.2, 0.1):
        rep['cohorts'][f'top_{int(frac*100)}pct_eff_n'] = compare_groups(df, top_frac=frac)
    return rep


def save_report(report: dict, path: str | None = None) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = path or os.path.join(OUT_DIR, 'high_entropy_upset_report.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    return path
