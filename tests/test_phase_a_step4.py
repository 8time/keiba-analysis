# -*- coding: utf-8 -*-
"""フェーズA step4: 工程監査接続。"""
import json
import os
import tempfile
import unittest

import pandas as pd

from core import audit_pipeline as ap
from core import audit_store
from core import bettype_selector as bts
from core import elim_engine as ee
from core import playbook_tickets as pb


class AuditPipelineFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.store = audit_store.AuditStore(db=self.tmp.name)
        self.ss = {}

    def tearDown(self):
        self.store.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_same_run_tracks_stages_in_order(self):
        rid = '209901010101'
        ap.begin_new_run(rid, 'scanner', session=self.ss, store=self.store)
        run = ap.current_run_id(rid, session=self.ss)
        ap.record_event(rid, 'scanner', {'vscore': 55}, session=self.ss, store=self.store)
        erows = [{'馬番': i, 'score': float(9 - i), 'pos': False, 'neg': False, '_tags': []}
                 for i in range(1, 9)]
        edf = ee.apply_verdict(erows, rid, border_cnt=1, record_fired=False, apply_learning=False)
        ap.record_event(
            rid, 'elim',
            ap.build_elim_payload(erows, edf, 1, rid),
            session=self.ss, store=self.store,
        )
        ap.record_event(
            rid, 'sra',
            ap.build_sra_payload(None, rid, [1, 2, 3], [1, 2, 3, 4], meta={}),
            session=self.ss, store=self.store,
        )
        evs = self.store.list_events(run)
        stages = [e['stage'] for e in evs]
        self.assertEqual(stages, ['scanner', 'elim', 'sra'])

    def test_reanalysis_new_run(self):
        rid = '209901010101'
        r1 = ap.begin_new_run(rid, 'sra_analyze', session=self.ss, store=self.store)
        r2 = ap.begin_new_run(rid, 'sra_analyze', session=self.ss, store=self.store)
        self.assertNotEqual(r1, r2)
        runs = self.store.list_analysis_runs(rid)
        self.assertEqual(len(runs), 2)

    def test_races_do_not_mix(self):
        ap.begin_new_run('209901010101', 'scanner', session=self.ss, store=self.store)
        ap.begin_new_run('209901010102', 'scanner', session=self.ss, store=self.store)
        run_a = ap.current_run_id('209901010101', session=self.ss)
        run_b = ap.current_run_id('209901010102', session=self.ss)
        ap.record_event('209901010101', 'scanner', {'race': 'A'}, session=self.ss, store=self.store)
        ap.record_event('209901010102', 'scanner', {'race': 'B'}, session=self.ss, store=self.store)
        ev_a = self.store.list_events(run_a)
        ev_b = self.store.list_events(run_b)
        self.assertEqual(json.loads(ev_a[0]['payload_json'])['race'], 'A')
        self.assertEqual(json.loads(ev_b[0]['payload_json'])['race'], 'B')

    def test_multi_tab_session_isolation(self):
        ss1 = {}
        ss2 = {}
        ap.begin_new_run('209901010101', 'scanner', session=ss1, store=self.store)
        ap.begin_new_run('209901010101', 'scanner', session=ss2, store=self.store)
        self.assertNotEqual(
            ap.current_run_id('209901010101', session=ss1),
            ap.current_run_id('209901010101', session=ss2),
        )

    def test_pool_delta_sra_recalc(self):
        rid = '209901010101'
        ap.begin_new_run(rid, 'sra', session=self.ss, store=self.store)
        payload = ap.build_sra_payload(
            None, rid, [1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 6], meta={})
        self.assertTrue(payload['pool_changed'])
        ap.record_event(rid, 'sra', payload, session=self.ss, store=self.store)
        run = ap.current_run_id(rid, session=self.ss)
        trace = ap.reconstruct_pool_trace(self.store.list_events(run))
        self.assertEqual(trace[-1]['before'], [1, 2, 3, 4, 5])
        self.assertEqual(trace[-1]['after'], [1, 2, 3, 4, 5, 6])

    def test_buy_method_pool(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        rec = pb.build_tickets('R', 55, hs, None, ltr, cross_n=3)
        payload = ap.build_playbook_payload(rec, hs[:6], 3, 55, 'C')
        self.assertEqual(len(payload['input_horses_umaban']), 6)
        self.assertTrue(payload['ticket_count'] >= 0)

    def test_record_failure_surfaces(self):
        rid = '209901010101'
        ap.clear_record_errors(session=self.ss)

        class BadStore:
            def append_event(self, *a, **k):
                raise RuntimeError('disk full')

            def create_analysis_run(self, *a, **k):
                return 'x'

        out = ap.record_event(rid, 'scanner', {}, session=self.ss, store=BadStore())
        self.assertFalse(out.ok)
        errs = ap.last_record_errors(session=self.ss)
        self.assertEqual(len(errs), 1)
        self.assertIn('disk full', errs[0]['error'])

    def test_not_run_status(self):
        rid = '209901010102'
        ap.begin_new_run(rid, 'elim', session=self.ss, store=self.store)
        out = ap.record_event(rid, 'elim', {'note': 'skipped'}, status='not_run',
                              session=self.ss, store=self.store)
        self.assertTrue(out.ok)
        run = ap.current_run_id(rid, session=self.ss)
        self.assertEqual(self.store.list_events(run)[0]['status'], 'not_run')


class StrategyStillInvariant(unittest.TestCase):
    def test_playbook_unchanged_after_audit_helpers(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        rec = pb.build_tickets('R', 30, hs, None, ltr, cross_n=0)
        self.assertEqual(rec['selected_playbook'], bts.PLAYBOOK_D_TRIO_2)
        _ = ap.build_playbook_payload(rec, hs, 0, 30)
        rec2 = pb.build_tickets('R', 30, hs, None, ltr, cross_n=0)
        self.assertEqual(rec2['n_points'], rec['n_points'])


if __name__ == '__main__':
    unittest.main()
