# -*- coding: utf-8 -*-
"""堅いレース×ランク上位4頭 3連単BOX バックテスト。

仮説: 堅いレース(vlabel D/C)でability_score上位4頭の3連単BOX(24点)は
      配当が十分高くROI 100%超えになるか？
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import pandas as pd
from scripts import csv_data

DB_PATH = os.path.join(csv_data.ROOT, 'data', 'jravan.db')


def load_trifecta_payouts():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'", con)
    con.close()
    df['u1'] = df['combo'].str[:2].astype(int)
    df['u2'] = df['combo'].str[2:4].astype(int)
    df['u3'] = df['combo'].str[4:6].astype(int)
    return df


def get_period(day_val):
    yr = int(day_val) // 10000
    if yr <= csv_data.TRAIN_END:
        return 'train'
    if yr == csv_data.HOLDOUT_YEAR:
        return 'holdout'
    if int(day_val) >= csv_data.RECENT_FROM:
        return 'recent'
    return None


def run():
    print("=" * 70)
    print("堅いレース × ランク上位N頭 3連単BOX バックテスト")
    print("=" * 70)

    horses = csv_data.load_horses(
        cols=['race_key', 'day', 'umaban', 'ninki', 'ability_score', 'chakujun'])
    races = csv_data.load_races(
        cols=['race_key', 'day', 'vlabel', 'field_size'])

    payouts = load_trifecta_payouts()
    pay_dict = {}
    for _, r in payouts.iterrows():
        pay_dict[(str(r['race_key']), r['u1'], r['u2'], r['u3'])] = r['payout']

    horses['race_key'] = horses['race_key'].astype(str)
    races['race_key'] = races['race_key'].astype(str)
    merged = horses.merge(races[['race_key', 'vlabel', 'field_size']],
                          on='race_key', how='left')

    # レースごとにランク列を付与
    merged['rank'] = merged.groupby('race_key')['ability_score'].rank(
        ascending=False, method='first').astype(int)
    # 着順ランク
    merged['fin_rank'] = merged.groupby('race_key')['chakujun'].rank(
        ascending=True, method='first').astype(int)

    # 1-3着馬を抽出
    top3_fin = merged[merged['fin_rank'] <= 3].copy()
    top3_wide = top3_fin.pivot_table(
        index='race_key', columns='fin_rank', values='umaban', aggfunc='first')
    top3_wide.columns = ['a1', 'a2', 'a3']
    top3_wide = top3_wide.dropna().astype(int).reset_index()

    # レース情報を結合
    race_info = merged.drop_duplicates('race_key')[['race_key', 'day', 'vlabel', 'field_size']]
    top3_wide = top3_wide.merge(race_info, on='race_key', how='left')

    # レースごとのランク上位N頭を辞書化
    rank_dict = {}
    for rk, grp in merged.groupby('race_key'):
        sorted_grp = grp.nsmallest(7, 'rank')
        rank_dict[rk] = sorted_grp['umaban'].tolist()

    solid_labels = {'D 鉄板(妙味薄)', 'C やや堅い'}
    all_labels = set(merged['vlabel'].dropna().unique())

    PERIODS = ['train', 'holdout', 'recent']

    for label_name, label_filter in [
        ('堅い(D+C)', solid_labels),
        ('鉄板のみ(D)', {'D 鉄板(妙味薄)'}),
        ('やや堅い(C)', {'C やや堅い'}),
        ('全レース', all_labels),
    ]:
        subset = top3_wide[top3_wide['vlabel'].isin(label_filter)].copy()
        subset['period'] = subset['day'].apply(get_period)
        subset = subset.dropna(subset=['period'])

        print(f"\n{'─' * 70}")
        print(f"■ {label_name}  ({len(subset)} レース)")
        print(f"{'─' * 70}")

        # BOX検証
        for top_n in [4, 5, 7]:
            n_tickets_map = {4: 24, 5: 60, 7: 210}
            n_tickets = n_tickets_map[top_n]

            results = {p: {'n': 0, 'hits': 0, 'payout': 0} for p in PERIODS}

            for _, row in subset.iterrows():
                rk = row['race_key']
                p = row['period']
                tops = rank_dict.get(rk, [])
                if len(tops) < top_n:
                    continue
                top_set = set(tops[:top_n])

                results[p]['n'] += 1
                a1, a2, a3 = int(row['a1']), int(row['a2']), int(row['a3'])
                if {a1, a2, a3}.issubset(top_set):
                    po = pay_dict.get((rk, a1, a2, a3), 0)
                    results[p]['hits'] += 1
                    results[p]['payout'] += po

            print(f"\n  top{top_n} BOX ({n_tickets}点)")
            for p in PERIODS:
                nr = results[p]['n']
                if nr == 0:
                    continue
                ht = results[p]['hits']
                cost = nr * n_tickets * 100
                roi = results[p]['payout'] / cost * 100 if cost > 0 else 0
                hit_rate = ht / nr * 100
                avg_pay = results[p]['payout'] / ht if ht > 0 else 0
                print(f"    {p:8s}: {nr:5d}R  的中{ht:4d} ({hit_rate:5.1f}%)  "
                      f"ROI {roi:6.1f}%  平均配当¥{avg_pay:,.0f}  "
                      f"投資¥{cost:,}  回収¥{results[p]['payout']:,}")

        # フォーメーション検証
        print(f"\n  ── フォーメーション案 ──")

        def check_formation(name, match_fn, n_tickets):
            results = {p: {'n': 0, 'hits': 0, 'payout': 0} for p in PERIODS}
            for _, row in subset.iterrows():
                rk = row['race_key']
                p = row['period']
                tops = rank_dict.get(rk, [])
                if len(tops) < 4:
                    continue
                results[p]['n'] += 1
                a1, a2, a3 = int(row['a1']), int(row['a2']), int(row['a3'])
                if match_fn(tops[:4], a1, a2, a3):
                    po = pay_dict.get((rk, a1, a2, a3), 0)
                    results[p]['hits'] += 1
                    results[p]['payout'] += po

            print(f"\n  {name} ({n_tickets}点)")
            for p in PERIODS:
                nr = results[p]['n']
                if nr == 0:
                    continue
                ht = results[p]['hits']
                cost = nr * n_tickets * 100
                roi = results[p]['payout'] / cost * 100 if cost > 0 else 0
                hit_rate = ht / nr * 100
                avg_pay = results[p]['payout'] / ht if ht > 0 else 0
                print(f"    {p:8s}: {nr:5d}R  的中{ht:4d} ({hit_rate:5.1f}%)  "
                      f"ROI {roi:6.1f}%  平均配当¥{avg_pay:,.0f}  "
                      f"投資¥{cost:,}  回収¥{results[p]['payout']:,}")

        # 1着=top2, 2着=top4, 3着=top4
        def fm_224(t4, a1, a2, a3):
            return a1 in t4[:2] and a2 in t4 and a3 in t4 and len({a1, a2, a3}) == 3
        check_formation("1着top2/2着top4/3着top4",
                        fm_224,
                        len([(a,b,c) for a in range(2) for b in range(4) for c in range(4)
                             if a!=b and a!=c and b!=c]))

        # 1着=top3, 2着=top4, 3着=top4
        def fm_344(t4, a1, a2, a3):
            return a1 in t4[:3] and a2 in t4 and a3 in t4 and len({a1, a2, a3}) == 3
        check_formation("1着top3/2着top4/3着top4",
                        fm_344,
                        len([(a,b,c) for a in range(3) for b in range(4) for c in range(4)
                             if a!=b and a!=c and b!=c]))

        # 1着=top2, 2着=top3, 3着=top4
        def fm_234(t4, a1, a2, a3):
            return a1 in t4[:2] and a2 in t4[:3] and a3 in t4 and len({a1, a2, a3}) == 3
        check_formation("1着top2/2着top3/3着top4",
                        fm_234,
                        len([(a,b,c) for a in range(2) for b in range(3) for c in range(4)
                             if a!=b and a!=c and b!=c]))

        # 人気ベース比較: 人気top4 BOX
        print(f"\n  ── 人気ベース比較 ──")
        ninki_rank = {}
        for rk, grp in merged.groupby('race_key'):
            sorted_grp = grp.nsmallest(7, 'ninki')
            ninki_rank[rk] = sorted_grp['umaban'].tolist()

        results_pop = {p: {'n': 0, 'hits': 0, 'payout': 0} for p in PERIODS}
        for _, row in subset.iterrows():
            rk = row['race_key']
            p = row['period']
            tops = ninki_rank.get(rk, [])
            if len(tops) < 4:
                continue
            top_set = set(tops[:4])
            results_pop[p]['n'] += 1
            a1, a2, a3 = int(row['a1']), int(row['a2']), int(row['a3'])
            if {a1, a2, a3}.issubset(top_set):
                po = pay_dict.get((rk, a1, a2, a3), 0)
                results_pop[p]['hits'] += 1
                results_pop[p]['payout'] += po

        print(f"\n  人気top4 BOX (24点) ※比較用")
        for p in PERIODS:
            nr = results_pop[p]['n']
            if nr == 0:
                continue
            ht = results_pop[p]['hits']
            cost = nr * 24 * 100
            roi = results_pop[p]['payout'] / cost * 100 if cost > 0 else 0
            hit_rate = ht / nr * 100
            avg_pay = results_pop[p]['payout'] / ht if ht > 0 else 0
            print(f"    {p:8s}: {nr:5d}R  的中{ht:4d} ({hit_rate:5.1f}%)  "
                  f"ROI {roi:6.1f}%  平均配当¥{avg_pay:,.0f}  "
                  f"投資¥{cost:,}  回収¥{results_pop[p]['payout']:,}")


if __name__ == '__main__':
    run()
