"""Offline representative-size fixture benchmark; never touches production DB."""
from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

from core import prediction_time_machine as tm


def fixture():
    horses = []
    for number in range(1, 17):
        row = {'Umaban': number, 'Name': f'Fixture {number}', 'Jockey': '騎手',
               'CurrentDistance': 1200, 'CurrentSurface': '芝',
               'Odds': 2.0 + number, 'Popularity': number,
               'PastRuns': [{'Rank': (i + number) % 16 + 1,
                             'Passing': '2-2-2-3', 'PassingType': 'Measured',
                             'Agari': 34.5 + i / 10, 'Distance': 1200,
                             'Surface': '芝'} for i in range(8)]}
        for i in range(100):
            row[f'Feature_{i}'] = (number * i) / 100
        horses.append(row)
    return {'race': {'race_id': '209910180511',
                     'scheduled_start_at': '2099-10-18T15:40:00+09:00'},
            'snapshot_created_at': tm.now_jst(), 'raw_input': horses,
            'horses': horses, 'market_features': [], 'non_market_features': horses,
            'provenance': {'fixture': {'source': 'UNKNOWN', 'fetched_at': None}},
            'predictions': {'battle_score': [], 'sra_projected_score': []},
            'missing_outputs': list(tm.REQUIRED_COMPONENTS)}


def main():
    import pandas as pd
    from core import calculator, pace_map
    horses = fixture()['horses']
    frame = pd.DataFrame(horses)
    score_times = []
    for _ in range(5):
        started = time.perf_counter()
        calculator.calculate_battle_score(frame.copy())
        score_times.append(time.perf_counter() - started)
    pace_horses = [{'umaban': row['Umaban'], 'name': row['Name'], 'score': 0.4,
                    'style': '先行'} for row in horses]
    ctx = pace_map.build_pace_context(pace_horses, {}, 1200, '芝')
    finish_times = []
    diag_times = []
    for _ in range(20):
        started = time.perf_counter()
        pace_map.predict_finish(pace_horses, {}, ctx, extras={})
        finish_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        pace_map.predict_finish(pace_horses, {}, ctx, extras={}, diagnostics={})
        diag_times.append(time.perf_counter() - started)
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / 'prediction_tm_benchmark.db'
        times = []
        for _ in range(10):
            body = fixture()
            started = time.perf_counter()
            tm.save_snapshot(body, db)
            times.append(time.perf_counter() - started)
        print({'fixture': '16 horses x 8 past runs x 100 scalar columns',
               'snapshot_count': 10,
               'median_save_seconds': round(statistics.median(times), 4),
               'max_save_seconds': round(max(times), 4),
               'median_battle_score_seconds': round(statistics.median(score_times), 4),
               'median_finish_seconds': round(statistics.median(finish_times), 6),
               'median_finish_with_diagnostics_seconds': round(statistics.median(diag_times), 6),
               'database_bytes': db.stat().st_size,
               'incremental_bytes_per_snapshot_approx': round(db.stat().st_size / 10)})


if __name__ == '__main__':
    main()
