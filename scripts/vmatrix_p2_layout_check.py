# -*- coding: utf-8 -*-
"""
P2-D1b — コース layout の展開MAP最終直線 x への追加効果（holdout・調査専用）。

layout_effect_backtest.py と同型:
  A: layout={}（なし）
  B: layout=get_course_layout(...)（既存あり）
  正解: chakujun / 予測: estimate_pace_map 最終フェーズ x / 指標: Spearman ρ

本番非接続。core/ app.py 変更禁止。
"""
import json
import os
import statistics
import sys
import sqlite3
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import jockey_jv as jj
from core import pace_map as pm

DB = jj.JV_DB_PATH
OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'vmatrix_p2_d')
HOLDOUT_FROM = 2024
HOLDOUT_TO = 2025
SUCCESS_DELTA = 0.02


def spearman(xs, ys):
    """layout_effect_backtest.py と同一。"""
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
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = (sum((a - mx) ** 2 for a in rx)) ** 0.5
    sy = (sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / (sx * sy) if sx * sy else 0.0


def connect_db():
    for attempt in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
        except sqlite3.OperationalError:
            time.sleep(4)
    return sqlite3.connect(DB)


def eval_period(con, yfrom, yto, min_tosu=8, sample_every=1, limit=None):
    """1期間を評価。paired (rho_a, rho_b) をレース単位で返す。"""
    races = con.execute(
        "SELECT race_key, kyori, surface, shusso_tosu FROM races "
        "WHERE CAST(year AS INTEGER) BETWEEN ? AND ? AND shusso_tosu >= ? "
        "ORDER BY race_key",
        (yfrom, yto, min_tosu)).fetchall()
    if sample_every > 1:
        races = races[::sample_every]
    if limit and len(races) > limit:
        races = races[:limit]

    paired = []
    fc_hit = fc_total = 0
    skipped_map = 0
    skipped_tosu = 0

    for idx, (rk, kyori, surf, _tosu) in enumerate(races):
        runners = con.execute(
            "SELECT bamei, umaban, ninki, chakujun "
            "FROM results WHERE race_key=? AND chakujun > 0 AND umaban > 0",
            (rk,)).fetchall()
        if len(runners) < min_tosu:
            skipped_tosu += 1
            continue

        actual = {r[1]: r[3] for r in runners}
        names = [r[0] for r in runners]

        profiles = pm.fetch_jv_profiles(
            names, max_runs=8, surface=surf, distance=kyori, before_key=rk)

        horses = []
        extras = {}
        for bamei, umaban, ninki, _ch in runners:
            prof = profiles.get(bamei)
            sc = prof['ten'] if prof and prof.get('ten') is not None else 0.5
            horses.append({
                'umaban': umaban, 'name': bamei,
                'score': sc, 'style': pm.style_from_score(sc),
            })
            ex = {}
            if ninki and ninki > 0:
                ex['pop'] = ninki
            p = profiles.get(bamei) or {}
            if p.get('agari') is not None:
                ex['kick'] = p['agari']
            if p.get('finish_hist') is not None:
                ex['power'] = p['finish_hist']
            if ex:
                extras[umaban] = ex

        venue = pm.venue_from_race_id(rk)
        ssurf = 'ダ' if 'ダ' in str(surf) else '芝'
        layout_b = pm.get_course_layout(venue, ssurf, kyori)
        fc_total += 1
        if layout_b.get('first_corner') is not None:
            fc_hit += 1

        pm_b = pm.estimate_pace_map(
            horses, distance=kyori, profiles=profiles,
            layout=layout_b, surface=surf, extras=extras)
        pm_a = pm.estimate_pace_map(
            horses, distance=kyori, profiles=profiles,
            layout={}, surface=surf, extras=extras)

        if not pm_a or not pm_b:
            skipped_map += 1
            continue

        final_a = pm_a[list(pm_a.keys())[-1]]
        final_b = pm_b[list(pm_b.keys())[-1]]

        us_a = [r['umaban'] for r in final_a]
        pred_a = [r['x'] for r in final_a]
        real_a = [actual.get(u, 99) for u in us_a]
        rho_a = spearman([-x for x in pred_a], real_a)

        us_b = [r['umaban'] for r in final_b]
        pred_b = [r['x'] for r in final_b]
        real_b = [actual.get(u, 99) for u in us_b]
        rho_b = spearman([-x for x in pred_b], real_b)

        if rho_a is not None and rho_b is not None:
            paired.append((rho_a, rho_b))

        if (idx + 1) % 500 == 0:
            print(f"  {yfrom}-{yto}: {idx + 1}/{len(races)}", file=sys.stderr)

    return {
        'yfrom': yfrom, 'yto': yto,
        'races_queried': len(races),
        'paired_n': len(paired),
        'skipped_tosu': skipped_tosu,
        'skipped_map': skipped_map,
        'fc_hit_rate': fc_hit / fc_total if fc_total else 0,
        'fc_hit': fc_hit,
        'fc_total': fc_total,
        'paired': paired,
    }


def summarize(raw, label):
    paired = raw['paired']
    if not paired:
        return {'label': label, 'n': 0}

    rho_a = [p[0] for p in paired]
    rho_b = [p[1] for p in paired]
    diffs = [b - a for a, b in paired]

    n = len(paired)
    md = sum(diffs) / n
    sd_d = statistics.stdev(diffs) if n > 1 else 0.0
    t = md / (sd_d / n ** 0.5) if sd_d > 0 else 0.0

    diffs_sorted = sorted(diffs)
    pct = lambda q: diffs_sorted[int(q * (n - 1))] if n > 1 else diffs_sorted[0]

    return {
        'label': label,
        'period': f"{raw['yfrom']}-{raw['yto']}",
        'races_queried': raw['races_queried'],
        'paired_n': n,
        'skipped_tosu': raw['skipped_tosu'],
        'skipped_map': raw['skipped_map'],
        'fc_hit_rate': round(raw['fc_hit_rate'], 4),
        'rho_A_mean': round(sum(rho_a) / n, 6),
        'rho_B_mean': round(sum(rho_b) / n, 6),
        'rho_A_sd': round(statistics.stdev(rho_a), 6) if n > 1 else 0.0,
        'rho_B_sd': round(statistics.stdev(rho_b), 6) if n > 1 else 0.0,
        'paired_delta_mean': round(md, 6),
        'paired_delta_sd': round(sd_d, 6),
        'paired_t': round(t, 4),
        'paired_delta_median': round(statistics.median(diffs), 6),
        'paired_delta_p10': round(pct(0.10), 6),
        'paired_delta_p25': round(pct(0.25), 6),
        'paired_delta_p75': round(pct(0.75), 6),
        'paired_delta_p90': round(pct(0.90), 6),
        'pct_improved': round(sum(1 for d in diffs if d > 0) / n, 4),
        'pct_worsened': round(sum(1 for d in diffs if d < 0) / n, 4),
        'pct_unchanged': round(sum(1 for d in diffs if d == 0) / n, 4),
        'success_delta_ge_002': md >= SUCCESS_DELTA,
    }


def verdict(delta_mean, t_stat, n):
    if n == 0:
        return 'NO-GO'
    if delta_mean >= SUCCESS_DELTA and abs(t_stat) >= 2.0:
        return 'GO'
    if delta_mean > 0 and delta_mean < SUCCESS_DELTA:
        return '保留'
    return 'NO-GO'


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--holdout-only', action='store_true', default=True)
    ap.add_argument('--repro', action='store_true',
                    help='layout_effect_backtest 同条件(2023-25,sample5,limit2000)')
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    con = connect_db()

    print('=== P2-D1b layout holdout ===', file=sys.stderr)
    holdout_raw = eval_period(con, HOLDOUT_FROM, HOLDOUT_TO, sample_every=1, limit=None)
    holdout = summarize(holdout_raw, 'holdout_2024-2025')

    repro = None
    if args.repro:
        repro_raw = eval_period(
            con, 2023, 2025, sample_every=5, limit=2000)
        repro = summarize(repro_raw, 'repro_layout_effect_bt')

    con.close()

    v = verdict(
        holdout.get('paired_delta_mean', -1),
        holdout.get('paired_t', 0),
        holdout.get('paired_n', 0),
    )

    summary = {
        'purpose': 'P2-D1b expansion map final straight x vs chakujun',
        'not_in_scope': [
            'V red frame', 'V coords', 'pos4', 'build_pace_context change',
            'layout→V wiring', 'new thresholds', 'ML',
        ],
        'comparison': {
            'A': 'layout={} (none)',
            'B': 'layout=get_course_layout (existing)',
            'ground_truth': 'chakujun',
            'prediction': 'estimate_pace_map final phase x',
            'metric': 'Spearman rho (-x vs chakujun)',
            'primary': 'paired mean(B - A)',
        },
        'success_gate': f'B - A >= {SUCCESS_DELTA} rho (pre-fixed)',
        'holdout': holdout,
        'repro_check': repro,
        'verdict': v,
        'implementation_note': (
            'Improvement is expansion MAP straight phase only. '
            'Does NOT justify layout→V baba/pace/coords. '
            'build_pace_context/pos4 unchanged by layout in current code.'
        ),
        'root_cause_zero_delta': (
            'estimate_pace_map final phase (直線) uses predict_finish only; '
            'gate_w affects スタート only; straight_push is computed but unused. '
            'layout on/off yields identical final x → identical Spearman rho.'
        ),
        'original_bt_reproduced': (
            'scripts/layout_effect_backtest.py on same sample also shows +0.0000 delta.'
        ),
    }

    out_path = os.path.join(OUT_DIR, 'summary.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'\nWrote {out_path}')


if __name__ == '__main__':
    main()
