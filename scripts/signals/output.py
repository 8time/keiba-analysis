"""
output.py — CSV出力・表示用変換
"""
import csv
from typing import Dict, List, Tuple

import pandas as pd

from .models import (
    Entry, EntityDailyVenueGroup, TrainerCrossVenueRaceGroup,
    DoubleCircleResult, BulletResult,
)


def entry_to_output_dict(entry: Entry) -> dict:
    """Entry を出力用 dict に変換する。"""
    return {
        "date": entry.date,
        "venue": entry.venue,
        "race_number": entry.race_number,
        "horse_number": entry.horse_number,
        "horse_name": entry.horse_name,
        "jockey": entry.jockey,
        "trainer": entry.trainer,
        "odds": entry.odds,
        "odds_rank": entry.odds_rank,
        "patterns_detected": entry.patterns_detected,
        "match_details": entry.match_details,
        "existing_score": entry.existing_score,
        "jockey_double_circle_flag": entry.jockey_double_circle_flag,
        "jockey_double_circle_rule_type": entry.jockey_double_circle_rule_type or "",
        "trainer_double_circle_flag": entry.trainer_double_circle_flag,
        "trainer_double_circle_rule_type": entry.trainer_double_circle_rule_type or "",
        "trainer_bullet_flag": entry.trainer_bullet_flag,
        "trainer_bullet_rule_types": ",".join(entry.trainer_bullet_rule_types),
        "trainer_bullet_match_details": " | ".join(entry.trainer_bullet_match_details),
        "special_marks": entry.special_marks,
        "total_score": entry.total_score,
    }


def build_double_circle_summary(
    groups: Dict[Tuple, EntityDailyVenueGroup],
    results: Dict[Tuple, DoubleCircleResult],
) -> List[dict]:
    """◎サマリー行を生成する。"""
    rows = []
    for key, res in results.items():
        if not res.flag:
            continue
        grp = groups[key]
        rows.append({
            "date": grp.date,
            "venue": grp.venue,
            "entity_type": grp.entity_type,
            "entity_name": grp.entity_name,
            "rule_type": res.rule_type,
            "entry_count": res.entry_count,
            "race_numbers": ",".join(str(r) for r in res.race_numbers),
            "horse_numbers": ",".join(str(h) for h in res.horse_numbers),
        })
    return rows


def build_bullet_summary(
    groups: Dict[Tuple, TrainerCrossVenueRaceGroup],
    results: Dict[Tuple, BulletResult],
) -> List[dict]:
    """●サマリー行を生成する。"""
    rows = []
    for key, res in results.items():
        if not res.flag:
            continue
        grp = groups[key]
        venues = sorted({e.venue for e in grp.entries})
        rows.append({
            "date": grp.date,
            "trainer": grp.trainer,
            "race_number": grp.race_number,
            "venues": ",".join(venues),
            "rule_types": ",".join(res.matched_rule_types),
            "matched_pairs_count": len(res.matched_pairs),
        })
    return rows


def export_entries_csv(entries: List[Entry], output_path: str) -> None:
    rows = [entry_to_output_dict(e) for e in entries]
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")


def export_double_circle_summary_csv(rows: List[dict], output_path: str) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")


def export_bullet_summary_csv(rows: List[dict], output_path: str) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
