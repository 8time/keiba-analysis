# -*- coding: utf-8 -*-
"""Phase B: 本番 core vs research runner の一致（固定入力）。"""
import json
import os
import unittest

from core import bettype_selector as bts
from core import formation_stats as fs
from core import playbook_tickets as pb
from research import csv_ltr

_FIXTURE = os.path.join(
    os.path.dirname(__file__), 'fixtures', 'phase_a_strategy_golden.json')


def _load_golden():
    with open(_FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def _standard_horses():
    return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]


def _standard_ltr():
    return {i: float(i) for i in range(1, 9)}


class PhaseBBaselineParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = _load_golden()

    def test_bettype_selector_golden(self):
        for case in self.golden['bettype_select_cases']:
            sel = bts.select(case['zone'], case['cross_n'])
            self.assertEqual(sel['selected_bet_type'], case['bet_type'])
            self.assertEqual(sel['selected_playbook'], case['playbook'])

    def test_playbook_build_tickets_golden(self):
        hs = _standard_horses()
        ltr = _standard_ltr()
        for case in self.golden['playbook_cases']:
            rec = pb.build_tickets(
                '209901010101', case['vscore'], hs, None, ltr,
                cross_n=case['cross_n'])
            exp = case['expected']
            self.assertEqual(rec['selected_playbook'], exp['selected_playbook'], case['id'])
            self.assertEqual(bool(rec.get('skip')), exp['skip'], case['id'])

    def test_zone_bounds_core(self):
        self.assertEqual(fs.zone_code(30), 'D')
        self.assertEqual(fs.zone_code(55), 'C')
        self.assertEqual(fs.zone_code(80), 'BA')

    def test_cross_n_requires_proj_not_ability(self):
        hs = _standard_horses()
        vh = {i: float(10 - i) for i in range(1, 9)}
        rec_no_proj = pb.build_tickets(
            '209901010101', 55.0, hs, None, _standard_ltr(),
            vh_scores=vh, proj_scores=None)
        self.assertEqual(rec_no_proj.get('cross_n_source'), 'unavailable')
        proj = {i: float(i) for i in range(1, 9)}
        rec_yes = pb.build_tickets(
            '209901010101', 55.0, hs, None, _standard_ltr(),
            vh_scores=vh, proj_scores=proj)
        self.assertEqual(rec_yes.get('cross_n_source'), 'computed')
        self.assertGreaterEqual(rec_yes.get('cross_n', 0), 0)

    def test_ltr_differs_from_ability_order(self):
        if not csv_ltr.ltr_available():
            self.skipTest('ltr model missing')
        import pandas as pd
        g = pd.DataFrame([
            {'umaban': 1, 'ninki': 1, 'win_odds': 2.0, 'futan': 570, 'bataiju': 480,
             'zogen': 0, 'sex_code': 1, 'age': 4, 'h7_fig': 50.0, 'spurt_mean3': 35.0,
             'prior_top3_rate': 0.5, 'avg_chaku5': 3.0, 'trainer_jyo_t3': 0.2,
             'jockey_jyo_win': 0.1, 'jockey_dist_win': 0.1, 'ability_score': 0.9},
            {'umaban': 2, 'ninki': 2, 'win_odds': 5.0, 'futan': 570, 'bataiju': 480,
             'zogen': 0, 'sex_code': 1, 'age': 4, 'h7_fig': 48.0, 'spurt_mean3': 34.0,
             'prior_top3_rate': 0.4, 'avg_chaku5': 4.0, 'trainer_jyo_t3': 0.2,
             'jockey_jyo_win': 0.1, 'jockey_dist_win': 0.1, 'ability_score': 0.1},
        ])
        meta = {'field_size': 2, 'is_handi1': 0, 'surface_code': 0, 'kyori_int': 1600,
                'jyo': 5, 'race_num': 1, 'baba_code': 1}
        ltr = csv_ltr.predict_race_frame(g, meta)
        self.assertEqual(len(ltr), 2)
        ab_order = g.sort_values('ability_score', ascending=True)['umaban'].tolist()
        ltr_order = sorted(ltr.keys(), key=lambda u: -ltr[u])
        self.assertNotEqual(ab_order, ltr_order)


if __name__ == '__main__':
    unittest.main()
