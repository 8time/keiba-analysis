# -*- coding: utf-8 -*-
"""Favorite Survival research: high eff_n but favorites still finish (no production changes)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'data', 'research')
HORSE_EXPORT = os.path.join(ROOT, 'data', 'export', 'horse_races.csv')

TRAIN_END_DAY = 20221231
VAL_END_DAY = 20231231
HOLDOUT_START_DAY = 20240101

TARGET_PRIMARY = 'type_A_solid'

# Leak guard
POST_RACE_BLOCK = {
    'favorite_failure', 'top2_failure', 'longshot_place_6', 'longshot_place_7',
    'multi_longshot_5', 'multi_longshot_7', 'honsen', 'arareA', 'arareB', 'ana2',
    'win_payout', 'umaren_payout', 'umatan_payout', 'trio_payout', 'trifecta_payout',
    'payout_class_train_q', 'finish_1_ninki', 'finish_2_ninki', 'finish_3_ninki',
    'fav1_chakujun', 'fav2_chakujun', 'ninki_top3_logsum', 'finish_pattern',
    'top2_in_top3', 'top3_in_top3', 'n_in_top3_ge6', 'n_in_top3_ge7', 'n_in_top3_ge10',
    'type_B_hole1', 'type_C_hole2', 'type_D_fav_collapse', 'type_E_full_collapse',
    'type_F_payout_boom', 'stratum',
    'trio_payout_pct_global', 'trio_payout_pct_train', 'trio_payout_pct_stratum',
    'trifecta_payout_pct_global', 'trifecta_payout_pct_train', 'trifecta_payout_pct_stratum',
}


@dataclass
class ExplorationLog:
    n_features_screened: int = 0
    n_models_fitted: int = 0
    n_filter_thresholds_tried: int = 0
    feature_names: list[str] = field(default_factory=list)
    model_names: list[str] = field(default_factory=list)


def period_mask(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    d = df['day']
    train = d <= TRAIN_END_DAY
    val = (d > TRAIN_END_DAY) & (d <= VAL_END_DAY)
    hold = d >= HOLDOUT_START_DAY
    return train, val, hold


def eff_n_threshold_train_only(df: pd.DataFrame, top_frac: float = 0.2) -> float:
    train, _, _ = period_mask(df)
    sub = df.loc[train, 'eff_n'].dropna()
    if len(sub) < 100:
        return float(df['eff_n'].quantile(1 - top_frac))
    return float(sub.quantile(1 - top_frac))


def high_eff_n_mask(df: pd.DataFrame, top_frac: float = 0.2) -> pd.Series:
    thr = eff_n_threshold_train_only(df, top_frac)
    return df['eff_n'] >= thr


def add_auxiliary_targets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['y_fav1_top3'] = (out['fav1_chakujun'] <= 3).astype(float)
    out['y_either_fav12_top3'] = ((out['fav1_chakujun'] <= 3) | (out['fav2_chakujun'] <= 3)).astype(float)
    out['y_both_fav12_top3'] = ((out['fav1_chakujun'] <= 3) & (out['fav2_chakujun'] <= 3)).astype(float)
    out['y_top3_ninki_ge2_in_top3'] = (out['top3_in_top3'] >= 2).astype(float)
    out['y_honsen'] = out['honsen'].astype(float)
    return out


def enrich_favorite_horse_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-favorite ability / position ranks from horse_races export (pre-race)."""
    if not os.path.isfile(HORSE_EXPORT):
        return df
    keys = set(df['race_key'].astype(str))
    use = ['race_key', 'ninki', 'umaban', 'ability_score', 'vh2_score', 'h7_fig',
           'elim_n', 'avg_pos3', 'pos_ratio3']
    chunks = []
    for chunk in pd.read_csv(HORSE_EXPORT, encoding='utf-8', usecols=use, chunksize=200_000):
        chunk['race_key'] = chunk['race_key'].astype(str)
        chunk = chunk[chunk['race_key'].isin(keys)]
        if len(chunk):
            chunks.append(chunk)
    if not chunks:
        return df
    h = pd.concat(chunks, ignore_index=True)
    h = h[h['ninki'].isin([1, 2, 3])].copy()
    higher_better = {'ability_score', 'vh2_score', 'h7_fig'}
    for col in list(higher_better) + ['elim_n']:
        if col not in h.columns:
            continue
        asc = col == 'elim_n'
        h[f'{col}_rank'] = h.groupby('race_key')[col].rank(ascending=asc, method='min')
    for col in ('avg_pos3', 'pos_ratio3'):
        if col in h.columns:
            h[f'{col}_rank_fwd'] = h.groupby('race_key')[col].rank(ascending=True, method='min')

    wide = {}
    for nk in (1, 2, 3):
        sub = h[h['ninki'] == nk].drop_duplicates('race_key', keep='first').set_index('race_key')
        for src, dst in (
            ('ability_score_rank', f'fav{nk}_ability_rank'),
            ('vh2_score_rank', f'fav{nk}_vh2_rank'),
            ('h7_fig_rank', f'fav{nk}_h7_rank'),
            ('elim_n', f'fav{nk}_elim_n'),
            ('avg_pos3', f'fav{nk}_avg_pos3'),
            ('pos_ratio3', f'fav{nk}_pos_ratio3'),
            ('avg_pos3_rank_fwd', f'fav{nk}_pos_rank_fwd'),
        ):
            if src in sub.columns:
                wide[dst] = sub[src]

    out = df.copy()
    out['race_key'] = out['race_key'].astype(str)
    for col, ser in wide.items():
        out[col] = out['race_key'].map(ser)

    ab = h.pivot_table(index='race_key', columns='ninki', values='ability_score_rank', aggfunc='first')
    ab.columns = [int(c) for c in ab.columns]
    for c in (1, 2, 3):
        if c not in ab.columns:
            ab[c] = np.nan
    ab = ab.reindex(out['race_key'].values)
    ab.index = out.index
    ab1 = pd.to_numeric(ab[1], errors='coerce')
    ab2 = pd.to_numeric(ab[2], errors='coerce')
    ab3 = pd.to_numeric(ab[3], errors='coerce')
    out['fav_top2_in_ability_top3'] = (ab1 <= 3).astype(float) + (ab2 <= 3).astype(float)
    out['fav_top3_in_ability_top5'] = (ab1 <= 5).astype(float) + (ab2 <= 5).astype(float) + (ab3 <= 5).astype(float)
    out['fav1_is_ability_top1'] = (ab1 == 1).astype(float)
    out['fav1_is_ability_top3'] = (ab1 <= 3).astype(float)

    pos3 = h.pivot_table(index='race_key', columns='ninki', values='avg_pos3', aggfunc='first')
    for c in (1, 2, 3):
        if c not in pos3.columns:
            pos3[c] = np.nan
    pos3.columns = [int(c) for c in pos3.columns]
    for c in (1, 2, 3):
        if c not in pos3.columns:
            pos3[c] = np.nan
    pos3 = pos3.reindex(out['race_key'].values)
    pos3.index = out.index
    out['fav_top3_n_front'] = sum((pd.to_numeric(pos3[k], errors='coerce') <= 3).astype(float) for k in (1, 2, 3))

    field_pos = pd.read_csv(HORSE_EXPORT, encoding='utf-8', usecols=['race_key', 'ninki', 'avg_pos3'],
                            chunksize=300_000)
    ahead = {}
    for chunk in field_pos:
        chunk['race_key'] = chunk['race_key'].astype(str)
        chunk = chunk[chunk['race_key'].isin(keys)]
        chunk['avg_pos3'] = pd.to_numeric(chunk['avg_pos3'], errors='coerce')
        for rk, g in chunk.groupby('race_key'):
            fav1_pos = g.loc[g['ninki'] == 1, 'avg_pos3']
            if fav1_pos.empty or pd.isna(fav1_pos.iloc[0]):
                continue
            fp = float(fav1_pos.iloc[0])
            ahead[str(rk)] = int((g['avg_pos3'] < fp).sum())
    out['n_ahead_fav1_avg_pos3'] = out['race_key'].map(ahead)

    inv = 1.0 / out['fav1'].replace(0, np.nan)
    inv2 = 1.0 / out['fav2'].replace(0, np.nan)
    inv3 = 1.0 / out['fav3'].replace(0, np.nan)
    s = inv + inv2 + inv3
    out['top3_implied_share'] = s
    out['top3_implied_hhi'] = (inv ** 2 + inv2 ** 2 + inv3 ** 2) / (s ** 2)
    return out


