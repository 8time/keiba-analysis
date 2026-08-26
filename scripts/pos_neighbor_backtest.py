# -*- coding: utf-8 -*-
"""位置関係シグナルの仮説検証（予装ロジック追加なし）。

対象1: 勝ち馬の隣・周辺に穴馬が来るか（事後現象。勝ち馬は事前に未知）
対象2: 1番人気の反対側に穴馬が来るか（事前に既知）

比較:
  - 同一人気帯の全馬ベースライン
  - 非勝ち馬に限ったベースライン（対象1の公平比較）
  - ランダム馬の隣（位置そのものの効果）
  - 1番人気の隣（事前に既知のアンカー）

Usage: python scripts/pos_neighbor_backtest.py
"""
import os
import sys
import json
import math
import sqlite3
import time

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts import csv_data as cd
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
OUT = os.path.join(ROOT, 'data', 'pos_neighbor_backtest.json')
UNIT = 100.0

POP_BANDS = [('6-18', 6, 18), ('8-18', 8, 18), ('10-18', 10, 18)]
ZONES = [('ALL', None, None), ('D', 0.0, 50.0), ('C', 50.0, 70.0), ('BA', 70.0, 201.0)]
# 確認用はプロジェクト慣例の holdout（2025）+ 2026
ERAS = [
    ('2016-2023 発見前', lambda d: d < 20240000),
    ('2024-2026 確認期', lambda d: d >= 20240000),
    ('2025-2026 holdout', lambda d: d >= 20250101),
    ('全期間', lambda d: True),
]
# 事前に宣言する主検定（確認期・6-18・全ゾーン）。多重比較 Bonferroni N=8
PRIMARY = [
    'win_uma_pm1', 'win_uma_pm2', 'win_same_waku', 'win_adj_waku',
    'fav_mirror_uma', 'fav_opp_waku', 'fav_dist_ge6', 'rand_uma_pm1',
]


def wilson(k, n, z=1.96):
    if n <= 0:
        return None, None
    p = k / n
    z2 = z * z
    den = 1.0 + z2 / n
    mid = (p + z2 / (2.0 * n)) / den
    half = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def z_to_p(z):
    if z is None or not math.isfinite(z):
        return None
    return math.erfc(abs(z) / math.sqrt(2.0))


def two_prop_z(k1, n1, p0):
    """シグナル率 vs 既知ベースライン p0（大標本）。"""
    if n1 <= 0 or p0 is None or p0 <= 0 or p0 >= 1:
        return None, None
    p1 = k1 / n1
    se = math.sqrt(p0 * (1.0 - p0) / n1)
    if se <= 0:
        return None, None
    z = (p1 - p0) / se
    return z, z_to_p(z)


def load_fuku():
    con = sqlite3.connect('file:%s?mode=ro' % DB, uri=True, timeout=30)
    out = {}
    for rk, cb, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts "
            "WHERE bet_type='複勝' AND race_key>='2016'"):
        c = str(cb)
        if c.isdigit() and pay:
            out[(str(rk), int(c))] = float(pay)
    con.close()
    return out


