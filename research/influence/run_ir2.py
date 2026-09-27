# -*- coding: utf-8 -*-
"""Influence Rank Phase 2. Phase 1 files are not rewritten. ROI is not the rank objective."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from research.experiment_store import append_experiment

OUT = os.path.join(ROOT, 'data', 'research', 'influence_rank_phase2')
FOLDS = [(2020, 20191231), (2021, 20201231), (2022, 20211231),
         (2023, 20221231), (2024, 20231231), (2025, 20241231)]
INDEP = ['vh2_score', 'ability_inv', 'h7_fig', 'spurt_mean3', 'prior_top3_rate',
         'jockey_jyo_win', 'trainer_jyo_t3', 'elim_inv']
AWARE = INDEP + ['ninki_inv']
# Frozen before any test read: 1st=3, 2nd=2, 3rd=1, else=0. One encoding only.
# delta_rank = popularity_rank - influence_rank. Positive means influence ranks the horse higher.
# Buckets: >=4 strong upgrade, 2..3 upgrade, -1..1 neutral, -3..-2 downgrade, <=-4 strong downgrade.
# LGBM frozen: lambdarank, 60 trees, 15 leaves, lr 0.05, min_child 80, seed 42.
# Residual pass: mean logloss drop >= 0.001, >=4 years positive, pooled bootstrap CI excludes 0.
# Disagreement pass: ninki 1..8, >=4 years where >=5 levels have upgrade top3 > downgrade top3 (n>=30).
# Betting rule frozen, not used for rank selection: WIN 100 yen if influence rank<=3 and popularity rank>=6.
LGB_PARAMS = dict(objective='lambdarank', n_estimators=60, learning_rate=0.05, num_leaves=15,
                  min_child_samples=80, subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=-1)


def load():
    cols = ['race_key', 'day', 'chakujun', 'ninki', 'win_odds', 'vh2_score', 'ability_score', 'h7_fig',
            'spurt_mean3', 'prior_top3_rate', 'jockey_jyo_win', 'trainer_jyo_t3', 'elim_n']
    df = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'horse_races.csv'), usecols=cols)
    df = df[(df['day'] <= 20251231) & df['chakujun'].notna() & (df['chakujun'] > 0)].copy()
    df['race_key'] = df['race_key'].astype(str)
    df['ability_inv'] = -pd.to_numeric(df['ability_score'], errors='coerce')
    df['elim_inv'] = -pd.to_numeric(df['elim_n'], errors='coerce')
    df['ninki_inv'] = -pd.to_numeric(df['ninki'], errors='coerce')
    df['win'] = (df['chakujun'] == 1).astype(int)
    df['top3'] = (df['chakujun'] <= 3).astype(int)
    df['gain'] = np.where(df['chakujun'] == 1, 3, np.where(df['chakujun'] == 2, 2, np.where(df['chakujun'] == 3, 1, 0))).astype(int)
    return df


def _matrix(train, test, feats):
    xtr = train[feats].apply(pd.to_numeric, errors='coerce')
    xte = test[feats].apply(pd.to_numeric, errors='coerce')
    med = xtr.median()
    return xtr.fillna(med), xte.fillna(med)


def fit_logit(train, test, feats, label):
    xtr, xte = _matrix(train, test, feats)
    scaler = StandardScaler().fit(xtr)
    clf = LogisticRegression(C=1.0, max_iter=250, random_state=42)
    clf.fit(scaler.transform(xtr), train[label].to_numpy())
    score = clf.predict_proba(scaler.transform(xte))[:, 1]
    coef = {f: float(c) for f, c in zip(feats, clf.coef_[0])}
    return score, coef


def fit_ranker(train, test, feats):
    tr = train.sort_values('race_key')
    te = test.sort_values('race_key')
    xtr, xte = _matrix(tr, te, feats)
    scaler = StandardScaler().fit(xtr)
    groups = tr.groupby('race_key', sort=False).size().to_numpy()
    ranker = LGBMRanker(label_gain=[0, 1, 2, 3], **LGB_PARAMS)
    ranker.fit(scaler.transform(xtr), tr['gain'].to_numpy(), group=groups)
    score = pd.Series(ranker.predict(scaler.transform(xte)), index=te.index)
    imp = {f: float(v) for f, v in zip(feats, ranker.feature_importances_)}
    return score.reindex(test.index).to_numpy(), imp


def ndcg_at(keys, gains, scores, k):
    order = np.lexsort((-scores, keys))
    keys = keys[order]
    gains = gains[order]
    cuts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1], True])
    discounts = 1.0 / np.log2(np.arange(2, k + 2))
    total = 0.0
    n = 0
    for a, b in zip(cuts[:-1], cuts[1:]):
        g = gains[a:b]
        if g.size < 2:
            continue
        pred = g[:k]
        if pred.size < k:
            pred = np.pad(pred, (0, k - pred.size))
        ideal = np.sort(g)[::-1][:k]
        if ideal.size < k:
            ideal = np.pad(ideal, (0, k - ideal.size))
        idcg = float((ideal * discounts).sum())
        total += float((pred * discounts).sum()) / idcg if idcg else 0.0
        n += 1
    return total / n if n else None


def evaluate(df, score):
    work = df[['race_key', 'chakujun', 'gain', 'win', 'top3']].copy()
    work['score'] = score
    work['rk'] = work.groupby('race_key')['score'].rank(ascending=False, method='min')
    keys = work['race_key'].to_numpy()
    gains = work['gain'].to_numpy()
    sc = work['score'].to_numpy()
    r1 = work[work['rk'] == 1]
    capture = {}
    for depth in (2, 3):
        truth = work['chakujun'] <= 3
        got = work['rk'] <= depth
        # fraction of actual top3 horses inside predicted top `depth`, races with 3 finishers in top3
        both = work.loc[truth].groupby('race_key')['rk'].apply(lambda s: float((s <= depth).mean()) if len(s) >= 3 else np.nan)
        capture[depth] = float(both.mean())
    buckets = {}
    for k in list(range(1, 6)) + ['6+']:
        part = work[work['rk'] == k] if k != '6+' else work[work['rk'] >= 6]
        if part.empty:
            continue
        buckets[str(k)] = {
            'n': int(len(part)),
            'win': float(part['win'].mean()),
            'top2': float((part['chakujun'] <= 2).mean()),
            'top3': float(part['top3'].mean()),
        }
    top3s = [buckets[str(i)]['top3'] for i in range(1, 6) if str(i) in buckets]
    mono_steps = sum(a > b for a, b in zip(top3s, top3s[1:]))
    return {
        'rank1_win': float(r1['win'].mean()) if len(r1) else None,
        'rank1_top3': float(r1['top3'].mean()) if len(r1) else None,
        'top2_capture': capture[2],
        'top3_capture': capture[3],
        'ndcg3': ndcg_at(keys, gains, sc, 3),
        'ndcg5': ndcg_at(keys, gains, sc, 5),
        'buckets': buckets,
        'mono_adjacent': mono_steps,
        'rk': work['rk'].to_numpy(),
    }


def agree(pop_rk, infl_rk, top3):
    same1 = float(((pop_rk == 1) & (infl_rk == 1)).sum() / max((pop_rk == 1).sum(), 1))
    # top3 set overlap averaged per race is computed outside
    return same1


def race_overlap(keys, pop_rk, infl_rk):
    order = np.argsort(keys, kind='mergesort')
    keys = keys[order]
    pop_rk = pop_rk[order]
    infl_rk = infl_rk[order]
    cuts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1], True])
    acc = 0.0
    n = 0
    spears = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < 3:
            continue
        p = pop_rk[a:b] <= 3
        i = infl_rk[a:b] <= 3
        acc += len(np.intersect1d(np.flatnonzero(p), np.flatnonzero(i))) / 3.0
        n += 1
        if np.std(pop_rk[a:b]) > 0 and np.std(infl_rk[a:b]) > 0:
            spears.append(np.corrcoef(pop_rk[a:b], infl_rk[a:b])[0, 1])
    return acc / n if n else None, float(np.mean(spears)) if spears else None


def bucket_name(delta):
    if delta >= 4:
        return 'strong_upgrade'
    if delta >= 2:
        return 'upgrade'
    if delta >= -1:
        return 'neutral'
    if delta >= -3:
        return 'downgrade'
    return 'strong_downgrade'


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load()
    df['pop_score'] = df['ninki_inv']
    df['vh_score'] = pd.to_numeric(df['vh2_score'], errors='coerce')
    df['ab_score'] = df['ability_inv']
    rows = []
    curves = []
    coefs = []
    disagree_rows = []
    residual_rows = []
    ablation_rows = []
    boot_rows = []
    weight_rows = []
    bet_rows = []
    rng = np.random.default_rng(42)

    for year, end in FOLDS:
        train = df[df['day'] <= end]
        test = df[df['day'] // 10000 == year].copy()
        print(year, 'fit', file=sys.stderr)
        scores = {}
        scores['popularity'] = test['pop_score'].to_numpy()
        scores['vh'] = test['vh_score'].to_numpy()
        scores['ability'] = test['ab_score'].to_numpy()
        scores['phase1_win_independent'], c_p1 = fit_logit(train, test, INDEP, 'win')
        scores['phase1_win_aware'], _ = fit_logit(train, test, AWARE, 'win')
        scores['top3_independent'], c_t3 = fit_logit(train, test, INDEP, 'top3')
        scores['top3_aware'], c_t3a = fit_logit(train, test, AWARE, 'top3')
        scores['ltr_independent'], imp_i = fit_ranker(train, test, INDEP)
        scores['ltr_aware'], imp_a = fit_ranker(train, test, AWARE)
        coefs.append({'year': year, 'phase1_win_independent': c_p1, 'top3_independent': c_t3,
                      'top3_aware': c_t3a, 'ltr_independent_importance': imp_i, 'ltr_aware_importance': imp_a})

        # direct weights: 24 frozen random vectors, pick by train NDCG@3 on 2500 races
        sample_races = rng.choice(train['race_key'].unique(), size=min(2500, train['race_key'].nunique()), replace=False)
        sample = train[train['race_key'].isin(sample_races)]
        xtr, xte = _matrix(train, test, INDEP)
        scaler = StandardScaler().fit(xtr)
        ztr = scaler.transform(sample[INDEP].apply(pd.to_numeric, errors='coerce').fillna(xtr.median()))
        zte = scaler.transform(xte)
        best_w, best_nd = None, -1
        for _try in range(24):
            w = rng.uniform(-1.5, 1.5, size=len(INDEP))
            nd = ndcg_at(sample['race_key'].to_numpy(), sample['gain'].to_numpy(), ztr @ w, 3)
            if nd is not None and nd > best_nd:
                best_nd, best_w = nd, w
        scores['direct_weight'] = zte @ best_w
        weight_rows.append({'year': year, 'train_ndcg3': best_nd, 'weights': {f: float(v) for f, v in zip(INDEP, best_w)}})

        evals = {}
        for name, sc in scores.items():
            ev = evaluate(test, sc)
            evals[name] = ev
            rec = {'year': year, 'model': name, **{k: ev[k] for k in ('rank1_win', 'rank1_top3', 'top2_capture', 'top3_capture', 'ndcg3', 'ndcg5', 'mono_adjacent')}}
            rows.append(rec)
            if name in ('popularity', 'top3_independent', 'ltr_independent', 'ltr_aware', 'phase1_win_independent', 'direct_weight'):
                curves.append({'year': year, 'model': name, 'buckets': ev['buckets']})
            pass

        pop_rk = evals['popularity']['rk']
        infl = evals['ltr_independent']['rk']
        delta = pop_rk - infl
        overlap, spear = race_overlap(test['race_key'].to_numpy(), pop_rk, infl)
        top1 = float(((pop_rk == 1) & (infl == 1)).sum() / max((pop_rk == 1).sum(), 1))
        part = test[['ninki', 'win', 'top3', 'win_odds', 'chakujun']].copy()
        part['pop_rk'] = pop_rk
        part['infl_rk'] = infl
        part['delta'] = delta
        part['bucket'] = [bucket_name(float(v)) for v in delta]
        part['race_key'] = test['race_key'].to_numpy()
        for b, g in part.groupby('bucket'):
            disagree_rows.append({'year': year, 'bucket': b, 'n': int(len(g)), 'win': float(g['win'].mean()), 'top3': float(g['top3'].mean()),
                                  'mean_ninki': float(pd.to_numeric(g['ninki'], errors='coerce').mean())})
        level_hits = 0
        for nk in range(1, 9):
            sl = part[pd.to_numeric(part['ninki'], errors='coerce') == nk]
            up = sl[sl['delta'] >= 2]
            down = sl[sl['delta'] <= -2]
            base = sl
            disagree_rows.append({
                'year': year, 'ninki': nk, 'n_base': int(len(base)), 'n_up': int(len(up)), 'n_down': int(len(down)),
                'top3_base': float(base['top3'].mean()) if len(base) else None,
                'top3_up': float(up['top3'].mean()) if len(up) else None,
                'top3_down': float(down['top3'].mean()) if len(down) else None,
                'win_up': float(up['win'].mean()) if len(up) else None,
                'win_down': float(down['win'].mean()) if len(down) else None,
            })
            if len(up) >= 30 and len(down) >= 30 and up['top3'].mean() > down['top3'].mean():
                level_hits += 1
        disagree_rows.append({'year': year, 'kind': 'agreement', 'top1_agreement': top1, 'top3_overlap': overlap,
                              'spearman_ranks': spear, 'ninki_levels_up_gt_down': level_hits})

        # residual: market-only vs market + independent LTR score
        raw = test['ltr_independent_score'] if False else None
        xtr_m, xte_m = _matrix(train, test, ['ninki_inv'])
        # attach train ltr scores
        tr_score, _ = fit_ranker(train, train, INDEP)
        tr = train.copy()
        tr['infl'] = tr_score
        te = test.copy()
        te['infl'] = scores['ltr_independent']
        def _two(frame_tr, frame_te, cols):
            a, b = _matrix(frame_tr, frame_te, cols)
            sca = StandardScaler().fit(a)
            clf = LogisticRegression(C=1.0, max_iter=250, random_state=42)
            clf.fit(sca.transform(a), frame_tr['top3'].to_numpy())
            p = clf.predict_proba(sca.transform(b))[:, 1]
            return p
        p_m = _two(tr, te, ['ninki_inv'])
        p_b = _two(tr, te, ['ninki_inv', 'infl'])
        y = te['top3'].to_numpy()
        lm, lb = log_loss(y, p_m), log_loss(y, p_b)
        residual_rows.append({
            'year': year,
            'logloss_market': lm,
            'logloss_market_influence': lb,
            'logloss_drop': lm - lb,
            'brier_market': float(brier_score_loss(y, p_m)),
            'brier_both': float(brier_score_loss(y, p_b)),
            'auc_market': float(roc_auc_score(y, p_m)),
            'auc_both': float(roc_auc_score(y, p_b)),
        })
        # race bootstrap of logloss drop
        te = te.copy()
        te['pm'] = p_m
        te['pb'] = p_b
        races = te['race_key'].unique()
        drops = []
        for _b in range(80):
            take = rng.choice(races, size=len(races), replace=True)
            # map via merge of counts would be heavy; sample horse rows by race membership with replacement via index lists
            pieces = [te.loc[te['race_key'] == rk] for rk in take[:0]]
        # faster bootstrap: pre-index
        groups = {rk: g[['top3', 'pm', 'pb']].to_numpy() for rk, g in te.groupby('race_key')}
        keys = list(groups)
        for _b in range(80):
            take = rng.choice(len(keys), size=len(keys), replace=True)
            blocks = [groups[keys[i]] for i in take]
            arr = np.vstack(blocks)
            yy, pm, pb = arr[:, 0], arr[:, 1], arr[:, 2]
            pm = np.clip(pm, 1e-6, 1 - 1e-6)
            pb = np.clip(pb, 1e-6, 1 - 1e-6)
            drops.append(log_loss(yy, pm) - log_loss(yy, pb))
        drops = np.array(drops)
        boot_rows.append({'year': year, 'mean': float(drops.mean()), 'lo': float(np.quantile(drops, 0.025)), 'hi': float(np.quantile(drops, 0.975))})

        # ablation of top3 independent
        full_nd = evals['top3_independent']['ndcg3']
        for feat in INDEP:
            feats = [f for f in INDEP if f != feat]
            sc, _ = fit_logit(train, test, feats, 'top3')
            nd = ndcg_at(test['race_key'].to_numpy(), test['gain'].to_numpy(), sc, 3)
            ablation_rows.append({'year': year, 'dropped': feat, 'ndcg3': nd, 'delta_vs_full': full_nd - nd})

        # pre-registered bet, recorded always, promotion decided later
        bet = part[(part['infl_rk'] <= 3) & (part['pop_rk'] >= 6)]
        odds = pd.to_numeric(bet['win_odds'], errors='coerce')
        stake = 100.0 * odds.notna().sum()
        ret = float((odds.fillna(0) * 100.0 * (bet['chakujun'] == 1).to_numpy()).sum())
        bet_rows.append({'year': year, 'n': int(odds.notna().sum()), 'roi': ret / stake if stake else None, 'profit': ret - stake})
        print(year, 'done', round(evals['ltr_independent']['ndcg3'], 4), file=sys.stderr)

    # gates frozen above
    phase1 = [r for r in rows if r['model'] == 'phase1_win_independent']
    top3m = [r for r in rows if r['model'] == 'top3_independent']
    ltr = [r for r in rows if r['model'] == 'ltr_independent']
    a_years = sum(t['ndcg3'] > p['ndcg3'] + 1e-4 for t, p in zip(top3m, phase1))
    a_years_ltr = sum(t['ndcg3'] > p['ndcg3'] + 1e-4 for t, p in zip(ltr, phase1))
    drops = [r['logloss_drop'] for r in residual_rows]
    b_years = sum(d > 0 for d in drops)
    b_mean = float(np.mean(drops))
    # pooled CI: mean of yearly bootstrap intervals is not pooled; require every positive year CI or majority CI lo>0
    ci_pos = sum(r['lo'] > 0 for r in boot_rows)
    b_pass = b_mean >= 0.001 and b_years >= 4 and ci_pos >= 4
    level_rows = [r for r in disagree_rows if r.get('ninki_levels_up_gt_down') is not None]
    c_years = sum(r['ninki_levels_up_gt_down'] >= 5 for r in level_rows)
    c_pass = c_years >= 4
    gate = b_pass or c_pass
    bet_pos = int(sum((r['roi'] or 0) > 1 and r['n'] >= 80 for r in bet_rows))
    if not gate:
        status = 'NO_INCREMENTAL_INFLUENCE_SIGNAL'
    elif bet_pos >= 4:
        status = 'INFLUENCE_BETTING_CANDIDATE_FROZEN'
    else:
        status = 'INFLUENCE_RANK_SIGNAL_FOUND'

    summary = {
        'exit': status,
        'jev': 'JEV_NOT_AVAILABLE',
        'production_changed': False,
        'betting_rule_evaluated': True,
        'betting_promoted': status == 'INFLUENCE_BETTING_CANDIDATE_FROZEN',
        'phase1_files_rewritten': False,
        'existing_ltr_model': 'NOT_REPRODUCIBLE_FOR_WALKFORWARD',
        'relevance': {'1': 3, '2': 2, '3': 1, 'else': 0},
        'delta_definition': 'popularity_rank - influence_rank; positive = influence higher than market',
        'gates': {
            'A_top3_ndcg_beats_phase1_years': a_years,
            'A_ltr_ndcg_beats_phase1_years': a_years_ltr,
            'B_mean_logloss_drop': b_mean,
            'B_positive_years': b_years,
            'B_years_ci_excludes_0': ci_pos,
            'B_pass': b_pass,
            'C_years_majority_ninki': c_years,
            'C_pass': c_pass,
            'bet_years_roi_above_1': bet_pos,
        },
        'metrics': rows,
        'coefs': coefs,
        'curves': curves,
        'disagreement': disagree_rows,
        'residual': residual_rows,
        'bootstrap': boot_rows,
        'ablation': ablation_rows,
        'direct_weights': weight_rows,
        'betting_observed_not_for_selection': bet_rows,
    }
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(ROOT, 'data', 'research', 'checkpoints', 'influence_rank_phase2.json'), 'w', encoding='utf-8') as f:
        json.dump({'exit': status, 'gates': summary['gates'], 'jev': 'JEV_NOT_AVAILABLE'}, f, ensure_ascii=False, indent=2)
    print(json.dumps({'exit': status, 'gates': summary['gates']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
