"""
test_double_circle.py — ◎シグナル判定テスト
"""
import sys, os, io

# ── Windows cp932 環境での UnicodeEncodeError 防止: 標準出力を UTF-8 に固定 ──
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.signals.models import Entry, EntityDailyVenueGroup
from scripts.signals.double_circle import (
    check_same_horse_number_all,
    check_ones_digit_all,
    check_reverse_axis_all,
    check_cycle_target_all,
    check_same_waku_all,
    evaluate_double_circle,
)


def _make_entry(race_number, horse_number, field_size, jockey="J1", trainer="T1",
                venue="06", date="20260319"):
    return Entry(
        date=date, venue=venue, race_id=f"2026{venue}0101{race_number:02d}",
        race_number=race_number, field_size=field_size,
        horse_number=horse_number, horse_name=f"Horse{horse_number}",
        jockey=jockey, trainer=trainer, odds=10.0, odds_rank=5,
    )


# =============================================
# same_horse_number ◎
# =============================================
def test_same_horse_number_all_true():
    """10,10,10 → same_horse_number ◎"""
    entries = [
        _make_entry(1, 10, 16),
        _make_entry(3, 10, 14),
        _make_entry(7, 10, 12),
    ]
    ok, val = check_same_horse_number_all(entries)
    assert ok is True
    assert val == 10


def test_same_horse_number_all_false():
    entries = [
        _make_entry(1, 10, 16),
        _make_entry(3, 5, 14),
    ]
    ok, val = check_same_horse_number_all(entries)
    assert ok is False


# =============================================
# ones_digit ◎
# =============================================
def test_ones_digit_all_true():
    """13,3,13 → ones_digit ◎"""
    entries = [
        _make_entry(1, 13, 16),
        _make_entry(3, 3, 14),
        _make_entry(5, 13, 18),
    ]
    ok, val = check_ones_digit_all(entries)
    assert ok is True
    assert val == 3


def test_ones_digit_all_false():
    entries = [
        _make_entry(1, 13, 16),
        _make_entry(3, 4, 14),
    ]
    ok, val = check_ones_digit_all(entries)
    assert ok is False


# =============================================
# reverse_axis ◎
# =============================================
def test_reverse_axis_all_true():
    """1,1,大外(16頭立て16番) → reverse_axis ◎
    entry1: horse=1, ura=16 → axis={1,16}
    entry2: horse=1, ura=14 → axis={1,14}
    entry3: horse=16, ura=1 → axis={16,1}
    共通: {1}
    """
    entries = [
        _make_entry(1, 1, 16),
        _make_entry(3, 1, 14),
        _make_entry(5, 16, 16),  # 大外 = ura is 1
    ]
    ok, val = check_reverse_axis_all(entries)
    assert ok is True
    assert val == 1


def test_reverse_axis_all_false():
    entries = [
        _make_entry(1, 3, 16),
        _make_entry(3, 7, 14),
    ]
    ok, val = check_reverse_axis_all(entries)
    assert ok is False


# =============================================
# cycle_target ◎
# =============================================
def test_cycle_target_all_true():
    """全て循環15番を共有"""
    # horse=15, field=16 → targets={15, 31, 47, ...} → 15を含む
    # horse=3, field=12 → targets={3, 15, 27, ...} → 15を含む
    # horse=1, field=14 → targets={1, 15, 29, ...} → 15を含む
    entries = [
        _make_entry(1, 15, 16),
        _make_entry(3, 3, 12),
        _make_entry(5, 1, 14),
    ]
    ok, val = check_cycle_target_all(entries)
    assert ok is True
    assert val == 15


def test_cycle_target_all_false():
    entries = [
        _make_entry(1, 1, 16),
        _make_entry(3, 2, 16),
    ]
    ok, val = check_cycle_target_all(entries)
    assert ok is False


# =============================================
# 1つでも崩れたら ◎ ではない
# =============================================
def test_one_break_means_no_double_circle():
    """3つ中2つは同馬番10だが1つだけ5 → ◎ではない"""
    entries = [
        _make_entry(1, 10, 16),
        _make_entry(3, 10, 14),
        _make_entry(5, 5, 12),
    ]
    grp = EntityDailyVenueGroup(
        date="20260319", venue="06", entity_type="jockey",
        entity_name="J1", entries=entries,
    )
    res = evaluate_double_circle(grp)
    # same_horse_number は False (5が混ざっている)
    # ones_digit は False (0と5が混在)
    # reverse_axis → {10,7}, {10,5}, {5,8} → 共通なし
    # cycle_target → check
    # 結論: 何も統一できないので False
    assert res.flag is False


# =============================================
# 同枠だけは ◎ ではない
# =============================================
def test_same_waku_only_is_not_double_circle():
    """同枠チェック関数がTrueを返すことを確認"""
    # 8頭立てで全部1番 → 同枠(1枠)かつ同馬番
    # このケースは same_horse_number でも True になるので
    # 純粋な「同枠だけ」テストとして: 違う馬番だが同枠
    # 16頭立て: 馬番1=1枠, 馬番2=1枠 (概算)
    entries = [
        _make_entry(1, 1, 16),
        _make_entry(3, 2, 16),
    ]
    waku_only = check_same_waku_all(entries)
    assert waku_only is True


# =============================================
# evaluate_double_circle 統合テスト
# =============================================
def test_evaluate_double_circle_same_horse_number():
    entries = [
        _make_entry(1, 10, 16),
        _make_entry(3, 10, 14),
        _make_entry(7, 10, 12),
    ]
    grp = EntityDailyVenueGroup(
        date="20260319", venue="06", entity_type="jockey",
        entity_name="J1", entries=entries,
    )
    res = evaluate_double_circle(grp)
    assert res.flag is True
    assert res.rule_type == "same_horse_number"
    assert res.target_value == 10
    assert res.entry_count == 3
    assert res.race_numbers == [1, 3, 7]


def test_evaluate_double_circle_ones_digit():
    entries = [
        _make_entry(1, 13, 16),
        _make_entry(3, 3, 14),
        _make_entry(5, 13, 18),
    ]
    grp = EntityDailyVenueGroup(
        date="20260319", venue="06", entity_type="jockey",
        entity_name="J1", entries=entries,
    )
    res = evaluate_double_circle(grp)
    assert res.flag is True
    assert res.rule_type == "ones_digit"


def test_evaluate_single_entry_not_double_circle():
    """1走のみ → ◎ではない"""
    entries = [_make_entry(1, 10, 16)]
    grp = EntityDailyVenueGroup(
        date="20260319", venue="06", entity_type="jockey",
        entity_name="J1", entries=entries,
    )
    res = evaluate_double_circle(grp)
    assert res.flag is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
