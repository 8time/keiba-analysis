"""Point-in-time guards for the read-only front-retention research script."""

import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "forward_retention_research.py"
spec = importlib.util.spec_from_file_location("forward_retention_research", SCRIPT)
research = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = research
spec.loader.exec_module(research)


class ForwardRetentionResearchTests(unittest.TestCase):
    def test_current_result_and_measured_pace_do_not_enter_features(self):
        current = {"year": "2024", "monthday": "0107", "jyo": "06", "kyori": 1200,
                   "shusso_tosu": 16, "umaban": 3, "chakujun": 1, "mae3f": 310}
        clean = research.make_features(current, [])
        current.update(chakujun=16, mae3f=370, corner4=16, ato3f=999)
        self.assertEqual(clean, research.make_features(current, []))

    def test_same_date_does_not_enter_history(self):
        def row(race_id, finish):
            return {"race_key": race_id, "race_id": race_id, "year": "2024",
                    "monthday": "0107", "jyo": "06", "kyori": 1200, "surface": "芝",
                    "shusso_tosu": 8, "mae3f": 340, "ketto_num": "TEST",
                    "umaban": 1, "waku": 1, "corner4": 1, "chakujun": finish,
                    "ato3f": 340, "time": "1080", "ninki": 1, "win_odds": 2.0}
        records = research.build_dataset([row("A", 1), row("B", 8)])
        self.assertEqual(2, len(records))
        self.assertEqual([0, 0], [r["history_n"] for r in records])

    def test_target_snapshot_rejects_unknown_corner_evidence(self):
        train = research.build_dataset(research.load_rows(research.DB))
        rows = [r for r in train if r["year"] == 2024]
        fronts = [r for r in rows if r["front"]]
        s1 = research.fit_logit(rows, "front", research.FEATURE_GROUPS["stage1"])
        keys = ["past_finish", "past_top3", "history_n", "field", "waku_ratio", "rest_days"]
        s2 = research.fit_logit(fronts, "top3", keys + research.FEATURE_GROUPS["retention_shape"])
        result = research.target_application(
            research.ROOT / "data" / "research" / "forward" / "decisions.jsonl",
            research.DB, s1, s2)
        by_horse = {r["umaban"]: r for r in result["horses"]}
        self.assertLess(datetime.fromisoformat(result["captured_at"]),
                        datetime.fromisoformat("2026-09-27T15:40:00+09:00"))
        self.assertIn("2026.08.02", by_horse[16]["rejected_past_dates"])
        self.assertIn("2025.12.14", by_horse[14]["rejected_past_dates"])


if __name__ == "__main__":
    unittest.main()
