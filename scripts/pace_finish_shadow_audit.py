"""Read-only, time-split JV proxy audit for SRA finish hypotheses.

This cannot replay historical live BattleScore, Suitability, or timed odds.
JV final popularity is used for a labelled proxy comparison only. It must not
be cited as proof that the full production model improved.
"""
import argparse
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import pace_map as pm  # noqa: E402


def rho(predicted, actual):
    us = sorted(predicted.keys() & actual.keys())
    if len(us) < 3:
        return 0.0
    x = pm._rank_norm({u: predicted[u] for u in us})
    y = pm._rank_norm({u: actual[u] for u in us})
    mx = sum(x.values()) / len(us)
    my = sum(y.values()) / len(us)
    numerator = sum((x[u] - mx) * (y[u] - my) for u in us)
    denominator = math.sqrt(sum((x[u] - mx) ** 2 for u in us)
                            * sum((y[u] - my) ** 2 for u in us))
    return numerator / denominator if denominator else 0.0


def evaluate(db, year, limit):
    # Race features and labels are read from a SQLite connection that cannot write.
    con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT race_key, kyori, surface, jyo FROM races "
        "WHERE year=? AND shusso_tosu>=8 ORDER BY race_key", (str(year),)).fetchall()
    # Fixed systematic sample; no target-race selection or outcome-based sampling.
    sample = rows[::max(1, len(rows) // limit)][:limit]
    by_model = {key: [] for key in ('current_jv_proxy', 'popularity_only',
                                     'predicted_pos4_only', 'consistent_jv_proxy',
                                     'short_straight_pos4', 'long_straight_kick')}
    eligible = 0
    for race in sample:
        rk = race['race_key']
        if rk.startswith('20260604'):
            continue  # The diagnostic race is never used for model selection.
        runners = con.execute(
            "SELECT umaban,bamei,ninki,chakujun FROM results "
            "WHERE race_key=? AND umaban>0 AND chakujun>0", (rk,)).fetchall()
        if len(runners) < 8:
            continue
        horses = []
        actual = {}
        popularity = {}
        for r in runners:
            u = r['umaban']
            actual[u] = r['chakujun']
            if r['ninki'] and r['ninki'] > 0:
                popularity[u] = r['ninki']
            horses.append(dict(umaban=u, name=r['bamei'], score=.5, style='不明'))
        # Existing production pos4 code; target-day and future results excluded.
        profiles = pm.fetch_jv_profiles([h['name'] for h in horses], max_runs=8,
                                        surface=race['surface'], distance=race['kyori'],
                                        before_key=rk[:8], read_only=True)
        if len(profiles) < 6:
            continue
        for h in horses:
            p = profiles.get(h['name']) or {}
            h['score'] = p.get('ten') if p.get('ten') is not None else .5
            h['style'] = pm.style_from_score(h['score'])
        layout = pm.get_course_layout(pm.VENUE_CODES.get(str(race['jyo']).zfill(2)),
                                      race['surface'], race['kyori'])
        ctx = pm.build_pace_context(horses, profiles, race['kyori'],
                                    race['surface'], layout)
        extras = {u: {'pop': value} for u, value in popularity.items()}
        pred = {
            'current_jv_proxy': pm.predict_finish(horses, profiles, ctx, extras),
            'popularity_only': {u: popularity.get(u, len(horses) / 2)
                                for u in actual},
            'predicted_pos4_only': ctx['pos4'],
        }
        baseline = pm.predict_finish_shadow(horses, profiles, ctx, extras,
                                            popularity=popularity)
        pred['consistent_jv_proxy'] = baseline['finish']
        straight = layout.get('straight')
        pred['short_straight_pos4'] = (pm.predict_finish_shadow(
            horses, profiles, ctx, extras, popularity=popularity,
            tune={'w_pos4': .7})['finish'] if straight is not None and straight < 330
            else baseline['finish'])
        pred['long_straight_kick'] = (pm.predict_finish_shadow(
            horses, profiles, ctx, extras, popularity=popularity,
            tune={'w_kick': .8})['finish'] if straight is not None and straight >= 450
            else baseline['finish'])
        front = set(sorted(ctx['pos4'], key=ctx['pos4'].get)[:max(2, len(horses) // 4)])
        longshots = {u for u, p in popularity.items() if p >= 6}
        podium = {u for u, place in actual.items() if place <= 3}
        for name, values in pred.items():
            order = sorted(values, key=lambda u: (values[u], u))
            top3, top5 = set(order[:3]), set(order[:5])
            rear = set(order[-min(pm.rear_count(len(order)), len(order) - 1):])
            by_model[name].append({
                'rho': rho(values, actual),
                'venue': str(race['jyo']).zfill(2),
                'distance_band': ('short' if race['kyori'] < 1400 else
                                  'mile' if race['kyori'] < 1800 else
                                  'middle' if race['kyori'] < 2400 else 'long'),
                'podium_in_top3': len(podium & top3),
                'podium_in_top5': len(podium & top5),
                'front_podium_missed': len(front & podium - top5),
                'longshot_podium_missed': len(longshots & podium - top5),
                'rear_podium': len(rear & podium),
                'front_podium': len(front & podium),
                'longshot_podium': len(longshots & podium),
                'podium': len(podium),
            })
        eligible += 1
    con.close()
    result = {}
    for name, values in by_model.items():
        if not values:
            continue
        sums = {key: sum(v[key] for v in values) for key in values[0]
                if key not in ('venue', 'distance_band')}
        rho_se = statistics.stdev(v['rho'] for v in values) / math.sqrt(len(values))
        mean_rho = sums['rho'] / len(values)
        result[name] = {'races': len(values), 'mean_rho': round(mean_rho, 4),
                        'rho_95pct_normal_interval': [round(mean_rho - 1.96 * rho_se, 4),
                                                       round(mean_rho + 1.96 * rho_se, 4)],
                        'podium_top3_recall': round(sums['podium_in_top3'] / sums['podium'], 4),
                        'podium_top5_recall': round(sums['podium_in_top5'] / sums['podium'], 4),
                        'front_podium_miss_rate': round(
                            sums['front_podium_missed'] / max(1, sums['front_podium']), 4),
                        'longshot_podium_miss_rate': round(
                            sums['longshot_podium_missed'] / max(1, sums['longshot_podium']), 4),
                        'rear_podium_rate': round(sums['rear_podium'] / sums['podium'], 4),
                        'longshot_podium_n': sums['longshot_podium'],
                        'front_podium_n': sums['front_podium']}
        if name in ('current_jv_proxy', 'consistent_jv_proxy'):
            result[name]['by_venue'] = {
                venue: {'races': len(group),
                        'mean_rho': round(statistics.mean(v['rho'] for v in group), 4)}
                for venue in sorted({v['venue'] for v in values})
                if (group := [v for v in values if v['venue'] == venue])}
            result[name]['by_distance_band'] = {
                band: {'races': len(group),
                       'mean_rho': round(statistics.mean(v['rho'] for v in group), 4)}
                for band in ('short', 'mile', 'middle', 'long')
                if (group := [v for v in values if v['distance_band'] == band])}
    return {'year': year, 'sampled': len(sample), 'eligible': eligible, 'models': result}


def diagnose_snapshot(db, race_id):
    """Replay saved production inputs for diagnosis, never for model selection."""
    snapshot = json.loads((ROOT / 'data' / 'newspaper' / f'{race_id}.pace.json').read_text(encoding='utf-8'))
    saved = json.loads((ROOT / 'data' / 'score_cache' / f'{race_id}.full.json').read_text(encoding='utf-8'))
    records = saved['records']
    horses = [dict(umaban=int(r['Umaban']), name=r['Name'], score=.5, style='不明')
              for r in records]
    race_date = pm.history_cutoff(records[0].get('RaceDate'))
    profiles = pm.fetch_jv_profiles([h['name'] for h in horses], max_runs=8,
                                    surface=records[0].get('CurrentSurface'),
                                    distance=records[0].get('CurrentDistance'),
                                    before_key=race_date, read_only=True)
    ctx = {'pos4': {int(u): value for u, value in snapshot['pos4'].items()}}
    extras, popularity, odds = {}, {}, {}
    def finite(v):
        try:
            value = float(v)
        except (ValueError, TypeError, OverflowError):
            return None
        return value if math.isfinite(value) else None
    for r in records:
        u = int(r['Umaban'])
        ex = {}
        a = finite(r.get('AvgAgari'))
        s = finite(r.get('Suitability (Y)'))
        b = finite(r.get('BattleScore'))
        p = finite(r.get('Popularity'))
        o = finite(r.get('Odds'))
        if a is not None and a > 0: ex['kick'] = a
        if s is not None: ex['apt'] = -s
        if b is not None: ex['power'] = -b
        if p is not None and 0 < p < 99: popularity[u] = p
        if o is not None and 0 < o < 999: odds[u] = o
        if p is None or p >= 99: p = o if o is not None and 0 < o < 999 else None
        if p is not None: ex['pop'] = p
        extras[u] = ex
    current = pm.predict_finish(horses, profiles, ctx, extras)
    shadow = pm.predict_finish_shadow(horses, profiles, ctx, extras,
                                      popularity=popularity, odds=odds)
    old_rank = {u: i + 1 for i, u in enumerate(sorted(current, key=lambda u: (current[u], u)))}
    new_rank = {u: i + 1 for i, u in enumerate(sorted(shadow['finish'],
                                                    key=lambda u: (shadow['finish'][u], u)))}
    saved_finish = {int(u): value for u, value in snapshot['finish'].items()}
    return {'race_id': race_id, 'saved_after_race_possible': True,
            'score_snapshot_ts': saved.get('ts'), 'pace_snapshot_ts': snapshot.get('ts'),
            'race_date': race_date, 'model': shadow['model_version'],
            'max_current_replay_error': max(abs(current[u] - saved_finish[u]) for u in current),
            'sources': shadow['provenance'],
            'horses': [{'umaban': h['umaban'], 'name': h['name'],
                        'pos4': ctx['pos4'][h['umaban']],
                        'current_rank': old_rank[h['umaban']],
                        'shadow_rank': new_rank[h['umaban']],
                        'contributions': shadow['contributions'][h['umaban']]}
                       for h in sorted(horses, key=lambda h: h['umaban'])]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=300)
    parser.add_argument('--snapshot-race', help='diagnostic replay only; excluded from model selection')
    args = parser.parse_args()
    db = ROOT / 'data' / 'jravan.db'
    if not db.exists():
        raise SystemExit(f'Missing read-only JV data: {db}')
    if args.snapshot_race:
        print(json.dumps(diagnose_snapshot(db, args.snapshot_race), ensure_ascii=False), flush=True)
        raise SystemExit(0)
    # 2024 selects hypotheses; 2025 is untouched holdout. Minimum worthwhile
    # difference: +.01 rho without >.01 loss in podium recall or front/longshot
    # miss rates. These limits are fixed before examining the holdout.
    for year in (2024, 2025):
        print(json.dumps(evaluate(db, year, args.limit), ensure_ascii=False), flush=True)
