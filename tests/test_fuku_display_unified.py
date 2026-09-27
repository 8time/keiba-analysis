# -*- coding: utf-8 -*-
"""推定3着内率の表示ソース統一テスト（2026-09-08）。

背景: SRA画面で同じ馬の「推定3着内率」が2か所で食い違っていた。
  - テーブル🎯軸馬候補列: axis_confidence() = 階段テーブル(ODDS_FUKU)
      + 検証済み減点（前走1着 -1.5 / 圧勝 -5.0 / 先行 -1.2 / 牝馬1人気 -1.0）
  - 「軸の信頼度」ブロック: fuku_rate() = 対数補間カーブ(ODDS_FUKU_CURVE)・減点なし
  再現例(1番人気・オッズ2.8・前走1着・先行):
      階段 64.3 - 1.5 - 1.2 = 61.6 → "62%"
      カーブ(減点なし)       = 64.2 → "64%"

対応: 表示%は fuku_rate に統一（同じ馬には必ず同じ値）。
◎〇マークの判定ロジック（axis_confidence・減点・フロア）は検証済みのまま一切変更しない。

このテストは
  (1) 食い違いの再現（原因の固定）
  (2) 統一後に fav_check（軸ブロック）の % が fuku_rate と常に一致すること
  (3) 検証済み axis_confidence の値が変わっていないことのガード
を行う。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core import axis_selector
from core import fav_check


class DiscrepancyReproductionTests(unittest.TestCase):
    """2026-09-08 のスクショの食い違い（62%/64%, 48%）を関数レベルで再現・固定。"""

    def test_flicker_jab_62_vs_64(self):
        """フリッカージャブ再現: 1番人気・オッズ2.8・前走1着・先行。
        旧テーブル表示 "62%" / 軸ブロック表示 "64%" の分裂を再現。"""
        ax = axis_selector.axis_confidence(1, 2.8, prev_chaku=1, pos_ratio=0.25)
        fk = axis_selector.fuku_rate(1, 2.8)
        self.assertEqual(ax, 61.6)                 # 64.3 - 1.5(前走1着) - 1.2(先行)
        self.assertEqual(fk, 64.2)                 # カーブ補間・減点なし
        self.assertEqual(f"{ax:.0f}%", "62%")      # 旧テーブル🎯軸馬候補列
        self.assertEqual(f"{fk:.0f}%", "64%")      # 「軸の信頼度」ブロック

    def test_bureau_magic_near_boundary(self):
        """ビューロマジック再現: 2番人気・オッズ4.4・前走圧勝。
        旧テーブル側は 52.5 - 5.0(圧勝) = 47.5 → "48%"。
        fuku_rate 側は 49.7 → "50%"。スクショの 48%/48% は単一オッズでは
        再現できず（両関数が同時に48を返すオッズは存在しない）、
        描画中のオッズ更新ずれと判断。構造的原因は 62/64 と同じ。"""
        ax = axis_selector.axis_confidence(2, 4.4, prev_win_margin=1.2)
        fk = axis_selector.fuku_rate(2, 4.4)
        self.assertEqual(ax, 47.5)
        self.assertEqual(f"{ax:.0f}%", "48%")
        self.assertEqual(fk, 49.7)


class UnifiedDisplayParityTests(unittest.TestCase):
    """統一後: 「軸の信頼度」ブロック(fav_check)の % は fuku_rate と常に一致。
    テーブル🎯軸馬候補列も同じ fuku_rate を表示に使うため、同じ馬=同じ値が保証される。"""

    def test_fav_check_fuku_equals_fuku_rate_grid(self):
        pops = [1, 2, 3, 6, 9]
        odds_list = [None, 1.5, 2.2, 2.8, 3.4, 4.4, 9.5, 80.0]
        for nar in (False, True):
            for p in pops:
                for o in odds_list:
                    with self.subTest(nar=nar, pop=p, odds=o):
                        fav = {'umaban': 1, 'name': 'テスト', 'ninki': p, 'win_odds': o}
                        res = fav_check.check(fav, race={'is_nar': nar})
                        self.assertEqual(res['fuku'],
                                         axis_selector.fuku_rate(p, o, nar))

    def test_formatted_display_matches(self):
        """表示文字列(:.0f)レベルでも一致する（フリッカージャブ再現入力）。"""
        fav = {'umaban': 3, 'name': 'フリッカージャブ', 'ninki': 1, 'win_odds': 2.8,
               'prev_chaku': 1, 'pos_ratio': 0.25}
        res = fav_check.check(fav, race={'is_nar': False})
        block = f"{res['fuku']:.0f}%"                              # 軸ブロック側
        table = f"{axis_selector.fuku_rate(1, 2.8):.0f}%"          # テーブル側(統一後)
        self.assertEqual(block, table)
        self.assertEqual(block, "64%")


class AxisConfidenceGuardTests(unittest.TestCase):
    """マーク判定に使う検証済み axis_confidence を変更していないことのガード。
    値が変わったら誰かが検証済みロジックに触れた = このテストを落として気付く。"""

    def test_verified_values_unchanged(self):
        self.assertEqual(axis_selector.axis_confidence(1, 2.2), 68.7)
        self.assertEqual(axis_selector.axis_confidence(1, 2.2, prev_chaku=1), 67.2)
        self.assertEqual(axis_selector.axis_confidence(1, 2.2, prev_chaku=1,
                                                       pos_ratio=0.2), 66.0)
        self.assertEqual(axis_selector.axis_confidence(1, 2.2, fillies_race=True), 67.7)
        self.assertEqual(axis_selector.axis_confidence(2, 4.4, prev_win_margin=1.2), 47.5)

    def test_pop_gate_unchanged(self):
        self.assertIsNone(axis_selector.axis_confidence(7, 9.0))   # MAX_CAND_POP=6 で弾く
        self.assertIsNotNone(axis_selector.fuku_rate(7, 9.0))      # 表示用はゲートなし


if __name__ == '__main__':
    unittest.main()
