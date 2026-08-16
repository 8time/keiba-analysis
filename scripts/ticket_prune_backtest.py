# -*- coding: utf-8 -*-
"""チケットプルーニング バックテスト。

2-4-7フォーメーション(30点)の全組合せを生成し、各チケットのHarville確率から
期待配当を推定。期待配当がコスト(30×100=¥3,000)未満のトリガミ圏チケットを
間引いてROIが改善するか検証する。ゾーン別(D鉄板/C中庸/荒れ)で分割。

pruning方式:
  A) トリガミカット: 期待配当<コストの組合せを除外
  B) 上位N点のみ残す: 確率上位15/20/25点だけ買う
  C) 下位カット: 確率最低5/10点を除外(来ない穴を切る)
  D) ゾーン適応: D鉄板→上位15点 / C中庸→全30点 / 荒れ→見送り

Usage:
  python scripts/ticket_prune_backtest.py
"""
import os
import sys
import io
import math
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8
TAKEOUT = 0.25


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


def harville_prob(a, b, c, prob_map):
    """Harvilleモデルで3連単(a→b→c)の確率を返す。"""
    pa = prob_map.get(a, 0)
    pb = prob_map.get(b, 0)
    pc = prob_map.get(c, 0)
    if pa <= 0 or pb <= 0 or pc <= 0:
        return 0.0
    d1 = 1.0 - pa
    if d1 <= 0:
        return 0.0
    d2 = d1 - pb
    if d2 <= 0:
        return 0.0
    return pa * (pb / d1) * (pc / d2)


def make_tickets_247(ranked_umas):
    """2-4-7フォーメーションの全チケットを生成。"""
    col1 = ranked_umas[:2]
    col2 = ranked_umas[:4]
    col3 = ranked_umas[:min(7, len(ranked_umas))]
    tickets = []
    for a in col1:
        for b in col2:
            if b == a:
                continue
            for c in col3:
                if c == a or c == b:
                    continue
                tickets.append((a, b, c))
    return tickets


