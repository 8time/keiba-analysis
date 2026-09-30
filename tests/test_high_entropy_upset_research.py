# -*- coding: utf-8 -*-
import unittest

import numpy as np
import pandas as pd

from research.high_entropy_upset import dataset


class HighEntropyDatasetTests(unittest.TestCase):
    def test_labels_match_export_definitions(self):
        d = pd.DataFrame([
            {'race_key': 'R1', 'umaban': 1, 'ninki': 1, 'win_odds': 2.0, 'chakujun': 5},
            {'race_key': 'R1', 'umaban': 2, 'ninki': 2, 'win_odds': 4.0, 'chakujun': 4},
            {'race_key': 'R1', 'umaban': 5, 'ninki': 5, 'win_odds': 10.0, 'chakujun': 1},
            {'race_key': 'R1', 'umaban': 3, 'ninki': 7, 'win_odds': 20.0, 'chakujun': 2},
            {'race_key': 'R1', 'umaban': 4, 'ninki': 8, 'win_odds': 30.0, 'chakujun': 3},
        ])
        races = pd.DataFrame({'race_key': ['R1']})
        out = dataset.attach_post_labels(races, d)
        self.assertEqual(out.loc[0, 'favorite_failure'], 1.0)
        self.assertEqual(out.loc[0, 'top2_failure'], 1.0)
        self.assertEqual(out.loc[0, 'longshot_place_7'], 1.0)
        self.assertEqual(out.loc[0, 'multi_longshot_7'], 1.0)
        self.assertEqual(out.loc[0, 'honsen'], 0.0)
        self.assertEqual(out.loc[0, 'finish_pattern'], '5-7-8')
        self.assertEqual(out.loc[0, 'n_in_top3_ge7'], 2)
        self.assertEqual(out.loc[0, 'top2_in_top3'], 0)

    def test_finish_pattern_not_collapsed_by_longshot7(self):
        from research.high_entropy_upset import upset_structure as us
        rows = pd.DataFrame([
            {'finish_1_ninki': 1, 'finish_2_ninki': 2, 'finish_3_ninki': 7,
             'longshot_place_7': 1},
            {'finish_1_ninki': 12, 'finish_2_ninki': 5, 'finish_3_ninki': 7,
             'longshot_place_7': 1},
        ])
        out = us._enrich_from_finish_cols(rows)
        self.assertEqual(out.iloc[0]['finish_pattern'], '1-2-7')
        self.assertEqual(out.iloc[1]['finish_pattern'], '12-5-7')
        self.assertEqual(out.iloc[0]['n_in_top3_ge7'], 1)
        self.assertEqual(out.iloc[1]['n_in_top3_ge7'], 2)
        self.assertEqual(rows['longshot_place_7'].tolist(), [1, 1])

    def test_eff_n_threshold_uses_train_only(self):
        from research.high_entropy_upset import favorite_survival_analysis as fs
        df = pd.DataFrame({'day': [20200101, 20200102], 'eff_n': [5.0, 8.0]})
        thr = fs.eff_n_threshold_train_only(df, 0.5)
        self.assertGreaterEqual(thr, 5.0)
        self.assertLessEqual(thr, 8.0)

    def test_no_label_leak_guard(self):
        with self.assertRaises(ValueError):
            dataset.assert_no_label_leak(['eff_n', 'favorite_failure'])

    def test_arare_prob_uses_same_entropy(self):
        from core import value_scanner as vs
        odds = [4.5, 5.5, 6.5, 8, 9, 11, 13, 16]
        s = vs.odds_entropy_struct(odds, 8)
        p1 = vs.arare_prob(odds, {}, 8)
        p2 = vs.arare_prob(odds, {}, 8)
        self.assertEqual(p1, p2)
        self.assertAlmostEqual(s['eff_n'], np.exp(s['odds_entropy']))


if __name__ == '__main__':
    unittest.main()
