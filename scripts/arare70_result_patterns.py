# -*- coding: utf-8 -*-
"""妙味度70以上のレース結果を型に分ける（買い方ROIではなく着順の構成）。

出力: stdout に JSON。holdout=2025-2026、参考=全期間。
"""
from __future__ import annotations
import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib.util
import pandas as pd

_spec = importlib.util.spec_from_file_location(
    'csv_data', os.path.join(ROOT, 'scripts', 'csv_data.py'))
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)

MIN_HORSES = 8
FLAG = sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

JYO = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
       '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}


def zone(v):
    if pd.isna(v):
        return None
    v = float(v)
    if v >= 80:
        return '80+'
    if v >= 70:
        return '70-79'
    if v >= 50:
        return 'C50-69'
    return 'D0-49'


def bucket_ninki(n):
    n = int(n)
    if n <= 2:
        return '1-2番人気'
    if n <= 5:
        return '3-5番人気'
    if n <= 9:
        return '6-9番人気'
    return '10番人気以下'


def result_type(fav1, fav2, n_ana7, n_mid45):
    """互斥の結果型。先に当てはまったものを採用。"""
    both = fav1 and fav2
    if n_ana7 >= 2:
        return '複数穴（穴2頭以上）'
    if both:
        return '両軸残し（人気1・2が3着内）'
    if fav1 and n_ana7 == 1:
        return '本命残し＋穴1頭'
    if fav1:
        return '本命残し・中穴争い'
    if fav2:
        return '本命落下・対抗残し'
    return '上位総崩れ（人気1・2とも外）'


def pct(num, den):
    return round(100.0 * num / den, 1) if den else None


def se_pp(p, n):
    if not n:
        return None
    return round(100.0 * math.sqrt(p * (1 - p) / n), 1)


def summarize(sub_h, races_idx):
    """horse rows for a zone → race-level stats."""
    out_races = []
    for rk, g in sub_h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        t3 = g[g['chakujun'] <= 3]
        if len(t3) < 3:
            continue
        nmap = dict(zip(g['ninki'].astype(int), g['chakujun']))
        # ninki of each finish
        by_chaku = t3.sort_values('chakujun')
        nks = [int(x) for x in by_chaku['ninki'].tolist()[:3]]
        winner_nk = nks[0] if nks else None
        in_t3 = set(int(x) for x in t3['ninki'].tolist())
        fav1 = 1 in in_t3
        fav2 = 2 in in_t3
        n_ana7 = sum(1 for n in in_t3 if n >= 7)
        n_ana6 = sum(1 for n in in_t3 if n >= 6)
        n_mid45 = sum(1 for n in in_t3 if 3 <= n <= 5)
        typ = result_type(fav1, fav2, n_ana7, n_mid45)
        # VH order among ninki>=6
        ana = g[g['ninki'] >= 6].copy()
        vh_rank_of_t3_ana = []
        if len(ana) and ana['vh2_score'].notna().any():
            ana = ana.sort_values('vh2_score', ascending=False)
            ana['_vh'] = range(1, len(ana) + 1)
            hit = ana[ana['chakujun'] <= 3]
            vh_rank_of_t3_ana = hit['_vh'].tolist()
        win_row = g[g['chakujun'] == 1]
        win_pos = None
        if len(win_row) and pd.notna(win_row['avg_pos3'].iloc[0]):
            win_pos = float(win_row['avg_pos3'].iloc[0])
        # ability/LTR rank of winner (ability_score smaller = stronger)
        win_ability_rank = None
        if len(win_row) and win_row['ability_score'].notna().any():
            gg = g.dropna(subset=['ability_score']).sort_values('ability_score', ascending=True)
            um = int(win_row['umaban'].iloc[0])
            rks = gg['umaban'].astype(int).tolist()
            if um in rks:
                win_ability_rank = rks.index(um) + 1
        meta = races_idx.get(rk)
        out_races.append({
            'race_key': rk,
            'typ': typ,
            'fav1': fav1,
            'fav2': fav2,
            'both': fav1 and fav2,
            'neither': (not fav1) and (not fav2),
            'n_ana7': n_ana7,
            'n_ana6': n_ana6,
            'winner_nk': winner_nk,
            'nks': tuple(sorted(nks)),
            'nks_raw': tuple(nks),
            'win_bucket': bucket_ninki(winner_nk) if winner_nk else None,
            'vh1_in_t3': 1 in vh_rank_of_t3_ana,
            'vh2_in_t3': 2 in vh_rank_of_t3_ana,
            'any_vh12': (1 in vh_rank_of_t3_ana) or (2 in vh_rank_of_t3_ana),
            'win_pos': win_pos,
            'win_ability_rank': win_ability_rank,
            'field': int(g['field_size'].iloc[0]) if pd.notna(g['field_size'].iloc[0]) else len(g),
            'jyo': str(g['jyo'].iloc[0]).zfill(2) if pd.notna(g['jyo'].iloc[0]) else '',
            'surf': int(g['surface_code'].iloc[0]) if pd.notna(g['surface_code'].iloc[0]) else None,
            'kyori': int(g['kyori_int'].iloc[0]) if pd.notna(g['kyori_int'].iloc[0]) else None,
            'is_handi': int(meta['is_handi1']) if meta is not None else 0,
            'grade': str(meta['grade']) if meta is not None else '',
            'vscore': float(meta['vscore']) if meta is not None else None,
        })
    return out_races


