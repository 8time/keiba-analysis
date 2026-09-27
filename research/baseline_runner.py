# -*- coding: utf-8 -*-
"""Phase B 研究 Baseline: 本番 core を import して過去 CSV 上で再現。"""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict

import pandas as pd

from core import formation_stats as fs
from core import jockey_jv as jj
from core import playbook_tickets as pb
from core import value_scanner as vs
from research import csv_ltr
from research import elim_cache
from research import offline_elim
from research import splits
from research.metrics import UNIT_STAKE, aggregate_race_records, group_aggregate

MIN_HORSES = 8
BASELINE_ZONES = ('D', 'C')

_HORSE_USECOLS = [
    'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'chakujun',
    'ketto_num', 'sex_code', 'age', 'futan', 'bataiju', 'zogen',
    'h7_fig', 'spurt_mean3', 'prior_top3_rate', 'avg_chaku5',
    'trainer_jyo_t3', 'jockey_jyo_win', 'jockey_dist_win', 'vh2_score',
    'surface_code', 'kyori_int', 'field_size', 'is_handi1',
]

_RACE_USECOLS = [
    'race_key', 'day', 'jyo', 'surface_code', 'kyori', 'field_size',
    'is_handi1', 'vscore', 'baba_code', 'cushion', 'dirt_moisture', 'race_num',
]


def parity_status() -> dict:
    """LTR / Projected / elim の再現可否（実装根拠付き）。"""
    ltr = csv_ltr.ltr_available()
    proj = {
        'status': 'C',
        'reason': 'CSV/export に Projected Score 列なし。calculator 全量バッチ未実装。',
        'impact': 'cross_n は proj 無し時 build_tickets と同様 unavailable→0（C券種は安全側RRR寄り）',
    }
    elim = {
        'status': 'A_partial',
        'reason': 'elim_engine を JV 馬名+CSV オッズで実行。score_cache proj 無し。学習残しOFF。',
        'available': offline_elim.elim_engine_available(),
    }
    overall = 'PARTIAL'
    if ltr and elim['available'] and proj['status'] == 'C':
        overall = 'PARTIAL'
    elif not ltr:
        overall = 'NOT_REPRODUCIBLE'
    return {
        'overall': overall,
        'ltr': {'status': 'A' if ltr else 'C', 'detail': 'ltr_model.lgb + CSV features'},
        'projected_score': proj,
        'elim_keep': elim,
        'vh': {'status': 'B', 'detail': 'vh2_score in CSV'},
        'ability_score_not_used': True,
    }


def _load_payouts():
    out_trio = defaultdict(list)
    out_tri = defaultdict(list)
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    for rk, combo, pay, bt in con.execute(
            "SELECT race_key, combo, payout, bet_type FROM payouts WHERE payout>0 "
            "AND bet_type IN ('3連複','3連単')"):
        c = str(combo).strip()
        if len(c) != 6 or not c.isdigit():
            continue
        t = (int(c[:2]), int(c[2:4]), int(c[4:6]))
        if bt == '3連複':
            t = tuple(sorted(t))
            out_trio[str(rk)].append((t, float(pay)))
        else:
            out_tri[str(rk)].append((t, float(pay)))
    con.close()
    return dict(out_trio), dict(out_tri)


def _tickets_from_rec(rec) -> tuple[str | None, set]:
    if rec.get('skip') or rec.get('selected_playbook') == 'ba_skip':
        return None, set()
    if rec.get('trifecta'):
        tix = {tuple(x['combo']) for x in rec['trifecta']}
        return '3連単', tix
    if rec.get('trio'):
        tix = {tuple(x['combo']) for x in rec['trio']}
        return '3連複', tix
    return None, set()


def _score_race(kind, tickets, top3, payouts):
    tc = len(tickets)
    cost = tc * UNIT_STAKE
    if not tickets or not kind:
        return dict(cost=0, ret=0.0, hit=0, tc=0)
    if kind == '3連単':
        won = top3 in tickets
        key = top3
    else:
        sk = tuple(sorted(top3))
        won = sk in tickets
        key = sk
    ret = 0.0
    if won:
        for combo, pay in payouts or []:
            if combo == key:
                ret = pay
                break
    return dict(cost=cost, ret=ret, hit=int(won), tc=tc)


def _baba_label(code):
    return vs.baba_code_to_label(code) if code is not None else '良'


def _filter_elim(horses, keep: set[int] | None, min_size=3):
    if not keep:
        return horses, False
    filt = [h for h in horses if int(h['umaban']) in keep]
    if len(filt) >= min_size:
        return filt, True
    return horses, False


