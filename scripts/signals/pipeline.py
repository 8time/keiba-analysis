"""
pipeline.py — ◎●シグナル統合パイプライン
"""
from typing import Dict, List, Tuple

from .models import Entry, DoubleCircleResult, BulletResult
from .grouping import (
    build_entity_daily_venue_groups,
    filter_double_circle_candidate_groups,
    build_trainer_cross_venue_race_groups,
    filter_bullet_candidate_groups,
)
from .double_circle import evaluate_all_double_circle_groups
from .bullet_signal import evaluate_all_bullet_groups
from .annotator import (
    apply_jockey_double_circle_results,
    apply_trainer_double_circle_results,
    apply_trainer_bullet_results,
    refresh_special_marks,
)
from .scoring import refresh_scores


def run_double_circle_pipeline(entries: List[Entry]) -> Dict[Tuple, DoubleCircleResult]:
    """◎パイプライン: group化 → candidate抽出 → 判定。"""
    groups = build_entity_daily_venue_groups(entries)
    candidates = filter_double_circle_candidate_groups(groups)
    return evaluate_all_double_circle_groups(candidates)


def run_bullet_pipeline(entries: List[Entry]) -> Dict[Tuple, BulletResult]:
    """●パイプライン: group化 → candidate抽出 → 判定。"""
    groups = build_trainer_cross_venue_race_groups(entries)
    candidates = filter_bullet_candidate_groups(groups)
    return evaluate_all_bullet_groups(candidates)


def run_special_signal_pipeline(entries: List[Entry]) -> List[Entry]:
    """◎●統合パイプライン。
    処理順: ◎group → ●group → ◎判定 → ●判定 → annotate → marks → score
    """
    # 1. ◎用 group 作成 & 判定
    dc_groups = build_entity_daily_venue_groups(entries)
    dc_candidates = filter_double_circle_candidate_groups(dc_groups)
    dc_results = evaluate_all_double_circle_groups(dc_candidates)

    # 2. ●用 group 作成 & 判定
    bt_groups = build_trainer_cross_venue_race_groups(entries)
    bt_candidates = filter_bullet_candidate_groups(bt_groups)
    bt_results = evaluate_all_bullet_groups(bt_candidates)

    # 3. 各馬へ annotate
    apply_jockey_double_circle_results(entries, dc_results)
    apply_trainer_double_circle_results(entries, dc_results)
    apply_trainer_bullet_results(entries, bt_results)

    # 4. marks 更新
    refresh_special_marks(entries)

    # 5. score 更新
    refresh_scores(entries)

    return entries
