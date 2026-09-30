"""Shadow finish input isolation; production predictions stay unchanged."""
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import pace_map as pm


class FinishShadowTests(unittest.TestCase):
    def setUp(self):
        self.horses = [dict(umaban=u, name=str(u), score=.5, style='差し')
                       for u in (1, 2, 3)]
        self.ctx = {'pos4': {1: .1, 2: .5, 3: .9}}
        self.profiles = {str(u): {'agari': value, 'finish_hist': value}
                         for u, value in ((1, .7), (2, .3), (3, .5))}

    def test_partial_live_seconds_never_mix_with_jv_relative_ranks(self):
        extras = {1: {'kick': 33.4, 'power': -80},
                  2: {'kick': 34.1, 'power': -70}}
        out = pm.predict_finish_shadow(self.horses, self.profiles, self.ctx, extras)
        self.assertEqual(out['provenance']['kick']['source'], 'jv')
        self.assertEqual(out['provenance']['power']['source'], 'jv')
        self.assertEqual(out['provenance']['kick']['observed'], 3)
        self.assertEqual(out['contributions'][1]['kick'],
                         pm._FINISH_TUNE['w_kick'] * 1 / 3.5)

    def test_partial_popularity_does_not_mix_with_odds(self):
        out = pm.predict_finish_shadow(self.horses, self.profiles, self.ctx,
                                       popularity={1: 1, 2: 2},
                                       odds={1: 1.2, 2: 10, 3: 3})
        self.assertEqual(out['provenance']['pop']['source'], 'odds')
        self.assertLess(out['contributions'][3]['pop'], out['contributions'][2]['pop'])

    def test_nonfinite_values_are_neutral_or_fallback(self):
        extras = {1: {'kick': float('inf'), 'power': float('nan')},
                  2: {'kick': True, 'power': -50}, 3: {'kick': 34.0}}
        out = pm.predict_finish_shadow(self.horses, self.profiles, self.ctx,
                                       extras, odds={1: float('nan'), 2: True})
        self.assertEqual(out['provenance']['kick']['source'], 'jv')
        self.assertTrue(all(math.isfinite(v) for v in out['finish'].values()))

    def test_shadow_cannot_change_production_output(self):
        extras = {1: {'kick': 33.4, 'pop': 1}, 2: {'pop': 2}, 3: {'pop': 3}}
        before = pm.predict_finish(self.horses, self.profiles, self.ctx, extras)
        pm.predict_finish_shadow(self.horses, self.profiles, self.ctx, extras,
                                 popularity={1: 1, 2: 2, 3: 3})
        self.assertEqual(before, pm.predict_finish(
            self.horses, self.profiles, self.ctx, extras))

    def test_profile_audit_can_use_read_only_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.db'
            con = sqlite3.connect(path)
            try:
                con.execute('CREATE TABLE races(race_key TEXT, shusso_tosu INTEGER, '
                            'kyori INTEGER, surface TEXT)')
                con.execute('CREATE TABLE results(race_key TEXT, bamei TEXT, '
                            'corner1 INTEGER, corner2 INTEGER, corner3 INTEGER, '
                            'corner4 INTEGER, ato3f INTEGER, time TEXT, '
                            'kyakushitsu TEXT, chakujun INTEGER)')
                con.execute("INSERT INTO races VALUES('2024010101010101', 10, 1200, '芝')")
                con.execute("INSERT INTO results VALUES('2024010101010101', '1', "
                            "2, 2, 2, 2, 340, '1080', '2', 1)")
                con.commit()
            finally:
                con.close()
            self.assertIn('1', pm.fetch_jv_profiles(['1'], db_path=str(path),
                                                    before_key='20250101', read_only=True))


if __name__ == '__main__':
    unittest.main()
