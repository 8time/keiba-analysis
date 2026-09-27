# -*- coding: utf-8 -*-
"""研究用の払戻読み取り。production の money.py は変更しない。"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from core import jockey_jv as jj

ORDERED = {'3連単', '馬単'}
UNORDERED = {'馬連', 'ワイド', '3連複', '枠連'}
SINGLE = {'単勝', '複勝'}


def _combo(bet_type: str, raw: str):
    c = str(raw).strip()
    if not c.isdigit() or len(c) % 2:
        return None
    nums = tuple(int(c[i:i + 2]) for i in range(0, len(c), 2))
    if bet_type in UNORDERED:
        return tuple(sorted(nums))
    return nums


def load_maps(types):
    """race_key -> list of (combo_tuple, payout_yen_per_100)."""
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {t: defaultdict(list) for t in types}
    q = ','.join('?' for _ in types)
    for rk, bt, combo, pay in con.execute(
            f'SELECT race_key, bet_type, combo, payout FROM payouts WHERE bet_type IN ({q})',
            tuple(types)):
        parsed = _combo(bt, combo)
        if parsed is None:
            continue
        out[bt][str(rk)].append((parsed, float(pay)))
    con.close()
    return out


def yen_for(rows, key):
    """同着は払戻を合算しない。最初の一致を返す（研究ハーネスは1組1行を想定し、複数一致は呼び出し側で見る）。"""
    hits = [pay for combo, pay in rows if combo == key and pay > 0]
    return hits
