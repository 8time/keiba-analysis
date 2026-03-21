"""
bullet_signal.py — ●シグナル判定ロジック
"""
from collections import defaultdict
from typing import Dict, List, Tuple
from itertools import combinations

from .models import Entry, TrainerCrossVenueRaceGroup, BulletResult, PairMatch
from .utils_pattern import is_ones_digit_match, is_reverse_match, is_ura_match, is_cycle_match


def match_patterns_for_cross_venue(entry_a: Entry, entry_b: Entry) -> List[str]:
    """場跨ぎペアのパターン判定。返す候補: ones_digit, reverse, ura_match, cycle"""
    matched = []
    hn_a, fs_a = entry_a.horse_number, entry_a.field_size
    hn_b, fs_b = entry_b.horse_number, entry_b.field_size

    if is_ones_digit_match(hn_a, hn_b) and hn_a != hn_b:
        matched.append("ones_digit")
    if is_reverse_match(hn_a, fs_a, hn_b, fs_b):
        matched.append("reverse")
    if is_ura_match(hn_a, fs_a, hn_b, fs_b):
        matched.append("ura_match")
    if is_cycle_match(hn_a, fs_a, hn_b, fs_b):
        matched.append("cycle")

    return matched


def compute_trainer_daily_entry_counts(entries: List[Entry]) -> Dict[Tuple[str, str], int]:
    """計算関数: 同一日付における、その trainer の全出走数を数える。キーは(date, trainer)"""
    counts = defaultdict(int)
    for e in entries:
        if e.trainer and e.trainer not in ('-', '不明', ''):
            counts[(e.date, e.trainer)] += 1
    return counts


def is_strict_bullet_candidate(entries_for_race: List[Entry], total_entries_on_date: int) -> bool:
    """厳格候補判定:
    - 当日総出走2頭のみ
    - 異なるvenue
    - 各venue 1頭ずつ
    """
    if total_entries_on_date != 2:
        return False
    
    # このgroup(同一R)にちょうど2頭いないとおかしい（異なる場・同一Rで各1頭ずつという要件のため）
    if len(entries_for_race) != 2:
        return False
        
    v1 = entries_for_race[0].venue
    v2 = entries_for_race[1].venue
    
    if v1 == v2:
        return False # 同一場所はNG
        
    return True


def build_cross_venue_pairs(entries: List[Entry]) -> List[Tuple[Entry, Entry]]:
    """venue が異なるペアのみ列挙する。"""
    pairs = []
    for a, b in combinations(entries, 2):
        if a.venue != b.venue:
            pairs.append((a, b))
    return pairs


def evaluate_bullet(group: TrainerCrossVenueRaceGroup, trainer_daily_counts: Dict[Tuple[str, str], int]) -> BulletResult:
    """●判定メイン。厳密定義に基づき判定を行う。"""
    neg = BulletResult(flag=False)
    
    # A-2. 当日総出走数条件 (total == 2)
    total_on_date = trainer_daily_counts.get((group.date, group.trainer), 0)
    
    # A-3 ~ A-5. 候補判定
    if not is_strict_bullet_candidate(group.entries, total_on_date):
        return neg

    # A-6. パターン一致条件
    a, b = group.entries[0], group.entries[1]
    rules = match_patterns_for_cross_venue(a, b)
    
    if rules:
        matched_pairs = [PairMatch(
            venue_a=a.venue,
            venue_b=b.venue,
            race_number=group.race_number,
            horse_number_a=a.horse_number,
            horse_number_b=b.horse_number,
            matched_rule_types=rules,
        )]
        return BulletResult(
            flag=True,
            matched_rule_types=sorted(rules),
            matched_pairs=matched_pairs,
        )
    
    return neg


def evaluate_all_bullet_groups(
    groups: Dict[Tuple, TrainerCrossVenueRaceGroup],
    entries: List[Entry]
) -> Dict[Tuple, BulletResult]:
    """全●グループを一括判定する。"""
    trainer_daily_counts = compute_trainer_daily_entry_counts(entries)
    
    results = {}
    for key, grp in groups.items():
        results[key] = evaluate_bullet(grp, trainer_daily_counts)
    return results
