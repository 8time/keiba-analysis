# -*- coding: utf-8 -*-
"""Decompose post-race upset structure (research only)."""
from __future__ import annotations

import json
import os
from collections import Counter

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, 'data', 'research')
HOLDOUT_DAY = 20240101
TRAIN_END_DAY = 20231231


def _enrich_from_finish_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill structure columns when CSV predates dataset.py extension."""
    out = df.copy()
    need = {'top2_in_top3', 'finish_pattern', 'n_in_top3_ge7'}
    if need.issubset(out.columns):
        return out
    cols = ['finish_1_ninki', 'finish_2_ninki', 'finish_3_ninki']
    if not all(c in out.columns for c in cols):
        raise ValueError('finish ninki columns missing')
    vals = out[cols].astype(float)
    out['top2_in_top3'] = (vals <= 2).sum(axis=1)
    out['top3_in_top3'] = (vals <= 3).sum(axis=1)
    out['n_in_top3_ge6'] = (vals >= 6).sum(axis=1)
    out['n_in_top3_ge7'] = (vals >= 7).sum(axis=1)
    out['n_in_top3_ge10'] = (vals >= 10).sum(axis=1)
    out['finish_pattern'] = vals.apply(
        lambda r: '-'.join(str(int(x)) for x in r if pd.notna(x)), axis=1)
    return out


def add_payout_ranks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ('trio_payout', 'trifecta_payout'):
        if col not in out.columns:
            continue
        out[f'{col}_pct_global'] = out[col].rank(pct=True, method='average')
        out[f'{col}_pct_train'] = np.nan
        tr = out['day'] <= TRAIN_END_DAY
        out.loc[tr, f'{col}_pct_train'] = out.loc[tr, col].rank(pct=True, method='average')
        out.loc[~tr, f'{col}_pct_train'] = out.loc[~tr, col].apply(
            lambda v: (out.loc[tr, col] < v).mean() if pd.notna(v) else np.nan)
    out['stratum'] = (
        out['surface_code'].astype('Int64').astype(str) + '_'
        + pd.cut(out['field_size'], [0, 12, 15, 99], labels=['S', 'M', 'L']).astype(str)
    )
    for col in ('trio_payout', 'trifecta_payout'):
        if col not in out.columns:
            continue
        pct_col = f'{col}_pct_stratum'
        out[pct_col] = out.groupby('stratum')[col].rank(pct=True, method='average')
    return out


def propose_type_labels(df: pd.DataFrame, *, trio_hi: float | None = None,
                        tri_hi: float | None = None) -> tuple[pd.DataFrame, dict]:
    """Multi-label upset types from empirical thresholds (train-only for payout hi)."""
    out = df.copy()
    tr = out[out['day'] <= TRAIN_END_DAY]
    if trio_hi is None:
        trio_hi = float(tr['trio_payout'].quantile(0.90)) if tr['trio_payout'].notna().any() else np.nan
    if tri_hi is None:
        tri_hi = float(tr['trifecta_payout'].quantile(0.90)) if tr['trifecta_payout'].notna().any() else np.nan
    meta = {'trio_p90_train': trio_hi, 'trifecta_p90_train': tri_hi}

    solid = (out['honsen'] == 1) | (
        (out['top3_in_top3'] >= 3) & (out['n_in_top3_ge7'] == 0)
        & (out['favorite_failure'] == 0))
    hole1 = (out['n_in_top3_ge7'] == 1) & (out['favorite_failure'] == 0)
    hole2 = (out['n_in_top3_ge7'] >= 2)
    fav_collapse = (out['top2_failure'] == 1)
    full_collapse = (out['top3_in_top3'] <= 1) | (
        (out['favorite_failure'] == 1) & (out['top2_in_top3'] == 0))
    trio_st = out['trio_payout_pct_stratum'].fillna(0) if 'trio_payout_pct_stratum' in out.columns else 0
    tri_st = out['trifecta_payout_pct_stratum'].fillna(0) if 'trifecta_payout_pct_stratum' in out.columns else 0
    pay_boom = (
        (out['trio_payout'] >= trio_hi) | (out['trifecta_payout'] >= tri_hi)
        | (trio_st >= 0.95) | (tri_st >= 0.95))

    out['type_A_solid'] = solid.astype(int)
    out['type_B_hole1'] = hole1.astype(int)
    out['type_C_hole2'] = hole2.astype(int)
    out['type_D_fav_collapse'] = fav_collapse.astype(int)
    out['type_E_full_collapse'] = full_collapse.astype(int)
    out['type_F_payout_boom'] = pay_boom.astype(int)
    meta['counts'] = {c: int(out[c].sum()) for c in out.columns if c.startswith('type_')}
    meta['overlap'] = int((out[[c for c in out.columns if c.startswith('type_')]].sum(axis=1) > 1).sum())
    return out, meta


def distribution_report(df: pd.DataFrame) -> dict:
    d = df.dropna(subset=['finish_1_ninki'])
    pat = Counter(d['finish_pattern'].astype(str))
    top_pat = pat.most_common(25)
    rep = {
        'n_races': len(d),
        'top_finish_patterns': [{'pattern': p, 'n': n, 'rate': n / len(d)} for p, n in top_pat],
        'top2_in_top3': d['top2_in_top3'].value_counts(normalize=True).sort_index().to_dict(),
        'top3_in_top3': d['top3_in_top3'].value_counts(normalize=True).sort_index().to_dict(),
        'n_in_top3_ge7': d['n_in_top3_ge7'].value_counts(normalize=True).sort_index().to_dict(),
        'trio_payout_quantiles': d['trio_payout'].quantile([0.5, 0.75, 0.9, 0.95, 0.99]).to_dict(),
        'trifecta_payout_quantiles': d['trifecta_payout'].quantile([0.5, 0.75, 0.9, 0.95, 0.99]).to_dict(),
    }
    return rep


def eval_arare_by_label(df: pd.DataFrame, label_col: str, holdout_only: bool = True) -> dict:
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

    sub = df.dropna(subset=['arare_prob', label_col]).copy()
    if holdout_only:
        sub = sub[sub['day'] >= HOLDOUT_DAY]
    if len(sub) < 50:
        return {'label': label_col, 'n': len(sub), 'note': '件数不足'}
    y = sub[label_col].astype(int).values
    p = sub['arare_prob'].astype(float).values
    if y.sum() == 0 or y.sum() == len(y):
        return {'label': label_col, 'n': len(sub), 'note': '単一クラス'}
    out = {
        'label': label_col,
        'n': len(sub),
        'positive_rate': float(y.mean()),
        'auc': float(roc_auc_score(y, p)),
        'pr_auc': float(average_precision_score(y, p)),
        'brier': float(brier_score_loss(y, p)),
    }
    for pct in (0.1, 0.2):
        k = max(1, int(len(sub) * pct))
        top = sub.nlargest(k, 'arare_prob')
        out[f'precision_top_{int(pct*100)}pct'] = float(top[label_col].mean())
    return out


def high_effn_slice(df: pd.DataFrame, top_frac: float = 0.2) -> pd.DataFrame:
    thr = df['eff_n'].quantile(1 - top_frac)
    return df[df['eff_n'] >= thr].copy()


def cluster_explore(df: pd.DataFrame, k: int = 6) -> dict:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    cols = ['top2_in_top3', 'top3_in_top3', 'n_in_top3_ge7', 'n_in_top3_ge10']
    pay = df[['trio_payout', 'trifecta_payout']].apply(np.log1p)
    x = pd.concat([df[cols], pay], axis=1).dropna()
    if len(x) < k * 20:
        return {'note': '件数不足'}
    z = StandardScaler().fit_transform(x)
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    lab = km.fit_predict(z)
    x = x.copy()
    x['cluster'] = lab
    profiles = []
    for c in range(k):
        g = x[x['cluster'] == c]
        profiles.append({
            'cluster': c,
            'n': len(g),
            'mean_top2': float(g['top2_in_top3'].mean()),
            'mean_top3': float(g['top3_in_top3'].mean()),
            'mean_n7': float(g['n_in_top3_ge7'].mean()),
            'mean_log_trio': float(g['trio_payout'].mean()),
            'mean_log_tri': float(g['trifecta_payout'].mean()),
        })
    return {'k': k, 'profiles': profiles}


def write_upset_map_html(df: pd.DataFrame, path: str, sample: int = 4000) -> str:
    d = df.dropna(subset=['top2_in_top3', 'n_in_top3_ge7', 'eff_n']).copy()
    if len(d) > sample:
        d = d.sample(sample, random_state=42)
    d['x'] = d['top2_in_top3'] + np.random.default_rng(42).uniform(-0.08, 0.08, len(d))
    d['y'] = d['n_in_top3_ge7'] + np.random.default_rng(43).uniform(-0.08, 0.08, len(d))
    d['r'] = 4 + d.get('trifecta_payout_pct_global', 0.5).fillna(0.5) * 10
    points = d[['x', 'y', 'r', 'eff_n', 'finish_pattern', 'trio_payout', 'trifecta_payout',
                  'type_A_solid', 'type_F_payout_boom']].to_dict(orient='records')
    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>荒れ方マップ（研究）</title>
<style>body{{font-family:sans-serif;margin:16px}}#c{{border:1px solid #ccc;background:#fafafa}}
.tip{{font-size:12px;color:#555;margin-top:8px}}</style></head><body>
<h1>荒れ方マップ（研究用・{len(d):,}点サンプル）</h1>
<p>横軸=人気馬残存（TOP2が3着内に何頭）、縦軸=7番人気以下の3着内頭数、
点サイズ=3連単配当の全体分位、色=eff_n（青→低、赤→高）</p>
<canvas id="c" width="960" height="640"></canvas>
<p class="tip">本番予測には未接続。Prediction Time Machine / 新モデル導入前の探索用。</p>
<script>
const pts = {json.dumps(points, ensure_ascii=False)};
const c = document.getElementById('c'); const ctx = c.getContext('2d');
const effs = pts.map(p=>p.eff_n); const emin=Math.min(...effs), emax=Math.max(...effs);
function col(e){{ const t=(e-emin)/(emax-emin+1e-9); return `hsl(${{240-240*t}},70%,45%)`; }}
pts.forEach(p=>{{
  ctx.beginPath(); ctx.fillStyle=col(p.eff_n); ctx.arc(40+p.x*140, 600-p.y*120, p.r, 0, 6.28); ctx.fill();
}});
ctx.strokeStyle='#333'; ctx.strokeRect(40,40,560,560);
ctx.fillStyle='#333'; ctx.fillText('TOP2残存', 280, 630); ctx.save(); ctx.translate(15,320); ctx.rotate(-Math.PI/2);
ctx.fillText('穴(7+)侵入数', 0,0); ctx.restore();
</script></body></html>"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


def run_full(csv_path: str | None = None) -> dict:
    csv_path = csv_path or os.path.join(OUT_DIR, 'high_entropy_race_dataset.csv')
    df = pd.read_csv(csv_path, encoding='utf-8')
    df = _enrich_from_finish_cols(df)
    df = add_payout_ranks(df)
    df, type_meta = propose_type_labels(df)
    dist = distribution_report(df)
    labels = [c for c in df.columns if c.startswith('type_')]
    metrics = [eval_arare_by_label(df, c) for c in labels]
    metrics.append(eval_arare_by_label(df, 'longshot_place_7'))
    hi = high_effn_slice(df, 0.2)
    hi_rates = {c: float(hi[c].mean()) for c in labels}
    hi_solid = hi[hi['type_A_solid'] == 1]
    solid_profile = {
        'n': len(hi_solid),
        'mean_fav1': float(hi_solid['fav1'].mean()) if len(hi_solid) else None,
        'mean_gap21': float((hi_solid['fav2'] - hi_solid['fav1']).mean()) if len(hi_solid) else None,
        'mean_arare_prob': float(hi_solid['arare_prob'].mean()) if len(hi_solid) else None,
    }
    clusters = cluster_explore(df)
    type_summaries = {}
    for c in labels:
        g = df[df[c] == 1]
        pat = Counter(g['finish_pattern'].astype(str)).most_common(5)
        type_summaries[c] = {
            'n': len(g),
            'rate': len(g) / len(df),
            'trio_median': float(g['trio_payout'].median()) if len(g) else None,
            'trifecta_median': float(g['trifecta_payout'].median()) if len(g) else None,
            'mean_eff_n': float(g['eff_n'].mean()) if len(g) else None,
            'mean_entropy': float(g['odds_entropy'].mean()) if 'odds_entropy' in g.columns and len(g) else None,
            'mean_arare_prob': float(g['arare_prob'].mean()) if len(g) else None,
            'top_patterns': [{'pattern': p, 'n': n} for p, n in pat],
        }
    out_csv = os.path.join(OUT_DIR, 'high_entropy_race_dataset_structured.csv')
    df.to_csv(out_csv, index=False, encoding='utf-8')
    html_path = write_upset_map_html(df, os.path.join(OUT_DIR, 'upset_structure_map.html'))
    report = {
        'distribution': dist,
        'type_definition': type_meta,
        'arare_metrics_by_type': metrics,
        'high_eff_n_top20pct_type_rates': hi_rates,
        'high_eff_n_solid_profile': solid_profile,
        'type_summaries': type_summaries,
        'clusters': clusters,
        'outputs': {'structured_csv': out_csv, 'map_html': html_path},
    }
    rpath = os.path.join(OUT_DIR, 'upset_structure_report.json')
    with open(rpath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    report['report_json'] = rpath
    return report
