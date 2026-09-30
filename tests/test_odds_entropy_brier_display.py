# -*- coding: utf-8 -*-
import unittest

from core import money, value_scanner as vs


class OddsEntropyReuseTests(unittest.TestCase):
    def test_arare_prob_unchanged_after_refactor(self):
        odds_a = [1.5, 4.0, 8.0, 12, 20, 30, 50, 80, 100, 120]
        odds_b = [4.5, 5.5, 6.5, 8, 9, 11, 13, 16, 20, 25, 30, 40, 50, 60, 80, 100]
        meta = {'is_handicap': False, 'kigo': '11'}
        self.assertEqual(vs.arare_prob(odds_a, meta, 10),
                         vs.arare_prob(list(odds_a), dict(meta), 10))
        self.assertEqual(vs.arare_prob(odds_b, meta, 16),
                         vs.arare_prob(list(odds_b), dict(meta), 16))

    def test_eff_n_matches_arare_internals(self):
        odds = [1.6, 4.0, 8.0, 16.0]
        struct = vs.odds_entropy_struct(odds, 4)
        self.assertIsNotNone(struct)
        inv = sum(1.0 / o for o in sorted(odds))
        pn = [(1.0 / o) / inv for o in sorted(odds)]
        import math
        h = -sum(p * math.log(p) for p in pn)
        self.assertAlmostEqual(struct['odds_entropy'], h, places=9)
        self.assertAlmostEqual(struct['eff_n'], math.exp(h), places=9)
        self.assertAlmostEqual(struct['eff_n'], 2.92, places=2)

    def test_entropy_missing_odds_returns_none(self):
        self.assertIsNone(vs.odds_entropy_struct([], 16))
        self.assertIsNone(vs.arare_prob([], {}, 16))


class BrierDecompositionTests(unittest.TestCase):
    def test_identity_holds(self):
        probs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.15, 0.25, 0.35]
        outcomes = [0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 0, 1]
        direct = money.brier_score_mean(probs, outcomes)
        dec = money.brier_decomposition(probs, outcomes, n_bins=len(probs))
        self.assertAlmostEqual(direct, dec['brier'], places=6)
        self.assertLess(abs(dec['identity_delta']), 5e-4)
        coarse = money.brier_decomposition(probs, outcomes, n_bins=5)
        self.assertAlmostEqual(coarse['brier'], direct, places=6)

    def test_matches_ledger_formula(self):
        rows_probs = [0.3, 0.7, 0.5]
        rows_won = [0, 1, 0]
        legacy = sum((p - w) ** 2 for p, w in zip(rows_probs, rows_won)) / 3
        self.assertAlmostEqual(money.brier_score_mean(rows_probs, rows_won), legacy, places=9)


if __name__ == '__main__':
    unittest.main()
