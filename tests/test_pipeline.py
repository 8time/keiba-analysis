"""
test_pipeline.py — ◎●統合パイプラインテスト
"""
import sys, os, io

# ── Windows cp932 環境での UnicodeEncodeError 防止: 標準出力を UTF-8 に固定 ──
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.signals.models import Entry
from scripts.signals.pipeline import run_special_signal_pipeline
from scripts.signals.output import entry_to_output_dict


def _make_entry(race_number, horse_number, field_size, jockey="J1", trainer="T1",
                venue="06", date="20260319"):
    return Entry(
        date=date, venue=venue, race_id=f"2026{venue}0101{race_number:02d}",
        race_number=race_number, field_size=field_size,
        horse_number=horse_number, horse_name=f"Horse{horse_number}",
        jockey=jockey, trainer=trainer, odds=10.0, odds_rank=5,
        existing_score=3,
    )


def test_pipeline_jockey_double_circle_marks():
    """同一騎手が同一場で全出走同馬番 → J◎ が付く"""
    entries = [
        _make_entry(1, 10, 16, jockey="Jockey_A"),
        _make_entry(3, 10, 14, jockey="Jockey_A"),
        _make_entry(7, 10, 12, jockey="Jockey_A"),
        _make_entry(2, 5, 16, jockey="Jockey_B"),  # 別騎手
    ]
    result = run_special_signal_pipeline(entries)
    # Jockey_A の全3走に J◎ が付く
    ja_entries = [e for e in result if e.jockey == "Jockey_A"]
    for e in ja_entries:
        assert e.jockey_double_circle_flag is True
        assert e.jockey_double_circle_rule_type == "same_horse_number"
        assert "J◎" in e.special_marks

    # Jockey_B は1走のみなので◎なし
    jb_entries = [e for e in result if e.jockey == "Jockey_B"]
    for e in jb_entries:
        assert e.jockey_double_circle_flag is False


def test_pipeline_trainer_bullet_marks():
    """同一厩舎が場跨ぎ同一R番号で裏表逆 → T● が付く"""
    entries = [
        _make_entry(5, 3, 16, trainer="Trainer_A", venue="06"),   # ura=14
        _make_entry(5, 14, 16, trainer="Trainer_A", venue="09"),  # ura=3
        _make_entry(1, 1, 16, trainer="Trainer_B", venue="06"),   # 無関係
    ]
    result = run_special_signal_pipeline(entries)
    ta_entries = [e for e in result if e.trainer == "Trainer_A"]
    for e in ta_entries:
        assert e.trainer_bullet_flag is True
        assert "T●" in e.special_marks

    tb_entries = [e for e in result if e.trainer == "Trainer_B"]
    for e in tb_entries:
        assert e.trainer_bullet_flag is False


def test_pipeline_score_updated():
    """パイプライン実行後に total_score が更新される"""
    entries = [
        _make_entry(1, 10, 16, jockey="J_A"),
        _make_entry(3, 10, 14, jockey="J_A"),
    ]
    for e in entries:
        e.existing_score = 5

    result = run_special_signal_pipeline(entries)
    ja_entries = [e for e in result if e.jockey == "J_A"]
    for e in ja_entries:
        # existing_score(5) + jockey◎(+3) = 8 minimum
        assert e.total_score >= 8


def test_pipeline_output_dict_has_extra_columns():
    """出力dictに追加列が含まれる"""
    entries = [
        _make_entry(1, 10, 16, jockey="J_A"),
        _make_entry(3, 10, 14, jockey="J_A"),
    ]
    result = run_special_signal_pipeline(entries)
    d = entry_to_output_dict(result[0])
    assert "jockey_double_circle_flag" in d
    assert "jockey_double_circle_rule_type" in d
    assert "trainer_double_circle_flag" in d
    assert "trainer_double_circle_rule_type" in d
    assert "trainer_bullet_flag" in d
    assert "trainer_bullet_rule_types" in d
    assert "special_marks" in d
    assert "total_score" in d


def test_pipeline_both_dc_and_bullet():
    """同一馬に J◎ + T◎ + T● が同時に付くケース"""
    entries = [
        # 騎手J_A: 場06でR1,R3,R5に馬番10 → J◎(same_horse_number)
        # 厩舎T_A: 場06でR1,R3,R5に馬番10 → T◎(same_horse_number)
        _make_entry(1, 10, 16, jockey="J_A", trainer="T_A", venue="06"),
        _make_entry(3, 10, 14, jockey="J_A", trainer="T_A", venue="06"),
        _make_entry(5, 10, 12, jockey="J_A", trainer="T_A", venue="06"),
        # 厩舎T_A: 場09のR1に馬番14 → 場06 R1(馬番10, ura=7) vs 場09 R1(馬番14)
        # ura@06/16 = 7, ura@09/16 = 3. reverse: ura_a(7)==horse_b(14)?No. horse_a(10)==ura_b(3)?No
        # ones_digit: 10%10=0, 14%10=4 → No
        # 裏表逆にするため: 場09 R1 馬番7 field16 → ura=10 → horse_a(10)==ura_b(10) → reverse!
        _make_entry(1, 7, 16, jockey="J_B", trainer="T_A", venue="09"),
    ]
    result = run_special_signal_pipeline(entries)
    # R1, venue06, trainer T_A の馬
    r1_06 = [e for e in result if e.race_number == 1 and e.venue == "06"]
    assert len(r1_06) == 1
    e = r1_06[0]
    assert e.jockey_double_circle_flag is True
    assert e.trainer_double_circle_flag is True
    assert e.trainer_bullet_flag is True
    assert "J◎" in e.special_marks
    assert "T◎" in e.special_marks
    assert "T●" in e.special_marks


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