def run_baseline(
    splits_to_run=('train', 'validation'),
    apply_elim=True,
    max_races: int | None = None,
):
    """CSV 全期間から Baseline レース記録を生成。"""
    from scripts import csv_data as cd
    if not cd.available():
        raise FileNotFoundError('export CSV missing')

    horses = pd.read_csv(cd.HORSE_CSV, usecols=_HORSE_USECOLS)
    races = pd.read_csv(cd.RACE_CSV, usecols=_RACE_USECOLS)
    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)
    race_meta = {}
    for row in races.itertuples(index=False):
        d = row._asdict() if hasattr(row, '_asdict') else dict(zip(races.columns, row))
        race_meta[str(d['race_key'])] = d

    pay_trio, pay_tri = _load_payouts()
    elim_map = elim_cache.load_cache() if apply_elim else {}
    recs = []
    n_proc = 0

    for rk, g in horses.groupby('race_key', sort=False):
        if max_races is not None and n_proc >= max_races:
            break
        n_proc += 1
        if len(g) < MIN_HORSES:
            continue
        m = race_meta.get(rk)
        if m is None:
            continue
        day = int(g['day'].iloc[0])
        sp = splits.split_for_day(day)
        if sp not in splits_to_run:
            continue

        vscore = float(m['vscore']) if pd.notna(m.get('vscore')) else None
        if vscore is None:
            continue
        zone = fs.zone_code(vscore)
        if zone not in BASELINE_ZONES:
            continue

        valid = g[g['chakujun'].notna() & (g['chakujun'] > 0)]
        fin = valid.sort_values('chakujun')
        top3 = tuple(fin['umaban'].astype(int).tolist()[:3])
        if len(top3) < 3:
            continue

        horse_rows = []
        vh_scores = {}
        for r in g.itertuples(index=False):
            um = int(r.umaban)
            horse_rows.append({
                'umaban': um,
                'name': f'U{um}',
                'pop': int(r.ninki) if pd.notna(r.ninki) else None,
                'ninki': int(r.ninki) if pd.notna(r.ninki) else None,
                'win_odds': float(r.win_odds),
                'sex_code': r.sex_code,
                'age': r.age,
                'futan': r.futan,
                'bataiju': r.bataiju,
                'zogen': r.zogen,
                'h7_fig': r.h7_fig,
                'spurt_mean3': r.spurt_mean3,
                'prior_top3_rate': r.prior_top3_rate,
                'avg_chaku5': r.avg_chaku5,
                'trainer_jyo_t3': r.trainer_jyo_t3,
                'jockey_jyo_win': r.jockey_jyo_win,
                'jockey_dist_win': r.jockey_dist_win,
            })
            if pd.notna(r.vh2_score):
                vh_scores[um] = float(r.vh2_score)

        meta = {
            'day': day,
            'jyo': int(m['jyo']) if pd.notna(m.get('jyo')) else 0,
            'surface_code': int(m['surface_code']) if pd.notna(m.get('surface_code')) else 0,
            'kyori_int': int(m['kyori']) if pd.notna(m.get('kyori')) else 0,
            'field_size': int(m['field_size']) if pd.notna(m.get('field_size')) else len(g),
            'is_handi1': int(m['is_handi1']) if pd.notna(m.get('is_handi1')) else 0,
            'baba_code': m.get('baba_code'),
            'baba_label': _baba_label(m.get('baba_code')),
            'cushion': m.get('cushion'),
            'dirt_moisture': m.get('dirt_moisture'),
            'race_num': int(m['race_num']) if pd.notna(m.get('race_num')) else 0,
        }

        ltr_scores = csv_ltr.predict_race_frame(g, meta)
        proj_scores = None  # Phase B v1: 未エクスポート（C）

        horses_pb = [
            {'umaban': h['umaban'], 'name': h['name'], 'pop': h['pop']}
            for h in horse_rows
        ]
        elim_used = False
        if apply_elim and offline_elim.elim_engine_available():
            keep = elim_map.get(rk)
            if keep is None:
                keep = offline_elim.compute_elim_keep(
                    rk, horse_rows, meta, proj_scores=proj_scores)
                if keep is not None:
                    elim_cache.append_race(rk, keep)
                    elim_map[rk] = keep
            horses_pb, elim_used = _filter_elim(horses_pb, keep)

        rec_pb = pb.build_tickets(
            rk, vscore, horses_pb,
            ltr_scores=ltr_scores,
            vh_scores=vh_scores,
            proj_scores=proj_scores,
        )
        kind, tix = _tickets_from_rec(rec_pb)
        pays = pay_tri.get(rk) if kind == '3連単' else pay_trio.get(rk)
        sc = _score_race(kind, tix, top3, pays)

        ky = meta['kyori_int']
        if ky <= 1400:
            dist_band = '<=1400'
        elif ky <= 1800:
            dist_band = '1401-1800'
        elif ky <= 2200:
            dist_band = '1801-2200'
        else:
            dist_band = '2201+'
        surf_l = 'ダ' if meta['surface_code'] == 1 else '芝'

        recs.append({
            'rk': rk,
            'day': day,
            'year': day // 10000,
            'split': sp,
            'zone': zone,
            'vscore': vscore,
            'cross_n': rec_pb.get('cross_n'),
            'cross_n_source': rec_pb.get('cross_n_source'),
            'bet_type': rec_pb.get('selected_bet_type'),
            'playbook_id': rec_pb.get('selected_playbook'),
            'skip': rec_pb.get('skip'),
            'skip_reason': rec_pb.get('skip_reason'),
            'elim_used': elim_used,
            'jyo': meta['jyo'],
            'surface': surf_l,
            'dist_band': dist_band,
            'field_size': meta['field_size'],
            **sc,
        })

    return recs


def summarize_baseline(recs: list[dict]) -> dict:
    by_split = {}
    for sp in ('train', 'validation', 'holdout'):
        sub = [r for r in recs if r['split'] == sp]
        by_split[sp] = {
            'all': aggregate_race_records(sub),
            'by_year': group_aggregate(sub, lambda r: r['year']),
            'by_zone': group_aggregate(sub, lambda r: r['zone']),
            'by_bet_type': group_aggregate(
                [r for r in sub if r.get('tc', 0) > 0],
                lambda r: r.get('bet_type') or 'skip'),
            'by_playbook': group_aggregate(
                [r for r in sub if r.get('tc', 0) > 0],
                lambda r: r.get('playbook_id') or 'skip'),
            'by_jyo': group_aggregate(sub, lambda r: r['jyo']),
            'by_surface': group_aggregate(sub, lambda r: r['surface']),
            'by_dist_band': group_aggregate(sub, lambda r: r['dist_band']),
            'by_field_size': group_aggregate(
                sub, lambda r: '8-12' if r['field_size'] <= 12 else '13-16' if r['field_size'] <= 16 else '17+'),
        }
    return by_split