def _cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float('nan')
    va, vb = a.var(ddof=1), b.var(ddof=1)
    pooled = np.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    if pooled <= 0:
        return 0.0
    return float((a.mean() - b.mean()) / pooled)


def bootstrap_ci_diff(a: np.ndarray, b: np.ndarray, n_boot: int = 400, seed: int = 42) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return (float('nan'), float('nan'))
    diffs = []
    for _ in range(n_boot):
        sa = a[rng.integers(0, len(a), len(a))]
        sb = b[rng.integers(0, len(b), len(b))]
        diffs.append(sa.mean() - sb.mean())
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def compare_groups(df: pd.DataFrame, mask: pd.Series, y_col: str,
                   feature_cols: list[str]) -> list[dict]:
    sub = df.loc[mask].copy()
    pos = sub[y_col] == 1
    rows = []
    for col in feature_cols:
        if col not in sub.columns:
            continue
        a = pd.to_numeric(sub.loc[pos, col], errors='coerce').values
        b = pd.to_numeric(sub.loc[~pos, col], errors='coerce').values
        lo, hi = bootstrap_ci_diff(a, b)
        rows.append({
            'feature': col,
            'n_a': int(np.sum(~np.isnan(a))),
            'n_b': int(np.sum(~np.isnan(b))),
            'mean_a': float(np.nanmean(a)),
            'mean_b': float(np.nanmean(b)),
            'median_a': float(np.nanmedian(a)),
            'median_b': float(np.nanmedian(b)),
            'std_a': float(np.nanstd(a)),
            'std_b': float(np.nanstd(b)),
            'cohen_d': _cohen_d(a, b),
            'diff_ci_lo': lo,
            'diff_ci_hi': hi,
        })
    rows.sort(key=lambda r: abs(r['cohen_d']) if pd.notna(r['cohen_d']) else 0, reverse=True)
    return rows


