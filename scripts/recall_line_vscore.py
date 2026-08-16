# -*- coding: utf-8 -*-
"""妙味度(vscore)低レースでの recall@K 検証。"""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from scripts import csv_data


def run():
    print("=" * 70)
    print("妙味度別 × 頭数別 recall@K: 3着内3頭全員がランクK以内に入る確率")
    print("=" * 70)

    horses = csv_data.load_horses(
        cols=['race_key', 'day', 'umaban', 'ability_score', 'chakujun'])
    races = csv_data.load_races(
        cols=['race_key', 'day', 'vlabel', 'vscore', 'field_size'])

    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)

    merged = horses.merge(races[['race_key', 'vlabel', 'vscore', 'field_size']],
                          on='race_key', how='left')
    merged['rank'] = merged.groupby('race_key')['ability_score'].rank(
        ascending=False, method='first').astype(int)

    top3 = merged[merged['chakujun'] <= 3].copy()
    worst = top3.groupby('race_key').agg(
        worst_rank=('rank', 'max'),
        n_top3=('rank', 'count'),
    ).reset_index()
    worst = worst[worst['n_top3'] >= 3].drop(columns='n_top3')

    race_info = merged.drop_duplicates('race_key')[
        ['race_key', 'day', 'vlabel', 'vscore', 'field_size']].copy()
    worst = worst.merge(race_info, on='race_key', how='left')

    day = pd.to_numeric(worst['day'], errors='coerce')
    yr = day // 10000
    worst['period'] = 'other'
    worst.loc[yr <= csv_data.TRAIN_END, 'period'] = 'train'
    worst.loc[yr == csv_data.HOLDOUT_YEAR, 'period'] = 'holdout'
    worst.loc[day >= csv_data.RECENT_FROM, 'period'] = 'recent'

    size_bins = [(7, 10), (11, 14), (15, 18)]
    vscore_cuts = [
        ('vscore≤20 (超鉄板)', 0, 20),
        ('vscore≤30', 0, 30),
        ('vscore≤40', 0, 40),
        ('vscore≤50', 0, 50),
        ('全レース', 0, 999),
    ]

    for period_name, period_list in [('holdout(2025)', ['holdout']),
                                      ('train(≤2024)', ['train']),
                                      ('recent(2026)', ['recent'])]:
        pdf = worst[worst['period'].isin(period_list)]
        print(f"\n{'━' * 70}")
        print(f"■ {period_name}")
        print(f"{'━' * 70}")

        for vs_name, vs_lo, vs_hi in vscore_cuts:
            vdf = pdf[(pdf['vscore'] >= vs_lo) & (pdf['vscore'] <= vs_hi)]
            if len(vdf) < 10:
                continue
            print(f"\n  ◆ {vs_name}  ({len(vdf)}R)")

            for smin, smax in size_bins:
                ss = vdf[(vdf['field_size'] >= smin) & (vdf['field_size'] <= smax)]
                n = len(ss)
                if n < 10:
                    continue
                avg_fs = ss['field_size'].mean()
                print(f"    {smin}〜{smax}頭 ({n}R, 平均{avg_fs:.1f}頭)")

                prev_pct = 0
                for k in range(3, smax + 1):
                    captured = (ss['worst_rank'] <= k).sum()
                    pct = captured / n * 100
                    ratio = k / avg_fs * 100
                    marker = ""
                    if pct >= 50 and prev_pct < 50:
                        marker = " ◀50%"
                    if pct >= 70 and prev_pct < 70:
                        marker = " ◀70%"
                    if pct >= 80 and prev_pct < 80:
                        marker = " ◀80%"
                    print(f"      K={k:2d} ({ratio:4.0f}%)  {pct:5.1f}% ({captured}/{n}){marker}")
                    prev_pct = pct
                    if pct >= 90:
                        break

        # 最適ライン提案: 頭数比例で70%到達する%を探索
        print(f"\n  ── 最適ライン探索 (vscore≤30) ──")
        vdf30 = pdf[(pdf['vscore'] <= 30)]
        if len(vdf30) >= 10:
            for target_pct in [50, 60, 70]:
                best = None
                for line_pct in range(30, 100):
                    k_vals = np.maximum(3, np.round(
                        vdf30['field_size'].values * line_pct / 100)).astype(int)
                    captured = (vdf30['worst_rank'].values <= k_vals).sum()
                    actual = captured / len(vdf30) * 100
                    if actual >= target_pct:
                        best = line_pct
                        break
                if best:
                    ex8 = max(3, round(8 * best / 100))
                    ex12 = max(3, round(12 * best / 100))
                    ex16 = max(3, round(16 * best / 100))
                    print(f"    捕捉{target_pct}%: 頭数×{best}% "
                          f"(8頭→{ex8}, 12頭→{ex12}, 16頭→{ex16})")


if __name__ == '__main__':
    run()
