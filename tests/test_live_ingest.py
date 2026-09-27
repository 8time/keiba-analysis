# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from research.forward.automation import ForwardStore
from research.forward.live_ingest import JST, MemorySource, _id_is_not_another_day, parse_post_time, parse_race_list_times, status_view, tick


class LiveIngestTests(unittest.TestCase):
    def _race(self, post):
        return {
            'race_id': '202609220501',
            'venue': '東京',
            'post_at': post.isoformat(),
        }

    def test_clock_walks_to_evaluated(self):
        post = datetime(2026, 9, 22, 15, 0, tzinfo=JST)
        odds = [{'umaban': 1, 'decision_time_odds': 4.2, 'popularity': 1, 'final_odds': None}]
        source = MemorySource(
            races=[self._race(post)],
            odds={'202609220501': odds},
            results={'202609220501': {'finish': [1, 2, 3], 'payouts': {}, 'final_odds': {'1': 3.8}, 'source': 'sim'}},
        )
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            for minutes in (70, 60, 30, 15, 5):
                tick(store, source, post - timedelta(minutes=minutes))
            self.assertEqual(store.state('202609220501')['state'], 'SHADOW_CREATED')
            targets = status_view(store, post)['races'][0]['targets_done']
            self.assertEqual(targets, [60, 30, 15, 5])
            before = os.path.getsize(os.path.join(d, 'odds_snapshots.jsonl'))
            tick(store, source, post - timedelta(minutes=15))
            self.assertEqual(os.path.getsize(os.path.join(d, 'odds_snapshots.jsonl')), before)
            tick(store, source, post + timedelta(minutes=20))
            self.assertEqual(store.state('202609220501')['state'], 'EVALUATED')
            decisions = open(os.path.join(d, 'decisions.jsonl'), encoding='utf-8').read()
            self.assertNotIn('"final_odds": 3.8', decisions)
            self.assertIn('"purchased": false', decisions)

    def test_late_discovery_does_not_invent_decision(self):
        post = datetime(2026, 9, 22, 15, 0, tzinfo=JST)
        source = MemorySource(races=[self._race(post)], odds={'202609220501': []})
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            out = tick(store, source, post - timedelta(minutes=2))
            self.assertEqual(out['actions'][0]['skipped'], 'late_discovery')
            self.assertNotEqual((store.state('202609220501') or {}).get('state'), 'SHADOW_CREATED')

    def test_restart_keeps_targets(self):
        post = datetime(2026, 9, 22, 15, 0, tzinfo=JST)
        source = MemorySource(races=[self._race(post)], odds={'202609220501': [
            {'umaban': 1, 'decision_time_odds': 5, 'popularity': 1, 'final_odds': None}]})
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            tick(store, source, post - timedelta(minutes=60))
            store2 = ForwardStore(d)
            tick(store2, source, post - timedelta(minutes=60))
            self.assertEqual(status_view(store2, post)['races'][0]['targets_done'], [60])

    def test_yesterday_rejected_and_timezone(self):
        post = datetime(2026, 9, 21, 15, 0, tzinfo=JST)
        source = MemorySource(races=[{'race_id': 'old', 'post_at': post.isoformat()}])
        with tempfile.TemporaryDirectory() as d:
            store = ForwardStore(d)
            out = tick(store, source, datetime(2026, 9, 22, 10, 0, tzinfo=JST))
            self.assertEqual(out['actions'][0]['skipped'], 'not_today')
        parsed = parse_post_time('15:40', datetime(2026, 9, 22, tzinfo=JST))
        self.assertEqual(parsed.tzinfo, JST)
        self.assertEqual(parse_race_list_times('race_id=202609220501 foo 15:40')['202609220501'], '15:40')
        self.assertFalse(_id_is_not_another_day('202606040701', '20260922'))
        self.assertTrue(_id_is_not_another_day('202630092201', '20260922'))

    def test_no_purchase_symbols(self):
        text = open(os.path.join(os.path.dirname(__file__), '..', 'research', 'forward', 'live_ingest.py'), encoding='utf-8').read()
        self.assertNotIn('submit_bet', text)
        self.assertNotIn('bankroll', text)


if __name__ == '__main__':
    unittest.main()
