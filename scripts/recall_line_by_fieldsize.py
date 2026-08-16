# -*- coding: utf-8 -*-
"""頭数別 recall@K 検証: 線をどこに引けば3着内馬3頭が全員入るか。"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from scripts import csv_data


def run():
    print("=" * 70)
    print("頭数別 recall@K: 線をどこに引くか")
    print("=" * 70)

    horses = csv_data.load_horses(
        cols=['race_key', 'day', 'umaban', 'ability_score', 'chakujun'])
    races = csv_data.load_races(
        cols=['race_key', 'day', 'vlabel', 'field_size'])

    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)

    merged = horses.merge(races[['race_key', 'vlabel', 'field_size']],
                          on='race_key', how='left')

    merged['rank'] = merged.groupby('race_key')['ability_score'].rank(
        ascending=False, method='first').astype(int)

    # 各レースの3着内馬の最悪ランクを一括計算
    top3 = merged[merged['chakujun'] <= 3].copy()
    worst = top3.groupby('race_key').agg(
        worst_rank=('rank', 'max'),
        n_top3=('rank', 'count'),
    ).reset_index()
    worst = worst[worst['n_top3'] >= 3].drop(columns='n_top3')

    race_info = merged.drop_duplicates('race_key')[
        ['race_key', 'day', 'vlabel', 'field_size']].copy()
    worst = worst.merge(race_info, on='race_key', how='left')

    day = pd.to_numeric(worst['day'], errors='coerce')
    yr = day // 10000
    worst['period'] = 'other'
    worst.loc[yr <= csv_data.TRAIN_END, 'period'] = 'train'
    worst.loc[yr == csv_data.HOLDOUT_YEAR, 'period'] = 'holdout'
    worst.loc[day >= csv_data.RECENT_FROM, 'period'] = 'recent'

    solid_labels = {'D 鉄板(妙味薄)', 'C やや堅い'}
    all_labels = set(worst['vlabel'].dropna().unique())

    for label_name, label_filter, periods in [
        ('堅い(D+C) holdout', solid_labels, ['holdout']),
        ('堅い(D+C) train', solid_labels, ['train']),
        ('堅い(D+C) recent', solid_labels, ['recent']),
        ('全レース holdout', all_labels, ['holdout']),
    ]:
        df = worst[
            worst['vlabel'].isin(label_filter) &
            worst['period'].isin(periods)
        ].copy()

        print(f"\n{'━' * 70}")
        print(f"■ {label_name}  ({len(df)}R)")
        print(f"{'━' * 70}")

        size_bins = [(7, 9), (10, 12), (13, 14), (15, 16), (17, 18)]

        for smin, smax in size_bins:
            ss = df[(df['field_size'] >= smin) & (df['field_size'] <= smax)]
            n = len(ss)
            if n < 10:
                continue
            avg_fs = ss['field_size'].mean()

            print(f"\n  {smin}〜{smax}頭立て ({n}R, 平均{avg_fs:.1f}頭)")
            print(f"    K   頭数比  捕捉率")

            prev_pct = 0
            for k in range(3, smax + 1):
                captured = (ss['worst_rank'] <= k).sum()
                pct = captured / n * 100
                ratio = k / avg_fs * 100
                marker = ""
                if pct >= 70 and prev_pct < 70:
                    marker = " ◀ 70%"
                if pct >= 80 and prev_pct < 80:
                    marker = " ◀ 80%"
                if pct >= 90 and prev_pct < 90:
                    marker = " ◀ 90%"
                print(f"    {k:2d}  {ratio:5.1f}%  {pct:5.1f}% ({captured:4d}/{n}){marker}")
                prev_pct = pct
                if pct >= 95:
                    break

        # 比例ラインのサマリー
        print(f"\n  ── 比例ライン(頭数×N%)全頭数統合 ──")
        for pct_line in [35, 40, 45, 50]:
            k_vals = np.maximum(3, np.round(df['field_size'].values * pct_line / 100)).astype(int)
            captured = (df['worst_rank'].values <= k_vals).sum()
            n_total = len(df)
            ex8 = max(3, round(8 * pct_line / 100))
            ex16 = max(3, round(16 * pct_line / 100))
            print(f"    {pct_line}% (8頭→{ex8}, 16頭→{ex16}): "
                  f"捕捉 {captured}/{n_total} = {captured/n_total*100:.1f}%")


if __name__ == '__main__':
    run()