def univariate_metrics(df: pd.DataFrame, mask: pd.Series, y_col: str,
                       feature_cols: list[str]) -> list[dict]:
    from sklearn.metrics import roc_auc_score, average_precision_score

    sub = df.loc[mask].dropna(subset=[y_col])
    y = sub[y_col].astype(int).values
    rows = []
    for col in feature_cols:
        if col not in sub.columns:
            continue
        x = pd.to_numeric(sub[col], errors='coerce').values
        ok = ~np.isnan(x)
        if ok.sum() < 100 or y[ok].sum() in (0, ok.sum()):
            continue
        try:
            auc = float(roc_auc_score(y[ok], x[ok]))
            pr = float(average_precision_score(y[ok], x[ok]))
        except ValueError:
            continue
        rows.append({'feature': col, 'auc': auc, 'pr_auc': pr, 'n': int(ok.sum())})
    rows.sort(key=lambda r: max(r['auc'], 1 - r['auc']), reverse=True)
    return rows


def eff_n_matched_compare(df: pd.DataFrame, mask: pd.Series, y_col: str,
                          feature_cols: list[str], n_bins: int = 10) -> list[dict]:
    extra = [c for c in feature_cols if c in df.columns and c not in ('eff_n', y_col)]
    sub = df.loc[mask, ['eff_n', y_col] + extra].copy()
    sub = sub.dropna(subset=['eff_n'])
    sub['eff_bin'] = pd.qcut(sub['eff_n'], q=n_bins, duplicates='drop')
    rows = []
    for col in feature_cols:
        if col not in sub.columns or col == 'eff_n':
            continue
        ds = []
        for _, g in sub.groupby('eff_bin', observed=True):
            a = pd.to_numeric(g.loc[g[y_col] == 1, col], errors='coerce')
            b = pd.to_numeric(g.loc[g[y_col] == 0, col], errors='coerce')
            if len(a) >= 5 and len(b) >= 5:
                ds.append(_cohen_d(a.values, b.values))
        ds = [d for d in ds if pd.notna(d)]
        if not ds:
            continue
        rows.append({
            'feature': col,
            'mean_cohen_d_within_eff_bins': float(np.mean(ds)),
            'n_bins_used': len(ds),
        })
    rows.sort(key=lambda r: abs(r['mean_cohen_d_within_eff_bins']), reverse=True)
    return rows


