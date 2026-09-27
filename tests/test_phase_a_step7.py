# -*- coding: utf-8 -*-
"""フェーズA step7: E2E・整合性・障害注入。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core import audit_pipeline as ap
from core import audit_reconstruct as arcon
from core import audit_review as ar
from core import audit_store
from core import money
from core import playbook_tickets as pb


class PhaseAStep7Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901070701'

    def tearDown(self):
        self.lg.close()
        self.store.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _hs(self):
        return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]

    def _playbook_rec(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        return pb.build_tickets('R', 55, hs, None, ltr, cross_n=3), hs

    def _atomic_buy(self, rid, lines, session=None, intentional=False, nonce=None):
        ss = session or self.ss
        run_id = ap.ensure_run_id(rid, session=ss, store=self.store)
        rec_id, _ = ap.latest_recommendation_for_run(self.store, run_id)
        if not rec_id:
            pb_rec, hs = self._playbook_rec()
            ap.record_recommendation(
                rid, pb_rec, hs, 3, 55, session=ss, store=self.store)
        return ap.confirm_app_purchase_with_bets(
            rid, lines, self.lg, session=ss,
            intentional_repurchase=intentional, submit_nonce=nonce)

    def test_atomic_purchase_batch_and_bets(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 200}]
        po = self._atomic_buy(self.rid, lines, nonce='n1')
        self.assertTrue(po.ok)
        self.assertEqual(po.bets_recorded, 1)
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        self.assertEqual(batch['record_status'], 'committed')
        n = self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
        self.assertEqual(n, 1)

    def test_bets_failure_rolls_back_batch(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        before = {
            'runs': self.lg.con.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
            'events': self.lg.con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            'batches': self.lg.con.execute("SELECT COUNT(*) FROM purchase_batches").fetchone()[0],
            'bets': self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0],
        }
        calls = {'n': 0}
        real_rkb = self.lg.record_kelly_bets

        def fail_rkb(*args, **kwargs):
            calls['n'] += 1
            raise RuntimeError('simulated bets failure')

        lines = [{'kind': '単勝', 'label': '1', 'stake': 100}]
        with patch.object(self.lg, 'record_kelly_bets', side_effect=fail_rkb):
            po = ap.confirm_app_purchase_with_bets(
                self.rid, lines, self.lg, session=self.ss, store=self.store,
                submit_nonce='fail1')
        self.assertFalse(po.ok)
        self.assertIn('simulated bets failure', str(po.error or ''))
        self.assertGreaterEqual(calls['n'], 1)
        self.assertFalse(self.lg.con.in_transaction)
        after = {
            'runs': self.lg.con.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
            'events': self.lg.con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            'batches': self.lg.con.execute("SELECT COUNT(*) FROM purchase_batches").fetchone()[0],
            'bets': self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0],
        }
        self.assertEqual(before, after)
        self.assertEqual(
            len(self.store.list_purchase_batches(self.rid, committed_only=True)), 0)
        with patch.object(self.lg, 'record_kelly_bets', wraps=real_rkb):
            po2 = ap.confirm_app_purchase_with_bets(
                self.rid, lines, self.lg, session=self.ss, store=self.store,
                submit_nonce='fail1')
        self.assertTrue(po2.ok)
        self.assertEqual(po2.bets_recorded, 1)

    def test_pending_batch_excluded_from_totals(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        bid = self.store.create_purchase_batch(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            record_status='pending')
        self.lg.record_kelly_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            purchase_batch_id=bid, audit_link='linked')
        settled = ar.load_settled_result(self.lg, self.rid, '__all__')
        self.assertEqual(settled['total_stake'], 0)

    def test_intentional_same_content_repurchase(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        po1 = self._atomic_buy(self.rid, lines, nonce='a')
        po2 = self._atomic_buy(self.rid, lines, nonce='b-new-op', intentional=True)
        self.assertTrue(po1.ok and po2.ok)
        self.assertNotEqual(po1.purchase_batch_id, po2.purchase_batch_id)
        self.assertEqual(
            len(self.store.list_purchase_batches(self.rid, committed_only=True)), 2)

    def test_canonical_label_diff(self):
        rec = [{'kind': '3連複', 'label': '1-2-3', 'stake_suggested': 100}]
        pur = [{'kind': '3連複', 'label': '01→02→03', 'stake': 100}]
        d = ap.diff_recommendation_vs_purchase(rec, pur)
        self.assertTrue(d['flags']['purchased_as_recommended'])

    def test_umatan_order_preserved(self):
        d1 = ap.ticket_identity('馬単', '2-1')
        d2 = ap.ticket_identity('馬単', '1-2')
        self.assertNotEqual(d1, d2)

    def test_multi_batch_aggregate(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._atomic_buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], nonce='b1')
        self._atomic_buy(
            self.rid, [{'kind': '単勝', 'label': '2', 'stake': 200}],
            nonce='b2', intentional=True)
        settled = ar.load_settled_result(self.lg, self.rid, '__all__')
        self.assertEqual(settled['total_stake'], 300)
        self.assertEqual(len(settled['batch_totals']), 2)

    def test_legacy_bet_not_linked_to_new_run(self):
        self.lg.record_prediction(self.rid, 1, '1', None, 5.0, stake=100)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None, {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE purchase_batch_id IS NULL").fetchone()[0]
        chain = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.assertEqual(chain['audit_link'], ar.AUDIT_LINK_LEGACY)
        self.assertNotEqual(chain['recommendation_id'], rec.event_id)

    def test_reanalysis_links_recommendation_b(self):
        hs = self._hs()
        ltr = {i: float(i) for i in range(1, 9)}
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec_a = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, hs, None, ltr, 3),
            hs, 3, 55, session=self.ss, store=self.store)
        ap.begin_new_run(self.rid, 'sra_reanalyze', session=self.ss, store=self.store)
        rec_b = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 60, hs, None, ltr, 4),
            hs, 4, 60, session=self.ss, store=self.store)
        po = self._atomic_buy(
            self.rid, [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}], nonce='rb')
        self.assertEqual(po.recommendation_id, rec_b.event_id)
        self.assertNotEqual(po.recommendation_id, rec_a.event_id)
        pre = ar.load_pre_race_snapshot(
            self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['recommendation_id'], rec_b.event_id)

    def test_multi_race_sessions_isolated(self):
        ss_a, ss_b = {}, {}
        ra, rb = '209901070702', '209901070703'
        ap.begin_new_run(ra, 'sra', session=ss_a, store=self.store)
        ap.begin_new_run(rb, 'sra', session=ss_b, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            ra, pb_rec, hs, 3, 55, session=ss_a, store=self.store)
        po_a = ap.confirm_app_purchase_with_bets(
            ra, [{'kind': '単勝', 'label': '1', 'stake': 100}], self.lg,
            session=ss_a, submit_nonce='ra')
        self.assertTrue(po_a.ok)
        self.assertEqual(len(self.store.list_purchase_batches(rb)), 0)

    def test_audit_write_failure_no_success(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        with patch.object(
                audit_store.AuditStore, 'create_purchase_batch',
                side_effect=RuntimeError('audit down')):
            po = ap.confirm_app_purchase_with_bets(
                self.rid, [{'kind': '単勝', 'label': '3', 'stake': 100}],
                self.lg, session=self.ss, submit_nonce='err')
        self.assertFalse(po.ok)
        self.assertEqual(self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0], 0)

    def test_settlement_e2e_with_batch_link(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        po = self._atomic_buy(self.rid, [{'kind': '単勝', 'label': '3', 'stake': 100}], nonce='se')
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE purchase_batch_id=?",
            (po.purchase_batch_id,)).fetchone()[0]
        self.lg.settle_multi(self.rid, {
            'tan': [{'combo': [3], 'odds': 3.5}]})
        chain = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.assertEqual(chain['settlement_state'], 'hit')
        self.lg.void_settlement(bet_id, note='fix')
        self.lg.correct_settlement(bet_id, {
            'tan': [{'combo': [3], 'odds': 4.0}]}, note='fix2')
        chain2 = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.assertEqual(chain2['purchase_batch_id'], po.purchase_batch_id)
        det = ar.detect_settlement_correction_after_review(
            bet_id, '2000-01-01T00:00:00', ledger=self.lg)
        self.assertTrue(det['corrected_after_review'])

    def test_full_pipeline_reconstruct(self):
        hs = self._hs()
        ltr = {i: float(i) for i in range(1, 9)}
        run = ap.begin_new_run(self.rid, 'scanner', session=self.ss, store=self.store)
        ap.record_event(self.rid, 'scanner', {'vscore': 55}, session=self.ss, store=self.store)
        ap.record_event(
            self.rid, 'elim',
            {'before_set': [1, 2, 3, 4, 5, 6, 7, 8], 'after_set': [1, 2, 3, 4, 5, 6, 7]},
            session=self.ss, store=self.store)
        ap.record_event(
            self.rid, 'sra',
            {'candidates': [1, 2, 3, 4], 'meta': {'note': 'test'}},
            session=self.ss, store=self.store)
        ap.record_event(
            self.rid, 'anabaka_hunter', {'evaluated_count': 2, 'picks': [4, 5]},
            session=self.ss, store=self.store)
        rec = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, hs, None, ltr, 3),
            hs, 3, 55, session=self.ss, store=self.store)
        po = self._atomic_buy(
            self.rid,
            [{'kind': '3連複', 'label': '1-2-3', 'stake': 300},
             {'kind': 'ワイド', 'label': '1-2', 'stake': 100}],
            nonce='full')
        self.lg.settle_multi(self.rid, {
            'trio': [{'combo': [1, 2, 3], 'odds': 12.0}],
            'wide': [{'combo': [9, 8], 'odds': 5.0}],
        })
        story = arcon.reconstruct_race_story(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            ledger=self.lg, store=self.store)
        self.assertEqual(story['analysis_run_id'], run)
        self.assertEqual(story['recommendation_id'], rec.event_id)
        self.assertTrue(story['narrative_checks']['has_pre_race'])
        self.assertTrue(story['narrative_checks']['has_purchase'])
        self.assertEqual(story['settlement']['total_stake'], 400)
        self.assertGreater(story['settlement']['total_payout'], 0)
        self.assertIn('elim_before_after', story)
        self.assertIsNotNone(story['human_changes'])


if __name__ == '__main__':
    unittest.main()
