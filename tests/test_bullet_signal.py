"""
test_bullet_signal.py — ●シグナル判定テスト
"""
import sys, os, io

# ── Windows cp932 環境での UnicodeEncodeError 防止: 標準出力を UTF-8 に固定 ──
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.signals.models import Entry, TrainerCrossVenueRaceGroup
from scripts.signals.bullet_signal import (
    match_patterns_for_cross_venue,
    build_cross_venue_pairs,
    evaluate_bullet,
)


def _make_entry(race_number, horse_number, field_size, trainer="T1",
                venue="06", date="20260319", jockey="J1"):
    return Entry(
        date=date, venue=venue, race_id=f"2026{venue}0101{race_number:02d}",
        race_number=race_number, field_size=field_size,
        horse_number=horse_number, horse_name=f"Horse{horse_number}",
        jockey=jockey, trainer=trainer, odds=10.0, odds_rank=5,
    )


# =============================================
# 中山5R × 阪神5R 同一厩舎 裏同士一致 → ●
# =============================================
def test_bullet_ura_match():
    """中山(06) 16頭立て3番 ura=14 vs 阪神(09) 14頭立て14番 ura=1 → ura不一致
    実際に裏同士になる例: 06/16頭/3番(ura=14) vs 09/18頭/5番(ura=14) → ura一致
    """
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")   # ura = 14
    b = _make_entry(5, 5, 18, trainer="T1", venue="09")   # ura = 14
    rules = match_patterns_for_cross_venue(a, b)
    assert "ura_match" in rules


# =============================================
# 中山5R × 阪神5R 一の位一致 → ●
# =============================================
def test_bullet_ones_digit():
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")
    b = _make_entry(5, 13, 16, trainer="T1", venue="09")
    rules = match_patterns_for_cross_venue(a, b)
    assert "ones_digit" in rules


# =============================================
# 中山5R × 阪神5R 裏表逆 → ●
# =============================================
def test_bullet_reverse():
    """06/16頭/3番(ura=14) vs 09/16頭/14番(ura=3) → ura_a==horse_b → reverse"""
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")   # ura = 14
    b = _make_entry(5, 14, 16, trainer="T1", venue="09")  # ura = 3
    rules = match_patterns_for_cross_venue(a, b)
    assert "reverse" in rules


# =============================================
# 中山5R × 阪神5R 片方循環 → ●
# =============================================
def test_bullet_cycle():
    """06/12頭/3番 vs 09/16頭/15番 → 15 mod 12 = 3 → cycle一致"""
    a = _make_entry(5, 3, 12, trainer="T1", venue="06")
    b = _make_entry(5, 15, 16, trainer="T1", venue="09")
    rules = match_patterns_for_cross_venue(a, b)
    assert "cycle" in rules


# =============================================
# race番号違い → ●でない
# =============================================
def test_bullet_different_race_number():
    """race_number が違えばグループにならない"""
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")
    b = _make_entry(7, 3, 16, trainer="T1", venue="09")
    grp = TrainerCrossVenueRaceGroup(
        date="20260319", trainer="T1", race_number=5,
        entries=[a],  # bはR7なのでこのグループに入らない
    )
    res = evaluate_bullet(grp)
    assert res.flag is False


# =============================================
# 同場 → ●でない
# =============================================
def test_bullet_same_venue():
    """同じvenueの2頭 → cross_venue_pairs が空"""
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")
    b = _make_entry(5, 14, 16, trainer="T1", venue="06")
    pairs = build_cross_venue_pairs([a, b])
    assert len(pairs) == 0


# =============================================
# 同じvenueに複数頭 → ●でない (filter_bullet_candidate_groups で弾く)
# =============================================
def test_bullet_multiple_in_same_venue():
    """1つのvenueに2頭 → filter で弾かれるのでevaluateには来ない。
    ここではevaluateに来ても cross_venue_pairs で弾かれることを確認。
    """
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")
    b = _make_entry(5, 5, 16, trainer="T1", venue="06")
    c = _make_entry(5, 7, 16, trainer="T1", venue="09")
    grp = TrainerCrossVenueRaceGroup(
        date="20260319", trainer="T1", race_number=5,
        entries=[a, b, c],
    )
    # a-c, b-c は cross venue pair だが a-b は同場
    res = evaluate_bullet(grp)
    # pairs自体はa-c, b-cが存在するのでマッチ自体はあり得る
    # ただしfilter_bullet_candidate_groupsで弾かれるのが正しい挙動
    # ここではevaluateレベルのテストなので、pairsの中身を確認
    pairs = build_cross_venue_pairs(grp.entries)
    # 06に2頭いるので filter では弾かれるが、pairs自体は作れる
    assert len(pairs) == 2  # a-c, b-c


# =============================================
# evaluate_bullet 統合テスト
# =============================================
def test_evaluate_bullet_full():
    a = _make_entry(5, 3, 16, trainer="T1", venue="06")   # ura = 14
    b = _make_entry(5, 14, 16, trainer="T1", venue="09")  # ura = 3
    grp = TrainerCrossVenueRaceGroup(
        date="20260319", trainer="T1", race_number=5,
        entries=[a, b],
    )
    res = evaluate_bullet(grp)
    assert res.flag is True
    assert "reverse" in res.matched_rule_types
    assert len(res.matched_pairs) == 1
    assert res.matched_pairs[0].horse_number_a == 3
    assert res.matched_pairs[0].horse_number_b == 14


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
