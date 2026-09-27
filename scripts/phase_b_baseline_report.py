# -*- coding: utf-8 -*-
"""Phase B Baseline 再計測 → data/research/baseline_metrics.json"""
import json
import os
import sys
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from research import baseline_runner as br
from research import splits
from research.experiment_store import append_experiment
from scripts import csv_data as cd


def main():
    if not cd.available():
        print('CSV missing — run export_features_csv.py first', file=sys.stderr)
        sys.exit(1)

    horse_mtime = datetime.fromtimestamp(os.path.getmtime(cd.HORSE_CSV)).isoformat()
    races = cd.load_races(cols=['day'])
    max_day = int(races['day'].max())

    print('Running baseline (train + validation only)...', file=sys.stderr)
    recs = br.run_baseline(splits_to_run=('train', 'validation'), apply_elim=True)
    summary = br.summarize_baseline(recs)

    holdout_n = sum(1 for _ in cd.load_races(cols=['day']).itertuples()
                    if splits.split_for_day(_.day) == 'holdout')

    payload = {
        'baseline_version': splits.BASELINE_VERSION,
        'parity': br.parity_status(),
        'label': 'research_baseline_partial',
        'note': 'NOT production-identical while Projected Score absent (cross_n degraded on C).',
        'export_horse_csv_mtime': horse_mtime,
        'data_day_min': 20160105,
        'data_day_max': max_day,
        'splits': splits.split_doc(),
        'holdout_race_count_for_existence_only': holdout_n,
        'stake_per_point_yen': 100,
        'kelly_included': False,
        'metrics': summary,
    }

    out_dir = os.path.join(ROOT, 'data', 'research')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'baseline_metrics.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    append_experiment({
        'experiment_id': 'baseline_v1_measurement',
        'baseline_version': splits.BASELINE_VERSION,
        'variable_changed': 'none',
        'train': summary.get('train', {}).get('all'),
        'validation': summary.get('validation', {}).get('all'),
        'holdout': None,
        'verdict': 'baseline_fixed_partial',
    })

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f'\n→ {out_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
