"""
annotator.py — ◎●判定結果を各馬 Entry に反映する
"""
from typing import Dict, List, Tuple

from .models import Entry, DoubleCircleResult, BulletResult


def apply_jockey_double_circle_results(
    entries: List[Entry],
    group_results: Dict[Tuple, DoubleCircleResult]
) -> None:
    """jockey の ◎結果を各馬に反映する。"""
    for key, res in group_results.items():
        if not res.flag:
            continue
        date, venue, entity_type, entity_name = key
        if entity_type != "jockey":
            continue
        for e in entries:
            if e.date == date and e.venue == venue and e.jockey == entity_name:
                e.jockey_double_circle_flag = True
                e.jockey_double_circle_rule_type = res.rule_type


def apply_trainer_double_circle_results(
    entries: List[Entry],
    group_results: Dict[Tuple, DoubleCircleResult]
) -> None:
    """trainer の ◎結果を各馬に反映する。"""
    for key, res in group_results.items():
        if not res.flag:
            continue
        date, venue, entity_type, entity_name = key
        if entity_type != "trainer":
            continue
        for e in entries:
            if e.date == date and e.venue == venue and e.trainer == entity_name:
                e.trainer_double_circle_flag = True
                e.trainer_double_circle_rule_type = res.rule_type


def apply_trainer_bullet_results(
    entries: List[Entry],
    group_results: Dict[Tuple, BulletResult]
) -> None:
    """trainer の ●結果を各馬に反映する。"""
    for key, res in group_results.items():
        if not res.flag:
            continue
        date, trainer, race_number = key
        for e in entries:
            if e.date == date and e.trainer == trainer and e.race_number == race_number:
                e.trainer_bullet_flag = True
                e.trainer_bullet_rule_types = list(
                    set(e.trainer_bullet_rule_types) | set(res.matched_rule_types)
                )


def build_special_marks(entry: Entry) -> str:
    """表示用マーク文字列を生成する。"""
    marks = []
    if entry.jockey_double_circle_flag:
        marks.append("J◎")
    if entry.trainer_double_circle_flag:
        marks.append("T◎")
    if entry.trainer_bullet_flag:
        marks.append("●")
    if entry.jockey_single_ride_flag:
        marks.append("[1鞍限定]")
    return " ".join(marks)


def refresh_special_marks(entries: List[Entry]) -> None:
    """全馬の special_marks を更新する。"""
    for e in entries:
        e.special_marks = build_special_marks(e)