def prep():
    print('読込中...', file=sys.stderr)
    h = cd.load_horses(cols=[
        'race_key', 'day', 'umaban', 'waku_n', 'ninki', 'chakujun', 'top3', 'win',
        'win_odds', 'vh2_score', 'field_size'], with_period=True)
    r = cd.load_races(cols=['race_key', 'day', 'vscore', 'field_size'], with_period=True)
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    h = h.merge(r[['race_key', 'vscore']], on='race_key', how='left')
    h['umaban'] = pd.to_numeric(h['umaban'], errors='coerce')
    h['waku_n'] = pd.to_numeric(h['waku_n'], errors='coerce')
    h['ninki'] = pd.to_numeric(h['ninki'], errors='coerce')
    h['chakujun'] = pd.to_numeric(h['chakujun'], errors='coerce')
    h['vscore'] = pd.to_numeric(h['vscore'], errors='coerce')
    h['vh2_score'] = pd.to_numeric(h['vh2_score'], errors='coerce')
    h = h[h['umaban'].notna() & h['ninki'].notna() & (h['chakujun'] > 0)]
    nrun = h.groupby('race_key')['umaban'].transform('count')
    nmax = h.groupby('race_key')['umaban'].transform('max')
    h['n_run'] = nrun
    h['n_decl'] = pd.to_numeric(h['field_size'], errors='coerce').fillna(nmax)
    h = h[h['n_run'] >= 8]
    # winner / fav anchors
    win = (h.loc[h['chakujun'] == 1, ['race_key', 'umaban', 'waku_n']]
             .drop_duplicates('race_key')
             .rename(columns={'umaban': 'win_u', 'waku_n': 'win_w'}))
    fav = (h.loc[h['ninki'] == 1, ['race_key', 'umaban', 'waku_n']]
             .drop_duplicates('race_key')
             .rename(columns={'umaban': 'fav_u', 'waku_n': 'fav_w'}))
    # ランダムアンカー: race_key 末尾から決めた出走順インデックス（結果非依存）
    h['_rk'] = h.groupby('race_key').cumcount()
    nrun2 = h.groupby('race_key')['_rk'].transform('max') + 1
    seed = pd.to_numeric(h['race_key'].str[-6:], errors='coerce').fillna(0).astype(int)
    pick = (seed % nrun2.clip(lower=1)).astype(int)
    anc = (h.loc[h['_rk'] == pick, ['race_key', 'umaban', 'waku_n']]
             .drop_duplicates('race_key')
             .rename(columns={'umaban': 'rnd_u', 'waku_n': 'rnd_w'}))
    h = h.merge(win, on='race_key', how='inner')
    h = h.merge(fav, on='race_key', how='inner')
    h = h.merge(anc, on='race_key', how='left')
    h['d_win'] = (h['umaban'] - h['win_u']).abs()
    h['d_fav'] = (h['umaban'] - h['fav_u']).abs()
    h['d_rnd'] = (h['umaban'] - h['rnd_u']).abs()
    h['is_win'] = h['umaban'] == h['win_u']
    h['is_fav'] = h['umaban'] == h['fav_u']
    h['mirror_u'] = (h['n_decl'] + 1 - h['fav_u']).round()
    h['opp_w'] = 9 - h['fav_w']
    h['win2'] = (h['chakujun'] == 2).astype(int)
    h['win3'] = (h['chakujun'] == 3).astype(int)
    h['top3'] = (h['chakujun'] <= 3).astype(int)
    # VH: 人気6-以下のうちレース内 vh2 上位2
    sub = h[h['ninki'] >= 6].copy()
    sub['vh_rk'] = sub.groupby('race_key')['vh2_score'].rank(ascending=False, method='first')
    vh_idx = sub.loc[sub['vh_rk'] <= 2, ['race_key', 'umaban']].assign(vh2top=1)
    h = h.merge(vh_idx, on=['race_key', 'umaban'], how='left')
    h['vh2top'] = h['vh2top'].fillna(0).astype(int)
    print(f'馬行 {len(h):,}  レース {h.race_key.nunique():,}', file=sys.stderr)
    return h.drop(columns=['_rk'], errors='ignore')


def zone_mask(df, lo, hi):
    if lo is None:
        return pd.Series(True, index=df.index)
    v = df['vscore']
    return v.notna() & (v >= lo) & (v < hi)


def era_mask(df, fn):
    return df['day'].map(fn)


def pop_mask(df, lo, hi):
    return (df['ninki'] >= lo) & (df['ninki'] <= hi)