def agg(rows):
    n = len(rows)
    if not n:
        return {'n': 0}
    types = Counter(r['typ'] for r in rows)
    win_b = Counter(r['win_bucket'] for r in rows if r['win_bucket'])
    fav1_n = sum(r['fav1'] for r in rows)
    fav2_n = sum(r['fav2'] for r in rows)
    both_n = sum(r['both'] for r in rows)
    neither_n = sum(r['neither'] for r in rows)
    ana7_1 = sum(r['n_ana7'] == 1 for r in rows)
    ana7_2 = sum(r['n_ana7'] >= 2 for r in rows)
    ana7_0 = sum(r['n_ana7'] == 0 for r in rows)
    win7 = sum((r['winner_nk'] or 0) >= 7 for r in rows)
    win6 = sum((r['winner_nk'] or 0) >= 6 for r in rows)
    # when there is at least one ana in t3, did vh1/vh2 hit
    with_ana = [r for r in rows if r['n_ana6'] >= 1]
    vh1 = sum(r['vh1_in_t3'] for r in with_ana)
    vh12 = sum(r['any_vh12'] for r in with_ana)
    # winner prior position
    pos = [r['win_pos'] for r in rows if r['win_pos'] is not None]
    front_win = sum(p <= 3.5 for p in pos)
    rear_win = sum(p >= 7 for p in pos)
    # ability rank of winner
    ar = [r['win_ability_rank'] for r in rows if r['win_ability_rank']]
    rank12 = sum(x <= 2 for x in ar)
    rank15 = sum(x <= 5 for x in ar)
    # compact 1-2-x family
    family = Counter()
    for r in rows:
        a, b, c = r['nks']  # sorted ninki of top3
        if a == 1 and b == 2:
            family['人気1・2＋1頭'] += 1
        elif a == 1 and c <= 5:
            family['人気1＋中穴のみ'] += 1
        elif a == 1:
            family['人気1＋穴'] += 1
        elif a == 2:
            family['人気2が最高（本命落ち）'] += 1
        else:
            family['人気3以下が最高'] += 1
    type_rows = []
    order = ['両軸残し（人気1・2が3着内）', '本命残し＋穴1頭', '本命残し・中穴争い',
             '本命落下・対抗残し', '複数穴（穴2頭以上）', '上位総崩れ（人気1・2とも外）']
    for k in order:
        type_rows.append({'type': k, 'n': types[k], 'pct': pct(types[k], n)})
    win_rows = []
    for k in ['1-2番人気', '3-5番人気', '6-9番人気', '10番人気以下']:
        win_rows.append({'bucket': k, 'n': win_b[k], 'pct': pct(win_b[k], n)})
    return {
        'n': n,
        'fav1_in_t3': pct(fav1_n, n),
        'fav2_in_t3': pct(fav2_n, n),
        'both_in_t3': pct(both_n, n),
        'neither_in_t3': pct(neither_n, n),
        'ana7_0': pct(ana7_0, n),
        'ana7_1': pct(ana7_1, n),
        'ana7_2plus': pct(ana7_2, n),
        'winner_ana7': pct(win7, n),
        'winner_ana6': pct(win6, n),
        'vh1_when_ana': pct(vh1, len(with_ana)),
        'vh12_when_ana': pct(vh12, len(with_ana)),
        'n_with_ana6': len(with_ana),
        'front_type_win': pct(front_win, len(pos)) if pos else None,
        'rear_type_win': pct(rear_win, len(pos)) if pos else None,
        'n_pos': len(pos),
        'win_rank_top2': pct(rank12, len(ar)) if ar else None,
        'win_rank_top5': pct(rank15, len(ar)) if ar else None,
        'types': type_rows,
        'winner_buckets': win_rows,
        'family': [{'k': k, 'n': family[k], 'pct': pct(family[k], n)}
                   for k in ['人気1・2＋1頭', '人気1＋中穴のみ', '人気1＋穴',
                             '人気2が最高（本命落ち）', '人気3以下が最高']],
    }


