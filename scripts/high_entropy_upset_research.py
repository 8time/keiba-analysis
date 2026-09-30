# -*- coding: utf-8 -*-
"""Build research dataset + stats for high-eff_n upset study (no production changes).

Usage:
  python scripts/high_entropy_upset_research.py build
  python scripts/high_entropy_upset_research.py analyze
  python scripts/high_entropy_upset_research.py all
  python scripts/high_entropy_upset_research.py structure
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from research.high_entropy_upset import analyze, dataset


def cmd_build(args):
    df = dataset.build_dataset(min_year=args.min_year)
    path = dataset.save_dataset(df)
    print(f'Wrote {path} ({len(df):,} races)')


def cmd_analyze(args):
    path = os.path.join(dataset.OUT_DIR, 'high_entropy_race_dataset.csv')
    if not os.path.isfile(path):
        print('Dataset missing; run build first.', file=sys.stderr)
        sys.exit(1)
    import pandas as pd
    df = pd.read_csv(path, encoding='utf-8')
    rep = analyze.run_analysis(df)
    out = analyze.save_report(rep)
    print(f'Report → {out}')
    b = rep.get('baseline_holdout', {})
    print(f"Holdout n={b.get('n')} AUC={b.get('auc')} PR-AUC={b.get('pr_auc')} "
          f"prec@20%={b.get('precision_top_20pct')}")


def cmd_structure(_args):
    from research.high_entropy_upset.upset_structure import run_full
    rep = run_full()
    print(f"Report → {rep['report_json']}")
    print(f"Map → {rep['outputs']['map_html']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('build', 'analyze', 'all', 'structure'))
    p.add_argument('--min-year', type=int, default=2016)
    args = p.parse_args()
    if args.command in ('build', 'all'):
        cmd_build(args)
    if args.command in ('analyze', 'all'):
        cmd_analyze(args)
    if args.command == 'structure':
        cmd_structure(args)


if __name__ == '__main__':
    main()
