# -*- coding: utf-8 -*-
"""的中率研究用共通モジュール（オフライン専用。ライブから import しない）。"""
import io
import math
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import formation_stats as fs
from core import jockey_jv as jj
from core import value_scanner as vs
from core.bayes_stats import wilson_interval
from core.trio_engine import build_formation, build_trifecta_formation
from scripts import csv_data as cd

TRAIN_END = 20231231
HOLDOUT_FROM = 20240101
UNIT = 100
MIN_HORSES = 8
ROI_FLOOR_DEFAULT = 85.0
BOOT_N = 2000
BOOT_SEED = 42

PLAYBOOK_D = 'd_ninki_trio_2'
PLAYBOOK_C_TRIO = 'c_ltr_trio_236'
PLAYBOOK_C_TRI = 'c_ltr_trifecta_247'


def load_payouts(bet_type):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=? AND payout>0",
            (bet_type,)):
        c = str(combo).strip()
        if len(c) == 6 and c.isdigit():
            t = (int(c[:2]), int(c[2:4]), int(c[4:6]))
            if bet_type == '3連複':
                t = tuple(sorted(t))
            out[str(rk)].append((t, float(pay)))
    con.close()
    return dict(out)


def build_races(zones=('D', 'C')):
    zones = set(zones)
    h = cd.load_horses(cols=[
        'race_key', 'day', 'umaban', 'ninki', 'win_odds', 'chakujun',
        'ability_score', 'vh2_score', 'elim_n',
    ])
    r = cd.load_races(cols=[
        'race_key', 'kigo', 'is_handi1', 'vscore',
        'mean_elim', 'n_elim3', 'odds_entropy', 'field_size',
    ])
    h['race_key'] = h['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        day_val = int(g['day'].iloc[0])
        m = meta.get(rk)
        vscore = float(m.vscore) if m is not None and pd.notna(m.vscore) else None
        odds_list = [float(x) for x in g['win_odds'] if float(x) > 0]
        if vscore is None:
            rv = vs.race_value_score(
                odds_list,
                {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                 'kigo': str(getattr(m, 'kigo', '') or '')},
                n_horses=len(g))
            if not rv:
                continue
            vscore = float(rv['score'])
        zone = fs.zone_code(vscore)
        if zone not in zones:
            continue

        valid = g[g['chakujun'].notna() & (g['chakujun'] > 0)]
        fin = valid.sort_values('chakujun')
        top3 = tuple(fin['umaban'].astype(int).tolist()[:3])
        if len(top3) < 3:
            continue

        ninki_ord = g.sort_values('ninki')['umaban'].astype(int).tolist()
        rank_ord = g.sort_values('ability_score', ascending=True)['umaban'].astype(int).tolist()
        vh_ord = g.sort_values('vh2_score', ascending=False, na_position='last')['umaban'].astype(int).tolist()
        cross_n = len(set(rank_ord[:4]) & set(vh_ord[:4]))
        ninki_map = {int(r.umaban): int(r.ninki) for r in g.itertuples(index=False)}
        elim_map = {}
        for r in g.itertuples(index=False):
            en = getattr(r, 'elim_n', None)
            if en is not None and pd.notna(en):
                elim_map[int(r.umaban)] = int(en)

        period = 'train' if day_val <= TRAIN_END else 'holdout'
        gate = {}
        if m is not None:
            for k in ('mean_elim', 'n_elim3', 'odds_entropy', 'field_size', 'is_handi1'):
                v = getattr(m, k, None)
                gate[k] = float(v) if v is not None and pd.notna(v) else None
        gate['vscore'] = vscore

        out.append(dict(
            rk=rk, day=day_val, year=day_val // 10000, period=period,
            zone=zone, vscore=vscore, cross_n=cross_n,
            ninki_ord=ninki_ord, rank_ord=rank_ord, vh_ord=vh_ord,
            ninki_map=ninki_map, elim_map=elim_map,
            top3=top3, n_horses=len(g), gate=gate,
        ))
    return out


def live_tickets(race, playbook_id):
    """本番と同じ組み方。見送りは (kind, set())。"""
    if playbook_id == PLAYBOOK_D:
        inv = {}
        for u, nk in race['ninki_map'].items():
            if nk not in inv:
                inv[nk] = u
        u1, u2, p3, p4 = inv.get(1), inv.get(2), inv.get(3), inv.get(4)
        if None in (u1, u2, p3, p4) or len({u1, u2, p3, p4}) < 4:
            return '3連複', set()
        tix = {tuple(sorted((u1, u2, p3))), tuple(sorted((u1, u2, p4)))}
        return '3連複', tix

    rank = race['rank_ord']
    if playbook_id == PLAYBOOK_C_TRIO:
        if len(rank) < 6:
            return '3連複', set()
        tix = set(build_formation(rank[:2], rank[:3], rank[:6]))
        return '3連複', tix

    if playbook_id == PLAYBOOK_C_TRI:
        if len(rank) < 7:
            return '3連単', set()
        tix = set(build_trifecta_formation(rank[:2], rank[:4], rank[:7]))
        return '3連単', tix

    return None, set()


def rule_b_playbook(race):
    zone = race['zone']
    if zone == 'D':
        return PLAYBOOK_D
    if zone == 'C':
        if race['cross_n'] >= 3:
            return PLAYBOOK_C_TRIO
        return PLAYBOOK_C_TRI
    return None


def score_race(tickets, kind, top3, payouts_for_race):
    tc = len(tickets)
    cost = tc * UNIT
    hit = 0
    ret = 0.0
    if not tickets:
        return dict(cost=0, ret=0.0, hit=0, tc=0)
    if kind == '3連単':
        won = top3 in tickets
    else:
        won = tuple(sorted(top3)) in tickets
    if won:
        hit = 1
        key = top3 if kind == '3連単' else tuple(sorted(top3))
        for combo, pay in payouts_for_race or []:
            if combo == key:
                ret = pay
                break
    return dict(cost=cost, ret=ret, hit=hit, tc=tc)


def max_losing_streak(hits):
    m = c = 0
    for h in hits:
        c = 0 if h else c + 1
        m = max(m, c)
    return m


def summarise(recs):
    if not recs:
        return dict(
            n=0, hits=0, hit_rate=0.0, roi=0.0, loss_per_100=100.0,
            cost_per_hit=None, avg_pts=0.0, max_losing_streak=0,
            year_roi={}, year_hit={}, recs=[],
        )
    cost = sum(r['cost'] for r in recs)
    ret = sum(r['ret'] for r in recs)
    hits = sum(r['hit'] for r in recs)
    roi = ret / cost * 100 if cost else 0.0
    yr_cost = defaultdict(float)
    yr_ret = defaultdict(float)
    yr_hit = defaultdict(int)
    yr_n = defaultdict(int)
    for r in recs:
        y = r.get('year', r.get('day', 0) // 10000)
        yr_cost[y] += r['cost']
        yr_ret[y] += r['ret']
        yr_hit[y] += r['hit']
        yr_n[y] += 1
    hits_seq = [r['hit'] for r in sorted(recs, key=lambda x: (x.get('day', 0), x.get('rk', '')))]
    return dict(
        n=len(recs), hits=hits,
        hit_rate=hits / len(recs) * 100 if recs else 0.0,
        roi=roi,
        loss_per_100=100.0 - roi,
        cost_per_hit=cost / hits if hits else None,
        avg_pts=sum(r['tc'] for r in recs) / len(recs),
        max_losing_streak=max_losing_streak(hits_seq),
        year_roi={y: yr_ret[y] / yr_cost[y] * 100 if yr_cost[y] else 0 for y in yr_cost},
        year_hit={y: yr_hit[y] / yr_n[y] * 100 if yr_n[y] else 0 for y in yr_n},
        recs=recs,
    )


def block_ci_roi(recs, n_boot=BOOT_N, seed=BOOT_SEED):
    if not recs:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)
    costs = np.array([r['cost'] for r in recs], dtype=np.float64)
    rets = np.array([r['ret'] for r in recs], dtype=np.float64)
    days = np.array([r['day'] for r in recs])
    uniq, inv = np.unique(days, return_inverse=True)
    blocks = [np.where(inv == i)[0] for i in range(len(uniq))]
    rois = []
    for _ in range(n_boot):
        picks = rng.integers(0, len(blocks), size=len(blocks))
        idx = np.concatenate([blocks[p] for p in picks])
        st = costs[idx].sum()
        rois.append(rets[idx].sum() / st * 100 if st else 0.0)
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))


