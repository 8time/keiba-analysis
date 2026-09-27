# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest

from research.forward.automation import ForwardStore, odds_move, run_synthetic
from research.forward.quality import classify_decision


class ForwardAutomationTests(unittest.TestCase):
    def test_synthetic_reaches_evaluated(self):
        with tempfile.TemporaryDirectory() as d:
            summary = run_synthetic(d)
            self.assertEqual(summary['n_completed'], 1)
            self.assertEqual(summary['real_purchase'], 0)
            decisions = [json.loads(line) for line in open(os.path.join(d, 'decisions.jsonl'), encoding='utf-8')]
            self.assertTrue(all(row.get('final_odds') in (None, ) or 'final_odds' not in row for row in decisions))
            self.assertTrue(all(classify_decision(row) == 'valid' for row in decisions))
            self.assertTrue(all(row.get('purchased') is False for row in decisions if row.get('purpose') == 'shadow_observation' or row.get('SHADOW_ONLY')))

    def test_final_odds_rejected_on_decision(self):
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            store.observe('r1', {})
            with self.assertRaises(ValueError):
                store.capture_primary('r1', {'horses': [{'umaban': 1, 'decision_time_odds': 2, 'final_odds': 2}]})

    def test_duplicate_snapshot_and_missing_odds(self):
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            store.observe('r1', {})
            snap = {'timestamp': 't', 'minutes_to_post': 15, 'horses': [
                {'umaban': 1, 'decision_time_odds': None, 'final_odds': None}]}
            self.assertTrue(store.add_odds_snapshot('r1', snap))
            self.assertFalse(store.add_odds_snapshot('r1', snap))
            store.capture_primary('r1', {'horses': [{'umaban': 1, 'decision_time_odds': None}]})
            row = json.loads(open(os.path.join(d, 'decisions.jsonl'), encoding='utf-8').readline())
            self.assertIsNone(row['horses'][0]['decision_time_odds'])
            self.assertTrue(row['horses'][0]['raw_missing_odds'])
            self.assertNotEqual(row['horses'][0]['decision_time_odds'], 0)

    def test_primary_is_t15_not_t60(self):
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            store.observe('r1', {})
            store.add_odds_snapshot('r1', {'timestamp': 'a', 'minutes_to_post': 60, 'horses': [{'umaban': 1, 'decision_time_odds': 9, 'final_odds': None}]})
            store.add_odds_snapshot('r1', {'timestamp': 'b', 'minutes_to_post': 15, 'horses': [{'umaban': 1, 'decision_time_odds': 4, 'final_odds': None}]})
            self.assertEqual(store.choose_primary('r1')['minutes_to_post'], 15)

    def test_retry_then_result_and_no_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            run_part = ForwardStore(d)
            run_part.observe('r2', {})
            run_part.add_odds_snapshot('r2', {'timestamp': 'b', 'minutes_to_post': 15, 'horses': [{'umaban': 1, 'decision_time_odds': 5, 'final_odds': None}]})
            run_part.capture_primary('r2', {'horses': [{'umaban': 1, 'decision_time_odds': 5}]})
            run_part.capture_shadow('r2', {'bet_type': '3連複', 'tickets': []})
            run_part.mark_retry('r2', 'network')
            self.assertEqual(run_part.state('r2')['state'], 'FAILED_RETRYABLE')
            waiting = run_part.resume_waiting()
            self.assertEqual(waiting[0]['race_id'], 'r2')
            run_part.capture_result('r2', {'finish': [1], 'payouts': {'3連複': []}, 'final_odds': {'1': 5}, 'shadow_bet_type': '3連複'})
            self.assertEqual(run_part.state('r2')['state'], 'EVALUATED')
            with self.assertRaises(RuntimeError):
                run_part.append_event('r2', 'BAD', {'purchased': True}, 'x')

    def test_odds_move_separated(self):
        move = odds_move(8.0, 6.0)
        self.assertAlmostEqual(move['absolute_move'], -2.0)
        self.assertEqual(odds_move(None, 6.0)['status'], 'MISSING')


if __name__ == '__main__':
    unittest.main()
