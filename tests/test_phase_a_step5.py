# -*- coding: utf-8 -*-
"""フェーズA step5: 推奨と購入の分離・関連付け。"""
import json
import os
import tempfile
import unittest

from core import audit_pipeline as ap
from core import audit_store
from core import bettype_selector as bts
from core import money
from core import playbook_tickets as pb


class RecommendationPurchaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901010101'

    def tearDown(self):
        self.store.close()
        self.lg.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _playbook_rec(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        return pb.build_tickets('R', 55, hs, None, ltr, cross_n=3), hs

    def test_recommendation_alone_no_purchase_batch(self):
        pb_rec, hs = self._playbook_rec()
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        batches = self.store.list_purchase_batches(self.rid)
        self.assertEqual(len(batches), 0)
        lg = money.Ledger(db=self.tmp.name)
        n = lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
        lg.close()
        self.assertEqual(n, 0)

    def test_purchase_creates_batch_and_bets_separate(self):
        pb_rec, hs = self._playbook_rec()
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec = ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 200}]
        po = ap.confirm_app_purchase(
            self.rid, lines, recommendation_id=rec.event_id,
            session=self.ss, store=self.store, submit_nonce='p-batch1')
        self.assertTrue(po.ok)
        self.assertEqual(len(self.store.list_purchase_batches(self.rid)), 1)

    def test_diff_exact_match(self):
        rec_lines = [{'kind': '3連複', 'label': '1-2-3', 'stake_suggested': 100}]
        pur = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        d = ap.diff_recommendation_vs_purchase(rec_lines, pur)
        self.assertTrue(d['flags']['purchased_as_recommended'])
        self.assertEqual(d['summary'], '推奨どおり購入')

    def test_diff_remove_rec_ticket(self):
        rec_lines = [
            {'kind': '3連複', 'label': '1-2-3', 'stake_suggested': 0},
            {'kind': '3連複', 'label': '1-2-4', 'stake_suggested': 0},
        ]
        pur = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        d = ap.diff_recommendation_vs_purchase(rec_lines, pur)
        self.assertTrue(d['flags']['removed_from_recommendation'])
        self.assertTrue(d['flags']['unpurchased_recommendation_tickets'])

    def test_diff_add_extra(self):
        rec_lines = [{'kind': '3連複', 'label': '1-2-3', 'stake_suggested': 0}]
        pur = [
            {'kind': '3連複', 'label': '1-2-3', 'stake': 100},
            {'kind': 'ワイド', 'label': '1-2', 'stake': 100},
        ]
        d = ap.diff_recommendation_vs_purchase(rec_lines, pur)
        self.assertTrue(d['flags']['added_not_in_recommendation'])

    def test_diff_stake_change(self):
        rec_lines = [{'kind': '3連複', 'label': '1-2-3', 'stake_suggested': 100}]
        pur = [{'kind': '3連複', 'label': '1-2-3', 'stake': 300}]
        d = ap.diff_recommendation_vs_purchase(rec_lines, pur)
        self.assertTrue(d['flags']['stake_changed'])
        self.assertEqual(d['summary'], '金額変更')

    def test_two_recommendations_same_run(self):
        pb_rec, hs = self._playbook_rec()
        run = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        r1 = ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        r2 = ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 56, session=self.ss, store=self.store)
        self.assertNotEqual(r1.event_id, r2.event_id)
        recs = self.store.list_recommendations(run)
        self.assertEqual(len(recs), 2)

    def test_purchase_references_recommendation(self):
        pb_rec, hs = self._playbook_rec()
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec = ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        po = ap.confirm_app_purchase(
            self.rid, [{'kind': '3連複', 'label': '7-4-12', 'stake': 100}],
            recommendation_id=rec.event_id, session=self.ss, store=self.store,
            submit_nonce='pref-rec')
        row = self.store.list_purchase_batches(self.rid)[0]
        ref = json.loads(row['recommended_ref_json'])
        self.assertEqual(ref['recommendation_id'], rec.event_id)

    def test_duplicate_fingerprint_blocked(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        nonce = 'test-nonce-1'
        po1 = ap.confirm_app_purchase(
            self.rid, lines, session=self.ss, store=self.store, submit_nonce=nonce)
        po2 = ap.confirm_app_purchase(
            self.rid, lines, session=self.ss, store=self.store, submit_nonce=nonce)
        self.assertTrue(po1.ok)
        self.assertTrue(po2.duplicate)
        self.assertEqual(len(self.store.list_purchase_batches(self.rid)), 1)

    def test_intentional_second_batch_different_stake(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        po1 = ap.confirm_app_purchase(
            self.rid, [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}],
            session=self.ss, store=self.store, submit_nonce='st1')
        po2 = ap.confirm_app_purchase(
            self.rid, [{'kind': '3連複', 'label': '1-2-3', 'stake': 200}],
            session=self.ss, store=self.store, submit_nonce='st2')
        self.assertTrue(po1.ok and po2.ok)
        self.assertFalse(po2.duplicate)
        self.assertEqual(len(self.store.list_purchase_batches(self.rid)), 2)

    def test_races_isolated(self):
        ss1, ss2 = {}, {}
        ap.begin_new_run('209901010101', 'sra', session=ss1, store=self.store)
        ap.begin_new_run('209901010102', 'sra', session=ss2, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            '209901010101', pb_rec, hs, 3, 55, session=ss1, store=self.store)
        ap.confirm_app_purchase(
            '209901010101', [{'kind': '単勝', 'label': '5', 'stake': 100}],
            session=ss1, store=self.store, submit_nonce='iso1')
        self.assertEqual(len(self.store.list_purchase_batches('209901010101')), 1)
        self.assertEqual(len(self.store.list_purchase_batches('209901010102')), 0)

    def test_external_confirm_app_declared(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        ap.confirm_app_purchase(
            self.rid, [{'kind': '単勝', 'label': '3', 'stake': 100}],
            session=self.ss, store=self.store, submit_nonce='ext1')
        meta = json.loads(self.store.list_purchase_batches(self.rid)[0]['meta_json'])
        self.assertEqual(meta['external_confirm'], ap.EXTERNAL_CONFIRM_APP)

    def test_run_stage_summary_states(self):
        run = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        summary = ap.run_stage_summary(run, store=self.store)
        self.assertEqual(summary['scanner']['state'], 'not_run')
        ap.record_event(self.rid, 'sra', {'elim_keep_after_sra_recalc': [1, 2]},
                        session=self.ss, store=self.store)
        summary2 = ap.run_stage_summary(run, store=self.store)
        self.assertEqual(summary2['sra']['state'], 'executed_ok')
        ap.record_event(
            self.rid, 'recommendation',
            {'skip': True, 'lines': []}, session=self.ss, store=self.store)
        summary3 = ap.run_stage_summary(run, store=self.store)
        self.assertEqual(summary3['recommendation']['state'], 'no_candidates')
        summary4 = ap.run_stage_summary(
            run, store=self.store,
            record_errors=[{'stage': 'elim', 'error': 'disk'}])
        self.assertEqual(summary4['elim']['state'], 'audit_failed')


class StrategyInvariantStep5(unittest.TestCase):
    def test_playbook_after_recommendation_helpers(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        a = pb.build_tickets('R', 30, hs, None, ltr, cross_n=0)
        _ = ap.build_recommendation_payload(a, hs, 0, 30)
        b = pb.build_tickets('R', 30, hs, None, ltr, cross_n=0)
        self.assertEqual(a['n_points'], b['n_points'])
        self.assertEqual(a['selected_playbook'], bts.PLAYBOOK_D_TRIO_2)


if __name__ == '__main__':
    unittest.main()
