# -*- coding: utf-8 -*-
import unittest

from research.walkforward.catalog import FAILED_REFERENCE, FOLDS, RULES, SELECT_MAX_DAY


class WalkForwardContractTests(unittest.TestCase):
    def test_2026_not_a_selection_fold(self):
        for fold in FOLDS:
            self.assertLessEqual(fold[4], SELECT_MAX_DAY)
            self.assertLess(fold[4], 20260101)

    def test_failed_reference_present_but_named(self):
        ids = [r[0] for r in RULES]
        self.assertIn(FAILED_REFERENCE, ids)
        self.assertEqual(FAILED_REFERENCE, 'vh_rank2_ninki_ge6')

    def test_folds_do_not_overlap_test_into_train(self):
        for _name, tr0, tr1, te0, te1 in FOLDS:
            self.assertLess(tr1, te0)
            self.assertLess(te0, te1)


if __name__ == '__main__':
    unittest.main()
