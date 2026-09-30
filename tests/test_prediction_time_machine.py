import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core import prediction_time_machine as tm
from core import pace_map


class PredictionTimeMachineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'snapshots.db'
        self.base = {
            'snapshot_id': 'original',
            'race': {'race_id': '202610180511',
                     'scheduled_start_at': '2026-10-18T15:40:00+09:00'},
            'snapshot_created_at': '2026-10-18T15:30:20+09:00',
            'prediction_created_at': '2026-10-18T15:30:18+09:00',
            'raw_input': [{'Umaban': 1, 'Odds': 8.2},
                          {'Umaban': 2, 'Odds': 3.1},
                          {'Umaban': 3, 'Odds': 12.5}],
            'horses': [{'Umaban': 1, 'BattleScore': 55.0},
                       {'Umaban': 2, 'BattleScore': 61.0},
                       {'Umaban': 3, 'BattleScore': 47.0}],
            'odds_observations': [{'horse_number': u, 'odds': o,
                                   'popularity': rank,
                                   'odds_fetched_at': '2026-10-18T15:30:12+09:00',
                                   'odds_source': 'NETKEIBA',
                                   'popularity_fetched_at': '2026-10-18T15:30:12+09:00',
                                   'popularity_source': 'NETKEIBA'}
                                  for u, o, rank in [(1, 8.2, 2), (2, 3.1, 1),
                                                      (3, 12.5, 3)]],
            'provenance': {'odds': {'source': 'LIVE',
                                    'fetched_at': '2026-10-18T15:30:12+09:00',
                                    'is_imputed': False}},
            'evidence_class': 'hand_built_fixture',
            'predictions': {'Stage1': [1], 'BattleScore': [55.0], 'SRA': [1],
                            'VH': [0.2], 'GoalRank': [1],
                            'position_score_map': {'1': 0.2}, 'pace': 'middle',
                            'battle_score': [55.0], 'sra_projected_score': [61.0],
                            'vh': [0.2], 'hunter': [1], 'goal': [1],
                            'recommendation': {'skip': False}},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixture_e2e_replay_outcome_dataset(self):
        sid = tm.save_snapshot(copy.deepcopy(self.base), self.db)
        restored = tm.replay(sid, self.db)
        self.assertEqual(restored['data_quality']['status'], 'GREEN')
        self.assertEqual(restored['evidence_class'], 'hand_built_fixture')
        summary = tm.summarize_snapshot(restored)
        self.assertEqual(summary['quality'], 'GREEN')
        self.assertEqual(summary['blockers'], [])
        self.assertEqual(summary['workflow_profile'], 'UNSPECIFIED')
        self.assertEqual(summary['hunter'], self.base['predictions']['hunter'])
        self.assertIsNone(summary['stage1'])
        self.assertEqual(restored['predictions'], self.base['predictions'])
        tm.save_outcome(self.base['race']['race_id'], {'finish': [1, 2, 3]}, self.db)
        rows = tm.research_dataset('2026-10-18T15:35:00+09:00', 5, self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['prediction']['predictions'], self.base['predictions'])
        self.assertEqual(rows[0]['outcome'], {'finish': [1, 2, 3]})
        self.assertNotIn('outcome', restored)

    def test_immutable_and_hash_tampering(self):
        tm.save_snapshot(copy.deepcopy(self.base), self.db)
        with tm.connect(self.db) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('UPDATE prediction_snapshots SET quality=?', ('RED',))
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('DELETE FROM prediction_snapshots')
        with self.assertRaises(sqlite3.IntegrityError):
            tm.save_snapshot(copy.deepcopy(self.base), self.db)
        self.assertEqual(tm.replay('original', self.db)['fingerprint'],
                         tm.replay('original', self.db)['fingerprint'])
        with tm.connect(self.db) as con:
            con.execute('DROP TRIGGER ptm_no_update')
            body = tm.replay('original', self.db)
            body['predictions']['goal'] = ['forged']
            con.execute('UPDATE prediction_snapshots SET body_json=? WHERE snapshot_id=?',
                        (json.dumps(body), 'original'))
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            tm.replay('original', self.db)

    def test_future_and_unknown_odds_never_enter_dataset(self):
        for suffix, fetched in [('post', '2026-10-18T15:41:00+09:00'),
                                ('unknown', None),
                                ('future', '2026-10-18T15:31:00+09:00')]:
            value = copy.deepcopy(self.base)
            value['snapshot_id'] = suffix
            value['provenance']['odds']['fetched_at'] = fetched
            tm.save_snapshot(value, self.db)
        self.assertEqual(tm.replay('post', self.db)['data_quality']['status'], 'RED')
        self.assertEqual(tm.replay('unknown', self.db)['data_quality']['status'], 'YELLOW')
        self.assertEqual(tm.replay('future', self.db)['data_quality']['status'], 'RED')
        self.assertEqual(tm.research_dataset('2026-10-18T15:35:00+09:00', 0, self.db), [])

    def test_future_source_rejected_even_when_start_unknown(self):
        value = copy.deepcopy(self.base)
        value['snapshot_id'] = 'unknown-start'
        value['race']['scheduled_start_at'] = None
        value['provenance']['odds']['fetched_at'] = '2026-10-18T15:31:00+09:00'
        tm.save_snapshot(value, self.db)
        self.assertEqual(tm.replay('unknown-start', self.db)['data_quality']['status'], 'RED')

    def test_odds_observation_cannot_hide_behind_clean_provenance(self):
        value = copy.deepcopy(self.base)
        value['snapshot_id'] = 'post-odds'
        value['odds_observations'][0]['odds_fetched_at'] = '2026-10-18T15:41:00+09:00'
        tm.save_snapshot(value, self.db)
        self.assertEqual(tm.replay('post-odds', self.db)['data_quality']['status'], 'RED')

    def test_provenance_from_acquisition_and_finalized_run(self):
        df = pd.DataFrame([{'Umaban': 1, 'Name': 'Example', 'Odds': 8.2,
                            'Popularity': 2, 'PastRuns': [], 'BattleScore': 55.0,
                            'Projected Score': 61.0}])
        df.attrs['_ptm_acquisition'] = {
            'source': 'NETKEIBA', 'fetched_at': '2026-10-18T15:30:10+09:00'}
        df.attrs['_ptm_market_events'] = [
            {'field': 'Odds', 'source': 'NETKEIBA',
             'fetched_at': '2026-10-18T15:30:12+09:00', 'values': {'1': 8.2}},
            {'field': 'Popularity', 'source': 'NETKEIBA',
             'fetched_at': '2026-10-18T15:30:13+09:00', 'values': {'1': 2}},
        ]
        first = tm.capture_sra('202610180511', df, df,
                               {'date_val': '20261018', 'post_time': '15:40'},
                               analysis_run_id='run-fixture', db_path=self.db)
        original = tm.replay(first, self.db)
        self.assertEqual(original['provenance'][0]['values']['Name']['source'], 'NETKEIBA')
        battle = original['provenance'][0]['values']['BattleScore']
        self.assertEqual(battle['source'], 'DERIVED')
        self.assertIsNone(battle['fetched_at'])
        self.assertIn('PastRuns', battle['derived_from'])
        self.assertIsNotNone(battle['derived_at'])
        self.assertEqual(original['odds_observations'][0]['odds_fetched_at'],
                         '2026-10-18T15:30:12+09:00')
        for stage, outputs in [('position_stage', {'position_score_map': {'1': 0.2}}),
                               ('pace_4corner', {'pos4': {'1': 1}}),
                               ('pace_map_goal', {'finish': {'1': 1}}),
                               ('vh_edge_sets', {'vh': {'1': 0.3}}),
                               ('anabaka_hunter_full', {'candidates': [1]}),
                               ('recommendation', {'lines': [{'label': '1'}]})]:
            tm.observe_stage(stage, '202610180511', 'run-fixture', stage,
                             {'outputs': outputs}, self.db)
        final = tm.finalize_run_snapshot('202610180511', 'run-fixture', self.db)
        restored = tm.replay(final, self.db)
        self.assertEqual(restored['predictions']['goal']['finish'], {'1': 1})
        self.assertEqual(restored['predictions']['recommendation']['lines'][0]['label'], '1')
        self.assertEqual(tm.explain_horse(final, 1, self.db)['horse_number'], '1')
        self.assertEqual(tm.replay(first, self.db)['predictions']['goal'], None)

    def test_goal_diagnostics_preserve_production_result_and_show_mixed_units(self):
        horses = [{'umaban': 1, 'name': 'A'}, {'umaban': 2, 'name': 'B'},
                  {'umaban': 3, 'name': 'C'}]
        profiles = {'A': {'agari': 0.2, 'finish_hist': 0.2},
                    'B': {'agari': 0.5, 'finish_hist': 0.5},
                    'C': {'agari': 0.8, 'finish_hist': 0.8}}
        extras = {1: {'kick': 34.1, 'power': -70.0, 'pop': 1},
                  2: {'pop': 2}, 3: {'pop': 3}}
        ctx = {'pos4': {1: .1, 2: .4, 3: .8}}
        original = pace_map.predict_finish(horses, profiles, ctx, extras)
        diagnostics = {}
        observed = pace_map.predict_finish(horses, profiles, ctx, extras,
                                           diagnostics=diagnostics)
        self.assertEqual(original, observed)
        self.assertEqual(diagnostics['source_by_horse']['1']['kick'], 'LIVE')
        self.assertEqual(diagnostics['source_by_horse']['2']['kick'], 'JV')
        self.assertAlmostEqual(diagnostics['contributions']['1']['final'], original[1])

    def test_future_snapshot_and_source_cutoff(self):
        first = copy.deepcopy(self.base)
        first['snapshot_id'] = 'first'
        tm.save_snapshot(first, self.db)
        future = copy.deepcopy(self.base)
        future['snapshot_id'] = 'later'
        future['snapshot_created_at'] = '2026-10-18T15:38:00+09:00'
        future['provenance']['odds']['fetched_at'] = '2026-10-18T15:37:00+09:00'
        tm.save_snapshot(future, self.db)
        result = tm.research_dataset('2026-10-18T15:35:00+09:00', 0, self.db)
        self.assertEqual(result[0]['prediction']['snapshot_id'], 'first')

    def test_before_start_applies_to_every_source(self):
        value = copy.deepcopy(self.base)
        value['snapshot_id'] = 'late-source'
        value['snapshot_created_at'] = '2026-10-18T15:36:00+09:00'
        value['provenance']['odds']['fetched_at'] = '2026-10-18T15:36:00+09:00'
        value['odds_observations'][0]['odds_fetched_at'] = '2026-10-18T15:36:00+09:00'
        tm.save_snapshot(value, self.db)
        self.assertEqual(len(tm.research_dataset('2026-10-18T15:40:00+09:00', 5,
                                                 self.db)), 0)

    def test_outcome_rejected_from_prediction_and_stage_timeline(self):
        bad = copy.deepcopy(self.base)
        bad['outcome'] = {'finish': 1}
        with self.assertRaises(ValueError):
            tm.save_snapshot(bad, self.db)
        tm.save_snapshot(copy.deepcopy(self.base), self.db)
        tm.observe_stage('event-a', self.base['race']['race_id'], 'run-a',
                         'scanner', {'candidates': [1, 2]}, self.db)
        timeline = tm.replay_race(self.base['race']['race_id'], db_path=self.db)
        self.assertEqual([x['stage'] for x in timeline['observations']], ['scanner'])
        self.assertEqual(timeline['observations'][0]['payload']['candidates'], [1, 2])
        with tm.connect(self.db) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('UPDATE prediction_observations SET stage=?', ('elim',))

    def test_imputed_is_not_measured_and_sra_capture_is_honest(self):
        row = {'Umaban': 1, 'Name': 'Fixture', 'Odds': 8.2,
               'PastRuns': [{'Passing': '8-8', 'PassingType': 'Imputed'}],
               'BattleScore': 55.0}
        df = pd.DataFrame([row])
        sid = tm.capture_sra('202610180511', df, df,
                             {'date_val': '20261018', 'post_time': '15:40'},
                             db_path=self.db)
        restored = tm.replay(sid, self.db)
        self.assertTrue(restored['provenance'][0]['values']['PastRuns']['is_imputed'])
        self.assertEqual(restored['provenance'][0]['values']['PastRuns']['source'], 'IMPUTED')
        self.assertEqual(restored['data_quality']['status'], 'YELLOW')
        self.assertNotEqual(restored['provenance'][0]['values']['PastRuns']['source'], 'MEASURED')
        self.assertIsNone(restored['predictions']['GoalRank'] if 'GoalRank' in restored['predictions'] else
                          restored['predictions']['goal'])

    def test_result_odds_are_red_and_expected_odds_are_not_green(self):
        result = copy.deepcopy(self.base)
        result['snapshot_id'] = 'result-odds'
        for row in result['odds_observations']:
            row['odds_value_kind'] = 'result'
        tm.save_snapshot(result, self.db)
        self.assertEqual(tm.replay('result-odds', self.db)['data_quality']['status'], 'RED')
        expected = copy.deepcopy(self.base)
        expected['snapshot_id'] = 'expected-odds'
        for row in expected['odds_observations']:
            row['odds_value_kind'] = 'expected'
        tm.save_snapshot(expected, self.db)
        self.assertEqual(tm.replay('expected-odds', self.db)['data_quality']['status'], 'YELLOW')
        self.assertEqual(tm.research_dataset('2026-10-18T15:35:00+09:00', 5, self.db), [])

    def test_four_corner_rank_and_mixed_units_come_from_saved_values(self):
        horses = [{'umaban': 1, 'name': 'A'}, {'umaban': 2, 'name': 'B'}]
        profiles = {'A': {'agari': 0.2, 'finish_hist': 0.2},
                    'B': {'agari': 0.8, 'finish_hist': 0.8}}
        extras = {1: {'kick': 34.0, 'power': -10.0}, 2: {}}
        ctx = {'pos4': {1: 0.4, 2: 0.1}, 'pace': 'ミドル'}
        baseline = pace_map.predict_finish(horses, profiles, ctx, extras)
        diagnostics = {}
        observed = pace_map.predict_finish(horses, profiles, ctx, extras,
                                           diagnostics=diagnostics)
        self.assertEqual(baseline, observed)
        base = copy.deepcopy(self.base)
        base['snapshot_id'] = 'pace-base'
        base['analysis_run_id'] = 'pace-run'
        base['capture_scope'] = 'SRA dataframe and audit event only'
        tm.save_snapshot(base, self.db)
        tm.observe_stage('pace-4c', base['race']['race_id'], 'pace-run', 'pace_4corner',
                         {'outputs': ctx}, self.db)
        tm.observe_stage('pace-goal', base['race']['race_id'], 'pace-run', 'pace_map_goal',
                         {'outputs': {'finish': observed, 'decomposition': diagnostics}},
                         self.db)
        final = tm.replay(tm.finalize_run_snapshot(
            base['race']['race_id'], 'pace-run', self.db), self.db)
        self.assertEqual(final['predictions']['predicted_4c_rank'], {'2': 1, '1': 2})
        self.assertEqual(final['predictions']['goal']['finish'],
                         {str(k): v for k, v in baseline.items()})
        self.assertTrue(any(w['code'] == 'MIXED_UNIT_SOURCE'
                            for w in final['data_quality_warnings']))
        self.assertNotEqual(final['data_quality']['status'], 'GREEN')
        self.assertEqual(tm.replay('pace-base', self.db)['data_quality']['status'], 'GREEN')

    def test_snapshot_failure_does_not_change_the_score(self):
        from unittest.mock import patch
        frame = pd.DataFrame([{'Umaban': 1, 'Odds': 8.2, 'Popularity': 2,
                               'BattleScore': 55.0, 'Name': 'A'}])
        before = frame['BattleScore'].tolist()
        with patch.object(tm, 'save_snapshot', side_effect=OSError('readonly')):
            with self.assertRaises(OSError):
                tm.capture_sra('202610180511', frame, frame,
                               {'date_val': '20261018', 'post_time': '15:40'},
                               db_path=self.db)
        self.assertEqual(frame['BattleScore'].tolist(), before)

    def test_audit_save_failure_keeps_the_audit_result(self):
        from unittest.mock import patch
        from core import audit_pipeline as ap

        class Store:
            def append_event(self, *args, **kwargs):
                return 'event-1'

            def close(self):
                return None

        session = {}
        with patch('core.audit_pipeline.audit_store.AuditStore', return_value=Store()), \
                patch.object(tm, 'observe_stage', side_effect=OSError('disk full')):
            out = ap.record_event('202610180511', 'sra', {'projected': 1},
                                  analysis_run_id='run-1', session=session)
        self.assertTrue(out.ok)
        self.assertEqual(out.event_id, 'event-1')
        self.assertEqual(session['audit_record_errors'][0]['stage'], 'SNAPSHOT_SAVE_FAILED')

    def test_cache_sidecar_does_not_invent_a_fetch_time(self):
        folder = Path(self.tmp.name) / 'cache'
        stored = tm.remember_cache_source('202610180511', 'NETKEIBA',
                                          '2026-10-18T15:20:00+09:00', folder)
        self.assertEqual(tm.recall_cache_source('202610180511', folder)['source_fetched_at'],
                         '2026-10-18T15:20:00+09:00')
        self.assertNotEqual(stored['cached_at'], stored['source_fetched_at'])
        tm.remember_cache_source('old-race', 'UNKNOWN', None, folder)
        old = tm.recall_cache_source('old-race', folder)
        self.assertIsNone(old['source_fetched_at'])
        self.assertIsNone(tm.recall_cache_source('never-saved', folder))

    def test_production_only_dataset_excludes_fixture_green(self):
        fixture = copy.deepcopy(self.base)
        fixture['snapshot_id'] = 'fixture-green'
        fixture['capture_origin'] = 'fixture'
        tm.save_snapshot(fixture, self.db)
        production = copy.deepcopy(self.base)
        production['snapshot_id'] = 'production-green'
        production['race'] = dict(production['race'])
        production['race']['race_id'] = '202610180512'
        production['capture_origin'] = 'production'
        tm.save_snapshot(production, self.db)
        rows = tm.research_dataset('2026-10-18T15:35:00+09:00', 5, self.db,
                                   production_only=True)
        self.assertEqual([row['prediction']['snapshot_id'] for row in rows],
                         ['production-green'])
        self.assertEqual(tm.research_dataset('2026-10-18T15:35:00+09:00', 5, self.db,
                                             production_only=True, workflow='FULL_PREDICTION'),
                         [])

    def test_outcome_does_not_change_prediction_fingerprint(self):
        sid = tm.save_snapshot(copy.deepcopy(self.base), self.db)
        before = tm.replay(sid, self.db)['fingerprint']
        tm.save_outcome(self.base['race']['race_id'], {'finish': [2, 1, 3]}, self.db)
        self.assertEqual(tm.replay(sid, self.db)['fingerprint'], before)

    def test_forward_and_ptm_share_race_run(self):
        import json
        import pandas as pd
        from research.forward.from_sra import capture_sra as fwd
        from research.forward.ptm_link import links_for, record_link
        df = pd.DataFrame([{'Umaban': 1, 'Name': 'A', 'Odds': 3.0, 'Popularity': 1,
                            'BattleScore': 1.0, 'Projected Score': 2.0}])
        with tempfile.TemporaryDirectory() as directory:
            captured = fwd('202610180511', df, {'analysis_run_id': 'run-shared'},
                           directory=directory)
            row = json.loads(open(
                Path(directory) / 'decisions.jsonl', encoding='utf-8').readline())
            self.assertEqual(row['analysis_run_id'], 'run-shared')
            sid = tm.capture_sra('202610180511', df, df,
                                 {'date_val': '20991018', 'post_time': '15:40'},
                                 analysis_run_id='run-shared', capture_origin='fixture',
                                 db_path=self.db)
            body = tm.replay(sid, self.db)
            self.assertEqual(body['cross_refs']['forward_collector']['analysis_run_id'],
                             'run-shared')
            record_link('202610180511', 'run-shared', ptm_snapshot_id=sid,
                        forward_captured_at=captured, directory=directory)
            rows = links_for('202610180511', 'run-shared', directory=directory)
            self.assertEqual(rows[0]['ptm_snapshot_id'], sid)
            self.assertEqual(links_for('202610180511', 'other-run', directory=directory), [])

    def test_finalize_skipped_without_sra_base(self):
        tm.observe_stage('h1', '202610180511', 'run-no-sra', 'anabaka_hunter',
                         {'outputs': {'candidates': [1]}}, self.db)
        out = tm.finalize_run_snapshot_if_base('202610180511', 'run-no-sra', self.db)
        self.assertTrue(out.get('skipped'))
        self.assertEqual(out.get('reason'), 'no_sra_snapshot_for_analysis_run')
        with self.assertRaises(ValueError):
            tm.finalize_run_snapshot('202610180511', 'run-no-sra', self.db)

    def test_finalize_never_reuses_other_run_sra_base(self):
        import pandas as pd
        df = pd.DataFrame([{'Umaban': 1, 'Name': 'A', 'Odds': 3.0, 'Popularity': 1}])
        tm.capture_sra('202610180511', df, df, {'date_val': '20261018', 'post_time': '15:40'},
                       analysis_run_id='run-a', db_path=self.db)
        out = tm.finalize_run_snapshot_if_base('202610180511', 'run-b', self.db)
        self.assertTrue(out.get('skipped'))

    def test_sra_core_functions_reach_green_without_a_real_race_label(self):
        from core import calculator
        fetched = tm.now_jst()
        rows = []
        odds = {1: 3.1, 2: 5.2, 3: 8.4}
        popularity = {1: 1, 2: 2, 3: 3}
        for number in (1, 2, 3):
            rows.append({
                'Umaban': number, 'Name': f'Horse {number}', 'Jockey': '武豊',
                'Futan': 55.0, 'Weight': '480', '馬体重': '480',
                'CurrentSurface': '芝', 'CurrentDistance': 1200,
                'Odds': odds[number], 'Popularity': popularity[number],
                'PastRuns': [{
                    'Passing': '2-2-2-3', 'PassingType': 'Real',
                    'Agari': 34.2, 'AgariType': 'Real', 'Rank': number,
                    'Time': 70.0, 'Surface': '芝', 'Date': '2026.09.01',
                    'Distance': 1200}],
            })
        raw = pd.DataFrame(rows)
        raw.attrs['_ptm_acquisition'] = {'source': 'NETKEIBA', 'fetched_at': fetched}
        raw.attrs['_ptm_market_events'] = [
            {'field': 'Odds', 'source': 'NETKEIBA', 'fetched_at': fetched,
             'value_kind': 'win_odds_endpoint',
             'values': {str(number): value for number, value in odds.items()}},
            {'field': 'Popularity', 'source': 'NETKEIBA', 'fetched_at': fetched,
             'value_kind': 'win_odds_endpoint',
             'values': {str(number): value for number, value in popularity.items()}},
        ]
        scored = calculator.calculate_battle_score(raw.copy(deep=True))
        before = scored['BattleScore'].tolist()
        scored = calculator.calculate_strength_suitability(scored, '')
        self.assertEqual(scored['BattleScore'].tolist(), before)
        profile = calculator.analyze_pace_profile(scored)
        sid = tm.capture_sra('202610180511', raw, scored,
                             {'date_val': '20991018', 'post_time': '15:40'},
                             analysis_run_id='ready-run', capture_origin='fixture',
                             db_path=self.db)
        tm.record_component('202610180511', 'position_stage',
                            {'rows': len(scored)},
                            {'position_score_map': profile['position_score_map'],
                             'positional_map': profile['positional_map'],
                             'pace_label': profile['pace_label']},
                            analysis_run_id='ready-run', db_path=self.db)
        final = tm.replay(tm.finalize_run_snapshot('202610180511', 'ready-run', self.db),
                          self.db)
        self.assertEqual(scored['BattleScore'].tolist(), before)
        self.assertEqual(final['data_quality']['status'], 'GREEN',
                         final['data_quality']['blockers'])
        self.assertEqual(final['capture_origin'], 'fixture')
        self.assertEqual(final['workflow_profile'], 'SRA_CORE')
        self.assertEqual(final['data_quality']['stage_execution']['hunter'], 'NOT_EXECUTED')
        self.assertEqual(final['data_quality']['stage_execution']['elim'], 'NOT_EXECUTED')
        self.assertNotEqual(final['capture_origin'], 'production')
        self.assertEqual(tm.research_dataset('2099-10-18T15:00:00+09:00', 5, self.db,
                                             production_only=True), [])
        admitted = tm.research_dataset('2099-10-18T15:00:00+09:00', 5, self.db,
                                       workflow='SRA_CORE')
        self.assertEqual(admitted[0]['prediction']['snapshot_id'], final['snapshot_id'])
        summary = tm.summarize_snapshot(final)
        self.assertEqual(summary['quality'], 'GREEN')
        self.assertIsNotNone(summary['battle_score'])
        self.assertIsNotNone(summary['position_score_map'])
        self.assertIsNone(summary['hunter'])
        self.assertTrue(summary['code_version'])
        self.assertNotEqual(tm.replay(sid, self.db)['data_quality']['status'], 'GREEN')


if __name__ == '__main__':
    unittest.main()
