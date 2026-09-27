# -*- coding: utf-8 -*-
"""export CSV 列のリーク分類。研究入力は SAFE_PRE_RACE のみ。"""
from __future__ import annotations

# export_features_csv.py のコメントと生成式に基づく。
HORSE = {
    'race_key': 'SAFE_PRE_RACE', 'day': 'SAFE_PRE_RACE', 'jyo': 'SAFE_PRE_RACE',
    'surface_code': 'SAFE_PRE_RACE', 'kyori_int': 'SAFE_PRE_RACE', 'race_num': 'SAFE_PRE_RACE',
    'field_size': 'SAFE_PRE_RACE', 'ketto_num': 'SAFE_PRE_RACE', 'umaban': 'SAFE_PRE_RACE',
    'waku_n': 'SAFE_PRE_RACE', 'ninki': 'SAFE_PRE_RACE', 'win_odds': 'SAFE_PRE_RACE',
    'futan': 'SAFE_PRE_RACE', 'bataiju': 'SAFE_PRE_RACE', 'zogen': 'SAFE_PRE_RACE',
    'sex_code': 'SAFE_PRE_RACE', 'age': 'SAFE_PRE_RACE', 'is_handi1': 'SAFE_PRE_RACE',
    'h7_fig': 'SAFE_PRE_RACE', 'h7_rank': 'SAFE_PRE_RACE', 'h7_pct': 'SAFE_PRE_RACE',
    'spurt_idx': 'SAFE_PRE_RACE', 'spurt_race_pct': 'SAFE_PRE_RACE', 'spurt_mean3': 'SAFE_PRE_RACE',
    'prior_top3_rate': 'SAFE_PRE_RACE', 'avg_chaku5': 'SAFE_PRE_RACE', 'prior_margin': 'SAFE_PRE_RACE',
    'margin_best3': 'SAFE_PRE_RACE', 'days_since': 'SAFE_PRE_RACE', 'dist_change': 'SAFE_PRE_RACE',
    'avg_pos3': 'SAFE_PRE_RACE', 'pos_ratio3': 'SAFE_PRE_RACE', 'h_lap33': 'SAFE_PRE_RACE',
    'course_l33': 'SAFE_PRE_RACE', 'lap_align': 'SAFE_PRE_RACE', 'lap_fit_bin': 'SAFE_PRE_RACE',
    'sire_surf_t3': 'SAFE_PRE_RACE', 'sire_dist_t3': 'SAFE_PRE_RACE', 'bms_surf_t3': 'SAFE_PRE_RACE',
    'blood_race_pct': 'SAFE_PRE_RACE', 'sire': 'SAFE_PRE_RACE', 'bms': 'SAFE_PRE_RACE',
    'sire_winroi': 'SAFE_PRE_RACE', 'jockey_form_t3': 'SAFE_PRE_RACE', 'jk_race_pct': 'SAFE_PRE_RACE',
    'jockey_jyo_win': 'SAFE_PRE_RACE', 'jockey_dist_win': 'SAFE_PRE_RACE',
    'trainer_jyo_t3': 'SAFE_PRE_RACE', 'trainer_form_t3': 'SAFE_PRE_RACE',
    'elim_n': 'SAFE_PRE_RACE',
    'ability_score': 'SAFE_PRE_RACE', 'vh2_score': 'SAFE_PRE_RACE',
    # 2024+・7番人気以下だけのキャッシュ。TRAIN ではほぼ欠測。
    'combo': 'UNCERTAIN',
    'chakujun': 'LABEL_ONLY', 'top3': 'LABEL_ONLY', 'win': 'LABEL_ONLY',
}

RACE_LABEL = {'arareA', 'arareB', 'ana2', 'honsen', 'ninki_top3_logsum'}
RACE_UNCERTAIN = {'n_combo2', 'n_combo3', 'combo_cov'}

# レース集約は馬側 SAFE 列と事前オッズからのみ。
def race_class(col: str) -> str:
    if col in RACE_LABEL:
        return 'LABEL_ONLY'
    if col in RACE_UNCERTAIN:
        return 'UNCERTAIN'
    return 'SAFE_PRE_RACE'
