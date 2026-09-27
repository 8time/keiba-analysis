# -*- coding: utf-8 -*-
"""MAGI回顧の確認リスト。買い目は作らず、事実とクラス注意だけを出す。"""
import unittest

import pandas as pd

from core import magi_chat as mc


class ReviewChecklistTests(unittest.TestCase):
    def test_parse_weight_and_c4(self):
        self.assertEqual(mc._parse_body_weight('480(+8)'), (480, 8))
        self.assertEqual(mc._parse_body_weight('500（-12）'), (500, -12))
        self.assertIsNone(mc._parse_body_weight('発走前のため未公開'))
        self.assertEqual(mc._c4_pos('2-3-4-5'), 5)
        self.assertIsNone(mc._c4_pos(''))

    def test_dirt_maiden_note(self):
        notes = mc._review_class_notes(
            {'RaceName': '2歳新馬', 'surface': 'ダート'})
        self.assertTrue(any('ダート新馬' in n for n in notes))

    def test_fillies_and_open_notes(self):
        notes = mc._review_class_notes(
            {'RaceName': '牝馬限定 オープン', 'is_fillies': True})
        blob = '／'.join(notes)
        self.assertIn('オープン', blob)
        self.assertIn('牝馬', blob)

    def test_checklist_uses_passing_not_next_race_hunt(self):
        ar = {
            'race_info': {'distance': 1200, 'field_size': 16, 'race_name': '3歳未勝利'},
            'horses': {
                1: {'Name': 'A', 'Rank': 1, 'Passing': '1-1-1-1', 'Popularity': 4},
                2: {'Name': 'B', 'Rank': 2, 'Passing': '2-2-2-2', 'Popularity': 2},
                3: {'Name': 'C', 'Rank': 3, 'Passing': '3-3-3-3', 'Popularity': 6},
            },
        }
        df = pd.DataFrame([
            {'Umaban': 1, 'Name': 'A', 'Weight': '480(+10)', 'CurrentSurface': '芝',
             'CurrentDistance': 1200, 'Popularity': 4, 'Odds': 8.0},
        ])
        lines = mc._review_checklist(df, ar, {'condition': '良', 'RaceName': '3歳未勝利'})
        text = '\n'.join(lines)
        self.assertIn('回顧の確認リスト', text)
        self.assertIn('前め', text)
        self.assertIn('+10kg', text)
        self.assertIn('2歳・新馬・未勝利', text)
        self.assertNotIn('次走狙え', text)
        self.assertNotIn('距離短縮', text)
        self.assertNotIn('着外', text)

    def test_build_context_includes_checklist(self):
        df = pd.DataFrame([
            {'Umaban': 7, 'Name': '穴馬', 'Popularity': 8, 'Odds': 20.0,
             'Projected Score': 50, 'CurrentSurface': '芝'},
        ])
        ar = {
            'race_info': {'distance': 2000, 'field_size': 12, 'race_name': 'G3 重賞'},
            'horses': {
                7: {'Name': '穴馬', 'Rank': 1, 'Passing': '10-10-9-8',
                    'Popularity': 8, 'Agari': 34.0},
            },
        }
        ctx = mc.build_context(df, None, ar, meta={'RaceName': 'G3 重賞'})
        self.assertIn('回顧の確認リスト', ctx['text'])
        self.assertTrue(any('オープン・重賞' in x for x in ctx['review_checklist']))


if __name__ == '__main__':
    unittest.main()
