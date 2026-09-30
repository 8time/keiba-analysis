# -*- coding: utf-8 -*-
"""Research-only race dataset: pre-race features + post-race labels (no production use)."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
EXPORT_RACES = os.path.join(ROOT, 'data', 'export', 'races.csv')
EXPORT_HORSES = os.path.join(ROOT, 'data', 'export', 'horse_races.csv')
OUT_DIR = os.path.join(ROOT, 'data', 'research')

# Post-race labels (aligned with scripts/export_features_csv.py)
LONGSHOT_PLACE_NINKI = 7   # arare_prob / arareA
MULTI_LONGSHOT_NINKI_5 = 5  # ana2
MULTI_LONGSHOT_NINKI_7 = 7

POST_RACE_COLS = {
    'favorite_failure', 'top2_failure', 'longshot_place_7', 'longshot_place_6',
    'multi_longshot_5', 'multi_longshot_7', 'honsen', 'arareA', 'arareB', 'ana2',
    'win_payout', 'umaren_payout', 'umatan_payout', 'trio_payout', 'trifecta_payout',
    'payout_class_train_q', 'finish_1_ninki', 'finish_2_ninki', 'finish_3_ninki',
    'fav1_chakujun', 'fav2_chakujun', 'ninki_top3_logsum',
}

PRE_RACE_FEATURE_PREFIXES = (
    'day', 'jyo', 'kyori', 'field_size', 'fav', 'r21', 'r31', 'spread', 'odds_entropy',
    'eff_n', 'syn3', 'live', 'mid515', 'vscore', 'vlabel', 'arare_prob', 'lean',
    'nofav', 'n_front', 'n_hana', 'mean_elim', 'h7_', 'vh2_', 'mkt_ability',
)


def _utf8_streams():
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass


def load_payouts_by_type(bet_type: str) -> dict[str, list[tuple]]:
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=60)
    out: dict[str, list[tuple]] = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=? AND payout>0",
            (bet_type,)):
        out[str(rk)].append((str(combo), int(pay)))
    con.close()
    return out


def _winning_combo_umaban(h: pd.DataFrame, ordered: bool) -> str | None:
    top = h.sort_values('chakujun').head(3)
    if len(top) < 3:
        return None
    nums = [int(x) for x in top['umaban'].tolist()]
    if ordered:
        return ''.join(f'{u:02d}' for u in nums)
    return ''.join(f'{u:02d}' for u in sorted(nums))


def _lookup_payout(pay_map: dict, race_key: str, combo: str | None) -> float | None:
    if not combo:
        return None
    for c, p in pay_map.get(str(race_key), []):
        if c == combo:
            return float(p)
    return None


def load_horses_jv(min_year: int = 2016) -> pd.DataFrame:
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=120)
    df = pd.read_sql(f"""
        SELECT r.race_key, ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori,
               ra.shusso_tosu AS field_size, ra.baba_shiba, ra.baba_dirt, ra.juryo,
               r.umaban, r.ninki, r.win_odds, r.chakujun
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        WHERE ra.surface IN ('芝','ダート') AND ra.jyo <= '10'
          AND CAST(ra.year AS INTEGER) >= {int(min_year)}
          AND r.chakujun > 0 AND r.chakujun <= 28
    """, con)
    con.close()
    df['race_key'] = df['race_key'].astype(str)
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df['field_size'] = pd.to_numeric(df['field_size'], errors='coerce')
    df['kyori'] = pd.to_numeric(df['kyori'], errors='coerce')
    df['day'] = (pd.to_numeric(df['year'], errors='coerce').astype('Int64') * 10000
                 + pd.to_numeric(df['monthday'], errors='coerce'))
    df['is_handi1'] = (df['juryo'].astype(str) == '1').astype(int)
    surf = df['surface'].astype(str)
    df['surface_code'] = np.where(surf.str.contains('ダ'), 1, 0)
    baba = df['baba_dirt'].where(df['surface_code'] == 1, df['baba_shiba'])
    df['baba_code'] = pd.to_numeric(baba, errors='coerce')
    return df


def aggregate_pre_race(d: pd.DataFrame) -> pd.DataFrame:
    """Pre-race odds structure + arare_prob (same as export/scanner)."""
    from core import value_scanner as vs

    d = d.copy()
    d['race_key'] = d['race_key'].astype(str)
    d.loc[d['win_odds'] <= 0, 'win_odds'] = np.nan
    base = d.groupby('race_key', as_index=True).agg(
        day=('day', 'first'), year=('year', 'first'), jyo=('jyo', 'first'),
        kyori=('kyori', 'first'), field_size=('field_size', 'first'),
        surface_code=('surface_code', 'first'), baba_code=('baba_code', 'first'),
        is_handi1=('is_handi1', 'first'), n_run=('umaban', 'count'))

    v = d.dropna(subset=['win_odds']).sort_values(['race_key', 'win_odds'])
    v = v.assign(_rank=v.groupby('race_key').cumcount())
    for n, col in enumerate(('fav1', 'fav2', 'fav3')):
        base[col] = v[v['_rank'] == n].set_index('race_key')['win_odds']
    base['r21'] = base['fav2'] / base['fav1']
    base['r31'] = base['fav3'] / base['fav1']
    base['spread31'] = base['fav3'] - base['fav1']

    inv = v.assign(_p=1.0 / v['win_odds'])
    inv['_pn'] = inv['_p'] / inv.groupby('race_key')['_p'].transform('sum')
    base['odds_entropy'] = (-(inv['_pn'] * np.log(inv['_pn']))
                            .groupby(inv['race_key']).sum())
    base['eff_n'] = np.exp(base['odds_entropy'])
    base['syn3'] = 3.0 / (1.0 / base['fav1'] + 1.0 / base['fav2'] + 1.0 / base['fav3'])

    odds_lists = v.groupby('race_key')['win_odds'].apply(list)
    ap, vsc = [], []
    for rk, row in base.iterrows():
        ol = odds_lists.get(rk, [])
        surf = 'ダ' if row['surface_code'] == 1 else '芝'
        baba = vs.baba_code_to_label(row['baba_code']) if pd.notna(row['baba_code']) else ''
        meta = {'is_handicap': bool(row['is_handi1']), 'condition': baba, 'class': ''}
        prob = vs.arare_prob(ol, meta, int(row['field_size'] or len(ol)))
        ap.append(prob)
        vsc.append(prob * 100 if prob is not None else np.nan)
    base['arare_prob'] = ap
    base['vscore'] = vsc
    return base.reset_index()


def attach_post_labels(races: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    """Post-race labels only (export_features_csv definitions)."""
    out = races.copy()
    t3 = d['chakujun'] <= 3
    d = d.copy()
    d['in_top3'] = t3

    fav1 = d[d['ninki'] == 1].groupby('race_key')['chakujun'].min()
    fav2 = d[d['ninki'] == 2].groupby('race_key')['chakujun'].min()
    out['fav1_chakujun'] = out['race_key'].map(fav1)
    out['fav2_chakujun'] = out['race_key'].map(fav2)
    out['favorite_failure'] = (out['fav1_chakujun'] > 3).astype(float)
    out['top2_failure'] = ((out['fav1_chakujun'] > 3) & (out['fav2_chakujun'] > 3)).astype(float)

    rk = d['race_key']
    out['longshot_place_7'] = out['race_key'].map(
        (t3 & (d['ninki'] >= LONGSHOT_PLACE_NINKI)).groupby(rk).any()).astype(float)
    out['longshot_place_6'] = out['race_key'].map(
        (t3 & (d['ninki'] >= 6)).groupby(rk).any()).astype(float)
    out['multi_longshot_5'] = out['race_key'].map(
        (t3 & (d['ninki'] >= MULTI_LONGSHOT_NINKI_5)).groupby(rk).sum() >= 2).astype(float)
    out['multi_longshot_7'] = out['race_key'].map(
        (t3 & (d['ninki'] >= MULTI_LONGSHOT_NINKI_7)).groupby(rk).sum() >= 2).astype(float)

    out['arareA'] = out['longshot_place_7']
    winner_nk = d[d['chakujun'] == 1].groupby('race_key')['ninki'].min()
    out['arareB'] = (out['race_key'].map(winner_nk) >= 6).astype(float)
    out['ana2'] = out['multi_longshot_5']
    out['honsen'] = out['race_key'].map(
        (t3 & (d['ninki'] <= 2)).groupby(rk).sum() >= 2).astype(float)

    fin = d[d['chakujun'] <= 3].sort_values(['race_key', 'chakujun'])
    for i, col in enumerate(('finish_1_ninki', 'finish_2_ninki', 'finish_3_ninki'), 1):
        out[col] = fin[fin['chakujun'] == i].groupby('race_key')['ninki'].first().reindex(
            out['race_key']).values
    out['ninki_top3_logsum'] = fin.groupby('race_key')['ninki'].apply(
        lambda x: float(np.log(x).sum())).reindex(out['race_key']).values

    top3 = fin.pivot_table(index='race_key', columns='chakujun', values='ninki', aggfunc='first')
    for c in (1, 2, 3):
        if c not in top3.columns:
            top3[c] = np.nan
    nk = top3.reindex(out['race_key'])
    vals = nk[[1, 2, 3]].astype(float)
    out['top2_in_top3'] = (vals <= 2).sum(axis=1).values
    out['top3_in_top3'] = (vals <= 3).sum(axis=1).values
    out['n_in_top3_ge6'] = (vals >= 6).sum(axis=1).values
    out['n_in_top3_ge7'] = (vals >= 7).sum(axis=1).values
    out['n_in_top3_ge10'] = (vals >= 10).sum(axis=1).values
    out['finish_pattern'] = vals.apply(
        lambda r: '-'.join(str(int(x)) for x in r if pd.notna(x)), axis=1).values
    return out


def attach_payouts(races: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    pay_tan = load_payouts_by_type('単勝')
    pay_umaren = load_payouts_by_type('馬連')
    pay_umatan = load_payouts_by_type('馬単')
    pay_trio = load_payouts_by_type('3連複')
    pay_tri = load_payouts_by_type('3連単')

    h_by = {rk: g for rk, g in d.groupby('race_key')}
    win_p, umar, umat, trio, tri = [], [], [], [], []
    for rk in races['race_key']:
        h = h_by.get(rk)
        if h is None:
            win_p.append(np.nan); umar.append(np.nan); umat.append(np.nan)
            trio.append(np.nan); tri.append(np.nan)
            continue
        w = h[h['chakujun'] == 1]
        if len(w):
            wc = f"{int(w.iloc[0]['umaban']):02d}"
            win_p.append(_lookup_payout(pay_tan, rk, wc))
        else:
            win_p.append(np.nan)
        c2 = _winning_combo_umaban(h, ordered=False)
        c3o = _winning_combo_umaban(h, ordered=True)
        c3u = _winning_combo_umaban(h, ordered=False)
        umar.append(_lookup_payout(pay_umaren, rk, c2))
        umat.append(_lookup_payout(pay_umatan, rk, c3o))
        trio.append(_lookup_payout(pay_trio, rk, c3u))
        tri.append(_lookup_payout(pay_tri, rk, c3o))
    out = races.copy()
    out['win_payout'] = win_p
    out['umaren_payout'] = umar
    out['umatan_payout'] = umat
    out['trio_payout'] = trio
    out['trifecta_payout'] = tri
    return out


def payout_class_from_train_quantiles(races: pd.DataFrame, train_end_day: int,
                                      col: str = 'trifecta_payout') -> pd.DataFrame:
    """Quartile labels from train period only (no test leakage)."""
    out = races.copy()
    train = out[out['day'] <= train_end_day]
    valid = train[col].dropna()
    if len(valid) < 100:
        out['payout_class_train_q'] = np.nan
        return out
    qs = valid.quantile([0.25, 0.5, 0.75]).tolist()
    out['payout_class_train_q'] = pd.cut(
        out[col], bins=[-np.inf, qs[0], qs[1], qs[2], np.inf], labels=[1, 2, 3, 4])
    return out


def merge_export_extras(races: pd.DataFrame) -> pd.DataFrame:
    """Optional richer pre-race columns from data/export/races.csv."""
    if not os.path.isfile(EXPORT_RACES):
        return races
    extra = pd.read_csv(EXPORT_RACES, encoding='utf-8')
    extra['race_key'] = extra['race_key'].astype(str)
    races = races.copy()
    races['race_key'] = races['race_key'].astype(str)
    keep = [c for c in extra.columns if c not in races.columns and c != 'race_key']
    if not keep:
        return races
    return races.merge(extra[['race_key'] + keep], on='race_key', how='left')


def build_dataset(min_year: int = 2016, train_end_day: int = 20231231) -> pd.DataFrame:
    d = load_horses_jv(min_year=min_year)
    races = aggregate_pre_race(d)
    races = attach_post_labels(races, d)
    races = attach_payouts(races, d)
    races = payout_class_from_train_quantiles(races, train_end_day)
    races = merge_export_extras(races)
    races['dataset_version'] = 'high_entropy_upset_v1'
    return races


def assert_no_label_leak(feature_cols: list[str]) -> None:
    bad = [c for c in feature_cols if c in POST_RACE_COLS or c.startswith('finish_')]
    if bad:
        raise ValueError(f'post-race columns in features: {bad}')


def save_dataset(df: pd.DataFrame, name: str = 'high_entropy_race_dataset.csv') -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    df.to_csv(path, index=False, encoding='utf-8')
    meta = {
        'rows': len(df),
        'day_min': int(df['day'].min()) if len(df) else None,
        'day_max': int(df['day'].max()) if len(df) else None,
        'columns': list(df.columns),
    }
    with open(path.replace('.csv', '_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return path
