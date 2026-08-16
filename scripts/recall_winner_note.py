# -*- coding: utf-8 -*-
"""NOTE売り文句用: 勝ち馬/3着内馬の個別recall@K（頭数別）。

「勝ち馬がランク上位Kに入る確率」= recall@K の本来の指標。
人気順との比較・ランダムベースラインも出す。
"""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from scripts import csv_data


def run():
    print("=" * 70)
    print("NOTE用指標: 勝ち馬/3着内馬がランク上位Kに入る確率")
    print("=" * 70)

    horses = csv_data.load_horses(
        cols=['race_key', 'day', 'umaban', 'ninki', 'ability_score',
              'chakujun', 'top3', 'win'])
    races = csv_data.load_races(
        cols=['race_key', 'day', 'vlabel', 'vscore', 'field_size'])

    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)

    merged = horses.merge(races[['race_key', 'vlabel', 'vscore', 'field_size']],
                          on='race_key', how='left')
    merged['rank'] = merged.groupby('race_key')['ability_score'].rank(
        ascending=True, method='first').astype(int)
    merged['pop_rank'] = merged.groupby('race_key')['ninki'].rank(
        ascending=True, method='first').astype(int)

    day = pd.to_numeric(merged['day'], errors='coerce')
    yr = day // 10000
    merged['period'] = 'other'
    merged.loc[yr <= csv_data.TRAIN_END, 'period'] = 'train'
    merged.loc[yr == csv_data.HOLDOUT_YEAR, 'period'] = 'holdout'
    merged.loc[day >= csv_data.RECENT_FROM, 'period'] = 'recent'

    solid = {'D 鉄板(妙味薄)', 'C やや堅い'}
    all_labels = set(merged['vlabel'].dropna().unique())

    size_bins = [('少頭数(7-10)', 7, 10), ('中頭数(11-14)', 11, 14),
                 ('多頭数(15-18)', 15, 18)]

    for label_name, label_filter in [
        ('堅い(D+C)', solid),
        ('全レース', all_labels),
    ]:
        for period in ['holdout', 'train', 'recent']:
            df = merged[
                merged['vlabel'].isin(label_filter) &
                (merged['period'] == period)
            ]
            if len(df) < 100:
                continue

            winners = df[df['win'] == 1]
            top3_horses = df[df['top3'] == 1]
            n_races = df['race_key'].nunique()

            print(f"\n{'━' * 70}")
            print(f"■ {label_name} / {period}  ({n_races}R)")
            print(f"{'━' * 70}")

            # ── 勝ち馬 recall@K ──
            print(f"\n  ── 勝ち馬がランク上位Kに入る確率 ──")
            print(f"  {'K':>4s}  {'ランク':>8s}  {'人気順':>8s}  {'ランダム':>8s}  {'ランク-人気':>10s}")
            for k in [3, 5, 7, 'half']:
                if k == 'half':
                    label = '半分'
                    rank_hit = 0
                    pop_hit = 0
                    rand_sum = 0
                    n = 0
                    for _, w in winners.iterrows():
                        fs = int(w['field_size'])
                        kk = max(3, fs // 2)
                        n += 1
                        if w['rank'] <= kk:
                            rank_hit += 1
                        if w['pop_rank'] <= kk:
                            pop_hit += 1
                        rand_sum += kk / fs
                    rank_pct = rank_hit / n * 100
                    pop_pct = pop_hit / n * 100
                    rand_pct = rand_sum / n * 100
                else:
                    label = str(k)
                    rank_pct = (winners['rank'] <= k).mean() * 100
                    pop_pct = (winners['pop_rank'] <= k).mean() * 100
                    avg_fs = winners['field_size'].mean()
                    rand_pct = k / avg_fs * 100

                diff = rank_pct - pop_pct
                print(f"  K={label:>3s}  {rank_pct:6.1f}%   {pop_pct:6.1f}%   "
                      f"{rand_pct:6.1f}%   {diff:+6.1f}pp")

            # ── 3着内馬 recall@K ──
            print(f"\n  ── 3着内馬がランク上位Kに入る確率（個別） ──")
            print(f"  {'K':>4s}  {'ランク':>8s}  {'人気順':>8s}  {'ランダム':>8s}  {'ランク-人気':>10s}")
            for k in [3, 5, 7, 'half']:
                if k == 'half':
                    label = '半分'
                    rank_hit = 0
                    pop_hit = 0
                    rand_sum = 0
                    n = 0
                    for _, h in top3_horses.iterrows():
                        fs = int(h['field_size'])
                        kk = max(3, fs // 2)
                        n += 1
                        if h['rank'] <= kk:
                            rank_hit += 1
                        if h['pop_rank'] <= kk:
                            pop_hit += 1
                        rand_sum += kk / fs
                    rank_pct = rank_hit / n * 100
                    pop_pct = pop_hit / n * 100
                    rand_pct = rand_sum / n * 100
                else:
                    label = str(k)
                    rank_pct = (top3_horses['rank'] <= k).mean() * 100
                    pop_pct = (top3_horses['pop_rank'] <= k).mean() * 100
                    avg_fs = top3_horses['field_size'].mean()
                    rand_pct = k / avg_fs * 100

                diff = rank_pct - pop_pct
                print(f"  K={label:>3s}  {rank_pct:6.1f}%   {pop_pct:6.1f}%   "
                      f"{rand_pct:6.1f}%   {diff:+6.1f}pp")

            # ── 頭数別の勝ち馬recall ──
            print(f"\n  ── 頭数別 勝ち馬recall ──")
            for sz_name, smin, smax in size_bins:
                sw = winners[
                    (winners['field_size'] >= smin) &
                    (winners['field_size'] <= smax)]
                if len(sw) < 10:
                    continue
                avg_fs = sw['field_size'].mean()
                half_k = max(3, round(avg_fs / 2))

                row_parts = [f"    {sz_name} ({len(sw)}R):"]
                for k in [3, 5, 7, half_k]:
                    rp = (sw['rank'] <= k).mean() * 100
                    pp = (sw['pop_rank'] <= k).mean() * 100
                    row_parts.append(f"K={k}: {rp:.0f}%(人気{pp:.0f}%)")
                print('  '.join(row_parts))

            # ── 頭数比例ラインの勝ち馬recall ──
            print(f"\n  ── 頭数×N%ラインの勝ち馬recall ──")
            print(f"  {'%':>4s}  {'ランク':>8s}  {'人気順':>8s}  {'差':>8s}  {'平均K':>6s}")
            for pct in [40, 45, 50, 55, 60]:
                k_vals = np.maximum(3, np.round(
                    winners['field_size'].values * pct / 100)).astype(int)
                rank_hit = (winners['rank'].values <= k_vals).mean() * 100
                pop_hit = (winners['pop_rank'].values <= k_vals).mean() * 100
                avg_k = k_vals.mean()
                print(f"  {pct:3d}%  {rank_hit:6.1f}%   {pop_hit:6.1f}%   "
                      f"{rank_hit - pop_hit:+6.1f}pp  K≈{avg_k:.1f}")


if __name__ == '__main__':
    run()
