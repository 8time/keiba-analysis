"""
bullet_signal.py — ●シグナル判定ロジック
"""
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


def build_cross_venue_pairs(entries: List[Entry]) -> List[Tuple[Entry, Entry]]:
    """venue が異なるペアのみ列挙する。"""
    pairs = []
    for a, b in combinations(entries, 2):
        if a.venue != b.venue:
            pairs.append((a, b))
    return pairs


def evaluate_bullet(group: TrainerCrossVenueRaceGroup) -> BulletResult:
    """●判定メイン。"""
    neg = BulletResult(flag=False)
    pairs = build_cross_venue_pairs(group.entries)
    if not pairs:
        return neg

    all_rule_types = set()
    matched_pairs = []

    for a, b in pairs:
        rules = match_patterns_for_cross_venue(a, b)
        if rules:
            all_rule_types.update(rules)
            matched_pairs.append(PairMatch(
                venue_a=a.venue,
                venue_b=b.venue,
                race_number=group.race_number,
                horse_number_a=a.horse_number,
                horse_number_b=b.horse_number,
                matched_rule_types=rules,
            ))

    if matched_pairs:
        return BulletResult(
            flag=True,
            matched_rule_types=sorted(all_rule_types),
            matched_pairs=matched_pairs,
        )
    return neg


def evaluate_all_bullet_groups(
    groups: Dict[Tuple, TrainerCrossVenueRaceGroup]
) -> Dict[Tuple, BulletResult]:
    """全●グループを一括判定する。"""
    results = {}
    for key, grp in groups.items():
        results[key] = evaluate_bullet(grp)
    return results
