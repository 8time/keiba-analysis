# -*- coding: utf-8 -*-
"""
LTRランキング予測 — core/ltr_ranker.py

scripts/build_ltr_model.py で学習したLightGBM LambdaRankモデルを使い
出走馬をランキングする。get_scores(horses, race_info) → {umaban: score}。
"""
import os
import json
import sqlite3

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_PATH = os.path.join(_ROOT, 'data', 'ltr_model.lgb')
_META_PATH = os.path.join(_ROOT, 'data', 'ltr_meta.json')
_JV_DB = os.path.join(_ROOT, 'data', 'jravan.db')

_model = None
_meta = None


def available():
    return os.path.exists(_MODEL_PATH) and os.path.exists(_META_PATH)


def _load():
    global _model, _meta
    if _model is not None:
        return _model, _meta
    if not available():
        return None, None
    try:
        import lightgbm as lgb
        _model = lgb.Booster(model_file=_MODEL_PATH)
        with open(_META_PATH, 'r', encoding='utf-8') as f:
            _meta = json.load(f)
        return _model, _meta
    except Exception:
        return None, None


def _jv_con():
    if not os.path.exists(_JV_DB):
        return None
    try:
        return sqlite3.connect(f'file:{_JV_DB}?mode=ro', uri=True, timeout=10)
    except Exception:
        return None


def _prior_spurt(con, ketto):
    try:
        rows = con.execute("""
            SELECT r.ato3f FROM results r
            JOIN races ra ON r.race_key = ra.race_key
            WHERE r.ketto_num = ? AND r.chakujun > 0 AND r.ato3f > 0
            ORDER BY ra.year DESC, ra.monthday DESC LIMIT 3
        """, (str(ketto),)).fetchall()
        return sum(r[0] for r in rows) / len(rows) if rows else None
    except Exception:
        return None


def _prior_record(con, ketto):
    try:
        rows = con.execute("""
            SELECT r.chakujun FROM results r
            JOIN races ra ON r.race_key = ra.race_key
            WHERE r.ketto_num = ? AND r.chakujun > 0
            ORDER BY ra.year DESC, ra.monthday DESC LIMIT 7
        """, (str(ketto),)).fetchall()
        if not rows:
            return None, None
        ch = [r[0] for r in rows]
        return sum(1 for c in ch if c <= 3) / len(ch), sum(ch[:5]) / min(len(ch), 5)
    except Exception:
        return None, None


def get_scores(horses, race_info):
    """
    horses: [{umaban, ketto_num, ninki, win_odds, bataiju, zogen, sex, age, futan}, ...]
    race_info: {surface, kyori, field_size, baba, is_handicap, jyo, race_num, cushion, dirt_moisture}
    Returns {umaban(int): score(float)} or None.
    """
    model, meta = _load()
    if model is None:
        return None
    try:
        import core.corrected_time as ct
    except Exception:
        ct = None

    features = meta['features']
    fs = int(race_info.get('field_size') or len(horses))
    ih = 1 if race_info.get('is_handicap') else 0
    surf = str(race_info.get('surface', ''))
    sc = 1 if 'ダ' in surf else 0
    ky = int(race_info.get('kyori') or 0)
    # jravan.db codes: 1=良, 2=稍重, 3=重, 4=不良; runtime receives text from scraping
    bm = {'良': 1, '稍重': 2, '重': 3, '不良': 4}
    bc = bm.get(str(race_info.get('baba', '')), 0)
    # jravan.db codes: 1=牡, 2=牝, 3=セ; runtime receives text from scraping
    sx = {'牡': 1, '牝': 2, 'セ': 3}
    # Track bias Phase4 features
    jyo_code = int(race_info.get('jyo') or 0)
    race_num_code = int(race_info.get('race_num') or 0)
    cushion_val = race_info.get('cushion')
    dirt_moist = race_info.get('dirt_moisture')

    con = _jv_con()
    rows = []
    for h in horses:
        um = int(h.get('umaban', 0))
        kt = str(h.get('ketto_num', ''))
        ni = h.get('ninki')
        od = h.get('win_odds')

        fig = ct.get_figure(kt, surf) if ct and kt else None
        h7 = fig['fig'] if fig else None
        sp = _prior_spurt(con, kt) if con and kt else None
        t3, a5 = (_prior_record(con, kt) if con and kt else (None, None))

        rows.append({
            'umaban': um,
            'ninki': ni,
            'log_odds': float(np.log1p(float(od))) if od else None,
            'futan': h.get('futan'), 'bataiju': h.get('bataiju'),
            'zogen': h.get('zogen'), 'sex_code': sx.get(h.get('sex', ''), 0),
            'age': h.get('age'),
            'field_size': fs, 'is_handicap': ih, 'surface_code': sc,
            'kyori': ky, 'baba_code': bc,
            'h7_fig': h7, 'spurt_mean3': sp,
            'prior_top3_rate': t3, 'avg_chaku5': a5,
            'jyo_code': jyo_code, 'race_num_code': race_num_code,
            'cushion': cushion_val, 'dirt_moisture': dirt_moist,
        })
    if con:
        con.close()
    if not rows:
        return None

    vh = sorted([(r['umaban'], r['h7_fig']) for r in rows if r['h7_fig'] is not None],
                key=lambda x: x[1])
    h7r = {u: i + 1 for i, (u, _) in enumerate(vh)}
    vs = sorted([(r['umaban'], r['spurt_mean3']) for r in rows if r['spurt_mean3'] is not None],
                key=lambda x: x[1])
    spr = {u: i + 1 for i, (u, _) in enumerate(vs)}
    for r in rows:
        r['h7_rank'] = h7r.get(r['umaban'])
        r['spurt_rank'] = spr.get(r['umaban'])

    X = np.array([[r.get(f) for f in features] for r in rows], dtype=np.float64)
    scores = model.predict(X)
    return {r['umaban']: float(s) for r, s in zip(rows, scores)}
