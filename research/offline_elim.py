# -*- coding: utf-8 -*-
"""本番 elim_engine 経路で elim_keep を再計算（CSV+JV。elim_n 列とは別）。"""
from __future__ import annotations

import sqlite3
from functools import lru_cache

import pandas as pd

from core import elim_engine as ee
from core import jockey_jv as jj

_SEX_LABEL = {1: '牡', 2: '牝', 3: 'セ'}


@lru_cache(maxsize=1)
def _jv_names_by_race():
    """race_key → {umaban: (bamei, jockey_name)}"""
    path = jj.JV_DB_PATH
    if not path or not __import__('os').path.exists(path):
        return {}
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=60)
    cur = con.execute(
        "SELECT race_key, umaban, bamei, jockey_name FROM results "
        "WHERE race_key >= '201601010101'")
    out = {}
    for rk, um, nm, jk in cur:
        rk = str(rk)
        try:
            u = int(um)
        except (TypeError, ValueError):
            continue
        out.setdefault(rk, {})[u] = (str(nm or ''), str(jk or ''))
    con.close()
    return out


def elim_engine_available() -> bool:
    return bool(_jv_names_by_race())


def build_elim_df(race_key: str, horse_rows: list[dict], race_meta: dict) -> pd.DataFrame:
    """app.py 出走表に近い DataFrame を CSV 行から組み立てる。"""
    names = _jv_names_by_race().get(str(race_key), {})
    surf = 'ダ' if int(race_meta.get('surface_code') or 0) == 1 else '芝'
    dist = race_meta.get('kyori_int') or race_meta.get('kyori')
    rows = []
    for h in horse_rows:
        um = int(h['umaban'])
        nm, jk = names.get(um, (f'U{um}', ''))
        sc = h.get('sex_code')
        try:
            age = int(h.get('age') or 0)
        except (TypeError, ValueError):
            age = 0
        sa = f"{_SEX_LABEL.get(int(sc), '牡')}{age}" if age else ''
        rows.append({
            'Umaban': um,
            'Name': nm,
            'Popularity': h.get('ninki'),
            'Odds': h.get('win_odds'),
            'Jockey': jk,
            'SexAge': sa,
            'PastRuns': [],
        })
    df = pd.DataFrame(rows)
    df['CurrentSurface'] = surf
    df['CurrentDistance'] = dist
    return df


def compute_elim_keep(
    race_key: str,
    horse_rows: list[dict],
    race_meta: dict,
    proj_scores: dict | None = None,
) -> set[int] | None:
    """本番 compute_elim_rows + apply_verdict → 残馬 set。失敗時 None。"""
    if not horse_rows or len(horse_rows) < 3:
        return None
    df = build_elim_df(race_key, horse_rows, race_meta)
    if df.empty:
        return None
    day = str(race_meta.get('day') or '')
    baba = race_meta.get('baba_label') or '良'
    meta = {
        'condition': baba,
        'date_val': day,
        'is_handicap': bool(race_meta.get('is_handi1')),
    }
    proj_scores = proj_scores or {}
    from research import score_bridge as sb
    if proj_scores:
        sb.set_race_scores(str(race_key), proj_scores)
    try:
        with sb.patch_score_cache():
            erows = ee.compute_elim_rows(df, str(race_key), meta)
            edf = ee.apply_verdict(
                erows, str(race_key),
                border_cnt=ee.default_border_count(len(df), str(race_key)),
                record_fired=False,
                apply_learning=False,
            )
            keep = ee.keep_umaban_from_edf(edf)
            return set(keep) if keep else None
    except Exception:
        return None
    finally:
        sb.clear_race(str(race_key))