def main():
    print("3連単配当 読み込み...")
    pay_map = load_trifecta_payouts()
    print(f"  {len(pay_map):,}レース")

    print("CSV特徴ストア 読み込み...")
    df = cd.load_horses(cols=['race_key', 'day', 'ninki', 'win_odds',
                              'ability_score', 'chakujun', 'umaban',
                              'is_handi1', 'top3'])
    df = df[df['umaban'].notna() & df['win_odds'].notna()]
    df['race_key'] = df['race_key'].astype(str)
    by_race = defaultdict(list)
    for r in df.itertuples(index=False):
        by_race[r.race_key].append(r)

    # 戦略定義: (名前, prune関数(tickets, prob_map, total_cost) -> filtered_tickets)
    def prune_full(tks, pm, cost):
        return tks

    def prune_torigami(tks, pm, cost):
        out = []
        for t in tks:
            hp = harville_prob(t[0], t[1], t[2], pm)
            if hp <= 0:
                out.append(t)
                continue
            exp_pay = (1.0 - TAKEOUT) / hp
            if exp_pay * 100 >= cost:
                out.append(t)
        return out

    def prune_top_n(n):
        def fn(tks, pm, cost):
            scored = [(t, harville_prob(t[0], t[1], t[2], pm)) for t in tks]
            scored.sort(key=lambda x: -x[1])
            return [t for t, _ in scored[:n]]
        return fn

    def prune_drop_bottom(n):
        def fn(tks, pm, cost):
            scored = [(t, harville_prob(t[0], t[1], t[2], pm)) for t in tks]
            scored.sort(key=lambda x: -x[1])
            return [t for t, _ in scored[:-n]] if len(scored) > n else [scored[0][0]]
        return fn

    def prune_drop_top(n):
        """確率上位N点(=トリガミ圏の本命組合せ)を除外。"""
        def fn(tks, pm, cost):
            scored = [(t, harville_prob(t[0], t[1], t[2], pm)) for t in tks]
            scored.sort(key=lambda x: -x[1])
            return [t for t, _ in scored[n:]]
        return fn

    strategies = [
        ('全30点(baseline)',     prune_full),
        ('トリガミカット',        prune_torigami),
        ('上位20点のみ',         prune_top_n(20)),
        ('上位15点のみ',         prune_top_n(15)),
        ('上位10点のみ',         prune_top_n(10)),
        ('下位5点カット(25点)',   prune_drop_bottom(5)),
        ('下位10点カット(20点)', prune_drop_bottom(10)),
        ('上位5点カット(25点)',   prune_drop_top(5)),
        ('上位10点カット(20点)', prune_drop_top(10)),
    ]

    # {period: {zone: {strat: [cost, ret, hits, n, torigami_count]}}}
    zones = ['D鉄板', 'C中庸', '荒れ', '全体']
    agg = {}
    for period in ('train', 'holdout', 'recent'):
        agg[period] = {}
        for z in zones:
            agg[period][z] = {}
            for sn, _ in strategies:
                agg[period][z][sn] = [0.0, 0.0, 0, 0, 0]

    # 配当分布の記録(ゾーン別)
    payout_dist = {z: [] for z in zones[:3]}
    torigami_stats = {z: [0, 0] for z in zones[:3]}  # [total_races, torigami_races]

    skipped_no_odds = 0
    processed = 0

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

        tri_result = pay_map.get(rk)
        if not tri_result:
            continue

        odds_list = [r.win_odds for r in rows if r.win_odds and r.win_odds > 0]
        if len(odds_list) < 3:
            skipped_no_odds += 1
            continue

        ap = vs.arare_prob(odds_list, {'is_handicap': bool(rows[0].is_handi1)}, len(rows))
        if ap is None:
            continue

        if ap < 0.50:
            zone = 'D鉄板'
        elif ap < 0.70:
            zone = 'C中庸'
        else:
            zone = '荒れ'

        # prob_map: 馬番→勝率(Harville用)
        total_inv_odds = sum(1.0 / r.win_odds for r in rows if r.win_odds and r.win_odds > 0)
        if total_inv_odds <= 0:
            continue
        prob_map = {}
        for r in rows:
            if r.win_odds and r.win_odds > 0:
                prob_map[int(r.umaban)] = (1.0 / r.win_odds) / total_inv_odds

        ranked = sorted(rows, key=lambda x: (x.ninki if x.ninki and x.ninki == x.ninki else 99))
        rank_umas = [int(r.umaban) for r in ranked]

        all_tickets = make_tickets_247(rank_umas)
        if not all_tickets:
            continue
        total_cost = len(all_tickets) * 100

        win, pay = tri_result
        processed += 1

        # 配当分布の記録(holdout+recentのみ)
        if period in ('holdout', 'recent') and win in set(all_tickets):
            payout_dist[zone].append(pay)
            torigami_stats[zone][0] += 1
            if pay < total_cost:
                torigami_stats[zone][1] += 1

        for sn, prune_fn in strategies:
            pruned = prune_fn(all_tickets, prob_map, total_cost)
            if not pruned:
                continue
            pts = len(pruned)
            cost = pts * 100
            is_hit = win in set(pruned)

            for z in (zone, '全体'):
                a = agg[period][z][sn]
                a[0] += cost
                a[1] += pay if is_hit else 0.0
                a[2] += 1 if is_hit else 0
                a[3] += 1
                if is_hit and pay < cost:
                    a[4] += 1

    print(f"\n処理: {processed:,}レース (オッズ不足スキップ: {skipped_no_odds})")

    # トリガミ実態(holdout+recent)
    print(f"\n{'='*90}")
    print("■ トリガミ実態（2-4-7で的中したレースのうち配当<¥3,000）")
    print(f"{'='*90}")
    for z in zones[:3]:
        total, tri_n = torigami_stats[z]
        if total > 0:
            rate = tri_n / total * 100
            pays = sorted(payout_dist[z])
            med = pays[len(pays) // 2] if pays else 0
            p25 = pays[len(pays) // 4] if len(pays) >= 4 else 0
            p75 = pays[3 * len(pays) // 4] if len(pays) >= 4 else 0
            print(f"  {z:6s}: 的中{total:,}R中 トリガミ{tri_n:,}R ({rate:.1f}%)"
                  f"  配当中央¥{med:,.0f}  25%ile ¥{p25:,.0f}  75%ile ¥{p75:,.0f}")

    # メイン結果
    for period in ('holdout', 'recent', 'train'):
        marker = ' ★' if period != 'train' else ''
        print(f"\n{'='*90}")
        print(f"  {period}{marker}")
        print(f"{'='*90}")
        for z in zones:
            first_n = None
            print(f"\n  ── {z} ──")
            print(f"  {'戦略':22s} {'参加':>7s} {'的中':>6s} {'的中率':>7s} "
                  f"{'平均点':>6s} {'ROI':>7s} {'差分':>6s} {'ﾄﾘｶﾞﾐ':>5s}")
            for sn, _ in strategies:
                cost, ret, hits, n, tori = agg[period][z][sn]
                if n < 30:
                    continue
                roi = ret / cost * 100 if cost else 0
                hr = hits / n * 100 if n else 0
                avg_pts = cost / 100 / n if n else 0
                if first_n is None:
                    first_n = roi
                    diff = ''
                else:
                    diff = f'{roi - first_n:+.1f}'
                print(f"  {sn:22s} {n:>7,} {hits:>6,} {hr:>6.1f}% "
                      f"{avg_pts:>5.1f}  {roi:>6.1f}% {diff:>6s} {tori:>5d}")

    # ゾーン適応型(D鉄板→上位15/C中庸→全30/荒れ→見送り)の合成
    print(f"\n{'='*90}")
    print("■ ゾーン適応型の合成(holdout+recent)")
    print(f"{'='*90}")
    combos = [
        ('A: D→15点/C→30点/荒→skip', {'D鉄板': '上位15点のみ', 'C中庸': '全30点(baseline)', '荒れ': None}),
        ('B: D→20点/C→30点/荒→skip', {'D鉄板': '上位20点のみ', 'C中庸': '全30点(baseline)', '荒れ': None}),
        ('C: D→下5カット/C→30点/荒→skip', {'D鉄板': '下位5点カット(25点)', 'C中庸': '全30点(baseline)', '荒れ': None}),
        ('D: D→トリガミカット/C→30点/荒→skip', {'D鉄板': 'トリガミカット', 'C中庸': '全30点(baseline)', '荒れ': None}),
        ('E: 全ゾーン全30点(baseline)', {'D鉄板': '全30点(baseline)', 'C中庸': '全30点(baseline)', '荒れ': '全30点(baseline)'}),
        ('F: D→トリガミカット/C→トリガミカット/荒→skip', {'D鉄板': 'トリガミカット', 'C中庸': 'トリガミカット', '荒れ': None}),
        ('G: D→上位5カット/C→30点/荒→skip', {'D鉄板': '上位5点カット(25点)', 'C中庸': '全30点(baseline)', '荒れ': None}),
        ('H: D→上位5カット/C→上位5カット/荒→skip', {'D鉄板': '上位5点カット(25点)', 'C中庸': '上位5点カット(25点)', '荒れ': None}),
    ]
    print(f"  {'戦略':42s} {'参加':>7s} {'的中':>6s} {'的中率':>7s} {'平均点':>6s} {'ROI':>7s}")
    for label, zmap in combos:
        total_cost = total_ret = total_hits = total_n = 0
        for period in ('holdout', 'recent'):
            for z in ('D鉄板', 'C中庸', '荒れ'):
                sn = zmap.get(z)
                if sn is None:
                    continue
                cost, ret, hits, n, _ = agg[period][z][sn]
                total_cost += cost
                total_ret += ret
                total_hits += hits
                total_n += n
        if total_n < 30:
            continue
        roi = total_ret / total_cost * 100 if total_cost else 0
        hr = total_hits / total_n * 100 if total_n else 0
        avg_pts = total_cost / 100 / total_n if total_n else 0
        print(f"  {label:42s} {total_n:>7,} {total_hits:>6,} {hr:>6.1f}% "
              f"{avg_pts:>5.1f}  {roi:>6.1f}%")

    print("\n完了。")


if __name__ == '__main__':
    main()
