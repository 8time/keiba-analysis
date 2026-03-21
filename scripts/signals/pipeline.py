"""
pipeline.py — ◎●シグナル統合パイプライン
"""
from collections import defaultdict
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
    return evaluate_all_bullet_groups(candidates, entries)


def apply_jockey_single_ride(
    entries: List[Entry],
    scope: str = "venue",
) -> None:
    """当日同一場でレースをで1回だけ乗権する騎手にフラグを立てる。

    scope='venue'  → (date, venue) 内で騎手の出走数が1の場合にフラグ
    scope='all'    → 当日全場を通じて騎手の出走数が1の場合にフラグ
    """
    # (date, venue, jockey) ごとの出走数をカウント
    ride_count: dict = defaultdict(int)
    for e in entries:
        key = (e.date, e.venue, e.jockey) if scope == "venue" else (e.date, e.jockey)
        ride_count[key] += 1

    for e in entries:
        key = (e.date, e.venue, e.jockey) if scope == "venue" else (e.date, e.jockey)
        e.jockey_single_ride_flag = (ride_count[key] == 1)


import logging

logger = logging.getLogger(__name__)

def validate_entries(entries: List[Entry], threshold: float = 0.3) -> bool:
    """Entryの必須項目を検証し、異常率が高い場合はFalseを返す"""
    if not entries: return False
    
    invalid_count = 0
    trainer_missing = 0
    
    for e in entries:
        is_invalid = False
        if not e.horse_name or not e.jockey or not e.race_id:
            is_invalid = True
        if e.field_size <= 0 or e.horse_number <= 0:
            is_invalid = True
            
        if not e.trainer or e.trainer in ('-', '不明', ''):
            trainer_missing += 1
            # Trainer missing alone is just a warning, handled in grouping
            # but we record it for statistics
            
        if is_invalid:
            invalid_count += 1
            
    invalid_ratio = invalid_count / len(entries)
    if invalid_ratio > threshold:
        logger.error(f"[Fail-Fast] Entry invalid ratio ({invalid_ratio:.1%}) exceeds threshold ({threshold:.1%}). Suspending signal evaluation.")
        return False
        
    return True

def run_special_signal_pipeline(entries: List[Entry]) -> List[Entry]:
    """◎●統合パイプライン。
    処理順: Entry検証 → ◎group → ●group → ◎判定 → ●判定 → 1回騎乗 → annotate → marks → score
    """
    if not validate_entries(entries):
        return entries
    
    # 1. ◎用 group 作成 & 判定
    dc_groups = build_entity_daily_venue_groups(entries)
    dc_candidates = filter_double_circle_candidate_groups(dc_groups)
    dc_results = evaluate_all_double_circle_groups(dc_candidates)

    # 2. ●用 group 作成 & 判定
    bt_groups = build_trainer_cross_venue_race_groups(entries)
    bt_candidates = filter_bullet_candidate_groups(bt_groups)
    bt_results = evaluate_all_bullet_groups(bt_candidates, entries)

    # 3. 全場通じて1回のみ騎乗の騎手フラグ付け (追加要件2)
    apply_jockey_single_ride(entries, scope="all")

    # 4. 各馬へ annotate
    apply_jockey_double_circle_results(entries, dc_results)
    apply_trainer_double_circle_results(entries, dc_results)
    apply_trainer_bullet_results(entries, bt_results)

    # 5. marks 更新
    refresh_special_marks(entries)

    # 6. score 更新
    refresh_scores(entries)

    return entries
