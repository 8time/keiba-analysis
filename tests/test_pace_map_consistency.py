"""Regression tests for matching prediction phases and dated history."""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core import pace_map as pm, newspaper as paper


class PaceConsistencyTests(unittest.TestCase):
    def test_phase_uses_matching_corner_only(self):
        self.assertAlmostEqual(pm.phase_position('3角', {'c3': .2, 'c1': 1}, .6, .8), (.786+.2)/2)
        self.assertEqual(pm.phase_position('4角', {'c3': .2}, .6, .8), .8)
        self.assertAlmostEqual(pm.phase_position('3角', {}, .6, .8), .786)

    def test_field_size_normalization(self):
        a=pm.score_from_pastruns([{'Passing':'5-5', 'FieldSize':9}])
        b=pm.score_from_pastruns([{'Passing':'9-9', 'FieldSize':17}])
        self.assertEqual(a,b)
        self.assertEqual(a,.5)
        self.assertEqual(pm.score_from_pastruns([{'Passing':'20','FieldSize':8}]),.5)

    def test_equal_values_do_not_favor_horse_number(self):
        self.assertEqual(pm._rank_norm({1:4,2:4,3:4}),{1:.5,2:.5,3:.5})
        self.assertEqual(pm._rank_norm({1:4,2:4,3:8}),{1:.25,2:.25,3:1})

    def test_cutoff(self):
        for day in ['2026/09/27','2026-09-27','2026.09.27','20260927']:
            self.assertEqual(pm.history_cutoff(day),'20260927')
        for day in [None,'unknown','2026/02/30']:
            self.assertEqual(pm.history_cutoff(day),'00000000')

    def test_temporal_profiles_and_first_recorded_corner(self):
        with tempfile.TemporaryDirectory() as td:
            db=str(Path(td)/'test.db')
            with sqlite3.connect(db) as c:
                c.execute('create table races(race_key text, shusso_tosu int,kyori int,surface text)')
                c.execute('create table results(race_key text,bamei text,corner1 int,corner2 int,corner3 int,corner4 int,ato3f int,time text,kyakushitsu text,chakujun int)')
                for key,c1,c3 in [('2026010101010101',9,9),('2026020101010101',0,1),('2026030101010101',0,9),('2026040101010101',0,9)]:
                    c.execute('insert into races values(?,9,1200,?)',(key,'芝'))
                    c.execute('insert into results values(?,?,?,0,?,?,0,NULL,?,1)',(key,'試験馬',c1,c3,c3,'1'))
            c.close()
            prof=pm.fetch_jv_profiles(['試験馬'],db_path=db,before_key='20260301')['試験馬']
            self.assertEqual(prof['n_runs'],2)
            self.assertAlmostEqual(prof['ten'],.82/1.82,places=3)
            self.assertEqual(pm.fetch_jv_profiles(['試験馬'],db_path=db,before_key='00000000'),{})

    def test_map_keeps_phase_and_horse_coverage(self):
        horses=[dict(umaban=i,name=str(i),score=.5,style='差し') for i in range(1,5)]
        profiles={str(i):{'c3':i/5,'c4':(5-i)/5} for i in range(1,5)}
        result=pm.estimate_pace_map(horses,1200,profiles)
        self.assertEqual(list(result),['スタート','3角','4角','直線'])
        for rows in result.values():
            self.assertEqual({r['umaban'] for r in rows},{1,2,3,4})
        self.assertNotEqual([r['x'] for r in result['3角']],[r['x'] for r in result['4角']])

    def test_paper_uses_corner_not_finish_or_finish_rear(self):
        snapshot={'pos4':{'16':.05,'1':.9},'finish':{'16':.9,'1':.05}}
        with patch.object(paper,'load_pace',return_value=snapshot), patch('core.score_cache.read_rear',return_value={16}), patch.object(paper,'_pace_diagram_svg',return_value='') as diagram:
            html=paper._pace_html('test', [])
        self.assertIn('《4コーナー想定》(前) 16',html)
        self.assertIn('4コーナー後方想定: 1',html)
        self.assertNotIn('後方グループ(着順予想)',html)
        self.assertEqual(diagram.call_args.args[0],{16:.05,1:.9})

    def test_paper_legacy_finish_is_explicit(self):
        with patch.object(paper,'load_pace',return_value={'finish':{'1':.1,'2':.9}}),patch('core.score_cache.read_rear',return_value=None):
            self.assertIn('着順予想・旧データ',paper._pace_html('test', []))

    def test_app_comparison_is_downstream_of_context(self):
        source=(Path(pm.__file__).parents[1]/'app.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn("_app_left = _pm_ctx['pos4']",source)
        self.assertLess(source.index('_pm_ctx = _pmap.build_pace_context'),source.index("_app_left = _pm_ctx['pos4']"))
        self.assertIn('before_key=_pm_cutoff',source)


if __name__=='__main__': unittest.main()


