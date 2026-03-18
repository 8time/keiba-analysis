"""
scoring.py — ◎●シグナルのスコア加点
"""
from typing import List

from .models import Entry


def apply_special_signal_score(entry: Entry) -> int:
    """◎●シグナルの加点。jockey◎=+3, trainer◎=+3, trainer●=+2"""
    score = 0
    if entry.jockey_double_circle_flag:
        score += 3
    if entry.trainer_double_circle_flag:
        score += 3
    if entry.trainer_bullet_flag:
        score += 2
    return score


def apply_special_overlap_bonus(entry: Entry, existing_pattern_count: int) -> int:
    """既存パターンとの重複ボーナス。"""
    bonus = 0
    has_dc = entry.jockey_double_circle_flag or entry.trainer_double_circle_flag
    has_bullet = entry.trainer_bullet_flag

    # 既存2パターン以上 + ◎あり → +1
    if existing_pattern_count >= 2 and has_dc:
        bonus += 1
    # 既存1パターン以上 + ●あり → +1
    if existing_pattern_count >= 1 and has_bullet:
        bonus += 1
    # jockey◎ + trainer◎ + trainer● → +2
    if entry.jockey_double_circle_flag and entry.trainer_double_circle_flag and entry.trainer_bullet_flag:
        bonus += 2

    return bonus


def recompute_total_score(entry: Entry) -> int:
    """既存スコア + シグナルスコア + 重複ボーナスの合計。"""
    existing_count = len(entry.patterns_detected.split(",")) if entry.patterns_detected else 0
    signal = apply_special_signal_score(entry)
    overlap = apply_special_overlap_bonus(entry, existing_count)
    return entry.existing_score + signal + overlap


def refresh_scores(entries: List[Entry]) -> None:
    """全馬の total_score を再計算する。"""
    for e in entries:
        e.total_score = recompute_total_score(e)
