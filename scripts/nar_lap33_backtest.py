# -*- coding: utf-8 -*-
"""33ラップ理論のNAR横展開バックテスト。

JRAでの検証結果: 人気薄(6番人気+)×適合=複勝残差+0.9pp(train/holdout安定・z+6.8/+3.3)

NARデータ形式(nar_official.db):
- racelist.lap_N: 200m毎のラップ(秒)。1200m=6本, 1400m=7本, 1600m=8本, ...
- racelist.last_3f: レース全体の上がり3F(秒)
- horselist.last_3f: 各馬の上がり3F(秒)
- horselist.time_raw: 走破タイム MSSt形式(1164 = 1:16.4 = 76.4秒)

前半3F = lap_1 + lap_2 + lap_3 (200m × 3 = 600m)
33ラップ = 中盤3F相当ペース − 上がり3F
中盤3F相当ペース = (全タイム - 前半3F - 上がり3F) × 600 / (距離 - 1200)
1200m以下は mid = 前半3F (中盤が無いので前半のみ)
"""
import os
import sqlite3
import sys
import io
import math
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'nar_official.db')


def main():
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)

    venues = ('大井', '船橋', '川崎', '浦和')

    # Step 0: ラップ構造の検証
    print('=== Step 0: ラップ構造の検証 ===')
    for row in con.execute('''
        SELECT venue, race_date, race_no, distance, last_3f,
               lap_1, lap_2, lap_3, lap_4, lap_5, lap_6, lap_7, lap_8
        FROM racelist
        WHERE venue='大井' AND last_3f IS NOT NULL AND lap_1 IS NOT NULL
          AND race_date >= '20240101'
        LIMIT 3
    '''):
        dist = row[3]
        n_laps = dist // 200
        laps = [x for x in row[5:5+n_laps] if x is not None]
        mae3f = sum(laps[:3])
        lap_total = sum(laps)
        print(f'  {row[1]} {row[2]}R {dist}m: 前3F(lap1-3)={mae3f:.1f} '
              f'上3F={row[4]:.1f} ラップ合計={lap_total:.1f} ({len(laps)}/{n_laps}本)')

    # Step 1: レースの33ラップ算出(2010-2025)
    print('\n=== Step 1: レースの33ラップ算出(南関4場) ===')
    races = con.execute(f'''
        SELECT r.venue, r.race_date, r.race_no, r.distance, r.last_3f,
               r.lap_1, r.lap_2, r.lap_3, r.lap_4, r.lap_5, r.lap_6,
               r.lap_7, r.lap_8, r.lap_9, r.lap_10, r.lap_11, r.lap_12,
               r.lap_13, r.lap_14, r.lap_15
        FROM racelist r
        WHERE r.venue IN ({",".join("?" * len(venues))})
          AND r.race_date >= '20100101' AND r.race_date <= '20251231'
          AND r.last_3f IS NOT NULL AND r.lap_1 IS NOT NULL
    ''', venues).fetchall()
    print(f'  ラップ付きレース数: {len(races):,}')

    course_vals = defaultdict(list)
    race_mid = {}

    for row in races:
        venue, date, rno, dist, race_ato3f = row[0], row[1], row[2], row[3], row[4]
        if dist is None or dist < 800 or race_ato3f is None:
            continue

        n_laps = dist // 200
        laps = list(row[5:5 + n_laps])
        if len(laps) < 3 or any(x is None for x in laps):
            continue

        mae3f = sum(laps[:3])  # 200m × 3 = 600m = 前半3F
        race_time = sum(laps)

        if dist <= 1200:
            mid = mae3f
        else:
            mid_len = dist - 1200
            mid_time = race_time - mae3f - race_ato3f
            if mid_time <= 0 or mid_len <= 0:
                continue
            mid = mid_time * 600.0 / mid_len

        lap33_val = mid - race_ato3f
        course_vals[(venue, dist)].append(lap33_val)
        race_mid[(venue, date, rno)] = mid

    print(f'  33ラップ算出可能レース: {len(race_mid):,}')

    print(f'\n  コース別平均33ラップ(n≥50):')
    print(f'  {"コース":>12} {"平均33":>7} {"SD":>6} {"n":>6}')
    for (v, d), vals in sorted(course_vals.items(), key=lambda x: (x[0][0], x[0][1])):
        if len(vals) < 50:
            continue
        avg = sum(vals) / len(vals)
        sd = (sum((x - avg) ** 2 for x in vals) / len(vals)) ** 0.5
        print(f'  {v}{d}m{"":<5} {avg:>+7.2f} {sd:>6.2f} {len(vals):>6,}')

    course_avg = {k: sum(v) / len(v) for k, v in course_vals.items() if len(v) >= 20}

    # Step 2: 馬の過去走33ラップ蓄積
    print('\n=== Step 2: 馬の過去走33ラップ蓄積 ===')
    horse_history = defaultdict(list)

    for row in con.execute(f'''
        SELECT h.venue, h.race_date, h.race_no, h.horse_no, h.horse_name,
               h.last_3f
        FROM horselist h
        WHERE h.venue IN ({",".join("?" * len(venues))})
          AND h.race_date >= '20100101' AND h.race_date <= '20251231'
          AND h.last_3f IS NOT NULL
    ''', venues).fetchall():
        venue, date, rno, hno, name, h_ato = row
        mid = race_mid.get((venue, date, rno))
        if mid is None:
            continue
        try:
            h_ato_f = float(h_ato)
        except (TypeError, ValueError):
            continue
        val = mid - h_ato_f
        horse_history[name].append((date, val))

    for name in horse_history:
        horse_history[name].sort(key=lambda x: x[0])

    print(f'  過去走33ラップ保有馬数: {len(horse_history):,}')

    # Step 3: バックテスト(2016-2025)
    print('\n=== Step 3: 適合 × 人気帯別 複勝率 ===')
    horses = con.execute(f'''
        SELECT h.venue, h.race_date, h.race_no, h.horse_no, h.horse_name,
               h.last_3f, h.finish_pos, h.popularity,
               r.distance
        FROM horselist h JOIN racelist r
          ON r.venue=h.venue AND r.race_date=h.race_date AND r.race_no=h.race_no
        WHERE h.venue IN ({",".join("?" * len(venues))})
          AND h.race_date >= '20160101' AND h.race_date <= '20251231'
          AND h.finish_pos IS NOT NULL AND h.finish_pos != ''
          AND h.popularity IS NOT NULL AND h.popularity != ''
    ''', venues).fetchall()
    print(f'  出走データ: {len(horses):,} 頭')

    def run_backtest(horse_rows, lo, hi, label, min_past=2):
        fit_stats = defaultdict(lambda: [0, 0])
        n_eval = 0
        for row in horse_rows:
            venue, date, rno, hno, name, h_ato, fpos, pop, dist = row
            if date < lo or date > hi or dist is None:
                continue
            try:
                fpos_int = int(fpos)
                pop_int = int(pop)
            except (TypeError, ValueError):
                continue
            cavg = course_avg.get((venue, dist))
            if cavg is None:
                continue
            history = horse_history.get(name, [])
            past = [v for d, v in history if d < date]
            if len(past) < min_past:
                continue
            horse_avg = sum(past) / len(past)
            is_fit = (horse_avg > 0) == (cavg > 0)
            is_top3 = fpos_int <= 3
            if pop_int <= 3:
                bucket = '1-3'
            elif pop_int <= 5:
                bucket = '4-5'
            else:
                bucket = '6+'
            fit_stats[(bucket, is_fit)][0] += 1
            fit_stats[(bucket, is_fit)][1] += is_top3
            n_eval += 1

        print(f'\n  {label} (n={n_eval:,})')
        print(f'  {"人気帯":>6} {"適合":>6} {"頭数":>8} {"3着内":>6} {"3着内率":>7} {"残差":>7}')
        for bucket in ['1-3', '4-5', '6+']:
            for is_fit in [True, False]:
                key = (bucket, is_fit)
                total, top3 = fit_stats[key]
                if total == 0:
                    continue
                rate = top3 / total * 100
                other = fit_stats[(bucket, not is_fit)]
                base = (other[1] / other[0] * 100) if other[0] > 0 else 0
                resid = rate - base
                lbl = '適合' if is_fit else '不適合'
                print(f'  {bucket:>6} {lbl:>6} {total:>8,} {top3:>6,} {rate:>6.1f}% {resid:>+6.1f}pp')

        # 6+のz-score
        n1, h1 = fit_stats[('6+', True)]
        n0, h0 = fit_stats[('6+', False)]
        if n1 > 0 and n0 > 0:
            p1 = h1 / n1
            p0 = h0 / n0
            p_pool = (h1 + h0) / (n1 + n0)
            se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n0))
            z = (p1 - p0) / se if se > 0 else 0
            print(f'  → 6+人気: 適合{p1*100:.1f}% vs 不適合{p0*100:.1f}% = '
                  f'{(p1-p0)*100:+.1f}pp  z={z:+.2f}')
        return fit_stats

    run_backtest(horses, '20160101', '20251231', '全期間(2016-2025)')
    run_backtest(horses, '20160101', '20221231', 'Train(2016-2022)')
    run_backtest(horses, '20230101', '20251231', 'Holdout(2023-2025)')

    # Step 4: 場別(6+人気のみ)
    print('\n=== Step 4: 場別(6+人気・全期間) ===')
    for target_venue in venues:
        fit_stats = defaultdict(lambda: [0, 0])
        for row in horses:
            venue, date, rno, hno, name, h_ato, fpos, pop, dist = row
            if venue != target_venue:
                continue
            try:
                pop_int = int(pop)
                fpos_int = int(fpos)
            except (TypeError, ValueError):
                continue
            if pop_int < 6:
                continue
            cavg = course_avg.get((venue, dist))
            if cavg is None:
                continue
            history = horse_history.get(name, [])
            past = [v for d, v in history if d < date]
            if len(past) < 2:
                continue
            horse_avg = sum(past) / len(past)
            is_fit = (horse_avg > 0) == (cavg > 0)
            is_top3 = fpos_int <= 3
            fit_stats[is_fit][0] += 1
            fit_stats[is_fit][1] += is_top3

        n1, h1 = fit_stats[True]
        n0, h0 = fit_stats[False]
        if n1 > 0 and n0 > 0:
            p1 = h1 / n1
            p0 = h0 / n0
            p_pool = (h1 + h0) / (n1 + n0)
            se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n0))
            z = (p1 - p0) / se if se > 0 else 0
            print(f'  {target_venue}: 適合{p1*100:.1f}%({n1:,}) vs '
                  f'不適合{p0*100:.1f}%({n0:,}) = {(p1-p0)*100:+.1f}pp z={z:+.2f}')

    con.close()
    print('\n完了')


if __name__ == '__main__':
    main()
