# -*- coding: utf-8 -*-
"""軸信頼度による1着頭数の動的切替バックテスト。

仮説: 補正T×人気の重複数(overlap)が高い＝軸が堅い→1着を1頭固定(1-4-7=12点)。
      重複が低い＝軸が不安→1着を2頭(2-4-7=30点)のまま。
      点数を減らせる分、ROIが上がるのでは？

overlap定義: h7_rank≤3(補正Tトップ3)かつninki≤3(人気トップ3)を満たす馬の頭数(0-3)。
  [[verified_time_pop_overlap]]で検証済み: overlap3=1番人気複勝74%、overlap0=55%。

検証形:
  baseline: 常に2-4-7 (30点)
  A: overlap≥2 → 1-4-7(12点) / else → 2-4-7(30点)
  B: overlap=3 → 1-4-7(12点) / else → 2-4-7(30点)
  C: overlap≥2 → 1-5-8(24点) / else → 2-4-7(30点)
  ※1着固定=人気1位のみ。Rank源(ability_score)版も並行検証。

Usage:
  python scripts/axis_fix_formation_backtest.py
"""
import os
import sys
import io
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from scripts import csv_data as cd
from core import jockey_jv as jj

MIN_HORSES = 8


def load_trifecta_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[str(rk)] = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
    con.close()
    return out


def load_trio_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連複'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[str(rk)] = (tuple(sorted((int(c[:2]), int(c[2:4]), int(c[4:6])))), float(pay))
    con.close()
    return out


def trifecta_tickets(col1, col2, col3):
    tickets = set()
    for a in col1:
        for b in col2:
            if b == a:
                continue
            for c in col3:
                if c == a or c == b:
                    continue
                tickets.add((a, b, c))
    return tickets


def trio_tickets(col1, col2, col3):
    tickets = set()
    for a in col1:
        for b in col2:
            if b == a:
                continue
            for c in col3:
                if c == a or c == b:
                    continue
                tickets.add(tuple(sorted((a, b, c))))
    return tickets


def calc_overlap(rows):
    h7 = [(r.umaban, r.h7_rank) for r in rows
           if r.h7_rank is not None and not (isinstance(r.h7_rank, float) and r.h7_rank != r.h7_rank)]
    pop = [(r.umaban, r.ninki) for r in rows
           if r.ninki is not None and not (isinstance(r.ninki, float) and r.ninki != r.ninki)]
    if len(h7) < 3 or len(pop) < 3:
        return None
    top3_h7 = {int(u) for u, v in sorted(h7, key=lambda x: x[1])[:3]}
    top3_pop = {int(u) for u, v in sorted(pop, key=lambda x: x[1])[:3]}
    return len(top3_h7 & top3_pop)


