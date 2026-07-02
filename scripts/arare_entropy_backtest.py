# -*- coding: utf-8 -*-
"""オッズ本命不在フラグ(コンピ大穴の等価再現)の荒れ残差検証。

大谷式: コンピ1位<=79 & 1-3位差<15 & 単勝30倍未満10頭 = 大穴レース。
これをオッズで等価再現:
  fav1_odds >= N (抜けた本命不在) & odds3/odds1 <= R (上位拮抗) & live30 >= L (手広い)

プロトコル(リーク防止):
  - 閾値グリッドは 2021-2024(train) の z 最大で選択して凍結
  - 2025(holdout) で凍結閾値を評価
  - 既存の検証済みフラグ(ハンデ juryo='1' / フルゲート16頭)からの独立性は
    「非ハンデ & 10-15頭」層内での lift/z で判定
荒れ定義: 3着以内に6番人気以下が1頭以上入る。
"""
import sys
import io
import os
import math
import sqlite3
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(_ROOT, 'data', 'jravan.db')


def two_prop_z(p1, n1, p0, n0):
    """2標本比率のz検定"""
    if n1 == 0 or n0 == 0:
        return 0.0
    p = (p1 * n1 + p0 * n0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    return (p1 - p0) / se if se > 0 else 0.0


def load_races(con, y_from, y_to):
    """レース単位の特徴と荒れ結果を構築"""
    # 単勝オッズ(確定)から fav1/fav3/live30
    odds_rows = con.execute("""
        SELECT o.race_key, o.combo, o.odds, o.ninki
        FROM odds o JOIN races ra ON ra.race_key = o.race_key
        WHERE o.bet_type='win' AND ra.jyo BETWEEN '01' AND '10'
          AND ra.year BETWEEN ? AND ? AND o.odds > 0
    """, (y_from, y_to)).fetchall()
    by_race = defaultdict(list)
    for rk, combo, odds, ninki in odds_rows:
        by_race[rk].append((int(ninki) if ninki else 99, float(odds), combo))

    # 荒れ結果: 3着以内に6人気以下(人気はオッズ順位で自前計算=結果人気のnull回避)
    res_rows = con.execute("""
        SELECT r.race_key, r.umaban, r.chakujun
        FROM results r JOIN races ra ON ra.race_key = r.race_key
        WHERE ra.jyo BETWEEN '01' AND '10' AND ra.year BETWEEN ? AND ?
          AND r.chakujun BETWEEN 1 AND 3
    """, (y_from, y_to)).fetchall()
    top3_by_race = defaultdict(list)
    for rk, um, chaku in res_rows:
        top3_by_race[rk].append(str(um).zfill(2))

    meta = {rk: (juryo, int(tosu or 0)) for rk, juryo, tosu in con.execute("""
        SELECT race_key, juryo, shusso_tosu FROM races
        WHERE jyo BETWEEN '01' AND '10' AND year BETWEEN ? AND ?
    """, (y_from, y_to))}

    races = []
    for rk, lst in by_race.items():
        if rk not in top3_by_race or len(top3_by_race[rk]) < 3 or rk not in meta:
            continue
        lst.sort(key=lambda x: x[1])  # オッズ昇順=人気順
        if len(lst) < 8:
            continue
        odds_rank = {combo: i + 1 for i, (_, _, combo) in enumerate(lst)}
        fav1, fav3 = lst[0][1], lst[2][1]
        live30 = sum(1 for _, o, _ in lst if o < 30.0)
        arare = any(odds_rank.get(um, 99) >= 6 for um in top3_by_race[rk])
        juryo, tosu = meta[rk]
        races.append({'fav1': fav1, 'ratio31': fav3 / fav1, 'live30': live30,
                      'arare': arare, 'handicap': juryo == '1', 'tosu': tosu})
    return races


def eval_flag(races, fav1_min, ratio_max, live_min):
    flag = [r for r in races if r['fav1'] >= fav1_min and r['ratio31'] <= ratio_max
            and r['live30'] >= live_min]
    rest = [r for r in races if not (r['fav1'] >= fav1_min and r['ratio31'] <= ratio_max
                                     and r['live30'] >= live_min)]
    if not flag or not rest:
        return None
    p1 = sum(r['arare'] for r in flag) / len(flag)
    p0 = sum(r['arare'] for r in rest) / len(rest)
    z = two_prop_z(p1, len(flag), p0, len(rest))
    return {'n_flag': len(flag), 'n_rest': len(rest), 'p_flag': p1, 'p_rest': p0,
            'lift_pp': (p1 - p0) * 100, 'z': z}


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

    print('=== train 2021-2024 でグリッド選択 ===')
    train = load_races(con, 2021, 2024)
    print(f'train races: {len(train)} / 全体荒れ率: {sum(r["arare"] for r in train)/len(train):.1%}')

    best, best_key = None, None
    for fav1_min in (2.5, 3.0, 3.5, 4.0):
        for ratio_max in (2.0, 2.5, 3.0):
            for live_min in (8, 10, 12):
                ev = eval_flag(train, fav1_min, ratio_max, live_min)
                if ev and ev['n_flag'] >= 300:
                    if best is None or ev['z'] > best['z']:
                        best, best_key = ev, (fav1_min, ratio_max, live_min)

    f1, rm, lm = best_key
    print(f'凍結閾値: fav1>={f1} & odds3/odds1<={rm} & live30>={lm}')
    print(f'  train: flag n={best["n_flag"]} 荒れ{best["p_flag"]:.1%} vs rest {best["p_rest"]:.1%} '
          f'(+{best["lift_pp"]:.1f}pp z={best["z"]:.2f})')

    print('\n=== holdout 2025 (閾値凍結) ===')
    hold = load_races(con, 2025, 2025)
    print(f'holdout races: {len(hold)} / 全体荒れ率: {sum(r["arare"] for r in hold)/len(hold):.1%}')
    ev = eval_flag(hold, f1, rm, lm)
    print(f'  全体   : flag n={ev["n_flag"]} 荒れ{ev["p_flag"]:.1%} vs rest {ev["p_rest"]:.1%} '
          f'(+{ev["lift_pp"]:.1f}pp z={ev["z"]:.2f})')

    # 既存フラグからの独立性: 非ハンデ & 10-15頭 層
    strata = [r for r in hold if not r['handicap'] and 10 <= r['tosu'] <= 15]
    ev_s = eval_flag(strata, f1, rm, lm)
    if ev_s:
        print(f'  非ハンデ&10-15頭(独立性): flag n={ev_s["n_flag"]} 荒れ{ev_s["p_flag"]:.1%} '
              f'vs rest {ev_s["p_rest"]:.1%} (+{ev_s["lift_pp"]:.1f}pp z={ev_s["z"]:.2f})')

    # 加法性: ハンデ層内 / 16頭層内
    for label, sub in (('ハンデ層内', [r for r in hold if r['handicap']]),
                       ('16頭以上層内', [r for r in hold if r['tosu'] >= 16])):
        ev2 = eval_flag(sub, f1, rm, lm)
        if ev2 and ev2['n_flag'] >= 30:
            print(f'  {label}: flag n={ev2["n_flag"]} 荒れ{ev2["p_flag"]:.1%} '
                  f'vs rest {ev2["p_rest"]:.1%} (+{ev2["lift_pp"]:.1f}pp z={ev2["z"]:.2f})')

    # 2026 confirmatory (第2holdout)
    print('\n=== 2026 confirmatory (同閾値) ===')
    h26 = load_races(con, 2026, 2026)
    if len(h26) >= 300:
        ev3 = eval_flag(h26, f1, rm, lm)
        print(f'  全体: flag n={ev3["n_flag"]} 荒れ{ev3["p_flag"]:.1%} vs rest {ev3["p_rest"]:.1%} '
              f'(+{ev3["lift_pp"]:.1f}pp z={ev3["z"]:.2f})')
        st26 = [r for r in h26 if not r['handicap'] and 10 <= r['tosu'] <= 15]
        ev4 = eval_flag(st26, f1, rm, lm)
        if ev4:
            print(f'  非ハンデ&10-15頭: flag n={ev4["n_flag"]} 荒れ{ev4["p_flag"]:.1%} '
                  f'vs rest {ev4["p_rest"]:.1%} (+{ev4["lift_pp"]:.1f}pp z={ev4["z"]:.2f})')
    else:
        print(f'  (2026データ不足: {len(h26)}R)')

    con.close()


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace', line_buffering=True)
    main()
