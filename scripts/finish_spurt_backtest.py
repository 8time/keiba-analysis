# -*- coding: utf-8 -*-
"""predict_finish に末脚指数(spurt_index)を投入したときの着順予測精度バックテスト。

検証: spurt_index を w_spurt で加えると、Spearman相関が改善するか？
  baseline = w_spurt=0（現行モデル: pos4+kick+power+pop）
  candidate = w_spurt を 0.1〜0.8 で走査し、最良を探す

方法:
  1. JVからテストレースを抽出（2023-25, 8頭以上）
  2. 各レースで before_key を使い「事前データのみ」で
     fetch_jv_profiles / spurt_index / predict_finish を実行
  3. 予測finish順位 vs 実着順の Spearman ρ を全レースで集計
  4. baseline(w_spurt=0) と candidate を比較
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
        return 0.0
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
    ap.add_argument('--limit', type=int, default=3000, help='max races to evaluate')
    ap.add_argument('--sample-every', type=int, default=3, dest='sample_every',
                    help='evaluate every Nth race (speed)')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print('レース読み込み中...')
    races = con.execute(
        "SELECT race_key, kyori, surface, shusso_tosu FROM races "
        "WHERE CAST(year AS INTEGER) BETWEEN ? AND ? AND shusso_tosu >= ?",
        (args.yfrom, args.yto, args.min_tosu)).fetchall()
    print(f"  {len(races):,}レース (>={args.min_tosu}頭, {args.yfrom}-{args.yto})")

    # サンプリング
    races = races[::args.sample_every]
    if len(races) > args.limit:
        races = races[:args.limit]
    print(f"  サンプル {len(races):,}レース")

    # w_spurt 候補
    w_candidates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8]
    rho_by_w = {w: [] for w in w_candidates}
    top3_hit_by_w = {w: [0, 0] for w in w_candidates}  # [hit, total]

    for idx, race in enumerate(races):
        rk = race['race_key']
        kyori = race['kyori']
        surf = race['surface']
        tosu = race['shusso_tosu']

        # 出走馬
        runners = con.execute(
            "SELECT ketto_num, bamei, umaban, ninki, chakujun "
            "FROM results WHERE race_key=? AND chakujun > 0 AND umaban > 0",
            (rk,)).fetchall()
        if len(runners) < args.min_tosu:
            continue

        actual = {r['umaban']: r['chakujun'] for r in runners}
        names = [r['bamei'] for r in runners]
        umaban_of = {r['bamei']: r['umaban'] for r in runners}

        # JVプロファイル（before_key で未来遮断）
        profiles = pm.fetch_jv_profiles(names, max_runs=8,
                                        surface=surf, distance=kyori,
                                        before_key=rk)

        # 各馬の spurt_index
        spurt_map = {}
        for r in runners:
            si, sr = jj._spurt_index(con, r['ketto_num'],
                                      [r2['race_key'] for r2 in con.execute(
                                          "SELECT race_key FROM results WHERE ketto_num=? "
                                          "AND race_key<? AND chakujun>0 ORDER BY race_key DESC LIMIT 8",
                                          (r['ketto_num'], rk)).fetchall()])
            if si is not None and sr >= 2:
                spurt_map[r['umaban']] = -si  # 高い=良い → 反転して0=最良

        # 各馬のhorses構造 + extras
        horses = []
        extras = {}
        for r in runners:
            u = r['umaban']
            sc = pm.score_from_pastruns([])  # 0.5 default
            prof = profiles.get(r['bamei'])
            if prof and prof.get('ten') is not None:
                sc = prof['ten']
            horses.append({
                'umaban': u,
                'name': r['bamei'],
                'score': sc,
                'style': pm.style_from_score(sc),
            })
            ex = {}
            if r['ninki'] and r['ninki'] > 0:
                ex['pop'] = r['ninki']
            p = profiles.get(r['bamei']) or {}
            if p.get('agari') is not None:
                ex['kick'] = p['agari']
            if p.get('finish_hist') is not None:
                ex['power'] = p['finish_hist']
            if u in spurt_map:
                ex['spurt'] = spurt_map[u]
            if ex:
                extras[u] = ex

        # コースレイアウト
        venue = pm.venue_from_race_id(rk)
        ssurf = 'ダ' if 'ダ' in str(surf) else '芝'
        layout = pm.get_course_layout(venue, ssurf, kyori)

        # build_pace_context
        ctx = pm.build_pace_context(horses, profiles, kyori, surf, layout)

        # predict_finish を各 w_spurt で
        for w in w_candidates:
            tune = {'w_spurt': w}
            finish = pm.predict_finish(horses, profiles, ctx, extras=extras, tune=tune)
            if len(finish) < args.min_tosu:
                continue
            us = sorted(finish.keys())
            pred = [finish[u] for u in us]
            real = [actual.get(u, 99) for u in us]
            rho = spearman(pred, real)
            rho_by_w[w].append(rho)
            # top3 hit: 予測上位3頭に実際の1着が含まれるか
            top3_pred = sorted(us, key=lambda u: finish[u])[:3]
            winner = min(actual, key=lambda u: actual[u])
            top3_hit_by_w[w][1] += 1
            if winner in top3_pred:
                top3_hit_by_w[w][0] += 1

        if (idx + 1) % 200 == 0:
            print(f"  {idx+1}/{len(races)} 処理中...")

    con.close()

    print(f"\n{'='*70}")
    print(f"predict_finish 末脚指数(w_spurt)較正バックテスト")
    print(f"対象: {args.yfrom}-{args.yto}, {args.min_tosu}頭以上, "
          f"sample_every={args.sample_every}")
    print(f"{'='*70}")
    print(f"{'w_spurt':>8} | {'レース数':>8} | {'Spearman ρ':>10} | {'ρ SD':>8} | "
          f"{'Top3的中':>8} | {'改善(ρ)':>8}")
    print(f"{'-'*8}-+-{'-'*8}-+-{'-'*10}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")

    base_rho = None
    best_w = 0.0
    best_rho = -1.0
    for w in w_candidates:
        vals = rho_by_w[w]
        n = len(vals)
        if n == 0:
            continue
        m = sum(vals) / n
        sd = statistics.stdev(vals) if n > 1 else 0
        hit, total = top3_hit_by_w[w]
        hit_pct = hit / total * 100 if total else 0
        if w == 0.0:
            base_rho = m
        diff = (m - base_rho) if base_rho is not None else 0
        sign = '+' if diff > 0 else ''
        print(f"{w:8.1f} | {n:8d} | {m:10.4f} | {sd:8.4f} | {hit_pct:7.1f}% | {sign}{diff:.4f}")
        if m > best_rho:
            best_rho = m
            best_w = w

    print(f"\n最良 w_spurt = {best_w:.1f} (ρ = {best_rho:.4f})")
    if base_rho is not None and best_rho > base_rho + 0.002:
        print(f"→ ベースライン比 +{best_rho - base_rho:.4f} 改善。採用推奨。")
    else:
        print(f"→ 改善幅が小さい or 悪化。w_spurt=0（無効）のまま据え置き。")


if __name__ == '__main__':
    main()