def build_feature_sets(all_cols: list[str]) -> dict[str, list[str]]:
    market = [c for c in all_cols if c in {
        'fav1', 'fav2', 'fav3', 'r21', 'r31', 'spread31', 'odds_entropy', 'eff_n', 'syn3',
        'live10', 'live30', 'mid515', 'n_odds', 'top3_implied_share', 'top3_implied_hhi',
    }]
    chaos = ['arare_prob', 'odds_entropy', 'eff_n']
    align = [c for c in all_cols if 'ability' in c or 'vh2' in c or 'h7' in c or c == 'mkt_ability_corr'
             or c.startswith('fav') and ('rank' in c or 'is_' in c or 'in_ability' in c)]
    position = [c for c in all_cols if c in {'n_front', 'n_hana', 'mean_posr', 'fav_top3_n_front'}
                or 'avg_pos3' in c or 'pos_ratio' in c or 'pos_rank' in c]
    env = [c for c in all_cols if c in {'mean_elim', 'n_elim3', 'n_lowelim_pop7', 'combo_cov', 'n_pop7',
                                        'n_ahead_fav1_avg_pos3', 'n_combo2', 'n_combo3'}]
    return {'market': market, 'chaos': chaos, 'ability_align': align,
            'position': position, 'environment': env}


def _prep_xy(df: pd.DataFrame, features: list[str], y_col: str):
    feats = [f for f in features if f in df.columns and f not in POST_RACE_BLOCK]
    x = df[feats].apply(pd.to_numeric, errors='coerce')
    y = df[y_col].astype(float)
    return x, y, feats


def fit_logistic_pipeline(train_df: pd.DataFrame, test_df: pd.DataFrame,
                          features: list[str], y_col: str) -> dict:
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    x_tr, y_tr, feats = _prep_xy(train_df, features, y_col)
    x_te, y_te, _ = _prep_xy(test_df, features, y_col)
    ok_tr = y_tr.notna() & (x_tr.notna().any(axis=1))
    ok_te = y_te.notna() & (x_te.notna().any(axis=1))
    if ok_tr.sum() < 80 or ok_te.sum() < 30:
        return {'model': feats, 'note': '件数不足', 'n_train': int(ok_tr.sum()), 'n_test': int(ok_te.sum())}
    pipe = Pipeline([
        ('imp', SimpleImputer(strategy='median')),
        ('sc', StandardScaler()),
        ('lr', LogisticRegression(max_iter=800, C=1.0, class_weight='balanced')),
    ])
    pipe.fit(x_tr.loc[ok_tr], y_tr.loc[ok_tr].astype(int))
    p = pipe.predict_proba(x_te.loc[ok_te])[:, 1]
    yt = y_te.loc[ok_te].astype(int).values
    if yt.sum() in (0, len(yt)):
        return {'model': feats, 'note': '単一クラス'}
    return {
        'features': feats,
        'n_train': int(ok_tr.sum()),
        'n_test': int(ok_te.sum()),
        'auc': float(roc_auc_score(yt, p)),
        'pr_auc': float(average_precision_score(yt, p)),
        'brier': float(brier_score_loss(yt, p)),
        'pipe': pipe,
        'proba_test': p,
        'y_test': yt,
        'test_index': test_df.loc[ok_te].index,
    }


