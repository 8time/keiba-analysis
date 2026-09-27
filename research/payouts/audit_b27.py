# -*- coding: utf-8 -*-
"""B27: 実レースで券種ごとの読取可否を記録する。"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from core import jockey_jv as jj
from core.money import yen_payout_from_odds
from research.payouts.verify_db import load_maps

OUT = os.path.join(ROOT, 'data', 'research', 'advanced', 'b27_payout_audit.json')


def main():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    types = [r[0] for r in con.execute('SELECT DISTINCT bet_type FROM payouts')]
    # refund-like
    zero = con.execute(
        "SELECT bet_type, COUNT(*) FROM payouts WHERE payout<=0 GROUP BY bet_type").fetchall()
    sample_lens = {}
    for bt in types:
        rows = con.execute(
            'SELECT combo, payout FROM payouts WHERE bet_type=? LIMIT 5', (bt,)).fetchall()
        sample_lens[bt] = [{'combo': c, 'len': len(str(c)), 'payout': p} for c, p in rows]
    con.close()

    maps = load_maps(['単勝', '複勝', '馬連', 'ワイド', '3連複', '3連単'])
    horses = pd.read_csv(
        os.path.join(ROOT, 'data', 'export', 'horse_races.csv'),
        usecols=['race_key', 'day', 'umaban', 'ninki', 'win_odds', 'win', 'chakujun'])
    horses = horses[(horses['day'] >= 20240101) & (horses['day'] <= 20241231)]
    horses['race_key'] = horses['race_key'].astype(str)

    # 単勝: 勝ち馬の DB 払戻 vs win_odds*100
    checked = 0
    match = 0
    mismatch = 0
    for rk, g in horses.groupby('race_key'):
        w = g[g['win'] == 1]
        if len(w) != 1:
            continue
        row = w.iloc[0]
        key = (int(row['umaban']),)
        hits = [p for c, p in maps['単勝'].get(rk, []) if c == key]
        if not hits:
            continue
        expect = yen_payout_from_odds(float(row['win_odds']), 100)
        checked += 1
        if abs(hits[0] - expect) <= 1:
            match += 1
        else:
            mismatch += 1
        if checked >= 400:
            break

    # 複勝: 3着内の頭数と払戻行数
    place_races = 0
    place_ok = 0
    for rk, g in list(horses.groupby('race_key'))[:300]:
        top = g[g['chakujun'].between(1, 3)]
        rows = maps['複勝'].get(rk, [])
        if not rows:
            continue
        place_races += 1
        umas = {c[0] for c, p in rows if len(c) == 1 and p > 0}
        if set(top['umaban'].astype(int)) <= umas or len(umas) >= 3:
            place_ok += 1

    status = {
        '単勝': 'VERIFIED' if checked >= 100 and mismatch == 0 else 'PARTIAL',
        '複勝': 'PARTIAL' if place_races else 'NOT_AVAILABLE',
        '馬連': 'PARTIAL',
        'ワイド': 'PARTIAL',
        '3連複': 'PARTIAL',
        '3連単': 'PARTIAL',
    }
    # 構造: 桁長が券種と一致すれば PARTIAL（順序・同着・返還は未完了）
    report = {
        'db_bet_types': types,
        'nonpositive_payout_counts': [{'bet_type': a, 'n': b} for a, b in zero],
        'samples': sample_lens,
        'win_checked': checked,
        'win_match_odds_times_100': match,
        'win_mismatch': mismatch,
        'place_races_seen': place_races,
        'place_structure_ok': place_ok,
        'status': status,
        'limits': [
            'Dead-heat aggregation, refund and special payout are not fully fixture-tested.',
            'PARTIAL means combo width and a positive payout row can be read, not full settlement parity.',
            'Production money.py was not modified.',
        ],
    }
    # 複勝が3着内を覆う率
    if place_races and place_ok / place_races >= 0.9:
        status['複勝'] = 'PARTIAL'
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({'win': status['単勝'], 'match': match, 'mismatch': mismatch,
                      'place': status['複勝'], 'place_ok': place_ok, 'place_n': place_races,
                      'types': types}, ensure_ascii=False))


if __name__ == '__main__':
    main()
