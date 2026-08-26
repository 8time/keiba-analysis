# -*- coding: utf-8 -*-
"""穴馬ハンター表示馬（精鋭以外も含む）× 逆ショッカー / 血統期待値高 / 期待値高。

表示 = 6番人気以下（ページに出る馬。精鋭・広域網・圏外すべて）。
逆ショッカー = 前走3角≥5 かつ 今回距離短縮（①②のみ。③は使わない）。
期待値高 = 帯の単勝回収 ≥0.90（core/blood_ev.WIN_EV_HIGH）。
血統期待値高 = レース内相対 ≥1.25 かつ血統がレース上位約4割。
両方高い = 期待値高 × 血統期待値高 × 大穴除外（12番人気未満・50倍以下）。

判定: 見る+確認で複残差 z>=+2 かつ残差>0 なら『来ている』材料。
Usage: python scripts/hunter_display_flags_backtest.py
"""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import blood_ev as bev
from core import jockey_jv as jj
from scripts import csv_data as cd
from scripts.hunter_miss_complement import MIN_N, POP, add_light_score, fmt, stats

Z_GATE = 2.0


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def both_pos(train, hold):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return (train['z'] >= Z_GATE and hold['z'] >= Z_GATE
            and train['resid'] > 0 and hold['resid'] > 0)


def print_block(title, mask, periods, df, e3):
    print(f'--- {title} ---')
    row = {}
    for pname, pm in periods.items():
        st = stats(df[mask & pm], e3)
        row[pname] = st
        print(f'  {pname:12s} {fmt(st)}')
    ok = both_pos(row.get('見る(〜2024)'), row.get('確認(2025)'))
    print('  → ' + ('★来ている（両窓 z>=+2）' if ok else 'ゲート未達'))
    return row, ok


def add_blood_ev_flags(df, bands):
    surf = np.where(df['surface_code'] == 1, 'ダート', '芝')
    df = df.copy()
    df['_surf'] = surf
    # 血統スコアはキャッシュ付き。レース単位の相対はあとで。
    df['blood_place'] = [
        bev.blood_place(
            None if pd.isna(s) else s,
            None if pd.isna(b) else b,
            su,
            0 if pd.isna(d) else int(d),
        )
        for s, b, su, d in zip(df['sire'], df['bms'], df['_surf'], df['kyori_int'])
    ]
    df['win_ev'] = [
        bev.win_ev(o, bands) for o in df['win_odds']
    ]
    g = df.groupby('race_key', sort=False)
    mean_b = g['blood_place'].transform('mean')
    mp = df['win_odds'].map(lambda o: bev.market_place(o, bands))
    df['market_place'] = mp
    mean_m = mp.groupby(df['race_key']).transform('mean')
    mean_b = mean_b.replace(0, np.nan).fillna(0.25)
    mean_m = mean_m.replace(0, np.nan).fillna(0.22)
    df['blood_ev'] = (df['blood_place'] / mean_b) / (df['market_place'] / mean_m)
    df['blood_rank'] = g['blood_place'].rank(ascending=False, method='min')
    n = g['umaban'].transform('size')
    cut = np.maximum(3, np.round(n * 0.4).astype(int))
    skip = (df['win_odds'] > bev.ODDS_E) | (df['ninki'] >= bev.NINKI_E)
    win_hi = df['win_ev'] >= bev.WIN_EV_HIGH
    blood_hi = (df['blood_ev'] >= bev.BLOOD_HIGH) & (df['blood_rank'] <= cut)
    df['win_hi'] = win_hi & ~skip
    df['blood_hi'] = blood_hi
    df['overlap'] = win_hi & blood_hi & ~skip
    return df


def load_gyaku():
    print('逆ショッカー（前走3角・距離）...', flush=True)
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True, timeout=10)
    rows = con.execute(
        """SELECT r.ketto_num, r.race_key, r.umaban, r.corner3, r.chakujun,
                  r.time, ra.kyori, ra.year, ra.monthday
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート')
             AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
           ORDER BY r.ketto_num, ra.year, ra.monthday"""
    ).fetchall()
    con.close()
    from collections import defaultdict
    from core.pace_map import _parse_jv_time
    from core.gyaku_shocker import is_prev_close

    win_sec = {}
    tmp = defaultdict(list)
    for kt, rkey, um, c3, chaku, tm, kyori, y, md in rows:
        s = _parse_jv_time(tm)
        if s is not None:
            tmp[str(rkey)].append((chaku, s))
    for rkey, lst in tmp.items():
        lst.sort(key=lambda x: (x[0] != 1, x[1]))
        win_sec[rkey] = lst[0][1]

    by_h = defaultdict(list)
    for kt, rkey, um, c3, chaku, tm, kyori, y, md in rows:
        by_h[kt].append({
            'rk': str(rkey), 'um': int(um or 0),
            'c3': c3 or 0, 'kyori': kyori or 0,
            'chaku': chaku, 'tm': tm,
        })
    gmap, pmap = {}, {}
    for hist in by_h.values():
        for i, cur in enumerate(hist):
            if i == 0:
                continue
            prev = hist[i - 1]
            key = (cur['rk'], cur['um'])
            gmap[key] = bool((0 < (prev['c3'] or 0) >= 5) and cur['kyori'] < prev['kyori'])
            sec = _parse_jv_time(prev['tm'])
            w = win_sec.get(prev['rk'])
            margin = (sec - w) if (sec is not None and w is not None) else None
            pmap[key] = bool(gmap[key] and is_prev_close(prev['chaku'], margin))
    print(f'  逆ショッカー該当 {sum(gmap.values()):,}走')
    return gmap, pmap


