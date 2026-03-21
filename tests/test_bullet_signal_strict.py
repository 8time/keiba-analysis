"""
test_bullet_signal_strict.py — ●シグナル判定の厳密条件テスト
"""
import sys, os, io
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.signals.models import Entry, TrainerCrossVenueRaceGroup, BulletResult
from scripts.signals.bullet_signal import (
    evaluate_bullet,
    compute_trainer_daily_entry_counts,
    is_strict_bullet_candidate,
)
from scripts.signals.annotator import apply_trainer_bullet_results

def _make_entry(race_number, horse_number, field_size, trainer="T1",
                venue="06", date="20260322", jockey="J1"):
    return Entry(
        date=date, venue=venue, race_id=f"2026{venue}0101{race_number:02d}",
        race_number=race_number, field_size=field_size,
        horse_number=horse_number, horse_name=f"Horse{horse_number}",
        jockey=jockey, trainer=trainer, odds=10.0, odds_rank=5,
    )

# 1. 同一厩舎が当日ちょうど2頭出走、別開催地、同一race_number、裏同士一致 -> ● True
def test_strict_bullet_success():
    a = _make_entry(5, 3, 16, trainer="T-STRICT", venue="06") # ura=14
    b = _make_entry(5, 5, 18, trainer="T-STRICT", venue="09") # ura=14
    
    all_entries = [a, b]
    counts = compute_trainer_daily_entry_counts(all_entries)
    
    grp = TrainerCrossVenueRaceGroup(date="20260322", trainer="T-STRICT", race_number=5, entries=[a, b])
    res = evaluate_bullet(grp, counts)
    
    assert res.flag is True
    assert "ura_match" in res.matched_rule_types

# 2. 同一厩舎が当日3頭以上出走 -> ● False
def test_strict_bullet_fail_3_entries():
    a = _make_entry(5, 3, 16, trainer="T-3", venue="06")
    b = _make_entry(5, 5, 18, trainer="T-3", venue="09")
    c = _make_entry(10, 1, 16, trainer="T-3", venue="06") # 同一厩舎の3頭目
    
    all_entries = [a, b, c]
    counts = compute_trainer_daily_entry_counts(all_entries)
    
    grp = TrainerCrossVenueRaceGroup(date="20260322", trainer="T-3", race_number=5, entries=[a, b])
    res = evaluate_bullet(grp, counts)
    
    assert res.flag is False # 3頭以上なのでNG

# 3. 同一厩舎が当日2頭出走だが race_number が違う -> ● False
def test_strict_bullet_fail_diff_race_number():
    a = _make_entry(5, 3, 16, trainer="T-DIFF-R", venue="06")
    b = _make_entry(6, 3, 16, trainer="T-DIFF-R", venue="09")
    
    all_entries = [a, b]
    counts = compute_trainer_daily_entry_counts(all_entries)
    
    # R5 のグループを評価してみる
    grp = TrainerCrossVenueRaceGroup(date="20260322", trainer="T-DIFF-R", race_number=5, entries=[a])
    res = evaluate_bullet(grp, counts)
    
    # R5のグループには1頭しかいないのでNG
    assert res.flag is False

# 4. 同一厩舎が当日2頭出走だが同一開催地 -> ● False
def test_strict_bullet_fail_same_venue():
    a = _make_entry(5, 3, 16, trainer="T-SAME-V", venue="06")
    b = _make_entry(5, 5, 16, trainer="T-SAME-V", venue="06")
    
    all_entries = [a, b]
    counts = compute_trainer_daily_entry_counts(all_entries)
    
    grp = TrainerCrossVenueRaceGroup(date="20260322", trainer="T-SAME-V", race_number=5, entries=[a, b])
    res = evaluate_bullet(grp, counts)
    
    assert res.flag is False # 同一場所なのでNG

# 5. 同一厩舎が当日2頭出走、別開催地、同一race_number だがパターン不一致 -> ● False
def test_strict_bullet_fail_no_pattern():
    a = _make_entry(5, 1, 16, trainer="T-NOPAT", venue="06")
    b = _make_entry(5, 8, 16, trainer="T-NOPAT", venue="09")
    
    all_entries = [a, b]
    counts = compute_trainer_daily_entry_counts(all_entries)
    
    grp = TrainerCrossVenueRaceGroup(date="20260322", trainer="T-NOPAT", race_number=5, entries=[a, b])
    res = evaluate_bullet(grp, counts)
    
    assert res.flag is False

# 6. trainer_bullet_match_details に bullet 根拠だけが入る
def test_bullet_match_details_separation():
    a = _make_entry(5, 3, 16, trainer="T-DETAIL", venue="06")
    b = _make_entry(5, 13, 16, trainer="T-DETAIL", venue="09") # ones_digit match
    
    all_entries = [a, b]
    counts = compute_trainer_daily_entry_counts(all_entries)
    
    grp = TrainerCrossVenueRaceGroup(date="20260322", trainer="T-DETAIL", race_number=5, entries=[a, b])
    res = evaluate_bullet(grp, counts)
    assert res.flag is True
    
    results_map = {("20260322", "T-DETAIL", 5): res}
    apply_trainer_bullet_results(all_entries, results_map)
    
    assert "一の位一致" in all_entries[0].trainer_bullet_match_details[0]
    assert "065R(3番) と 095R(13番)" in all_entries[0].trainer_bullet_match_details[0]

if __name__ == "__main__":
    test_strict_bullet_success()
    test_strict_bullet_fail_3_entries()
    test_strict_bullet_fail_diff_race_number()
    test_strict_bullet_fail_same_venue()
    test_strict_bullet_fail_no_pattern()
    test_bullet_match_details_separation()
    print("All strict bullet tests passed!")