def wilson(k, n):
    lo, hi = wilson_interval(k, n)
    if lo is None:
        return None, None
    return lo * 100, hi * 100


def mcnemar(base_hits, test_hits):
    base_only = test_only = both = 0
    for bh, th in zip(base_hits, test_hits):
        if bh and th:
            both += 1
        elif bh:
            base_only += 1
        elif th:
            test_only += 1
    n_disc = base_only + test_only
    if n_disc:
        z = (test_only - base_only) / math.sqrt(n_disc)
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    else:
        z = 0.0
        p = 1.0
    return dict(b=base_only, c=test_only, both=both, z=z, p=p)


def write_memo(path, title, description, sections):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = '\n\n'.join(sections)
    text = (
        '---\n'
        f'name: {title}\n'
        f'description: {description}\n'
        'metadata:\n'
        '  node_type: memory\n'
        '  type: project\n'
        '---\n\n'
        f'# {title}\n\n'
        f'{body}\n'
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def fmt_row(name, kind, pts, s):
    lo, hi = block_ci_roi(s['recs']) if s['recs'] else (0, 0)
    cph = f"{s['cost_per_hit']:.0f}" if s['cost_per_hit'] else '—'
    yrs = ' '.join(f"{y}:{v:.0f}%" for y, v in sorted(s['year_roi'].items()))
    return (
        f"{name} | {kind} | {pts:.0f} | {s['n']} | {s['hit_rate']:.1f}% | "
        f"{s['roi']:.1f}% | {s['loss_per_100']:.1f} | {cph} | "
        f"{s['max_losing_streak']} | [{lo:.0f}-{hi:.0f}] | {yrs}"
    )


def eval_playbook_races(races, pall_tri, pall_tri_o, playbook_id=None):
    """Rule B または指定 playbook でレース群を採点。"""
    recs = []
    for race in races:
        pb = playbook_id or rule_b_playbook(race)
        if not pb:
            continue
        kind, tix = live_tickets(race, pb)
        if not tix:
            continue
        pall = pall_tri_o if kind == '3連単' else pall_tri
        sc = score_race(tix, kind, race['top3'], pall.get(race['rk']))
        recs.append(dict(
            day=race['day'], year=race['year'], rk=race['rk'],
            cost=sc['cost'], ret=sc['ret'], hit=sc['hit'], tc=sc['tc'],
        ))
    return recs
