# -*- coding: utf-8 -*-
"""VH_TOP2_POP6_WIN_V1 の HOLDOUT を1回だけ評価する。ルールは変更しない。"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.experiment_store import append_experiment
from research.metrics import max_drawdown, max_losing_streak

CANDIDATE_ID = 'VH_TOP2_POP6_WIN_V1'
UNIT = 100
HOLDOUT_FROM = 20250101
BOOT_N = 2000
RNG = np.random.default_rng(42)
OUT = os.path.join(ROOT, 'data', 'research', 'historical_v1')

RULE = {
    'candidate_id': CANDIDATE_ID,
    'vh2_rank_in_race': [1, 2],
    'ninki_min': 6,
    'bet': 'win',
    'stake_per_horse': UNIT,
    'multiple_horses': 'each_100',
    'projected_score': False,
    'rule_b': False,
    'kelly': False,
}


def freeze_record():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'holdout_freeze.json')
    if os.path.exists(path):
        return json.load(open(path, encoding='utf-8'))
    rec = {
        'candidate_id': CANDIDATE_ID,
        'frozen_at': datetime.now(timezone.utc).isoformat(),
        'rule': RULE,
        'holdout_from': HOLDOUT_FROM,
        'holdout_to': 'export_max_day',
        'note': 'Written before holdout aggregation.',
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec


def load_holdout():
    cols = ['race_key', 'day', 'umaban', 'ninki', 'win_odds', 'vh2_score', 'win', 'chakujun']
    df = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'horse_races.csv'), usecols=cols)
    df = df[pd.to_numeric(df['day'], errors='coerce') >= HOLDOUT_FROM].copy()
    df['race_key'] = df['race_key'].astype(str)
    df['vh_rank'] = df.groupby('race_key')['vh2_score'].rank(ascending=False, method='min')
    return df


def select(df):
    m = df['vh_rank'].isin([1, 2]) & (df['ninki'] >= 6) & df['win_odds'].notna() & (df['win_odds'] > 0)
    return df.loc[m].sort_values(['day', 'race_key', 'umaban']).copy()


def enrich(bets: pd.DataFrame) -> pd.DataFrame:
    b = bets.copy()
    b['stake'] = UNIT
    b['payout'] = np.where(b['win'].to_numpy() == 1, b['win_odds'].to_numpy() * UNIT, 0.0)
    b['profit'] = b['payout'] - UNIT
    b['year'] = (b['day'] // 10000).astype(int)
    b['month'] = (b['day'] // 100).astype(int)
    b['pop_band'] = np.where(b['ninki'] >= 11, '11+', b['ninki'].astype(int).astype(str))
    return b


def roi_of(payout, stake):
    return 100.0 * payout / stake if stake else 0.0


def block_metrics(bets: pd.DataFrame, n_races_universe: int) -> dict:
    if bets.empty:
        return {'n_bets': 0}
    stake = float(bets['stake'].sum())
    payout = float(bets['payout'].sum())
    profit = payout - stake
    hits = bets[bets['win'] == 1]
    hit_pays = hits['payout'].to_numpy()
    race_pl = bets.groupby(['day', 'race_key'], sort=True)['profit'].sum()
    hits_seq = bets.groupby(['day', 'race_key'], sort=True)['win'].max().astype(int).tolist()
    # bootstrap ROI on race profits
    pl = race_pl.to_numpy()
    stakes_r = bets.groupby(['day', 'race_key'], sort=True)['stake'].sum().to_numpy()
    rois = []
    idx = np.arange(len(pl))
    for _ in range(BOOT_N):
        take = RNG.choice(idx, size=len(idx), replace=True)
        rois.append(roi_of(pl[take].sum() + stakes_r[take].sum(), stakes_r[take].sum()))
    lo, hi = np.percentile(rois, [2.5, 97.5])
    n_races_bet = int(bets['race_key'].nunique())
    return {
        'races_universe': int(n_races_universe),
        'races_bet': n_races_bet,
        'n_bets': int(len(bets)),
        'bet_rate_races': n_races_bet / n_races_universe if n_races_universe else 0.0,
        'hits': int(len(hits)),
        'hit_rate': float(len(hits) / len(bets)),
        'stake': stake,
        'payout': payout,
        'profit': profit,
        'roi': roi_of(payout, stake),
        'avg_hit_payout': float(hit_pays.mean()) if len(hit_pays) else 0.0,
        'median_hit_payout': float(np.median(hit_pays)) if len(hit_pays) else 0.0,
        'max_drawdown': max_drawdown(list(race_pl.to_numpy())),
        'max_losing_streak': max_losing_streak(hits_seq),
        'roi_ci95': [float(lo), float(hi)],
    }


def sensitivity(bets: pd.DataFrame) -> dict:
    hits = bets[bets['win'] == 1].sort_values('payout', ascending=False)
    total_profit = float(bets['profit'].sum())
    stake = float(bets['stake'].sum())
    payout = float(bets['payout'].sum())

    def drop(n):
        if hits.empty:
            return {'roi': None, 'profit': total_profit}
        drop_idx = hits.head(n).index
        kept = bets.drop(index=drop_idx)
        st = float(kept['stake'].sum())
        py = float(kept['payout'].sum())
        return {'n_removed': n, 'roi': roi_of(py, st), 'profit': py - st, 'stake': st, 'payout': py}

    def contrib(n):
        if hits.empty or total_profit == 0:
            return None
        part = float(hits.head(n)['profit'].sum())
        return part / total_profit

    top1 = float(hits.iloc[0]['payout']) if len(hits) else 0.0
    return {
        'top1_payout': top1,
        'roi_without_top1': drop(1),
        'roi_without_top3': drop(3),
        'profit_share_top1': contrib(1),
        'profit_share_top3': contrib(3),
        'total_profit': total_profit,
        'full_roi': roi_of(payout, stake),
    }


def monthly(bets: pd.DataFrame) -> list:
    rows = []
    cum = 0.0
    for month, g in bets.groupby('month', sort=True):
        st = float(g['stake'].sum())
        py = float(g['payout'].sum())
        pr = py - st
        cum += pr
        rows.append({
            'month': int(month),
            'n': int(len(g)),
            'profit': pr,
            'roi': roi_of(py, st),
            'cum_profit': cum,
        })
    return rows


def slice_metrics(bets, key):
    out = {}
    for k, g in bets.groupby(key, sort=True):
        st = float(g['stake'].sum())
        py = float(g['payout'].sum())
        out[str(k)] = {
            'n': int(len(g)),
            'hit_rate': float(g['win'].mean()),
            'roi': roi_of(py, st),
            'profit': py - st,
        }
    return out


def main():
    frozen = freeze_record()
    df = load_holdout()
    max_day = int(df['day'].max())
    universe = df.groupby(df['day'] // 10000)['race_key'].nunique().to_dict()
    n_all = int(df['race_key'].nunique())
    bets = enrich(select(df))
    by_year = {}
    for year, g in bets.groupby('year'):
        n_u = int(df.loc[df['day'] // 10000 == year, 'race_key'].nunique())
        by_year[str(int(year))] = block_metrics(g, n_u)
    result = {
        'candidate_id': CANDIDATE_ID,
        'frozen_at': frozen['frozen_at'],
        'rule': RULE,
        'max_day': max_day,
        'note_2026': '2026 is partial through 2026-06-21',
        'all': block_metrics(bets, n_all),
        'by_year': by_year,
        'by_popularity': slice_metrics(bets, 'pop_band'),
        'by_vh_rank': slice_metrics(bets, 'vh_rank'),
        'monthly': monthly(bets),
        'sensitivity': sensitivity(bets),
        'universe_races_by_year': {str(int(k)): int(v) for k, v in universe.items()},
    }
    path = os.path.join(OUT, 'holdout_result.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({
        'frozen_at': frozen['frozen_at'],
        'max_day': max_day,
        'all': result['all'],
        'by_year': result['by_year'],
        'sensitivity': result['sensitivity'],
    }, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
