# -*- coding: utf-8 -*-
"""頭数比例ライン × 「3着内馬のうち平均何頭が線の中にいるか」。

NOTEで使う売り文句の根拠データ。
線の引き方候補: 固定K / 頭数×N% / 頭数別テーブル
"""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from scripts import csv_data


def run():
    print("=" * 70)
    print("3着内馬のうち何頭がランクK以内にいるか（平均）")
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

    # 3着内馬のみ
    top3 = merged[merged['chakujun'] <= 3].copy()

    # レースごとに3着内馬のランクを集約
    race_agg = top3.groupby('race_key').agg(
        ranks=('rank', list),
        n_top3=('rank', 'count'),
    ).reset_index()
    race_agg = race_agg[race_agg['n_top3'] >= 3]

    race_info = merged.drop_duplicates('race_key')[
        ['race_key', 'day', 'vlabel', 'vscore', 'field_size']].copy()
    race_agg = race_agg.merge(race_info, on='race_key', how='left')

    day = pd.to_numeric(race_agg['day'], errors='coerce')
    yr = day // 10000
    race_agg['period'] = 'other'
    race_agg.loc[yr <= csv_data.TRAIN_END, 'period'] = 'train'
    race_agg.loc[yr == csv_data.HOLDOUT_YEAR, 'period'] = 'holdout'
    race_agg.loc[day >= csv_data.RECENT_FROM, 'period'] = 'recent'

    solid_labels = {'D 鉄板(妙味薄)', 'C やや堅い'}
    all_labels = set(race_agg['vlabel'].dropna().unique())

    def calc_stats(df, k_func):
        """k_func: field_size -> K"""
        results = []
        for _, row in df.iterrows():
            k = k_func(int(row['field_size']))
            ranks = row['ranks']
            n_in = sum(1 for r in ranks if r <= k)
            results.append({
                'n_in': n_in,
                'all3': int(n_in == 3),
                'at_least2': int(n_in >= 2),
                'at_least1': int(n_in >= 1),
                'field_size': row['field_size'],
                'k': k,
            })
        rdf = pd.DataFrame(results)
        return {
            'n': len(rdf),
            'avg_in': rdf['n_in'].mean(),
            'all3_pct': rdf['all3'].mean() * 100,
            'ge2_pct': rdf['at_least2'].mean() * 100,
            'ge1_pct': rdf['at_least1'].mean() * 100,
            'avg_k': rdf['k'].mean(),
            'avg_ratio': (rdf['k'] / rdf['field_size']).mean() * 100,
        }

    # ランダムベースライン計算
    def random_baseline(df, k_func):
        total = 0
        for _, row in df.iterrows():
            fs = int(row['field_size'])
            k = k_func(fs)
            total += 3 * k / fs
        return total / len(df)

    size_bins = [('少頭数(7-10)', 7, 10), ('中頭数(11-14)', 11, 14),
                 ('多頭数(15-18)', 15, 18), ('全体', 7, 18)]

    for label_name, label_filter, vs_max in [
        ('堅い(D+C) vscore≤40', solid_labels, 40),
        ('堅い(D+C) 全て', solid_labels, 999),
        ('全レース', all_labels, 999),
    ]:
        for period_name, period_list in [('holdout', ['holdout']),
                                          ('train', ['train']),
                                          ('recent', ['recent'])]:
            df = race_agg[
                race_agg['vlabel'].isin(label_filter) &
                race_agg['period'].isin(period_list) &
                (race_agg['vscore'] <= vs_max)
            ]
            if len(df) < 20:
                continue

            print(f"\n{'━' * 70}")
            print(f"■ {label_name} / {period_name}  ({len(df)}R)")
            print(f"{'━' * 70}")

            # 固定K
            print(f"\n  ── 固定K ──")
            print(f"  {'K':>4s}  {'平均捕捉':>8s}  {'3頭的中':>8s}  {'2頭以上':>8s}  {'1頭以上':>8s}  {'ランダム':>8s}")
            for k in [4, 5, 6, 7, 8]:
                s = calc_stats(df, lambda fs, _k=k: _k)
                rb = random_baseline(df, lambda fs, _k=k: _k)
                print(f"  K={k:2d}  {s['avg_in']:.2f}/3   "
                      f"{s['all3_pct']:5.1f}%    {s['ge2_pct']:5.1f}%    "
                      f"{s['ge1_pct']:5.1f}%    {rb:.2f}/3")

            # 頭数比例
            print(f"\n  ── 頭数×N% (頭数で線が変わる) ──")
            print(f"  {'%':>4s}  {'平均K':>6s}  {'平均捕捉':>8s}  {'3頭的中':>8s}  {'2頭以上':>8s}  {'1頭以上':>8s}  {'ランダム':>8s}")
            for pct in [40, 45, 50, 55, 60, 65, 70]:
                s = calc_stats(df, lambda fs, _p=pct: max(3, round(fs * _p / 100)))
                rb = random_baseline(df, lambda fs, _p=pct: max(3, round(fs * _p / 100)))
                print(f"  {pct:3d}%  K≈{s['avg_k']:.1f}  {s['avg_in']:.2f}/3   "
                      f"{s['all3_pct']:5.1f}%    {s['ge2_pct']:5.1f}%    "
                      f"{s['ge1_pct']:5.1f}%    {rb:.2f}/3")

            # 頭数別の最適K
            print(f"\n  ── 頭数別 最適ライン (平均2頭以上を目標) ──")
            for sz_name, smin, smax in size_bins:
                ss = df[(df['field_size'] >= smin) & (df['field_size'] <= smax)]
                if len(ss) < 10:
                    continue
                best_k = None
                for k in range(3, smax + 1):
                    s = calc_stats(ss, lambda fs, _k=k: _k)
                    if s['avg_in'] >= 2.0 and best_k is None:
                        best_k = k
                    if best_k and k == best_k:
                        avg_fs = ss['field_size'].mean()
                        rb = random_baseline(ss, lambda fs, _k=k: _k)
                        print(f"    {sz_name}: K={k} ({k/avg_fs*100:.0f}%) "
                              f"平均{s['avg_in']:.2f}頭 "
                              f"(3頭{s['all3_pct']:.0f}%/2頭+{s['ge2_pct']:.0f}%/1頭+{s['ge1_pct']:.0f}%) "
                              f"ランダム{rb:.2f}頭  {len(ss)}R")
                        break
                if best_k is None:
                    print(f"    {sz_name}: 到達せず")


if __name__ == '__main__':
    run()