def slice_stats(rows, keyfn, min_n=40):
    bags = defaultdict(list)
    for r in rows:
        bags[keyfn(r)].append(r)
    out = []
    for k, rs in bags.items():
        if k is None or k == '' or len(rs) < min_n:
            continue
        a = agg(rs)
        out.append({
            'slice': k,
            'n': a['n'],
            'both': a['both_in_t3'],
            'neither': a['neither_in_t3'],
            'ana7_2plus': a['ana7_2plus'],
            'winner_ana7': a['winner_ana7'],
            'fav1': a['fav1_in_t3'],
            'vh12': a['vh12_when_ana'],
            'multi_ana_type': next((t['pct'] for t in a['types']
                                    if t['type'].startswith('複数穴')), None),
            'collapse_type': next((t['pct'] for t in a['types']
                                   if t['type'].startswith('上位総崩れ')), None),
            'dual_axis': next((t['pct'] for t in a['types']
                               if t['type'].startswith('両軸')), None),
        })
    out.sort(key=lambda x: -x['n'])
    return out


def main():
    races = cd.load_races(cols=['race_key', 'day', 'jyo', 'surface_code', 'kyori',
                                'field_size', 'is_handi1', 'grade', 'vscore', 'vlabel',
                                'arareA', 'arareB', 'ana2', 'honsen',
                                'fav1', 'spread31', 'n_front'])
    races['race_key'] = races['race_key'].astype(str)
    horses = cd.load_horses(cols=['race_key', 'day', 'jyo', 'surface_code', 'kyori_int',
                                  'field_size', 'umaban', 'ninki', 'win_odds',
                                  'avg_pos3', 'ability_score', 'vh2_score',
                                  'chakujun', 'top3', 'win'])
    horses['race_key'] = horses['race_key'].astype(str)
    horses['year'] = (pd.to_numeric(horses['day'], errors='coerce') // 10000).astype('Int64')

    ridx = {str(row['race_key']): row for row in races.to_dict('records')}
    horses = horses.merge(races[['race_key', 'vscore']], on='race_key', how='left')
    horses['zone'] = horses['vscore'].map(zone)

    # holdout 2025-2026 vs all
    def filt_year(df, holdout):
        if holdout:
            return df[df['year'] >= 2025]
        return df[df['year'] >= 2016]

    payload = {'source': 'data/export horse_races.csv + races.csv',
               'holdout': '2025-2026', 'all': '2016-2026', 'min_horses': MIN_HORSES}

    for tag, holdout in [('holdout', True), ('all', False)]:
        h = filt_year(horses, holdout)
        zones = {}
        for zname in ['D0-49', 'C50-69', '70-79', '80+', '70+']:
            if zname == '70+':
                sub = h[h['vscore'] >= 70]
            else:
                sub = h[h['zone'] == zname]
            rows = summarize(sub, ridx)
            zones[zname] = agg(rows)
            if zname == '70+' and tag == 'holdout':
                payload['holdout_70_slices'] = {
                    'handi': slice_stats(rows, lambda r: 'ハンデ' if r['is_handi'] else '定量'),
                    'surf': slice_stats(rows, lambda r: 'ダート' if r['surf'] == 1 else '芝'),
                    'dist': slice_stats(rows, lambda r: (
                        '芝短≤1400' if r['surf'] != 1 and r['kyori'] and r['kyori'] <= 1400 else
                        '芝中1401-1899' if r['surf'] != 1 and r['kyori'] and r['kyori'] < 1900 else
                        '芝長≥1900' if r['surf'] != 1 else
                        'ダ短≤1400' if r['kyori'] and r['kyori'] <= 1400 else
                        'ダ中1401-1899' if r['kyori'] and r['kyori'] < 1900 else
                        'ダ長≥1900')),
                    'field': slice_stats(rows, lambda r: (
                        '少頭数≤11' if r['field'] <= 11 else
                        '中頭数12-14' if r['field'] <= 14 else '多頭数15+')),
                    'jyo': slice_stats(rows, lambda r: JYO.get(r['jyo'], r['jyo']), min_n=30),
                    'grade': slice_stats(rows, lambda r: (
                        '重賞' if str(r['grade']) in ('A', 'B', 'C', 'F', 'G') else
                        'OP/L' if str(r['grade']) in ('D', 'L', 'H') else '条件戦'), min_n=25),
                }
                # stability: 70 vs 80 split types
                payload['holdout_70_rows_n'] = len(rows)
                payload['holdout_70_types_7079'] = agg([r for r in rows if r['vscore'] and r['vscore'] < 80])
                payload['holdout_70_types_80'] = agg([r for r in rows if r['vscore'] and r['vscore'] >= 80])
        payload[tag] = zones

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
