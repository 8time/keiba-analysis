"""Production-function chain with a deterministic pre-race page fixture."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core import calculator, consensus_view, pace_map, prediction_time_machine as tm, scraper


RACE_ID = '202610180511'
HTML = '''<html><body><div class="RaceList_NameBox"><div class="RaceName">Fixture</div>
<div class="RaceData01">芝1200m 15:40</div></div><div>2026年10月18日</div>
<table id="sort_table"><tbody>
<tr class="HorseList"><td class="Waku1">1</td><td class="Waku">1</td>
<td class="HorseInfo"><a href="/horse/1000000001/">Horse A</a></td></tr>
<tr class="HorseList"><td class="Waku1">2</td><td class="Waku">2</td>
<td class="HorseInfo"><a href="/horse/1000000002/">Horse B</a></td></tr>
<tr class="HorseList"><td class="Waku2">3</td><td class="Waku">3</td>
<td class="HorseInfo"><a href="/horse/1000000003/">Horse C</a></td></tr>
</tbody></table></body></html>'''


class ProductionPathTimeMachineTests(unittest.TestCase):
    def test_scraper_calculator_pace_snapshot_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'prediction.db'
            with patch.object(scraper, 'fetch_robust_html', return_value=HTML), \
                 patch.object(scraper, 'fetch_win_odds', return_value=pd.Series(
                     {'01': 8.2, '02': 3.1, '03': 12.5})), \
                 patch.object(scraper, 'fetch_popularity', return_value={
                     '01': 2, '02': 1, '03': 3}):
                raw = scraper.get_race_data(RACE_ID, use_storage=False)
            self.assertEqual(len(raw), 3)
            self.assertEqual(raw.attrs['_ptm_acquisition']['source'], 'NETKEIBA')
            self.assertIsNotNone(raw.attrs['_ptm_acquisition']['fetched_at'])

            scored = calculator.calculate_battle_score(raw.copy(deep=True))
            battle_before = scored['BattleScore'].tolist()
            scored = calculator.calculate_strength_suitability(scored, '')
            again_scored = calculator.calculate_strength_suitability(
                calculator.calculate_battle_score(raw.copy(deep=True)), '')
            self.assertEqual(scored['BattleScore'].tolist(), battle_before)
            self.assertEqual(scored['BattleScore'].tolist(),
                             again_scored['BattleScore'].tolist())
            pace = calculator.analyze_pace_profile(scored)
            edges = consensus_view.build_edge_sets(scored, raw.attrs.get('metadata', {}),
                                                  RACE_ID)
            horses = [{'umaban': int(row.Umaban), 'name': row.Name,
                       'score': pace['position_score_map'].get(int(row.Umaban), .5),
                       'style': '先行'} for row in scored.itertuples()]
            ctx = pace_map.build_pace_context(horses, {}, 1200, '芝')
            baseline = pace_map.predict_finish(horses, {}, ctx, extras={})
            diagnostics = {}
            again = pace_map.predict_finish(horses, {}, ctx, extras={},
                                            diagnostics=diagnostics)
            self.assertEqual(baseline, again)

            sid = tm.capture_sra(RACE_ID, raw, scored,
                                 {'date_val': '20261018', 'post_time': '15:40'},
                                 analysis_run_id='fixture-run', capture_origin='fixture',
                                 db_path=db)
            tm.observe_stage('fixture-pace', RACE_ID, 'fixture-run',
                             'pace_4corner', {'outputs': ctx}, db)
            tm.observe_stage('fixture-goal', RACE_ID, 'fixture-run',
                             'pace_map_goal', {'outputs': {'finish': again,
                                                           'decomposition': diagnostics}}, db)
            tm.observe_stage('fixture-vh', RACE_ID, 'fixture-run',
                             'vh_edge_sets', {'outputs': edges}, db)
            final_id = tm.finalize_run_snapshot(RACE_ID, 'fixture-run', db)
            final = tm.replay(final_id, db)
            self.assertEqual(final['predictions']['goal']['finish'],
                             {str(k): v for k, v in baseline.items()})
            self.assertEqual(final['predictions']['vh'], tm._safe(edges))
            self.assertEqual(tm.replay(sid, db)['predictions']['goal'], None)
            self.assertEqual(final['data_quality']['status'], 'YELLOW')
            self.assertEqual(set(final['data_quality']['blockers']), {
                'UNKNOWN_TIME', 'CRITICAL_INPUT_MISSING', 'NOT_EXECUTED_POSITION'})
            self.assertEqual(final['data_quality']['blocker_details']['CRITICAL_INPUT_MISSING'],
                             {'Jockey': 3})
            self.assertEqual(final['data_quality']['workflow_profile'], 'SRA_CORE')
            self.assertEqual(final['capture_origin'], 'fixture')
            self.assertNotIn(final['snapshot_id'], {
                row['prediction']['snapshot_id'] for row in tm.research_dataset(
                    '2026-10-18T15:35:00+09:00', 5, db, production_only=True)})
            self.assertEqual(final['evidence_class'], 'production_capture')
            self.assertNotEqual(final['evidence_class'], 'hand_built_fixture')
            saved = tm.replay(sid, db)
            self.assertEqual(saved['odds_observations'][0]['odds_value_kind'],
                             'win_odds_endpoint')
            self.assertTrue(saved['predictions']['battle_score'][0]['components'])
            battle_cell = saved['provenance'][0]['values']['BattleScore']
            self.assertEqual(battle_cell['source'], 'DERIVED')
            self.assertIsNone(battle_cell['fetched_at'])
            self.assertEqual(scored['BattleScore'].tolist(),
                             again_scored['BattleScore'].tolist())
            self.assertEqual(tm.research_dataset('2026-10-18T15:35:00+09:00',
                                                 5, db), [])

    def test_expected_and_result_odds_keep_their_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'prediction.db'
            empty = {}
            with patch.object(scraper, 'fetch_robust_html', return_value=HTML), \
                    patch.object(scraper, 'fetch_win_odds', return_value=empty), \
                    patch.object(scraper, 'fetch_popularity', return_value=empty), \
                    patch.object(scraper, 'fetch_realtime_odds_api', return_value=empty), \
                    patch.object(scraper, 'fetch_result_odds_pop', return_value=(empty, empty)), \
                    patch.object(scraper, 'fetch_expected_odds', return_value=(
                        {1: 8.2, 2: 3.1, 3: 12.5}, {1: 2, 2: 1, 3: 3})):
                raw = scraper.get_race_data(RACE_ID, use_storage=False)
            self.assertEqual([float(v) for v in raw['Odds'].tolist()], [8.2, 3.1, 12.5])
            sid = tm.capture_sra(RACE_ID, raw, raw,
                                 {'date_val': '20261018', 'post_time': '15:40'},
                                 db_path=db)
            saved = tm.replay(sid, db)
            self.assertEqual(saved['odds_observations'][0]['odds_value_kind'], 'expected')
            self.assertNotEqual(saved['data_quality']['status'], 'GREEN')
            self.assertEqual(tm.research_dataset('2026-10-18T15:40:00+09:00', 0, db), [])

            with patch.object(scraper, 'fetch_robust_html', return_value=HTML), \
                    patch.object(scraper, 'fetch_win_odds', return_value=empty), \
                    patch.object(scraper, 'fetch_popularity', return_value=empty), \
                    patch.object(scraper, 'fetch_realtime_odds_api', return_value=empty), \
                    patch.object(scraper, 'fetch_result_odds_pop', return_value=(
                        {1: 5.0, 2: 2.0, 3: 9.0}, {1: 2, 2: 1, 3: 3})):
                resulted = scraper.get_race_data(RACE_ID, use_storage=False)
            self.assertEqual([float(v) for v in resulted['Odds'].tolist()], [5.0, 2.0, 9.0])
            result_id = tm.capture_sra(RACE_ID, resulted, resulted,
                                       {'date_val': '20261018', 'post_time': '15:40'},
                                       db_path=db)
            self.assertEqual(tm.replay(result_id, db)['data_quality']['status'], 'RED')

    def test_real_green_ready_production_origin_sra_core(self):
        """Pre-race production-origin path: SRA + position + finalize → GREEN (isolated DB)."""
        import datetime as dt
        fetched = tm.now_jst()
        odds = {1: 3.2, 2: 4.5, 3: 6.0}
        popularity = {1: 1, 2: 2, 3: 3}
        rows = []
        for number in (1, 2, 3):
            rows.append({
                'Umaban': number, 'Name': f'Horse {number}', 'Jockey': '武豊',
                'Futan': 55.0, 'Weight': '480', '馬体重': '480',
                'CurrentSurface': '芝', 'CurrentDistance': 1200,
                'Odds': odds[number], 'Popularity': popularity[number],
                'PastRuns': [{
                    'Passing': '2-2-2-3', 'PassingType': 'Real',
                    'Agari': 34.2, 'AgariType': 'Real', 'Rank': number,
                    'Time': 70.0, 'Surface': '芝', 'Date': '2099.09.01',
                    'Distance': 1200}],
            })
        raw = pd.DataFrame(rows)
        raw.attrs['_ptm_acquisition'] = {'source': 'NETKEIBA', 'fetched_at': fetched}
        raw.attrs['_ptm_market_events'] = [
            {'field': 'Odds', 'source': 'NETKEIBA', 'fetched_at': fetched,
             'value_kind': 'win_odds_endpoint',
             'values': {str(n): v for n, v in odds.items()}},
            {'field': 'Popularity', 'source': 'NETKEIBA', 'fetched_at': fetched,
             'value_kind': 'win_odds_endpoint',
             'values': {str(n): v for n, v in popularity.items()}},
        ]
        scored = calculator.calculate_battle_score(raw.copy(deep=True))
        scored = calculator.calculate_strength_suitability(scored, '')
        profile = calculator.analyze_pace_profile(scored)
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'prediction.db'
            run_id = 'prod-green-run'
            tm.capture_sra(RACE_ID, raw, scored,
                           {'date_val': '20991018', 'post_time': '15:40'},
                           analysis_run_id=run_id, capture_origin='production',
                           db_path=db)
            tm.record_component(RACE_ID, 'position_stage', {}, profile,
                                analysis_run_id=run_id, db_path=db)
            final_id = tm.finalize_run_snapshot(RACE_ID, run_id, db)
            final = tm.replay(final_id, db)
            self.assertEqual(final['data_quality']['status'], 'GREEN',
                             final['data_quality']['blockers'])
            self.assertEqual(final['capture_origin'], 'production')
            self.assertEqual(final['workflow_profile'], 'SRA_CORE')
            admitted = tm.research_dataset(
                '2099-10-18T15:00:00+09:00', 5, db,
                production_only=True, workflow='SRA_CORE')
            self.assertEqual(len(admitted), 1)
            self.assertEqual(admitted[0]['prediction']['snapshot_id'], final_id)
            self.assertLess(
                dt.datetime.fromisoformat(final['snapshot_created_at']),
                dt.datetime.fromisoformat(final['race']['scheduled_start_at']))


if __name__ == '__main__':
    unittest.main()
