# -*- coding: utf-8 -*-
"""Phase 3 market residual top3 corrector.

Frozen before test results:
- Relevance and Phase 2 features stay as Phase 2.
- Market spec is chosen on the last year inside TRAIN only, among ninki / log_odds / both.
- Residual stage-2 sees time-aware out-of-fold market probabilities, never in-sample fitted values.
- DeltaLogLoss = market_logloss - model_logloss (positive = better).
- DeltaBrier same direction. DeltaNDCG = model_ndcg - market_ndcg (positive = better).
- Correction buckets on probability points: >=0.05, 0.02..0.05, -0.02..0.02, -0.05..-0.02, <=-0.05.
- Gate uses logistic residual, not the test-best family.
- Pass if logloss drop > 0 in >=5 years, mean drop >= 0.002, bootstrap lo>0 in >=4 years,
  mean ECE of residual is not worse than market by more than 0.01,
  and inside pre-fixed market bands the positive-correction horses beat negative ones
  in >=4 years. No betting rule is registered.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from research.experiment_store import append_experiment
from research.influence.run_ir2 import INDEP, fit_ranker, load, ndcg_at

OUT = os.path.join(ROOT, 'data', 'research', 'influence_rank_phase3')
FOLDS = [(2020, 20191231), (2021, 20201231), (2022, 20211231),
         (2023, 20221231), (2024, 20231231), (2025, 20241231)]
SPECS = {
    'ninki': ['ninki_num'],
    'odds': ['log_odds'],
    'ninki_odds': ['ninki_num', 'log_odds'],
}
LGB = dict(n_estimators=40, learning_rate=0.05, num_leaves=15, min_child_samples=80,
           subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=-1)
EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0001]
BANDS = [(0.0, 0.15), (0.15, 0.25), (0.25, 0.40), (0.40, 1.01)]


def _num(df, cols):
    x = df[cols].apply(pd.to_numeric, errors='coerce')
    return x


def fit_predict(train, test, feats, ycol='top3', kind='logit'):
    xtr = _num(train, feats)
    xte = _num(test, feats)
    med = xtr.median()
    xtr = xtr.fillna(med)
    xte = xte.fillna(med)
    scaler = StandardScaler().fit(xtr)
    ztr, zte = scaler.transform(xtr), scaler.transform(xte)
    if kind == 'logit':
        clf = LogisticRegression(C=1.0, max_iter=250, random_state=42)
        clf.fit(ztr, train[ycol].to_numpy())
        p = clf.predict_proba(zte)[:, 1]
        coef = {f: float(c) for f, c in zip(feats, clf.coef_[0])}
        extra = {'intercept': float(clf.intercept_[0])}
    else:
        clf = LGBMClassifier(**LGB)
        clf.fit(ztr, train[ycol].to_numpy())
        p = clf.predict_proba(zte)[:, 1]
        coef = {f: float(c) for f, c in zip(feats, clf.feature_importances_)}
        extra = {}
    return p, coef, extra, scaler, med


def metrics(y, p, keys, gain):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        'logloss': float(log_loss(y, p)),
        'brier': float(brier_score_loss(y, p)),
        'auc': float(roc_auc_score(y, p)),
        'ndcg3': float(ndcg_at(keys, gain, p, 3)),
        'ece': ece(y, p),
    }


def ece(y, p):
    total = 0.0
    n = len(y)
    for a, b in zip(EDGES[:-1], EDGES[1:]):
        m = (p >= a) & (p < b)
        if m.sum() == 0:
            continue
        total += m.sum() / n * abs(float(y[m].mean()) - float(p[m].mean()))
    return float(total)


def bucket(delta):
    if delta >= 0.05:
        return 'strong_positive'
    if delta >= 0.02:
        return 'positive'
    if delta > -0.02:
        return 'neutral'
    if delta > -0.05:
        return 'negative'
    return 'strong_negative'


def oof_market(train, feats):
    years = sorted(int(y) for y in train['year'].unique())
    p = pd.Series(np.nan, index=train.index)
    for y in years:
        if y == years[0]:
            continue
        tr = train[train['year'] < y]
        te = train[train['year'] == y]
        if tr.empty or te.empty:
            continue
        pred, _, _, _, _ = fit_predict(tr, te, feats)
        p.loc[te.index] = pred
    return p


def choose_spec(train):
    val_year = int(train['year'].max())
    inner_tr = train[train['year'] < val_year]
    inner_va = train[train['year'] == val_year]
    best, best_ll = None, 1e9
    scores = {}
    for name, feats in SPECS.items():
        p, _, _, _, _ = fit_predict(inner_tr, inner_va, feats)
        ll = float(log_loss(inner_va['top3'], np.clip(p, 1e-6, 1 - 1e-6)))
        scores[name] = ll
        if ll < best_ll:
            best, best_ll = name, ll
    return best, scores


def reproduce(df):
    stored = json.load(open(os.path.join(ROOT, 'data', 'research', 'influence_rank_phase2', 'summary.json'), encoding='utf-8'))
    got = []
    for year, end in FOLDS:
        train = df[df['day'] <= end]
        test = df[df['year'] == year]
        tr_score, _ = fit_ranker(train, train, INDEP)
        te_score, _ = fit_ranker(train, test, INDEP)
        tr = train.copy()
        te = test.copy()
        tr['infl'] = tr_score
        te['infl'] = te_score
        def two(cols):
            a = tr[cols].apply(pd.to_numeric, errors='coerce')
            b = te[cols].apply(pd.to_numeric, errors='coerce')
            med = a.median()
            a, b = a.fillna(med), b.fillna(med)
            sc = StandardScaler().fit(a)
            clf = LogisticRegression(C=1.0, max_iter=250, random_state=42)
            clf.fit(sc.transform(a), tr['top3'].to_numpy())
            return clf.predict_proba(sc.transform(b))[:, 1]
        pm, pb = two(['ninki_inv']), two(['ninki_inv', 'infl'])
        y = te['top3'].to_numpy()
        got.append(float(log_loss(y, pm) - log_loss(y, pb)))
    ref = [r['logloss_drop'] for r in stored['residual']]
    ok = all(abs(a - b) < 0.0015 for a, b in zip(got, ref))
    return ok, {'recomputed_logloss_drop': got, 'phase2_logloss_drop': ref}


def boot_deltas(keys, y, gain, p_m, p_b, rng, n=60):
    groups = {}
    df = pd.DataFrame({'k': keys, 'y': y, 'g': gain, 'm': p_m, 'b': p_b})
    for k, g in df.groupby('k'):
        groups[k] = g[['y', 'g', 'm', 'b']].to_numpy()
    names = list(groups)
    dll, dbr, dnd = [], [], []
    for _ in range(n):
        take = rng.choice(len(names), size=len(names), replace=True)
        arr = np.vstack([groups[names[i]] for i in take])
        yy, gg, pm, pb = arr[:, 0], arr[:, 1], np.clip(arr[:, 2], 1e-6, 1 - 1e-6), np.clip(arr[:, 3], 1e-6, 1 - 1e-6)
        kk = np.repeat(np.arange(len(take)), [len(groups[names[i]]) for i in take])
        dll.append(log_loss(yy, pm) - log_loss(yy, pb))
        dbr.append(brier_score_loss(yy, pm) - brier_score_loss(yy, pb))
        dnd.append(ndcg_at(kk, gg, pb, 3) - ndcg_at(kk, gg, pm, 3))
    def pack(v):
        v = np.asarray(v, dtype=float)
        return {'mean': float(v.mean()), 'lo': float(np.quantile(v, 0.025)), 'hi': float(np.quantile(v, 0.975))}
    return {'logloss': pack(dll), 'brier': pack(dbr), 'ndcg3': pack(dnd)}


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load()
    df['year'] = (df['day'] // 10000).astype(int)
    df['ninki_num'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['log_odds'] = np.log(pd.to_numeric(df['win_odds'], errors='coerce').clip(lower=1.01))
    print('reproduce', file=sys.stderr)
    ok, repro = reproduce(df)
    if not ok:
        status = 'REPRODUCTION_FAILURE'
        payload = {'exit': status, 'reproduction': repro}
        json.dump(payload, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        json.dump(payload, open(os.path.join(ROOT, 'data', 'research', 'checkpoints', 'influence_rank_phase3.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(json.dumps(payload))
        return

    rng = np.random.default_rng(42)
    rows, boots, buckets, bands, ablations, specs, coefs = [], [], [], [], [], [], []
    pred_dir = os.path.join(OUT, 'predictions')
    os.makedirs(pred_dir, exist_ok=True)
    for year, end in FOLDS:
        train = df[df['day'] <= end].copy()
        test = df[df['year'] == year].copy()
        spec, spec_scores = choose_spec(train)
        feats = SPECS[spec]
        specs.append({'year': year, 'chosen_on_inner_train': spec, 'inner_logloss': spec_scores})
        print(year, spec, file=sys.stderr)
        p_m, coef_m, _, _, _ = fit_predict(train, test, feats, kind='logit')
        joint_feats = feats + INDEP
        p_j, coef_j, _, _, _ = fit_predict(train, test, joint_feats, kind='logit')
        oof = oof_market(train, feats)
        tr2 = train.loc[oof.notna()].copy()
        tr2['logit_p'] = np.log(np.clip(oof.loc[tr2.index], 1e-4, 1 - 1e-4) / (1 - np.clip(oof.loc[tr2.index], 1e-4, 1 - 1e-4)))
        te2 = test.copy()
        te2['logit_p'] = np.log(np.clip(p_m, 1e-4, 1 - 1e-4) / (1 - np.clip(p_m, 1e-4, 1 - 1e-4)))
        res_feats = ['logit_p'] + INDEP
        p_r, coef_r, extra_r, _, _ = fit_predict(tr2, te2, res_feats, kind='logit')
        p_m_g, _, _, _, _ = fit_predict(train, test, feats, kind='lgb')
        p_j_g, _, _, _, _ = fit_predict(train, test, joint_feats, kind='lgb')
        p_r_g, _, _, _, _ = fit_predict(tr2, te2, res_feats, kind='lgb')
        coefs.append({'year': year, 'market': coef_m, 'joint': coef_j, 'residual': coef_r, 'residual_intercept': extra_r})
        y = test['top3'].to_numpy()
        keys = test['race_key'].to_numpy()
        gain = test['gain'].to_numpy()
        named = {
            'market_logit': p_m, 'joint_logit': p_j, 'residual_logit': p_r,
            'market_lgb': p_m_g, 'joint_lgb': p_j_g, 'residual_lgb': p_r_g,
        }
        base = metrics(y, p_m, keys, gain)
        for name, p in named.items():
            met = metrics(y, p, keys, gain)
            rec = {'year': year, 'model': name, **met,
                   'delta_logloss': base['logloss'] - met['logloss'],
                   'delta_brier': base['brier'] - met['brier'],
                   'delta_auc': met['auc'] - base['auc'],
                   'delta_ndcg3': met['ndcg3'] - base['ndcg3']}
            rows.append(rec)
            append_experiment({
                'experiment_id': f'ir3_{name}_{year}',
                'phase': 'INFLUENCE_RANK_PHASE3',
                'hypothesis': name,
                'test_period': year,
                'logloss': met['logloss'],
                'delta_logloss_vs_market_logit': rec['delta_logloss'],
                'status': 'tested',
                'objective': 'top3 probability; ROI excluded',
            })
        boots.append({'year': year, 'joint': boot_deltas(keys, y, gain, p_m, p_j, rng),
                      'residual': boot_deltas(keys, y, gain, p_m, p_r, rng)})
        corr = p_r - p_m
        part = pd.DataFrame({'market_p': p_m, 'corr': corr, 'top3': y, 'p': p_r})
        part['bucket'] = [bucket(float(v)) for v in corr]
        for b, g in part.groupby('bucket'):
            buckets.append({'year': year, 'bucket': b, 'n': int(len(g)),
                            'market_p': float(g['market_p'].mean()), 'corrected_p': float(g['p'].mean()),
                            'actual_top3': float(g['top3'].mean())})
        band_hits = 0
        band_n = 0
        for lo, hi in BANDS:
            sl = part[(part['market_p'] >= lo) & (part['market_p'] < hi)]
            pos = sl[sl['corr'] >= 0.02]
            neg = sl[sl['corr'] <= -0.02]
            recb = {'year': year, 'band': [lo, hi], 'n_pos': int(len(pos)), 'n_neg': int(len(neg)),
                    'top3_pos': float(pos['top3'].mean()) if len(pos) else None,
                    'top3_neg': float(neg['top3'].mean()) if len(neg) else None}
            bands.append(recb)
            if len(pos) >= 80 and len(neg) >= 80:
                band_n += 1
                if pos['top3'].mean() > neg['top3'].mean():
                    band_hits += 1
        bands.append({'year': year, 'kind': 'summary', 'bands_pos_gt_neg': band_hits, 'bands_compared': band_n})
        full_ll = metrics(y, p_r, keys, gain)['logloss']
        for label, subset in (
            ('vh_only', ['vh2_score']),
            ('vh_prior', ['vh2_score', 'prior_top3_rate']),
            ('drop_vh', [f for f in INDEP if f != 'vh2_score']),
            ('drop_prior', [f for f in INDEP if f != 'prior_top3_rate']),
        ):
            p_s, _, _, _, _ = fit_predict(tr2, te2, ['logit_p'] + subset)
            ll = metrics(y, p_s, keys, gain)['logloss']
            ablations.append({'year': year, 'variant': label, 'logloss': ll, 'worse_than_full': ll - full_ll})
        for feat in INDEP:
            if feat in ('vh2_score', 'prior_top3_rate'):
                continue
            subset = [f for f in INDEP if f != feat]
            p_s, _, _, _, _ = fit_predict(tr2, te2, ['logit_p'] + subset)
            ll = float(log_loss(y, np.clip(p_s, 1e-6, 1 - 1e-6)))
            ablations.append({'year': year, 'variant': 'drop_' + feat, 'logloss': ll, 'worse_than_full': ll - full_ll})
        # field-size diagnostic only
        sizes = test.groupby('race_key')['race_key'].transform('size')
        diag = []
        for name, mask in (('small', sizes < 10), ('mid', (sizes >= 10) & (sizes < 15)), ('large', sizes >= 15)):
            if mask.sum() < 50:
                continue
            diag.append({'year': year, 'field': name, 'n': int(mask.sum()),
                         'delta_logloss': float(log_loss(y[mask], np.clip(p_m[mask], 1e-6, 1 - 1e-6)) - log_loss(y[mask], np.clip(p_r[mask], 1e-6, 1 - 1e-6)))})
        specs[-1]['field_diagnostic'] = diag
        outp = pd.DataFrame({
            'race_key': keys, 'market_top3_p': p_m, 'joint_top3_p': p_j, 'corrected_top3_p': p_r,
            'correction': corr, 'top3': y,
        })
        outp['correction_rank'] = outp.groupby('race_key')['corrected_top3_p'].rank(ascending=False, method='min')
        outp.to_csv(os.path.join(pred_dir, f'{year}.csv.gz'), index=False, compression='gzip')

    res_rows = [r for r in rows if r['model'] == 'residual_logit']
    drops = [r['delta_logloss'] for r in res_rows]
    ece_gap = np.mean([next(r['ece'] for r in rows if r['year'] == y and r['model'] == 'residual_logit')
                       - next(r['ece'] for r in rows if r['year'] == y and r['model'] == 'market_logit')
                       for y, _ in FOLDS])
    ci_pos = sum(b['residual']['logloss']['lo'] > 0 for b in boots)
    band_years = sum(b.get('bands_pos_gt_neg', 0) >= 3 and b.get('bands_compared', 0) >= 3
                     for b in bands if b.get('kind') == 'summary')
    passed = (sum(d > 0 for d in drops) >= 5 and float(np.mean(drops)) >= 0.002 and ci_pos >= 4
              and float(ece_gap) <= 0.01 and band_years >= 4)
    status = 'TOP3_PREDICTION_CANDIDATE_FROZEN' if passed else 'NO_STABLE_TOP3_CORRECTOR'
    code = open(__file__, 'rb').read()
    spec = None
    if passed:
        spec = {
            'candidate_id': 'TOP3_MARKET_RESIDUAL_V1',
            'kind': 'PREDICTION_CANDIDATE',
            'not': 'BETTING_CANDIDATE',
            'market_model': 'logistic; spec chosen each fold on inner train among ninki, log odds, both',
            'correction_model': 'logistic on logit(OOF market p) + 8 independent features',
            'features_independent': INDEP,
            'training_period_note': 'expanding walk-forward, test years 2020-2025 not used to fit the reported fold',
            'normalization': 'train median impute + StandardScaler',
            'calibration_bins': EDGES,
            'output_schema': ['market_top3_p', 'corrected_top3_p', 'correction', 'correction_rank'],
            'code_hash': hashlib.sha256(code).hexdigest()[:16],
            'historical_odds': 'final win_odds, not decision-time quotes',
        }
        json.dump(spec, open(os.path.join(OUT, 'candidate_spec.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    summary = {
        'exit': status,
        'reproduction_ok': True,
        'reproduction': repro,
        'jev': 'JEV_NOT_AVAILABLE',
        'production_changed': False,
        'betting_research': False,
        'historical_odds_note': 'win_odds are final odds; this is incremental prediction evidence, not an executable price',
        'gates': {
            'positive_logloss_years': int(sum(d > 0 for d in drops)),
            'mean_delta_logloss': float(np.mean(drops)),
            'bootstrap_lo_positive_years': int(ci_pos),
            'mean_ece_residual_minus_market': float(ece_gap),
            'band_years': int(band_years),
            'passed': passed,
        },
        'market_spec_by_fold': specs,
        'metrics': rows,
        'bootstrap': boots,
        'buckets': buckets,
        'bands': bands,
        'ablation': ablations,
        'coefs': coefs,
        'candidate': spec,
        'track_a_missing_inputs': ['ability', 'h7_fig', 'spurt_mean3', 'prior_top3_rate', 'jockey_jyo_win', 'trainer_jyo_t3', 'elim_n'],
        'track_a_present_inputs': ['decision_time_popularity', 'decision_time_odds', 'vh_score'],
    }
    json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump({'exit': status, 'gates': summary['gates']}, open(os.path.join(ROOT, 'data', 'research', 'checkpoints', 'influence_rank_phase3.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(json.dumps({'exit': status, 'gates': summary['gates']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
