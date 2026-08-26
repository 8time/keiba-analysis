# -*- coding: utf-8 -*-
"""俗説総合TOP5 × 穴馬ハンター精鋭/広域網の重複馬の3着以内率。

定義は repo/brief_folklore_top5_hunter_overlap.md。実装しない。2026年だけ。

Usage: python scripts/folklore_top5_hunter_overlap.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from scripts import csv_data as cd
from scripts.folklore_top5_axis_backtest import mark_top5, score_all
from scripts.hunter_miss_complement import POP, add_light_score

MIN_N = 50
YEAR = 2026
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, 'data', 'folklore_top5_hunter_overlap.json')


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def stats_from(sub, e3=None):
    n = len(sub)
    if n == 0:
        return None
    t3 = sub['top3'].to_numpy(dtype=float)
    hits = int(t3.sum())
    hit = float(t3.mean())
    out = {
        'n': int(n),
        'hits': hits,
        'hit': hit,
        'races': int(sub['race_key'].nunique()) if 'race_key' in sub.columns else None,
    }
    if e3 is not None:
        resid = t3 - e3.loc[sub.index].to_numpy(dtype=float)
        se = (0.22 * 0.78 / n) ** 0.5
        out['resid'] = float(resid.mean())
        out['z'] = float(resid.mean() / se) if se > 0 else 0.0
        out['exp'] = float(e3.loc[sub.index].mean())
    return out


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)  3着内 {s['hits']}/{s['n']}"
    extra = ''
    if 'resid' in s:
        extra = f"  帯期待{s['exp']:5.1%} 残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}"
    r = f"  {s['races']}R" if s.get('races') else ''
    return (f"n={s['n']:6d}{r}  3着内 {s['hits']:4d}/{s['n']}"
            f"  {s['hit']:5.1%}{extra}")


def pack(s):
    if not s:
        return None
    out = {}
    for k, v in s.items():
        if isinstance(v, (float, np.floating)):
            out[k] = None if v != v else float(v)
        elif isinstance(v, (int, np.integer)):
            out[k] = int(v)
        else:
            out[k] = v
    return out


def main():
    if not cd.available():
        raise SystemExit('data/export/horse_races.csv が無い')
    print('馬行を読みます…')
    horses = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'surface_code', 'kyori_int', 'field_size',
        'umaban', 'waku_n', 'ninki', 'win_odds', 'futan', 'bataiju', 'zogen',
        'sex_code', 'age', 'is_handi1', 'days_since', 'dist_change',
        'sire', 'bms', 'top3', 'win',
        'h7_fig', 'spurt_idx', 'blood_race_pct', 'combo', 'elim_n', 'avg_pos3',
    ], with_period=False)
    races = cd.load_races(cols=[
        'race_key', 'day', 'baba_code', 'race_name', 'grade', 'fillies',
        'open_cls', 'is_handi1', 'is_2yo',
    ], with_period=False)
    horses['day'] = pd.to_numeric(horses['day'], errors='coerce')
    races['day'] = pd.to_numeric(races['day'], errors='coerce')
    horses = horses[(horses['day'] // 10000) == YEAR].copy()
    races = races[(races['day'] // 10000) == YEAR].copy()
    if horses.empty:
        raise SystemExit('2026年の馬行が無い')
    day_min = int(horses['day'].min())
    day_max = int(horses['day'].max())
    print(f"2026 {day_min}〜{day_max}  馬 {len(horses):,} / レース {horses['race_key'].nunique():,}")

    print('総合スコア…')
    scored = score_all(horses, races)
    scored = mark_top5(scored)

    print('穴馬スコア…')
    for c in ('ninki', 'win_odds', 'top3', 'h7_fig', 'spurt_idx',
              'blood_race_pct', 'combo', 'elim_n', 'avg_pos3'):
        scored[c] = pd.to_numeric(scored[c], errors='coerce')
    scored = scored[scored['win_odds'].notna() & (scored['win_odds'] > 0)
                    & scored['ninki'].notna()].copy()
    scored = scored.reset_index(drop=True)
    scored = add_light_score(scored)
    scored['shown'] = scored['ninki'] >= POP
    scored['elite_show'] = scored['shown'] & scored['elite']
    scored['wide_show'] = scored['shown'] & scored['wide'] & ~scored['elite']
    scored['hunter'] = scored['elite_show'] | scored['wide_show']
    scored['overlap'] = scored['in_top5'] & scored['hunter']
    scored['ov_elite'] = scored['in_top5'] & scored['elite_show']
    scored['ov_wide'] = scored['in_top5'] & scored['wide_show']

    print('オッズ帯の平均…')
    exp = jj.calibrate_odds_expectation()
    e3 = _band_exp(scored['win_odds'], exp, 'top3', 0.22)

    rows = [
        ('6番人気以下 全体', scored['shown']),
        ('精鋭（総合は不問）', scored['elite_show']),
        ('広域網（総合は不問）', scored['wide_show']),
        ('精鋭または広域網', scored['hunter']),
        ('総合TOP5 全体', scored['in_top5']),
        ('総合TOP5のうち6番以下', scored['in_top5'] & scored['shown']),
        ('★重複 総合TOP5×精鋭or広域', scored['overlap']),
        ('  うち精鋭', scored['ov_elite']),
        ('  うち広域網', scored['ov_wide']),
    ]
    print(f"\n=== 2026年 {day_min}〜{day_max} 頭単位 ===")
    packed = {}
    for title, mask in rows:
        st = stats_from(scored.loc[mask], e3)
        print(f"{title:24s} {fmt(st)}")
        packed[title] = pack(st)

    ov = scored.loc[scored['overlap']]
    race_hit = None
    if not ov.empty:
        g = ov.groupby('race_key', sort=False)['top3'].max()
        n_r = int(len(g))
        h_r = int(g.sum())
        race_hit = {
            'n': n_r,
            'hits': h_r,
            'hit': float(g.mean()),
            'per_race': float(ov.groupby('race_key').size().mean()),
        }
        print(f"\n=== レース単位（重複が1頭以上いるレース） ===")
        print(f"重複のどれかが3着内  {h_r}/{n_r}  {g.mean():5.1%}"
              f"  1Rあたり重複 {race_hit['per_race']:.2f}頭")

    all_r = int(scored['race_key'].nunique())
    ov_r = int(scored.loc[scored['overlap'], 'race_key'].nunique())
    print(f"\n重複が出たレース {ov_r}/{all_r} ({ov_r / all_r if all_r else 0:.1%})")

    summary = {
        'year': YEAR,
        'day_min': day_min,
        'day_max': day_max,
        'n_horses': int(len(scored)),
        'n_races': all_r,
        'n_overlap_races': ov_r,
        'pop': POP,
        'blocks': packed,
        'race_any_overlap_top3': pack(race_hit),
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n書いた {OUT_JSON}")


if __name__ == '__main__':
    main()