def main():
    print("3連単配当 読み込み...")
    pay_tri = load_trifecta_payouts()
    print(f"  {len(pay_tri):,}レース")
    print("3連複配当 読み込み...")
    pay_trio = load_trio_payouts()
    print(f"  {len(pay_trio):,}レース")

    print("CSV特徴ストア 読み込み...")
    df = cd.load_horses(cols=['race_key', 'day', 'ninki', 'win_odds', 'ability_score',
                              'h7_rank', 'h7_fig', 'chakujun', 'umaban',
                              'vh2_score', 'combo', 'top3'])
    df = df[df['umaban'].notna()]
    df['race_key'] = df['race_key'].astype(str)
    by_race = defaultdict(list)
    for r in df.itertuples(index=False):
        by_race[r.race_key].append(r)

    FORMS = {
        '2-4-7': (2, 4, 7),
        '1-4-7': (1, 4, 7),
        '1-5-8': (1, 5, 8),
        '2-5-8': (2, 5, 8),
        '3-3-10': (3, 3, 10),
    }

    strategies = [
        ('baseline_2-4-7',    lambda ov: '2-4-7'),
        ('A: ov≥2→1-4-7',    lambda ov: '1-4-7' if ov >= 2 else '2-4-7'),
        ('B: ov=3→1-4-7',    lambda ov: '1-4-7' if ov >= 3 else '2-4-7'),
        ('C: ov≥2→1-5-8',    lambda ov: '1-5-8' if ov >= 2 else '2-4-7'),
        ('D: ov≥2→1-4-7/ov0→2-5-8', lambda ov: '1-4-7' if ov >= 2 else ('2-5-8' if ov == 0 else '2-4-7')),
    ]

    # {period: {rank_src: {strat_name: {bet_type: [cost, ret, hits, n]}}}}
    agg = {}
    overlap_dist = defaultdict(lambda: defaultdict(int))
    for period in ('train', 'holdout', 'recent'):
        agg[period] = {}
        for rs in ('ninki', 'ability'):
            agg[period][rs] = {}
            for sn, _ in strategies:
                agg[period][rs][sn] = {
                    '3連単': [0.0, 0.0, 0, 0],
                    '3連複': [0.0, 0.0, 0, 0],
                }

    for rk, rows in by_race.items():
        if len(rows) < MIN_HORSES:
            continue
        day = int(rows[0].day)
        yr = day // 10000
        if yr <= cd.TRAIN_END:
            period = 'train'
        elif yr == cd.HOLDOUT_YEAR:
            period = 'holdout'
        elif day >= cd.RECENT_FROM:
            period = 'recent'
        else:
            continue

        ov = calc_overlap(rows)
        if ov is None:
            continue
        overlap_dist[period][ov] += 1

        tri_result = pay_tri.get(rk)
        trio_result = pay_trio.get(rk)
        if not tri_result and not trio_result:
            continue

        for rs in ('ninki', 'ability'):
            if rs == 'ninki':
                ranked = sorted(rows, key=lambda x: (x.ninki if x.ninki and x.ninki == x.ninki else 99))
            else:
                ranked = sorted(rows, key=lambda x: (x.ability_score if x.ability_score is not None and x.ability_score == x.ability_score else 1e9))
            rank_umas = [int(r.umaban) for r in ranked]

            for sn, strat_fn in strategies:
                form_name = strat_fn(ov)
                c1n, c2n, c3n = FORMS[form_name]
                col1 = rank_umas[:c1n]
                col2 = rank_umas[:c2n]
                col3 = rank_umas[:min(c3n, len(rank_umas))]

                if tri_result:
                    win, pay = tri_result
                    tks = trifecta_tickets(col1, col2, col3)
                    pts = len(tks)
                    if pts > 0:
                        is_hit = win in tks
                        a = agg[period][rs][sn]['3連単']
                        a[0] += pts * 100
                        a[1] += pay if is_hit else 0.0
                        a[2] += 1 if is_hit else 0
                        a[3] += 1

                if trio_result:
                    win_trio, pay_trio_v = trio_result
                    tks = trio_tickets(col1, col2, col3)
                    pts = len(tks)
                    if pts > 0:
                        is_hit = win_trio in tks
                        a = agg[period][rs][sn]['3連複']
                        a[0] += pts * 100
                        a[1] += pay_trio_v if is_hit else 0.0
                        a[2] += 1 if is_hit else 0
                        a[3] += 1

    print(f"\n{'='*90}")
    print("overlap分布 (補正Tトップ3 ∩ 人気トップ3 の重複頭数)")
    print(f"{'='*90}")
    for period in ('train', 'holdout', 'recent'):
        d = overlap_dist[period]
        total = sum(d.values())
        if total == 0:
            continue
        print(f"\n  {period}: ", end='')
        for ov in range(4):
            print(f"  ov={ov}: {d[ov]:,} ({d[ov]/total:.1%})", end='')
        print(f"  total={total:,}")

    for bt in ('3連単', '3連複'):
        print(f"\n{'='*90}")
        print(f"  {bt}")
        print(f"{'='*90}")
        for period in ('holdout', 'recent', 'train'):
            marker = ' ★' if period != 'train' else ''
            print(f"\n  ── {period}{marker} ──")
            print(f"  {'Rank源':8s} {'戦略':26s} {'参加':>7s} {'的中':>6s} {'的中率':>7s} "
                  f"{'平均点':>7s} {'ROI':>7s} {'差分':>6s}")
            for rs in ('ninki', 'ability'):
                base_roi = None
                for sn, _ in strategies:
                    cost, ret, hits, n = agg[period][rs][sn][bt]
                    if n < 50:
                        continue
                    roi = ret / cost * 100 if cost else 0
                    hr = hits / n * 100 if n else 0
                    avg_pts = cost / 100 / n if n else 0
                    if base_roi is None:
                        base_roi = roi
                        diff = ''
                    else:
                        diff = f'{roi - base_roi:+.1f}'
                    print(f"  {rs:8s} {sn:26s} {n:>7,} {hits:>6,} {hr:>6.1f}% "
                          f"{avg_pts:>6.1f}  {roi:>6.1f}% {diff:>6s}")

    # overlap別の的中率・ROI内訳(最重要: 「ov≥2で本当に1着固定が有利か」)
    print(f"\n{'='*90}")
    print("overlap別 内訳 (3連単・ninki源・holdout+recent)")
    print(f"{'='*90}")

    detail = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0, 0]))
    for rk, rows in by_race.items():
        if len(rows) < MIN_HORSES:
            continue
        day = int(rows[0].day)
        yr = day // 10000
        if yr <= cd.TRAIN_END:
            continue
        if yr != cd.HOLDOUT_YEAR and day < cd.RECENT_FROM:
            continue
        ov = calc_overlap(rows)
        if ov is None:
            continue
        tri_result = pay_tri.get(rk)
        if not tri_result:
            continue
        win, pay = tri_result
        ranked = sorted(rows, key=lambda x: (x.ninki if x.ninki and x.ninki == x.ninki else 99))
        rank_umas = [int(r.umaban) for r in ranked]

        for form_name, (c1n, c2n, c3n) in FORMS.items():
            if c3n > len(rank_umas):
                c3n_adj = len(rank_umas)
            else:
                c3n_adj = c3n
            col1 = rank_umas[:c1n]
            col2 = rank_umas[:c2n]
            col3 = rank_umas[:c3n_adj]
            tks = trifecta_tickets(col1, col2, col3)
            pts = len(tks)
            if pts <= 0:
                continue
            is_hit = win in tks
            a = detail[ov][form_name]
            a[0] += pts * 100
            a[1] += pay if is_hit else 0.0
            a[2] += 1 if is_hit else 0
            a[3] += 1

    print(f"\n  {'overlap':>7s} {'形':>8s} {'参加':>7s} {'的中率':>7s} {'平均点':>6s} {'ROI':>7s}")
    for ov in range(4):
        for fn in ('1-4-7', '2-4-7', '1-5-8', '2-5-8'):
            cost, ret, hits, n = detail[ov][fn]
            if n < 30:
                continue
            roi = ret / cost * 100 if cost else 0
            hr = hits / n * 100 if n else 0
            avg_pts = cost / 100 / n if n else 0
            print(f"  ov={ov:>3d}   {fn:>8s} {n:>7,} {hr:>6.1f}% {avg_pts:>5.1f}  {roi:>6.1f}%")
        print()

    print("\n完了。")


if __name__ == '__main__':
    main()
