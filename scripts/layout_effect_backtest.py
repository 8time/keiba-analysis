# -*- coding: utf-8 -*-
"""コースレイアウト拡充(94エントリ+内/外バグ修正)の効果測定。

比較:
  A) layout = get_course_layout(venue, surf, dist)  ← 拡充済み
  B) layout = {}                                     ← デフォルト(gate_w=0.45固定)
各レースで estimate_pace_map → 直線の順位 vs 実着順 の Spearman ρ を比較。
追加: first_corner ヒット率（拡充前は~20/94エントリ分だけヒット→拡充後はどれだけカバー）。
"""
import os, sys, sqlite3, statistics
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import pace_map as pm

DB = jj.JV_DB_PATH


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    def _ranks(v):
        idx = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        for rank, i in enumerate(idx):
            r[i] = rank
        return r
    rx, ry = _ranks(xs), _ranks(ys)
    mx = sum(rx) / n; my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = (sum((a - mx) ** 2 for a in rx)) ** 0.5
    sy = (sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / (sx * sy) if sx * sy else 0.0


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='yfrom', type=int, default=2023)
    ap.add_argument('--to', dest='yto', type=int, default=2025)
    ap.add_argument('--min-tosu', type=int, default=8, dest='min_tosu')
    ap.add_argument('--sample-every', type=int, default=5, dest='sample_every')
    ap.add_argument('--limit', type=int, default=2000)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print('レース読み込み中...')
    races = con.execute(
        "SELECT race_key, kyori, surface, shusso_tosu FROM races "
        "WHERE CAST(year AS INTEGER) BETWEEN ? AND ? AND shusso_tosu >= ?",
        (args.yfrom, args.yto, args.min_tosu)).fetchall()
    races = races[::args.sample_every]
    if len(races) > args.limit:
        races = races[:args.limit]
    print(f"  サンプル {len(races):,}レース")

    rho_with = []
    rho_without = []
    fc_hit = 0
    fc_total = 0

    for idx, race in enumerate(races):
        rk = race['race_key']
        kyori = race['kyori']
        surf = race['surface']

        runners = con.execute(
            "SELECT ketto_num, bamei, umaban, ninki, chakujun "
            "FROM results WHERE race_key=? AND chakujun > 0 AND umaban > 0",
            (rk,)).fetchall()
        if len(runners) < args.min_tosu:
            continue

        actual = {r['umaban']: r['chakujun'] for r in runners}
        names = [r['bamei'] for r in runners]

        profiles = pm.fetch_jv_profiles(names, max_runs=8,
                                        surface=surf, distance=kyori,
                                        before_key=rk)

        horses = []
        extras = {}
        for r in runners:
            u = r['umaban']
            prof = profiles.get(r['bamei'])
            sc = prof['ten'] if prof and prof.get('ten') is not None else 0.5
            horses.append({
                'umaban': u, 'name': r['bamei'],
                'score': sc, 'style': pm.style_from_score(sc),
            })
            ex = {}
            if r['ninki'] and r['ninki'] > 0:
                ex['pop'] = r['ninki']
            p = profiles.get(r['bamei']) or {}
            if p.get('agari') is not None:
                ex['kick'] = p['agari']
            if p.get('finish_hist') is not None:
                ex['power'] = p['finish_hist']
            if ex:
                extras[u] = ex

        venue = pm.venue_from_race_id(rk)
        ssurf = 'ダ' if 'ダ' in str(surf) else '芝'

        # A: with layout
        layout_a = pm.get_course_layout(venue, ssurf, kyori)
        fc_total += 1
        if layout_a.get('first_corner') is not None:
            fc_hit += 1

        pm_a = pm.estimate_pace_map(horses, distance=kyori, profiles=profiles,
                                     layout=layout_a, surface=surf, extras=extras)
        # B: without layout (defaults)
        pm_b = pm.estimate_pace_map(horses, distance=kyori, profiles=profiles,
                                     layout={}, surface=surf, extras=extras)

        if not pm_a or not pm_b:
            continue

        phases_a = list(pm_a.keys())
        phases_b = list(pm_b.keys())
        final_a = pm_a[phases_a[-1]]
        final_b = pm_b[phases_b[-1]]

        us_a = [r['umaban'] for r in final_a]
        pred_a = [r['x'] for r in final_a]
        real_a = [actual.get(u, 99) for u in us_a]
        # x is higher=more forward=better → negate for rank correlation with chakujun
        rho_a = spearman([-x for x in pred_a], real_a)

        us_b = [r['umaban'] for r in final_b]
        pred_b = [r['x'] for r in final_b]
        real_b = [actual.get(u, 99) for u in us_b]
        rho_b = spearman([-x for x in pred_b], real_b)

        if rho_a is not None:
            rho_with.append(rho_a)
        if rho_b is not None:
            rho_without.append(rho_b)

        if (idx + 1) % 200 == 0:
            print(f"  {idx+1}/{len(races)} 処理中...")

    con.close()

    n = min(len(rho_with), len(rho_without))
    print(f"\n{'='*60}")
    print(f"コースレイアウト拡充 効果測定")
    print(f"対象: {args.yfrom}-{args.yto}, {args.min_tosu}頭以上")
    print(f"{'='*60}")
    print(f"first_corner ヒット率: {fc_hit}/{fc_total} = {fc_hit/fc_total*100:.1f}%")
    print()

    m_w = sum(rho_with) / len(rho_with) if rho_with else 0
    m_wo = sum(rho_without) / len(rho_without) if rho_without else 0
    sd_w = statistics.stdev(rho_with) if len(rho_with) > 1 else 0
    sd_wo = statistics.stdev(rho_without) if len(rho_without) > 1 else 0

    print(f"{'条件':>20} | {'レース':>6} | {'Spearman ρ':>10} | {'SD':>8}")
    print(f"{'-'*20}-+-{'-'*6}-+-{'-'*10}-+-{'-'*8}")
    print(f"{'With layout':>20} | {len(rho_with):>6} | {m_w:>10.4f} | {sd_w:>8.4f}")
    print(f"{'Without layout':>20} | {len(rho_without):>6} | {m_wo:>10.4f} | {sd_wo:>8.4f}")
    diff = m_w - m_wo
    print(f"\n差分: {diff:+.4f} ({'改善' if diff > 0 else '悪化' if diff < 0 else '変化なし'})")

    # ペア差の有意性(paired)
    if n >= 10:
        diffs = [rho_with[i] - rho_without[i] for i in range(n)]
        md = sum(diffs) / n
        sd_d = (sum((d - md) ** 2 for d in diffs) / (n - 1)) ** 0.5
        t = md / (sd_d / n ** 0.5) if sd_d > 0 else 0
        print(f"paired t = {t:.2f} (n={n}, |t|>2.0 で有意)")


if __name__ == '__main__':
    main()
