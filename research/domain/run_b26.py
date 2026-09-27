# -*- coding: utf-8 -*-
"""B26–B29 の事前登録チケット。TEST 年で閾値は動かさない。

Projected Score / cross_n は使わない。
VH_TOP2_POP6 単勝は再評価しない。
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
from research.metrics import max_drawdown
from research.payouts.verify_db import load_maps

OUT = os.path.join(ROOT, 'data', 'research', 'advanced')
UNIT = 100
YEARS = (2020, 2021, 2022, 2023, 2024, 2025)


def load():
    h = pd.read_csv(
        os.path.join(ROOT, 'data', 'export', 'horse_races.csv'),
        usecols=['race_key', 'day', 'umaban', 'ninki', 'vh2_score', 'ability_score', 'chakujun', 'win'])
    r = pd.read_csv(os.path.join(ROOT, 'data', 'export', 'races.csv'), usecols=['race_key', 'vscore'])
    h = h[h['day'] <= 20251231]
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    df = h.merge(r, on='race_key', how='left')
    df['vh_rank'] = df.groupby('race_key')['vh2_score'].rank(ascending=False, method='min')
    df['ab_rank'] = df.groupby('race_key')['ability_score'].rank(ascending=True, method='min')
    return df


def pay_of(rows, key):
    hits = [p for c, p in rows if c == key and p > 0]
    if not hits:
        return 0.0
    return float(hits[0])


def score_bets(records):
    """records: list of {day, race, stake, payout, hit}."""
    if not records:
        return {'n_races': 0, 'tickets': 0, 'stake': 0, 'payout': 0, 'profit': 0,
                'roi': None, 'hit_rate': None, 'max_dd': 0}
    df = pd.DataFrame(records).sort_values(['day', 'race'])
    stake = float(df['stake'].sum())
    payout = float(df['payout'].sum())
    pl = (df['payout'] - df['stake']).to_numpy()
    return {
        'n_races': int(df['race'].nunique()),
        'tickets': int(df['tickets'].sum()),
        'stake': stake,
        'payout': payout,
        'profit': payout - stake,
        'roi': 100.0 * payout / stake if stake else None,
        'hit_rate': float(df['hit'].mean()),
        'max_dd': max_drawdown(list(pl)),
        'tickets_per_race': float(df['tickets'].mean()),
    }


def eval_year(df, maps, year):
    sub = df[df['day'] // 10000 == year]
    place = maps['複勝']
    wide = maps['ワイド']
    trio = maps['3連複']
    out = {k: [] for k in ('place_fav', 'place_vh1', 'place_ab1', 'wide_12', 'trio_d')}
    pos = []
    for rk, g in sub.groupby('race_key', sort=False):
        day = int(g['day'].iloc[0])
        by_n = {}
        for row in g.itertuples(index=False):
            if pd.notna(row.ninki):
                by_n.setdefault(int(row.ninki), int(row.umaban))
        # position rows
        for row in g.itertuples(index=False):
            if pd.isna(row.chakujun):
                continue
            ch = int(row.chakujun)
            pos.append((int(row.vh_rank) if pd.notna(row.vh_rank) else None,
                        int(row.ab_rank) if pd.notna(row.ab_rank) else None,
                        int(row.ninki) if pd.notna(row.ninki) else None,
                        ch))
        u1 = by_n.get(1)
        if u1 is not None and rk in place:
            py = pay_of(place[rk], (u1,))
            out['place_fav'].append({'day': day, 'race': rk, 'stake': UNIT, 'payout': py,
                                     'hit': int(py > 0), 'tickets': 1})
        vh1 = g[g['vh_rank'] == 1]
        if len(vh1) == 1 and rk in place:
            u = int(vh1.iloc[0]['umaban'])
            py = pay_of(place[rk], (u,))
            out['place_vh1'].append({'day': day, 'race': rk, 'stake': UNIT, 'payout': py,
                                     'hit': int(py > 0), 'tickets': 1})
        ab1 = g[g['ab_rank'] == 1]
        if len(ab1) == 1 and rk in place:
            u = int(ab1.iloc[0]['umaban'])
            py = pay_of(place[rk], (u,))
            out['place_ab1'].append({'day': day, 'race': rk, 'stake': UNIT, 'payout': py,
                                     'hit': int(py > 0), 'tickets': 1})
        u2 = by_n.get(2)
        if u1 and u2 and rk in wide:
            key = tuple(sorted((u1, u2)))
            py = pay_of(wide[rk], key)
            out['wide_12'].append({'day': day, 'race': rk, 'stake': UNIT, 'payout': py,
                                   'hit': int(py > 0), 'tickets': 1})
        vs = g['vscore'].iloc[0]
        u3, u4 = by_n.get(3), by_n.get(4)
        if pd.notna(vs) and float(vs) < 50 and u1 and u2 and u3 and u4 and rk in trio:
            keys = [tuple(sorted((u1, u2, u3))), tuple(sorted((u1, u2, u4)))]
            py = 0.0
            hit = 0
            for key in keys:
                got = pay_of(trio[rk], key)
                if got:
                    py += got
                    hit = 1
            out['trio_d'].append({'day': day, 'race': rk, 'stake': 2 * UNIT, 'payout': py,
                                  'hit': hit, 'tickets': 2})
    return out, pos


def position_summary(rows):
    """vh/ability/ninki rank 1-3 の着順傾向。戦略選択には使わない。"""
    df = pd.DataFrame(rows, columns=['vh', 'ab', 'ninki', 'ch'])
    summary = {}
    for name, col in (('vh_rank', 'vh'), ('ability_rank', 'ab'), ('ninki', 'ninki')):
        part = {}
        for k in (1, 2, 3):
            g = df[df[col] == k]
            if g.empty:
                continue
            part[str(k)] = {
                'n': int(len(g)),
                'p_win': float((g['ch'] == 1).mean()),
                'p_2nd': float((g['ch'] == 2).mean()),
                'p_3rd': float((g['ch'] == 3).mean()),
                'p_top3': float((g['ch'] <= 3).mean()),
            }
        summary[name] = part
    return summary


def main():
    df = load()
    maps = load_maps(['複勝', 'ワイド', '3連複'])
    catalog = {}
    pos_by_year = {}
    for year in YEARS:
        bets, pos = eval_year(df, maps, year)
        pos_by_year[str(year)] = position_summary(pos)
        for name, recs in bets.items():
            met = score_bets(recs)
            catalog.setdefault(name, {})[str(year)] = met
            append_experiment({
                'experiment_id': f'b26_{name}_{year}',
                'phase': 'B26',
                'hypothesis': name,
                'test_period': year,
                'train_period': 'pre-registered, no threshold fit',
                'n': met['n_races'],
                'stake': met['stake'],
                'payout': met['payout'],
                'profit': met['profit'],
                'ROI': met['roi'],
                'hit_rate': met['hit_rate'],
                'max_DD': met['max_dd'],
                'status': 'tested',
                'reason': 'domain ticket, payout PARTIAL except prior win verification',
            })
        print(year, 'done', file=sys.stderr)
    survivors = []
    for name, years in catalog.items():
        rois = [v['roi'] for v in years.values() if v.get('roi') is not None and v['n_races'] >= 200]
        if len(rois) >= 4 and sum(r > 100 for r in rois) >= 4 and min(rois) >= 80:
            survivors.append(name)
    summary = {
        'track': 'DOMAIN_POSITION_TICKET_TRACK',
        'payout_status': '複勝/ワイド/3連複=PARTIAL (positive rows). 単勝=VERIFIED earlier.',
        'not_reproducible': ['cross_n', 'Projected Score', 'C 2-3-6 via LTR×VH cross', 'C248 shadow selection'],
        'strategies': catalog,
        'position_by_year': pos_by_year,
        'survivors': survivors,
        'exit': 'HAS_SURVIVOR' if survivors else 'NO_ADVANCED_HISTORICAL_EDGE_FOUND',
    }
    path = os.path.join(OUT, 'b26_summary.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False)
    ck = os.path.join(ROOT, 'data', 'research', 'checkpoints', 'phase_b26.json')
    with open(ck, 'w', encoding='utf-8') as f:
        json.dump({'exit': summary['exit'], 'survivors': survivors}, f, indent=2)
    print(json.dumps({'exit': summary['exit'], 'survivors': survivors}, ensure_ascii=False))


if __name__ == '__main__':
    main()