def flags(df):
    """各シグナル。アンカー自身は必ず除外。"""
    nw = ~df['is_win']
    nf = ~df['is_fav']
    nr = df['umaban'] != df['rnd_u']
    return {
        'win_uma_pm1': nw & (df['d_win'] == 1),
        'win_uma_pm2': nw & (df['d_win'].between(1, 2)),
        'win_same_waku': nw & (df['waku_n'] == df['win_w']) & df['waku_n'].notna(),
        'win_adj_waku': nw & ((df['waku_n'] - df['win_w']).abs() == 1),
        'fav_mirror_uma': nf & (df['umaban'] == df['mirror_u']),
        'fav_opp_waku': nf & (df['waku_n'] == df['opp_w']) & df['waku_n'].notna(),
        'fav_uma_pm1': nf & (df['d_fav'] == 1),
        'rand_uma_pm1': nr & (df['d_rnd'] == 1),
        'fav_dist_1': nf & (df['d_fav'] == 1),
        'fav_dist_2': nf & (df['d_fav'] == 2),
        'fav_dist_3': nf & (df['d_fav'] == 3),
        'fav_dist_4': nf & (df['d_fav'] == 4),
        'fav_dist_5': nf & (df['d_fav'] == 5),
        'fav_dist_6': nf & (df['d_fav'] == 6),
        'fav_dist_7': nf & (df['d_fav'] == 7),
        'fav_dist_8': nf & (df['d_fav'] == 8),
        'fav_dist_ge6': nf & (df['d_fav'] >= 6),
        'fav_dist_ge8': nf & (df['d_fav'] >= 8),
    }


LABEL = {
    'win_uma_pm1': '勝ち馬 馬番±1',
    'win_uma_pm2': '勝ち馬 馬番±2',
    'win_same_waku': '勝ち馬 同枠',
    'win_adj_waku': '勝ち馬 隣枠',
    'fav_mirror_uma': '1番人気 馬番対称',
    'fav_opp_waku': '1番人気 対向枠',
    'fav_uma_pm1': '1番人気 馬番±1（対照）',
    'rand_uma_pm1': 'ランダム馬 馬番±1（対照）',
    'fav_dist_1': '1番人気から距離1',
    'fav_dist_2': '1番人気から距離2',
    'fav_dist_3': '1番人気から距離3',
    'fav_dist_4': '1番人気から距離4',
    'fav_dist_5': '1番人気から距離5',
    'fav_dist_6': '1番人気から距離6',
    'fav_dist_7': '1番人気から距離7',
    'fav_dist_8': '1番人気から距離8',
    'fav_dist_ge6': '1番人気から距離≥6',
    'fav_dist_ge8': '1番人気から距離≥8',
}


def score(sub, fuku, base, baseline_excl_win=False):
    n = int(len(sub))
    if n < 30:
        return None
    k3 = int(sub['top3'].sum())
    k1 = int((sub['chakujun'] == 1).sum())
    k2 = int(sub['win2'].sum())
    k3rd = int(sub['win3'].sum())
    rate = k3 / n
    lo, hi = wilson(k3, n)
    p0 = base['top3']
    z, pval = two_prop_z(k3, n, p0)
    keys = list(zip(sub['race_key'].astype(str), sub['umaban'].astype(int)))
    paid = 0.0
    for k, t3 in zip(keys, sub['top3'].to_numpy()):
        if t3:
            paid += fuku.get(k, 0.0)
    staked = UNIT * n
    roi = (paid / staked * 100.0) if staked else None
    return {
        'n': n,
        'top3': round(rate * 100, 2),
        'base_top3': round(p0 * 100, 2),
        'pp': round((rate - p0) * 100, 2),
        'rel_pct': round(((rate / p0) - 1.0) * 100, 1) if p0 else None,
        'win1': round(k1 / n * 100, 2),
        'win2': round(k2 / n * 100, 2),
        'win3': round(k3rd / n * 100, 2),
        'base_win1': round(base['win1'] * 100, 2),
        'base_win2': round(base['win2'] * 100, 2),
        'base_win3': round(base['win3'] * 100, 2),
        'roi': None if roi is None else round(roi, 1),
        'base_roi': None if base.get('roi') is None else round(base['roi'], 1),
        'ci95_lo': None if lo is None else round(lo * 100, 2),
        'ci95_hi': None if hi is None else round(hi * 100, 2),
        'z': None if z is None else round(z, 2),
        'p': None if pval is None else round(pval, 4),
        'sig05': bool(pval is not None and pval < 0.05 and (rate - p0) > 0),
        'sig_bonf': bool(pval is not None and pval < 0.05 / len(PRIMARY) and (rate - p0) > 0),
    }


