# -*- coding: utf-8 -*-
"""Favorite Survival research runner (no production changes).

Usage: python scripts/favorite_survival_research.py
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

from research.high_entropy_upset.favorite_survival_analysis import run_full

if __name__ == '__main__':
    rep = run_full()
    c = rep['cohort']
    print('Report:', rep['paths']['report_json'])
    print(f"High eff_n n={c['n_high_eff_n']} type_A={c['n_type_a_in_cohort']} ({100*c['type_a_rate']:.1f}%)")
    print('Verdict:', rep['three_stage_verdict']['label'])
    for name, m in rep['models_holdout'].items():
        if m.get('auc'):
            print(name, 'AUC=', round(m['auc'], 4))
