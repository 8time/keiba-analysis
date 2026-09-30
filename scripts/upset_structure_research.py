# -*- coding: utf-8 -*-
"""Upset structure decomposition (research only).

Usage: python scripts/upset_structure_research.py
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from research.high_entropy_upset.upset_structure import run_full

if __name__ == '__main__':
    rep = run_full()
    print('Report:', rep['report_json'])
    print('Map:', rep['outputs']['map_html'])
    print('Structured CSV:', rep['outputs']['structured_csv'])
    for row in rep['arare_metrics_by_type']:
        if row.get('auc'):
            print(row['label'], 'n=', row['n'], 'AUC=', round(row['auc'], 4),
                  'prec@20%=', row.get('precision_top_20pct'))