def baseline_of(pool, fuku):
    n = len(pool)
    if n < 30:
        return None
    keys = list(zip(pool['race_key'].astype(str), pool['umaban'].astype(int)))
    paid = 0.0
    for k, t3 in zip(keys, pool['top3'].to_numpy()):
        if t3:
            paid += fuku.get(k, 0.0)
    staked = UNIT * n
    return {
        'n': n,
        'top3': float(pool['top3'].mean()),
        'win1': float((pool['chakujun'] == 1).mean()),
        'win2': float(pool['win2'].mean()),
        'win3': float(pool['win3'].mean()),
        'roi': (paid / staked * 100.0) if staked else None,
    }


def run(df, fuku):
    fl = flags(df)
    rows = []
    vh_rows = []
    for era_name, era_fn in ERAS:
        e = era_mask(df, era_fn)
        for zname, zlo, zhi in ZONES:
            z = zone_mask(df, zlo, zhi)
            for bname, plo, phi in POP_BANDS:
                pop = pop_mask(df, plo, phi)
                pool = df[e & z & pop]
                base = baseline_of(pool, fuku)
                if not base:
                    continue
                pool_nw = pool[~pool['is_win']]
                base_nw = baseline_of(pool_nw, fuku)
                for key, m in fl.items():
                    sub = df[e & z & pop & m]
                    use_base = base_nw if key.startswith('win_') else base
                    s = score(sub, fuku, use_base)
                    if not s:
                        continue
                    rec = {
                        'era': era_name, 'zone': zname, 'pop': bname,
                        'signal': key, 'label': LABEL[key],
                        'baseline_kind': 'non_winner_same_band' if key.startswith('win_') else 'all_same_band',
                        **s,
                    }
                    rows.append(rec)
                # VH交差（確認期・全ゾーン・6-18 のみ）
                if era_name == '2024-2026 確認期' and zname == 'ALL' and bname == '6-18':
                    vh = df[e & z & pop & (df['vh2top'] == 1)]
                    bvh = baseline_of(vh, fuku)
                    if bvh:
                        for key in ('win_uma_pm1', 'fav_mirror_uma', 'fav_opp_waku',
                                    'fav_dist_ge6', 'rand_uma_pm1'):
                            sub = df[e & z & pop & (df['vh2top'] == 1) & fl[key]]
                            s = score(sub, fuku, bvh)
                            if s:
                                vh_rows.append({
                                    'signal': key, 'label': LABEL[key] + ' ∩ VH上位2',
                                    'vh_only_top3': round(bvh['top3'] * 100, 2),
                                    'vh_only_n': bvh['n'],
                                    **s,
                                })
    return rows, vh_rows


def fmt_row(r):
    sig = ''
    if r.get('sig_bonf'):
        sig = '**'
    elif r.get('sig05'):
        sig = '*'
    p = r.get('p')
    ptxt = 'NA' if p is None else f'{p:.4f}'
    roi = r.get('roi')
    return (f"{r['era'][:12]:12s} {r['zone']:4s} {r['pop']:5s} {r['label']:22s} "
            f"n={r['n']:7d}  3着内 {r['top3']:5.2f}%  基 {r['base_top3']:5.2f}%  "
            f"{r['pp']:+6.2f}pp  rel{r['rel_pct']:+6.1f}%  "
            f"1着{r['win1']:5.2f} 2着{r['win2']:5.2f} 3着{r['win3']:5.2f}  "
            f"複回収{roi:6.1f}%  CI[{r['ci95_lo']:5.2f},{r['ci95_hi']:5.2f}]  "
            f"p={ptxt} {sig}")


