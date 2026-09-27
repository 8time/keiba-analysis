# -*- coding: utf-8 -*-
"""見送り理由コードの監査（N5）。

(a) data/newspaper/*.bets.json の skip_reason / degraded 集計
(b) D ゾーン相当レースで人気1-4が4頭揃わない件数

Usage: python scripts/skip_reason_audit.py
"""
import io
import os
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd

from core import formation_stats as fs
from core import value_scanner as vs
from core import playbook_ledger as pl


def _write_memo(path, title, description, sections):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = '\n\n'.join(sections)
    text = (
        '---\n'
        f'name: {title}\n'
        f'description: {description}\n'
        'metadata:\n'
        '  node_type: memory\n'
        '  type: project\n'
        '---\n\n'
        f'# {title}\n\n'
        f'{body}\n'
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def audit_newspaper():
    entries = pl.list_entries()
    by_reason = Counter()
    degraded = 0
    for e in entries:
        r = e.get('skip_reason')
        if r:
            by_reason[r] += 1
        if e.get('degraded'):
            degraded += 1
    lines = ['## (a) 保存済みプレイブック', f'- 件数: {len(entries)}']
    for k, v in sorted(by_reason.items()):
        lines.append(f'- skip_reason={k}: {v}件')
    lines.append(f'- degraded=True: {degraded}件')
    return lines, by_reason, degraded, len(entries)


def audit_csv_d_ninki():
    from scripts import csv_data as cd

    h = cd.load_horses(cols=[
        'race_key', 'day', 'umaban', 'ninki', 'win_odds', 'chakujun',
    ])
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore'])
    h['race_key'] = h['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    total_d = 0
    bad = 0
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < 8:
            continue
        m = meta.get(rk)
        vscore = float(m.vscore) if m is not None and pd.notna(m.vscore) else None
        if vscore is None:
            odds_list = [float(x) for x in g['win_odds'] if float(x) > 0]
            rv = vs.race_value_score(
                odds_list,
                {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                 'kigo': str(getattr(m, 'kigo', '') or '')},
                n_horses=len(g))
            if not rv:
                continue
            vscore = float(rv['score'])
        if fs.zone_code(vscore) != 'D':
            continue
        total_d += 1
        ninkis = g.sort_values('ninki')['ninki'].astype(int).tolist()
        top4 = [p for p in ninkis if 1 <= p <= 4]
        if len(set(top4)) < 4:
            bad += 1
    pct = bad / total_d * 100 if total_d else 0.0
    lines = [
        '## (b) D ゾーン相当・人気1-4欠損/重複',
        f'- D 相当レース: {total_d}',
        f'- 人気1-4が4頭揃わない: {bad} ({pct:.1f}%)',
    ]
    return lines, total_d, bad, pct


def main():
    sec_a, by_reason, degraded, n_ent = audit_newspaper()
    sec_b, total_d, bad, pct = audit_csv_d_ninki()

    print('\n'.join(sec_a))
    print()
    print('\n'.join(sec_b))

    memo_path = os.path.join(ROOT, 'repo', 'memory', 'verified_skip_reason_audit.md')
    _write_memo(
        memo_path,
        'verified_skip_reason_audit',
        'N5 見送り理由コードと D ゾーン人気欠損の実測',
        sec_a + sec_b + [
            '## 所見',
            f'- 保存済み {n_ent} 件、degraded {degraded} 件',
            f'- CSV D 相当 {total_d}R 中、人気1-4不整合 {bad}R ({pct:.1f}%)',
        ],
    )
    print(f'\n→ {memo_path}')


if __name__ == '__main__':
    main()