def baseline_scores(df: pd.DataFrame) -> dict[str, pd.Series]:
    s = {}
    s['baseline_arare_only'] = 1.0 - pd.to_numeric(df['arare_prob'], errors='coerce')
    s['baseline_eff_n_only'] = -pd.to_numeric(df['eff_n'], errors='coerce')
    s['baseline_entropy_only'] = -pd.to_numeric(df['odds_entropy'], errors='coerce')
    return s


def eval_scores(y: np.ndarray, score: np.ndarray) -> dict:
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
    ok = ~np.isnan(score) & ~np.isnan(y)
    if ok.sum() < 30 or y[ok].sum() in (0, ok.sum()):
        return {'note': '件数不足'}
    sc = score[ok]
    yt = y[ok]
    auc = roc_auc_score(yt, sc)
    if auc < 0.5:
        sc = -sc
        auc = roc_auc_score(yt, sc)
    p = (sc - sc.min()) / (sc.max() - sc.min() + 1e-9)
    return {
        'auc': float(auc),
        'pr_auc': float(average_precision_score(yt, p)),
        'brier': float(brier_score_loss(yt, p)),
        'n': int(ok.sum()),
    }


def filter_evaluation(df: pd.DataFrame, cohort: pd.Series, upset_mask: pd.Series,
                      survival_prob: pd.Series, y_col: str,
                      type_cols: dict[str, str], threshold: float) -> dict:
    cand = cohort & upset_mask
    idx = df.index[cand]
    sp = survival_prob.reindex(idx)
    excl = sp >= threshold
    kept = ~excl
    out = {'threshold': threshold, 'n_candidates': int(cand.sum())}
    ya = df.loc[idx, y_col].astype(int)
    out['excluded_n'] = int(excl.sum())
    out['excluded_type_a_n'] = int((ya[excl] == 1).sum())
    out['excluded_type_a_rate'] = float((ya[excl] == 1).mean()) if excl.any() else 0.0
    out['excluded_type_a_pct_of_all_type_a_in_cohort'] = None
    for tag, col in type_cols.items():
        if col not in df.columns:
            continue
        t = df.loc[idx, col].astype(int)
        n_pos = int(t.sum())
        out[f'{tag}_n_in_candidates'] = n_pos
        out[f'{tag}_n_kept_after_filter'] = int(t[kept].sum())
        out[f'{tag}_recall_after'] = float(t[kept].sum() / n_pos) if n_pos else 0.0
        n_pos_all = int(df.loc[cohort, col].sum())
        out[f'{tag}_recall_before_vs_cohort'] = float(n_pos / n_pos_all) if n_pos_all else 0.0
    return out


def try_tm_green_count() -> dict:
    db = os.path.join(ROOT, 'data', 'prediction_tm.db')
    if not os.path.isfile(db):
        return {'tm_green_races': 0, 'note': 'prediction_tm.db なし'}
    try:
        import sqlite3
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        n = con.execute(
            "SELECT COUNT(DISTINCT race_id) FROM snapshots WHERE json_extract(body,'$.data_quality.status')='GREEN'"
        ).fetchone()[0]
        con.close()
        if n < 50:
            return {'tm_green_races': int(n), 'note': 'サンプル不足（50未満）— TM特徴は未使用'}
        return {'tm_green_races': int(n), 'note': 'TM拡張は別途 race_id JOIN が必要'}
    except Exception as e:
        return {'tm_green_races': 0, 'note': str(e)}