def main():
    print('較正...', flush=True)
    exp = jj.calibrate_odds_expectation()
    bands = bev.calibrate_bands()
    print('CSV...', flush=True)
    df = cd.load_horses(cols=[
        'race_key', 'day', 'ninki', 'win_odds', 'top3', 'win', 'umaban',
        'h7_fig', 'spurt_idx', 'blood_race_pct', 'combo', 'elim_n',
        'avg_pos3', 'sire', 'bms', 'surface_code', 'kyori_int',
    ])
    for c in ('ninki', 'win_odds', 'top3', 'win', 'umaban', 'h7_fig',
              'spurt_idx', 'blood_race_pct', 'combo', 'elim_n', 'avg_pos3',
              'surface_code', 'kyori_int', 'day'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['win_odds'].notna() & (df['win_odds'] > 0)
            & df['ninki'].notna() & df['race_key'].notna()].copy()
    df = df.reset_index(drop=True)

    print('VHスコア...', flush=True)
    df = add_light_score(df)
    print('血統期待値...', flush=True)
    df = add_blood_ev_flags(df, bands)
    gmap, pmap = load_gyaku()
    keys = list(zip(df['race_key'].astype(str), df['umaban'].fillna(0).astype(int)))
    df['gyaku'] = [bool(gmap.get(k)) for k in keys]
    df['gyaku_pair'] = [bool(pmap.get(k)) for k in keys]
    e3 = _band_exp(df['win_odds'], exp, 'top3', 0.22)

    shown = df['ninki'] >= POP
    elite = shown & df['elite']
    wide = shown & df['wide'] & ~df['elite']
    other = shown & ~df['wide'] & ~df['elite']
    net = shown & (df['elite'] | df['wide'])  # 精鋭+広域（圏外以外）

    periods = {
        '見る(〜2024)': df['period'] == 'train',
        '確認(2025)': df['period'] == 'holdout',
        '直近(2026)': df['period'] == 'recent',
    }

    print(f'\n表示= {POP}番人気以下 {int(shown.sum()):,}走（精鋭・広域・圏外すべて）')
    print('残差 = 実複勝 − 同オッズ帯期待。★ = 両窓 z>=+2\n')

    conds = [
        ('表示全体（対照）', shown),
        ('精鋭だけ', elite),
        ('広域網だけ', wide),
        ('圏外（表示されているが網の外）', other),
        ('表示 × 逆ショッカー', shown & df['gyaku']),
        ('精鋭 × 逆ショッカー', elite & df['gyaku']),
        ('広域網 × 逆ショッカー', wide & df['gyaku']),
        ('圏外 × 逆ショッカー', other & df['gyaku']),
        ('精鋭+広域 × 逆ショッカー', net & df['gyaku']),
        ('表示 × 逆ショッカー×僅差', shown & df['gyaku_pair']),
        ('表示 × 通常の期待値=高い', shown & df['win_hi']),
        ('精鋭+広域 × 通常の期待値=高い', net & df['win_hi']),
        ('表示 × 血統期待値=高い', shown & df['blood_hi']),
        ('精鋭+広域 × 血統期待値=高い', net & df['blood_hi']),
        ('圏外 × 血統期待値=高い', other & df['blood_hi']),
        ('表示 × 両方高い', shown & df['overlap']),
        ('精鋭 × 両方高い', elite & df['overlap']),
        ('広域網 × 両方高い', wide & df['overlap']),
        ('精鋭+広域 × 両方高い', net & df['overlap']),
        ('圏外 × 両方高い', other & df['overlap']),
        ('表示 × 逆ショッカー × 両方高い', shown & df['gyaku'] & df['overlap']),
        ('精鋭+広域 × 逆ショッカー × 両方高い', net & df['gyaku'] & df['overlap']),
        ('精鋭+広域 × 逆ショッカー × 血統高い', net & df['gyaku'] & df['blood_hi']),
    ]
    stars = []
    for name, mask in conds:
        _, ok = print_block(name, mask, periods, df, e3)
        if ok:
            stars.append(name)

    print('\n======== まとめ ========')
    if not stars:
        print('ハンター表示馬の中でも、逆ショッカー／血統期待値高／両方高いは両窓の正残差に届かない。')
        print('絶対複勝は高く見えても、同じ人気帯の期待を超えていない。スコアには足さない。')
        return
    print('両窓で来ている:')
    for s in stars:
        print(f'  {s}')


if __name__ == '__main__':
    main()
