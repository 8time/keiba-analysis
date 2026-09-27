"""馬体重危険材料の境界値と、PDFの自動消去残馬表示。"""
import unittest
from unittest.mock import patch

import pandas as pd

from core import elim_engine as ee
from core import newspaper as np


class WeightDangerTests(unittest.TestCase):
    def compute(self, weight, **extra):
        row = dict(Umaban=1, Name='試験馬', Popularity=1, Odds=3,
                   Weight=weight, SexAge='牡4')
        row.update(extra)
        with patch('core.jockey_jv.resolve_horse', return_value=(None, None)), \
             patch('core.jockey_jv.is_golden_line', return_value=False), \
             patch('core.score_cache.read_scores', return_value=None):
            return ee.compute_elim_rows(pd.DataFrame([row]), '209905010101', {})[0]

    def test_threshold_and_unavailable(self):
        for weight in ('500(+19)', '500(-20)', '500(0)', '500', '', None, '未発表'):
            with self.subTest(weight=weight):
                row = self.compute(weight)
                self.assertNotIn('馬体重大幅増', row['危険材料'])
                self.assertEqual(row['score'], -1)
        for weight in ('500(+20)', '500(+22)'):
            with self.subTest(weight=weight):
                row = self.compute(weight)
                self.assertIn('馬体重大幅増(+20kg以上)', row['危険材料'])
                self.assertEqual(row['score'], -2.5)

    def test_existing_danger_not_double_penalized(self):
        before = self.compute('500(+19)', SexAge='牡7')
        after = self.compute('500(+20)', SexAge='牡7')
        self.assertIn('高齢', after['危険材料'])
        self.assertIn('馬体重大幅増', after['危険材料'])
        self.assertEqual(before['score'], after['score'])


class NewspaperSurvivorTests(unittest.TestCase):
    def test_verdict_is_authoritative_including_learning_rescue(self):
        rows = [dict(馬番=1, 馬名='残し馬', 判定='✅残し'),
                dict(馬番=2, 馬名='境界馬', 判定='🛟ボーダー残し'),
                dict(馬番=3, 馬名='復活馬', 判定='✅残し'),
                dict(馬番=4, 馬名='消去馬', 判定='🧹消し')]
        with patch.object(np, 'load_elim_verdict', return_value={'rows': rows}), \
             patch('core.score_cache.read_elim_keep', return_value={4}) as cached:
            html = np._elim_html({'aim': {'elim': {1: 5}}}, [], 'test')
        cached.assert_not_called()
        for name in ('残し馬', '境界馬', '復活馬'):
            self.assertIn(name, html)
        self.assertNotIn('消去馬', html)
        self.assertIn('3頭', html)
        self.assertEqual(html.count("class='exbox'"), 1)

    def test_old_auto_keep_and_escape(self):
        with patch.object(np, 'load_elim_verdict', return_value=None), \
             patch('core.score_cache.read_elim_keep', return_value={2}), \
             patch('core.score_cache.read_keep', return_value={1}) as manual:
            html = np._elim_html({}, [{'Umaban': 2, 'Name': '残馬&名'}], 'test')
        manual.assert_not_called()
        self.assertIn('残馬&amp;名', html)
        self.assertIn('1頭', html)

    def test_all_eliminated_does_not_resurrect_stale_cache(self):
        with patch.object(np, 'load_elim_verdict', return_value={'rows': [
                dict(馬番=1, 馬名='消去馬', 判定='🧹消し')]}), \
             patch('core.score_cache.read_elim_keep', return_value={1}) as cached:
            html = np._elim_html({}, [], 'test')
        cached.assert_not_called()
        self.assertIn('残馬なし', html)
        self.assertNotIn('消去馬', html)

    def test_unexecuted_not_manual_survivors(self):
        with patch.object(np, 'load_elim_verdict', return_value=None), \
             patch('core.score_cache.read_elim_keep', return_value=None), \
             patch('core.score_cache.read_keep', return_value={1}) as manual:
            self.assertEqual(np._elim_html({}, [], 'test'), '')
        manual.assert_not_called()


if __name__ == '__main__':
    unittest.main()