def select_screening_features(df: pd.DataFrame) -> list[str]:
    skip = POST_RACE_BLOCK | {TARGET_PRIMARY, 'race_key', 'dataset_version', 'day', 'year', 'month',
                              'jyo', 'kyori', 'race_num', 'race_name', 'grade', 'kigo', 'shubetsu',
                              'lean_label', 'vlabel', 'open_cls'}
    cols = []
    for c in df.columns:
        if c in skip or c.startswith('type_') or c.startswith('y_'):
            continue
        if df[c].dtype == object:
            continue
        cols.append(c)
    return cols


def run_full(csv_path: str | None = None, top_eff_frac: float = 0.2) -> dict:
    csv_path = csv_path or os.path.join(OUT_DIR, 'high_entropy_race_dataset_structured.csv')
    if not os.path.isfile(csv_path):
        csv_path = os.path.join(OUT_DIR, 'high_entropy_race_dataset.csv')
    df = pd.read_csv(csv_path, encoding='utf-8')
    df['race_key'] = df['race_key'].astype(str)
    if TARGET_PRIMARY not in df.columns:
        from research.high_entropy_upset import upset_structure as us
        df = us._enrich_from_finish_cols(df)
        df = us.add_payout_ranks(df)
        df, _ = us.propose_type_labels(df)

    df = add_auxiliary_targets(df)
    df = enrich_favorite_horse_features(df)

    train_m, val_m, hold_m = period_mask(df)
    eff_thr = eff_n_threshold_train_only(df, top_eff_frac)
    cohort = df['eff_n'] >= eff_thr
    hi = df.loc[cohort].copy()
    y_col = TARGET_PRIMARY

    screen_feats = select_screening_features(df)
    expl = ExplorationLog(n_features_screened=len(screen_feats), feature_names=screen_feats)

    desc_hi = compare_groups(df, cohort, y_col, screen_feats)
    uni_all = univariate_metrics(df, cohort, y_col, screen_feats)
    matched = eff_n_matched_compare(df, cohort, y_col, screen_feats)

    # Holdout-only univariate for reporting stability
    uni_hold = univariate_metrics(df, cohort & hold_m, y_col, screen_feats)

    groups = build_feature_sets(screen_feats)
    train_df = df.loc[cohort & train_m]
    val_df = df.loc[cohort & val_m]
    hold_df = df.loc[cohort & hold_m]

    model_specs = [
        ('m1_arare_only', ['arare_prob']),
        ('m2_chaos_only', ['odds_entropy', 'eff_n']),
        ('m3_market_structure', groups['market']),
        ('m4_plus_ability', groups['market'] + groups['ability_align']),
        ('m5_plus_position', groups['market'] + groups['ability_align'] + groups['position']),
        ('m6_full_env', groups['market'] + groups['ability_align'] + groups['position'] + groups['environment']),
    ]
    model_results = {}
    best_pipe = None
    best_name = None
    best_auc = 0.0
    fitted = {}
    for name, feats in model_specs:
        feats = list(dict.fromkeys(feats))
        expl.n_models_fitted += 1
        expl.model_names.append(name)
        if name == 'm1_arare_only':
            sc = 1.0 - pd.to_numeric(hold_df['arare_prob'], errors='coerce')
            yt = hold_df[y_col].astype(int).values
            model_results[name] = eval_scores(yt, sc.values)
            model_results[name]['features'] = feats
            auc = model_results[name].get('auc') or 0
            if auc > best_auc:
                best_auc = auc
                best_name = name
            continue
        res = fit_logistic_pipeline(train_df, hold_df, feats, y_col)
        fitted[name] = res
        model_results[name] = {k: v for k, v in res.items() if k not in ('pipe', 'proba_test', 'y_test', 'test_index')}
        auc = res.get('auc') or 0
        if res.get('pipe') and auc >= best_auc:
            best_auc = auc
            best_pipe = res['pipe']
            best_name = name

    # Validation-tuned filter threshold
    upset_thr = float(train_df['arare_prob'].quantile(0.80))
    upset_cand = cohort & (df['arare_prob'] >= upset_thr)
    filter_res = {}
    filter_model = 'm6_full_env' if 'm6_full_env' in fitted and fitted['m6_full_env'].get('pipe') else best_name
    filter_pipe = fitted.get(filter_model, {}).get('pipe') or best_pipe
    if filter_pipe is not None and filter_model in fitted:
        feat_use = fitted[filter_model]['features']
        best_pipe = filter_pipe
        x_val, y_val, _ = _prep_xy(val_df, feat_use, y_col)
        ok = y_val.notna() & x_val.notna().any(axis=1)
        p_val = best_pipe.predict_proba(x_val.loc[ok])[:, 1]
        thresholds = np.linspace(0.35, 0.75, 9)
        expl.n_filter_thresholds_tried = len(thresholds)
        best_t, best_score = 0.55, -1.0
        type_cols = {'type_C': 'type_C_hole2', 'type_D': 'type_D_fav_collapse', 'type_F': 'type_F_payout_boom'}
        val_idx = val_df.loc[ok].index
        for t in thresholds:
            excl = p_val >= t
            if excl.sum() < max(20, int(0.05 * len(p_val))):
                continue
            ya = y_val.loc[ok].astype(int)
            fa_rate = float(ya[excl].mean())
            t_c_all = val_df.loc[val_idx, 'type_C_hole2'].astype(int).values
            c_rec = float(t_c_all[~excl].sum() / t_c_all.sum()) if t_c_all.sum() else 1.0
            filter_res[str(t)] = {
                'excluded_n': int(excl.sum()),
                'excluded_type_a_rate': fa_rate,
                'type_C_recall_after': float(c_rec),
            }
            if c_rec < 0.85:
                continue
            score = fa_rate * np.sqrt(excl.sum())
            if score > best_score:
                best_score = score
                best_t = t
        x_hold, y_hold, _ = _prep_xy(hold_df, feat_use, y_col)
        okh = y_hold.notna() & x_hold.notna().any(axis=1)
        p_hold = pd.Series(best_pipe.predict_proba(x_hold.loc[okh])[:, 1], index=hold_df.loc[okh].index)
        survival = pd.Series(np.nan, index=df.index)
        survival.loc[p_hold.index] = p_hold
        filter_res['holdout'] = filter_evaluation(
            df, cohort, upset_cand, survival, y_col, type_cols, best_t)
        filter_res['val_threshold'] = best_t
    else:
        filter_res['note'] = 'モデル未成立'

    # Stratified slices (min n=80)
    slices = {}
    for label, col in [('surface_turf', df['surface_code'] == 0), ('surface_dirt', df['surface_code'] == 1),
                       ('field_le12', df['field_size'] <= 12), ('field_gt12', df['field_size'] > 12)]:
        m = cohort & col
        if m.sum() < 80:
            continue
        slices[label] = {'n': int(m.sum()), 'type_a_rate': float(df.loc[m, y_col].mean())}

    tm_info = try_tm_green_count()

    # Stage structure check
    hi_hold = df.loc[cohort & hold_m]
    auc_c = eval_scores(hi_hold['type_C_hole2'].astype(int).values,
                        pd.to_numeric(hi_hold['arare_prob'], errors='coerce').values)
    stage3 = eval_scores(hi_hold['type_C_hole2'].astype(int).values,
                         (1 - pd.to_numeric(hi_hold['arare_prob'], errors='coerce')).values)

    report = {
        'cohort': {
            'eff_n_threshold_train_only': eff_thr,
            'top_frac': top_eff_frac,
            'n_high_eff_n': int(cohort.sum()),
            'n_type_a_in_cohort': int(df.loc[cohort, y_col].sum()),
            'type_a_rate': float(df.loc[cohort, y_col].mean()),
            'mean_arare_prob_type_a': float(df.loc[cohort & (df[y_col] == 1), 'arare_prob'].mean()),
        },
        'auxiliary_targets_in_cohort': {
            t: float(df.loc[cohort, t].mean()) for t in
            ['y_fav1_top3', 'y_either_fav12_top3', 'y_both_fav12_top3', 'y_top3_ninki_ge2_in_top3', 'y_honsen']
        },
        'descriptive_type_a_vs_not': desc_hi[:40],
        'top10_effect_size_all': desc_hi[:10],
        'top10_univariate_auc_cohort': uni_all[:10],
        'eff_n_matched_top10': matched[:10],
        'feature_groups_compared': {k: len(v) for k, v in groups.items()},
        'models_holdout': model_results,
        'filter_analysis': filter_res,
        'condition_slices': slices,
        'exploration_log': {
            'n_features_screened': expl.n_features_screened,
            'n_models_fitted': expl.n_models_fitted,
            'n_filter_thresholds_tried': expl.n_filter_thresholds_tried,
            'models': expl.model_names,
        },
        'tm_green': tm_info,
        'leak_guard': 'POST_RACE_BLOCK applied; eff_n threshold from train≤2022 only',
        'stage_auc_high_eff_holdout': {
            'arare_vs_type_C': auc_c,
            'inverted_arare_vs_type_C': stage3,
        },
    }

    # Three-stage verdict
    m1 = model_results.get('m1_arare_only', {}).get('auc', 0) or 0
    m3 = model_results.get('m3_market_structure', {}).get('auc', 0) or 0
    m6 = model_results.get('m6_full_env', {}).get('auc', 0) or 0
    delta_vs_arare = m6 - m1 if m6 and m1 else 0
    delta_vs_market = m6 - m3 if m6 and m3 else 0
    hold_delta_ok = delta_vs_market >= 0.015
    matched_ok = len(matched) and abs(matched[0].get('mean_cohen_d_within_eff_bins', 0)) >= 0.08
    h_f = filter_res.get('holdout', {})
    filter_ok = (h_f.get('excluded_n', 0) >= 50
                 and h_f.get('excluded_type_a_rate', 0) >= 0.22)
    c_recall_ok = h_f.get('type_C_recall_after', 0) >= 0.85
    stage2_ok = hold_delta_ok and matched_ok
    if stage2_ok and filter_ok and c_recall_ok:
        verdict = '部分的に支持'
    elif delta_vs_market < 0.005 and not filter_ok:
        verdict = '支持しない'
    else:
        verdict = '部分的に支持（Stage2増分は小さい）'
    report['three_stage_verdict'] = {
        'label': verdict,
        'delta_auc_m6_vs_arare_holdout': delta_vs_arare,
        'delta_auc_m6_vs_market_holdout': delta_vs_market,
        'matched_top_feature_d': matched[0] if matched else None,
        'criteria': {'hold_delta_vs_market_ok': hold_delta_ok, 'matched_ok': matched_ok,
                     'filter_ok': filter_ok, 'c_recall_ok': c_recall_ok},
        'interpretation': (
            'Stage1=eff_n/arare(混戦), Stage2=type_A(人気残存), Stage3=type_C(穴2頭+)'
        ),
    }
    report['production_candidate'] = (
        'なし（Favorite Survivalによる実用増分なし）'
        if delta_vs_market < 0.01 or not filter_ok else '要再検証（研究のみ）'
    )
    report['incremental_note'] = (
        'Favorite Survivalによる増分なし'
        if delta_vs_market < 0.005 else None
    )

    rpath = os.path.join(OUT_DIR, 'favorite_survival_report.json')
    with open(rpath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    cand_path = os.path.join(OUT_DIR, 'favorite_survival_candidates.csv')
    out_cols = ['race_key', 'day', 'eff_n', 'arare_prob', y_col, 'type_C_hole2', 'type_D_fav_collapse',
                'type_F_payout_boom', 'fav1', 'r21', 'mkt_ability_corr', 'fav1_is_ability_top3',
                'fav_top3_n_front', 'n_ahead_fav1_avg_pos3']
    out_cols = [c for c in out_cols if c in df.columns]
    df.loc[cohort, out_cols].to_csv(cand_path, index=False, encoding='utf-8')

    report['paths'] = {'report_json': rpath, 'candidates_csv': cand_path}
    return report
