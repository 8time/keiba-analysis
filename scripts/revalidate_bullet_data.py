import sys, os
from collections import defaultdict
from typing import List, Dict, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.signals.models import Entry, TrainerCrossVenueRaceGroup, BulletResult, PairMatch
from scripts.signals.bullet_signal import (
    match_patterns_for_cross_venue,
    compute_trainer_daily_entry_counts,
    is_strict_bullet_candidate
)

def evaluate_bullet_old(group: TrainerCrossVenueRaceGroup) -> bool:
    """旧判定ロジック: 同一厩舎、別会場、同一R、パターン一致のみ"""
    if len(group.entries) < 2: return False
    # venue違いを簡易チェック
    venues = set(e.venue for e in group.entries)
    if len(venues) < 2: return False
    
    # パターン一致
    for i in range(len(group.entries)):
        for j in range(i + 1, len(group.entries)):
            if group.entries[i].venue != group.entries[j].venue:
                if match_patterns_for_cross_venue(group.entries[i], group.entries[j]):
                    return True
    return False

def evaluate_bullet_new(group: TrainerCrossVenueRaceGroup, counts: dict) -> bool:
    """新判定ロジック: 当日総出走ちょうど2頭、別会場1頭ずつ、同一R、パターン一致"""
    total = counts.get((group.date, group.trainer), 0)
    if total != 2: return False
    if len(group.entries) != 2: return False
    if group.entries[0].venue == group.entries[1].venue: return False
    if match_patterns_for_cross_venue(group.entries[0], group.entries[1]):
        return True
    return False

def run_revalidation():
    def _me(date, trainer, venue, race_number, horse_number, field_size=16):
        from scripts.signals.models import Entry
        return Entry(
            date=date, venue=venue, race_id=f"2026{venue}{race_number}", 
            race_number=race_number, field_size=field_size, horse_number=horse_number,
            horse_name=f"H{horse_number}", jockey="J", trainer=trainer, odds=10, odds_rank=5
        )

    # テストケース作成
    cases = []
    
    # Case 1: 3 entries total for T1. R5 has 2 entries in diff venues.
    # Old: True | New: False (Reason: 3 entries total)
    t1_entries = [
        _me("2026/03/22", "T1", "中山", 5, 3), # R5
        _me("2026/03/22", "T1", "阪神", 5, 14), # R5 (Reverse match with 3 ura=14)
        _me("2026/03/22", "T1", "中山", 10, 1), # R10 (3rd entry)
    ]
    cases.append(("T1", 5, t1_entries))

    # Case 2: 2 entries total for T2. R5 has 2 entries in diff venues. Pattern matches.
    # Old: True | New: True
    t2_entries = [
        _me("2026/03/22", "T2", "中山", 5, 3), # R5
        _me("2026/03/22", "T2", "阪神", 5, 13), # R5 (Ones match)
    ]
    cases.append(("T2", 5, t2_entries))

    # Case 3: 2 entries total for T3. R5 has 1, R6 has 1.
    # Old: False (group has 1 entry) | New: False
    t3_entries = [
        _me("2026/03/22", "T3", "中山", 5, 3),
        _me("2026/03/22", "T3", "阪神", 6, 3),
    ]
    cases.append(("T3", 5, t3_entries))

    # Case 4: 2 entries total for T4. R5 has 2 entries in SAME venue.
    # Old: False | New: False
    t4_entries = [
        _me("2026/03/22", "T4", "中山", 5, 3),
        _me("2026/03/22", "T4", "中山", 5, 13),
    ]
    cases.append(("T4", 5, t4_entries))

    # 全出走者
    all_entries = []
    for c in cases: all_entries.extend(c[2])
    counts = compute_trainer_daily_entry_counts(all_entries)

    # 検証
    report = []
    old_count = 0
    new_count = 0
    
    # グループ化（簡易）
    trainer_groups = defaultdict(lambda: defaultdict(list))
    for e in all_entries:
        trainer_groups[e.trainer][e.race_number].append(e)

    for trainer, races_dict in trainer_groups.items():
        for r_num, ents in races_dict.items():
            grp = TrainerCrossVenueRaceGroup(date="2026/03/22", trainer=trainer, race_number=r_num, entries=ents)
            old_f = evaluate_bullet_old(grp)
            new_f = evaluate_bullet_new(grp, counts)
            
            if old_f: old_count += 1
            if new_f: new_count += 1
            
            reason = "-"
            if old_f and not new_f:
                total = counts.get(("2026/03/22", trainer), 0)
                if total > 2: reason = "当日総出走数が2頭を超えていた"
                elif len(ents) != 2: reason = "race_number不一致 または 各場1頭ずつでない"
                elif ents[0].venue == ents[1].venue: reason = "venue条件不一致"
                else: reason = "パターン不一致"
            
            report.append({
                "date": "2026/03/22",
                "trainer": trainer,
                "race_number": r_num,
                "old": old_f,
                "new": new_f,
                "reason": reason
            })

    print(f"1. 旧判定件数: {old_count}")
    print(f"2. 新判定件数: {new_count}")
    print("\n3. 再検証結果:")
    print("date | trainer | race_number | old | new | exclusion_reason")
    for r in report:
        print(f"{r['date']} | {r['trainer']} | {r['race_number']} | {r['old']} | {r['new']} | {r['reason']}")

if __name__ == "__main__":
    run_revalidation()
