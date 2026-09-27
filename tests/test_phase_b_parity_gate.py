# -*- coding: utf-8 -*-
"""STOP A: experiments and HOLDOUT stay closed while Projected Score is unreproducible."""
import json
import os
import unittest

from research import parity_gate as gate
from research import splits
from research.features_registry import REGISTRY

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ParityGateTests(unittest.TestCase):
    def test_experiments_blocked(self):
        self.assertEqual(gate.PARITY, 'PARTIAL')
        self.assertEqual(gate.PROJECTED_SCORE, 'NOT_REPRODUCIBLE')
        self.assertFalse(gate.experiments_allowed())
        self.assertFalse(gate.HOLDOUT_EVAL_ALLOWED)

    def test_holdout_access_raises(self):
        with self.assertRaises(PermissionError):
            gate.assert_split_day_allowed(20250105)
        self.assertEqual(gate.assert_split_day_allowed(20230601), 'train')
        self.assertEqual(gate.assert_split_day_allowed(20240601), 'validation')

    def test_holdout_not_in_train_window(self):
        self.assertEqual(splits.split_for_day(20250101), 'holdout')
        self.assertNotEqual(splits.split_for_day(20231231), 'holdout')
        self.assertNotEqual(splits.split_for_day(20241231), 'holdout')

    def test_projected_registry_not_proxy(self):
        spec = REGISTRY['projected_score']
        self.assertEqual(spec['status'], 'NOT_REPRODUCIBLE_HISTORICAL')
        self.assertNotIn('ability_score', spec['producer'])

    def test_weights_file_still_has_scoring_signal(self):
        path = os.path.join(_ROOT, '.score_weights_main.json')
        with open(path, encoding='utf-8') as f:
            sw = json.load(f)
        self.assertGreater(float(sw.get('ScoringSignal', 0)), 0)
        self.assertGreater(float(sw.get('Base', 0)), 0)

    def test_cross_n_core_not_copied(self):
        from core.consensus_view import compute_cross_n
        rows = [{'umaban': i, 'proj': float(10 - i)} for i in range(1, 9)]
        vh = {i: float(i) for i in range(1, 9)}
        n = compute_cross_n(rows, vh)
        self.assertIsInstance(n, int)
        self.assertGreaterEqual(n, 0)
        self.assertLessEqual(n, 4)


if __name__ == '__main__':
    unittest.main()
