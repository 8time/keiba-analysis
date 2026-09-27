# -*- coding: utf-8 -*-
"""CSV 行から本番 LTR モデル (data/ltr_model.lgb) で Rank スコアを再推論。

ability_score とは別物（export の ability_score は h7/spurt/blood/jk の pct 平均）。
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_PATH = os.path.join(_ROOT, 'data', 'ltr_model.lgb')
_META_PATH = os.path.join(_ROOT, 'data', 'ltr_meta.json')

_SEX_MAP = {1: '牡', 2: '牝', 3: 'セ'}


def ltr_available() -> bool:
    return os.path.exists(_MODEL_PATH) and os.path.exists(_META_PATH)


def _load_model():
    if not ltr_available():
        return None, None
    import lightgbm as lgb
    with open(_META_PATH, encoding='utf-8') as f:
        meta = json.load(f)
    return lgb.Booster(model_file=_MODEL_PATH), meta


def predict_race_frame(
    horse_df: pd.DataFrame,
    race_meta: dict,
) -> dict[int, float]:
    """1レース分の馬行 DataFrame → {umaban: ltr_score}。欠損多い場合は部分返却。"""
    model, meta = _load_model()
    if model is None or horse_df is None or horse_df.empty:
        return {}
    features = meta['features']
    g = horse_df.copy()
    fs = int(race_meta.get('field_size') or len(g))
    ih = int(race_meta.get('is_handi1') or 0)
    sc = int(race_meta.get('surface_code') or 0)
    ky = int(race_meta.get('kyori_int') or race_meta.get('kyori') or 0)
    jyo = int(race_meta.get('jyo') or 0)
    rn = int(race_meta.get('race_num') or race_meta.get('race_num_code') or 0)
    bc = int(race_meta.get('baba_code') or 0)
    cushion = race_meta.get('cushion')
    dirt_m = race_meta.get('dirt_moisture')

    g['log_odds'] = np.log1p(pd.to_numeric(g['win_odds'], errors='coerce'))
    g['field_size'] = fs
    g['is_handicap'] = ih
    g['surface_code'] = sc
    g['kyori'] = ky
    g['baba_code'] = bc
    g['jyo_code'] = jyo
    g['race_num_code'] = rn
    g['cushion'] = cushion
    g['dirt_moisture'] = dirt_m

    g['h7_rank'] = pd.to_numeric(g['h7_fig'], errors='coerce').rank(
        method='min', ascending=True, na_option='bottom')
    g['spurt_rank'] = pd.to_numeric(g['spurt_mean3'], errors='coerce').rank(
        method='min', ascending=True, na_option='bottom')

    rows = []
    for r in g.itertuples(index=False):
        um = int(getattr(r, 'umaban', 0) or 0)
        if um <= 0:
            continue
        row = {
            'umaban': um,
            'ninki': getattr(r, 'ninki', None),
            'log_odds': getattr(r, 'log_odds', None),
            'futan': getattr(r, 'futan', None),
            'bataiju': getattr(r, 'bataiju', None),
            'zogen': getattr(r, 'zogen', None),
            'sex_code': getattr(r, 'sex_code', None),
            'age': getattr(r, 'age', None),
            'field_size': fs,
            'is_handicap': ih,
            'surface_code': sc,
            'kyori': ky,
            'baba_code': bc,
            'h7_fig': getattr(r, 'h7_fig', None),
            'h7_rank': getattr(r, 'h7_rank', None),
            'spurt_mean3': getattr(r, 'spurt_mean3', None),
            'spurt_rank': getattr(r, 'spurt_rank', None),
            'prior_top3_rate': getattr(r, 'prior_top3_rate', None),
            'avg_chaku5': getattr(r, 'avg_chaku5', None),
            'jyo_code': jyo,
            'race_num_code': rn,
            'cushion': cushion,
            'dirt_moisture': dirt_m,
            'trainer_jyo_t3': getattr(r, 'trainer_jyo_t3', None),
            'jockey_jyo_win': getattr(r, 'jockey_jyo_win', None),
            'jockey_dist_win': getattr(r, 'jockey_dist_win', None),
        }
        row['umaban'] = um
        rows.append(row)

    if not rows:
        return {}

    X = []
    ums = []
    for row in rows:
        ums.append(row['umaban'])
        X.append([row.get(f) for f in features])
    X = np.array(X, dtype=np.float64)
    scores = model.predict(X)
    return {u: float(s) for u, s in zip(ums, scores)}
