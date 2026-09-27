# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest

from research.forward.quality import classify_decision, classify_result
from research.forward.shadow_baseline import observe_production
from research.forward.snapshot import append_result, capture_decision


class ForwardPipelineTests(unittest.TestCase):
    def test_decision_result_settlement_path(self):
        with tempfile.TemporaryDirectory() as d:
            capture_decision({
                'race_id': '202601010101',
                'horses': [{
                    'umaban': 1,
                    'decision_time_odds': 3.2,
                    'final_odds': None,
                    'popularity': 1,
                }],
                'zone': 'D',
                'bet_type': '3連複',
            }, directory=d)
            observe_production('202601010101', {
                'zone': 'D',
                'selected_bet_type': '3連複',
                'selected_playbook': 'd_ninki_trio_2',
                'skip_reason': None,
                'cross_n': 0,
            }, {'tickets': {'trio': [{'combo': [1, 2, 3]}]}, 'horses': [{
                'umaban': 1, 'decision_time_odds': 3.2, 'final_odds': None,
            }]}, directory=d)
            append_result(
                '202601010101', '202601010101',
                finish=[1, 2, 3],
                payouts={'3連複': [{'combo': [1, 2, 3], 'yen_per_100': 450}]},
                final_odds={'1': 3.1},
                directory=d,
            )
            decisions = [
                json.loads(line)
                for line in open(os.path.join(d, 'decisions.jsonl'), encoding='utf-8')
            ]
            results = [
                json.loads(line)
                for line in open(os.path.join(d, 'results.jsonl'), encoding='utf-8')
            ]
            self.assertTrue(all(classify_decision(r) == 'valid' for r in decisions))
            self.assertEqual(classify_result(results[0]), 'valid')
            self.assertNotIn('finish', decisions[0])
            self.assertEqual(decisions[1]['purpose'], 'shadow_observation')
            self.assertFalse(decisions[1]['purchased'])
            stake = 100
            payout = results[0]['payouts']['3連複'][0]['yen_per_100']
            self.assertEqual(payout - stake, 350)

    def test_result_contamination_is_invalid(self):
        self.assertEqual(classify_decision({
            'race_id': '1', 'captured_at': 't', 'horses': [],
            'finish': [1, 2, 3],
        }), 'invalid')


if __name__ == '__main__':
    unittest.main()