def pick_best(rows, keys, era='2024-2026 確認期'):
    cand = [r for r in rows if r['era'] == era and r['signal'] in keys]
    if not cand:
        cand = [r for r in rows if r['signal'] in keys]
    cand = [r for r in cand if r.get('n', 0) >= 200]
    if not cand:
        return None
    return max(cand, key=lambda r: (r['pp'], r['n']))


def main():
    t0 = time.time()
    df = prep()
    print('複勝配当読込...', file=sys.stderr)
    fuku = load_fuku()
    print(f'複勝 {len(fuku):,}', file=sys.stderr)
    rows, vh = run(df, fuku)

    print('\n■ 主結果 確認期 2024-2026 / 6-18人気 / 全ゾーン')
    print(f"{'era':12s} {'zone':4s} {'pop':5s} {'signal':22s}")
    main_keys = ['win_uma_pm1', 'win_uma_pm2', 'win_same_waku', 'win_adj_waku',
                 'fav_mirror_uma', 'fav_opp_waku', 'fav_uma_pm1', 'rand_uma_pm1',
                 'fav_dist_ge6']
    for r in rows:
        if r['era'] == '2024-2026 確認期' and r['pop'] == '6-18' and r['zone'] == 'ALL' and r['signal'] in main_keys:
            print(fmt_row(r))

    print('\n■ 対象1 ゾーン別（確認期・6-18・勝ち馬±1と同枠）')
    for r in rows:
        if r['era'] == '2024-2026 確認期' and r['pop'] == '6-18' and r['signal'] in ('win_uma_pm1', 'win_same_waku', 'win_adj_waku'):
            print(fmt_row(r))

    print('\n■ 対象2 距離カーブ（確認期・6-18・全ゾーン）')
    for r in rows:
        if r['era'] == '2024-2026 確認期' and r['pop'] == '6-18' and r['zone'] == 'ALL' and r['signal'].startswith('fav_dist_'):
            print(fmt_row(r))

    print('\n■ 発見前 vs 確認期（6-18・全ゾーン・主シグナル）')
    for era in ('2016-2023 発見前', '2024-2026 確認期', '2025-2026 holdout'):
        for r in rows:
            if r['era'] == era and r['pop'] == '6-18' and r['zone'] == 'ALL' and r['signal'] in PRIMARY:
                print(fmt_row(r))

    print('\n■ VH上位2 ∩ 位置（確認期・6-18・全ゾーン）')
    for r in vh:
        print(f"  {r['label']:28s} n={r['n']:5d} 3着内{r['top3']:5.2f}%  VH単体基{r['vh_only_top3']:5.2f}%  "
              f"{r['pp']:+5.2f}pp  複回収{r['roi']}%  p={r['p']}")

    # 結論材料
    b1 = pick_best(rows, ['win_uma_pm1', 'win_uma_pm2', 'win_same_waku', 'win_adj_waku'])
    b2 = pick_best(rows, ['fav_mirror_uma', 'fav_opp_waku', 'fav_dist_ge6', 'fav_dist_ge8']
                   + [f'fav_dist_{i}' for i in range(1, 9)])

    out = {
        'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        'n_horses': int(len(df)),
        'n_races': int(df['race_key'].nunique()),
        'notes': [
            '対象1は勝ち馬の位置を使うため事前予測には使えない（事後の空間クラスター検定）。',
            '対象1のベースラインは同一人気帯の非勝ち馬。1着率は定義上ほぼ0。',
            '対象2は1番人気位置が事前既知。ベースラインは同一人気帯の全馬。',
            '主検定 Bonferroni α=0.05/8。* は未補正p<0.05、** は補正後も有意でプラス。',
            '複勝回収は実払戻（100円あたり）。',
        ],
        'primary': PRIMARY,
        'rows': rows,
        'vh_cross': vh,
        'elapsed_s': round(time.time() - t0, 1),
        'best1': b1,
        'best2': b2,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'\n保存 {OUT} ({time.time()-t0:.0f}s)', file=sys.stderr)


if __name__ == '__main__':
    main()
