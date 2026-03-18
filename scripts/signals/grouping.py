"""
grouping.py — ◎●シグナル用グループ構築
"""
from collections import defaultdict
from typing import Dict, List, Tuple

from .models import Entry, EntityDailyVenueGroup, TrainerCrossVenueRaceGroup


def build_entity_daily_venue_groups(entries: List[Entry]) -> Dict[Tuple, EntityDailyVenueGroup]:
    """◎判定用: (date, venue, entity_type, entity_name) でグループ化する。"""
    groups = {}

    # jockey 用
    jockey_map = defaultdict(list)
    for e in entries:
        jockey_map[(e.date, e.venue, "jockey", e.jockey)].append(e)
    for key, ents in jockey_map.items():
        groups[key] = EntityDailyVenueGroup(
            date=key[0], venue=key[1], entity_type="jockey",
            entity_name=key[3], entries=ents
        )

    # trainer 用
    trainer_map = defaultdict(list)
    for e in entries:
        trainer_map[(e.date, e.venue, "trainer", e.trainer)].append(e)
    for key, ents in trainer_map.items():
        groups[key] = EntityDailyVenueGroup(
            date=key[0], venue=key[1], entity_type="trainer",
            entity_name=key[3], entries=ents
        )

    return groups


def filter_double_circle_candidate_groups(
    groups: Dict[Tuple, EntityDailyVenueGroup]
) -> Dict[Tuple, EntityDailyVenueGroup]:
    """◎候補: entries数 >= 2 のみ残す。"""
    return {k: v for k, v in groups.items() if len(v.entries) >= 2}


def build_trainer_cross_venue_race_groups(
    entries: List[Entry]
) -> Dict[Tuple, TrainerCrossVenueRaceGroup]:
    """●判定用: (date, trainer, race_number) でグループ化する。"""
    tmp = defaultdict(list)
    for e in entries:
        tmp[(e.date, e.trainer, e.race_number)].append(e)

    groups = {}
    for key, ents in tmp.items():
        groups[key] = TrainerCrossVenueRaceGroup(
            date=key[0], trainer=key[1], race_number=key[2], entries=ents
        )
    return groups


def filter_bullet_candidate_groups(
    groups: Dict[Tuple, TrainerCrossVenueRaceGroup]
) -> Dict[Tuple, TrainerCrossVenueRaceGroup]:
    """●候補: venue数 >= 2 かつ 各venueに1頭ずつのみ。"""
    result = {}
    for key, grp in groups.items():
        venue_counts = defaultdict(int)
        for e in grp.entries:
            venue_counts[e.venue] += 1
        if len(venue_counts) < 2:
            continue
        # 各venueに1頭ずつのみ
        if all(c == 1 for c in venue_counts.values()):
            result[key] = grp
    return result
