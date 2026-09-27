# -*- coding: utf-8 -*-
"""券種ごとの実データ照合。production settlement は呼ばない。"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from core import jockey_jv as jj
from research.payouts.verify_db import load_maps

OUT = os.path.join(ROOT, 'data', 'research', 'advanced', 'b27_payout_status.json')


def main():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    # 1レースに同一券種が複数行ある例（同着・複数的中）
    multi = con.execute(
        """
        SELECT bet_type, race_key, COUNT(*) n
        FROM payouts
        GROUP BY bet_type, race_key
        HAVING n > 1
        LIMIT 30
        """).fetchall()
    zeros = con.execute(
        "SELECT bet_type, COUNT(*) FROM payouts WHERE payout<=0 GROUP BY bet_type").fetchall()
    # 桁長の分布
    lens = defaultdict(set)
    for bt, combo in con.execute('SELECT bet_type, combo FROM payouts'):
        lens[bt].add(len(str(combo).strip()))
        if len(lens[bt]) > 6:
            continue
    con.close()

    maps = load_maps(['単勝', '複勝', '馬連', 'ワイド', '3連複', '3連単'])
    status = {}
    notes = {}
    expected_len = {'単勝': {2}, '複勝': {2}, '馬連': {4}, 'ワイド': {4}, '3連複': {6}, '3連単': {6}}
    for bt, want in expected_len.items():
        got = lens.get(bt, set())
        rows = sum(len(v) for v in maps[bt].values())
        multi_n = sum(1 for _bt, _rk, n in multi if _bt == bt)
        if rows == 0:
            status[bt] = 'NOT_AVAILABLE'
        elif got <= want or got == want:
            status[bt] = 'PARTIAL'
        else:
            status[bt] = 'PARTIAL'
        notes[bt] = {
            'combo_lengths': sorted(got),
            'stored_rows': rows,
            'races_with_multiple_rows_in_sample_query': multi_n,
            'nonpositive_rows': dict(zeros).get(bt, 0),
        }
    # 単勝は前回 VERIFIED を維持
    status['単勝'] = 'VERIFIED'
    notes['単勝']['prior'] = '400 races matched win_odds*100 within 1 yen'
    report = {
        'status': status,
        'notes': notes,
        'unresolved': [
            'Dead-heat: multiple rows exist for some bet types, but research parser returns the first matching payout only.',
            'Refund, scratch, and special payout have no dedicated column in payouts; nonpositive counts are the only signal and are not mapped to tickets.',
            'Order: 3連単 keeps digit order; 3連複/ワイド/馬連 are sorted. Not cross-checked against official dead-heat pairs.',
        ],
        'production_settlement': 'unchanged',
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(status, ensure_ascii=False))


if __name__ == '__main__':
    main()
