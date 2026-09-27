# -*- coding: utf-8 -*-
"""フェーズA P1 修正1〜4 回帰テスト（Astra再監査）。"""
import json
import os
import tempfile
import unittest

from core import audit_pipeline as ap
from core import audit_review as ar
from core import audit_store
from core import money
from core import playbook_tickets as pb


class P1FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901150101'

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
        hs = self._hs()
        ltr = {i: float(i) for i in range(1, 9)}
        return pb.build_tickets('R', 55, hs, None, ltr, cross_n=3), hs

    def _buy(self, lines, nonce='op1', intentional=False):
        return ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg, session=self.ss,
            submit_nonce=nonce, intentional_repurchase=intentional)

    # --- 実購入分離 ---
    def test_calibration_does_not_change_actual_roi(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        for i in range(1, 101):
            self.lg.record_prediction(
                self.rid, i, f'H{i}', 0.1, 10.0, 100,
                bet_purpose=money.BET_PURPOSE_CALIBRATION)
        rep0 = self.lg.report()
        self.assertEqual(rep0.get('actual_staked', 0), 0)
        self.assertEqual(rep0.get('roi', 0.0), 0.0)

    def test_actual_only_in_roi_after_mixed(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None, {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], nonce='mix1')
        for i in range(50):
            self.lg.record_prediction(
                self.rid, i, 'x', 0.2, 5.0, 100, bet_purpose=money.BET_PURPOSE_CALIBRATION)
        rep = self.lg.report()
        self.assertEqual(rep.get('actual_staked', 0), 0)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [1], 'odds': 2.0}]})
        rep2 = self.lg.report()
        self.assertEqual(rep2.get('actual_staked'), 100)

    # --- 精算 ---
    def test_payout_820_yen(self):
        self.lg.record_prediction(
            self.rid, 1, '1', None, 8.2, 100, bet_type='単勝',
            bet_purpose=money.BET_PURPOSE_ACTUAL)
        m = money.match_bet_to_payout(
            {'bet_type': '単勝', 'umaban': 1, 'stake': 100},
            {'tan': [{'combo': [1], 'odds': 8.2}]})
        self.assertEqual(m['payout'], 820)

    def test_empty_tan_stays_unsettled(self):
        self.lg.record_prediction(self.rid, 1, '1', None, 5.0, 100, bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle_multi(self.rid, {'tan': []})
        row = money.bet_row_dict(self.lg.con.execute("SELECT * FROM bets").fetchone())
        self.assertEqual(row['settled'], 0)

    def test_unknown_only_stays_unsettled(self):
        self.lg.record_prediction(self.rid, 1, '1', None, 5.0, 100, bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [1], 'pay_raw': '???'}]})
        row = money.bet_row_dict(self.lg.con.execute("SELECT * FROM bets").fetchone())
        self.assertEqual(row['settled'], 0)

    def test_confirmed_miss(self):
        self.lg.record_prediction(self.rid, 1, '1', None, 5.0, 100, bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [9], 'odds': 10.0}]})
        row = money.bet_row_dict(self.lg.con.execute("SELECT * FROM bets").fetchone())
        self.assertEqual(row['settled'], 1)
        self.assertEqual(row['won'], 0)

    def test_unsettled_not_counted_as_loss(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None, {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        po = self._buy([{'kind': '単勝', 'label': '3', 'stake': 100}], nonce='u1')
        settled = ar.load_settled_result(self.lg, self.rid, po.purchase_batch_id)
        self.assertEqual(settled['unsettled_stake'], 100)
        self.assertEqual(settled['confirmed_pnl'], 0)

    def test_report_no_typeerror_without_prob(self):
        self.lg.record_prediction(
            self.rid, 2, '2', None, 4.0, 100, bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [2], 'odds': 4.0}]})
        rep = self.lg.report()
        self.assertIsNotNone(rep)
        self.assertIn('brier', rep)

    # --- run ---
    def test_parent_run_on_reanalyze(self):
        r_scan = ap.begin_new_run(self.rid, 'scanner', session=self.ss, store=self.store)
        ap.record_event(self.rid, 'scanner', {'v': 1}, session=self.ss, store=self.store)
        r_sra = ap.begin_new_run(self.rid, 'sra_analyze', session=self.ss, store=self.store)
        run_row = self.store.con.execute(
            "SELECT meta_json FROM analysis_runs WHERE analysis_run_id=?",
            (r_sra,)).fetchone()
        meta = json.loads(run_row['meta_json'])
        self.assertEqual(meta.get('parent_analysis_run_id'), r_scan)

    def test_dedupe_per_run_allows_same_signature_new_run(self):
        sig = {'x': 1}
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        o1 = ap.record_event_deduped(self.rid, 'sra', sig, {'n': 1}, session=self.ss, store=self.store)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        o2 = ap.record_event_deduped(self.rid, 'sra', sig, {'n': 2}, session=self.ss, store=self.store)
        self.assertTrue(o1.event_id)
        self.assertTrue(o2.event_id)
        self.assertNotEqual(o1.event_id, o2.event_id)

    def test_new_run_purchase_not_old_recommendation(self):
        hs = self._hs()
        ltr = {i: float(i) for i in range(1, 9)}
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec_a = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, hs, None, ltr, 3),
            hs, 3, 55, session=self.ss, store=self.store)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec_b = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 60, hs, None, ltr, 4),
            hs, 4, 60, session=self.ss, store=self.store)
        po = self._buy([{'kind': '3連複', 'label': '1-2-3', 'stake': 100}], nonce='rb')
        self.assertEqual(po.recommendation_id, rec_b.event_id)
        self.assertNotEqual(po.recommendation_id, rec_a.event_id)

    # --- snapshot ---
    def test_purchase_snapshot_fixed_after_later_elim(self):
        run = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_event(
            self.rid, 'elim',
            {'after_set': [1, 2, 3]}, session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None, {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        po = self._buy([{'kind': '3連複', 'label': '1-2-3', 'stake': 100}], nonce='snap1')
        pre1 = ar.load_pre_race_snapshot(self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        ap.record_event(
            self.rid, 'elim',
            {'after_set': [8, 9]}, session=self.ss, store=self.store)
        pre2 = ar.load_pre_race_snapshot(self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(
            pre1['elim_payload'].get('after_set'),
            pre2['elim_payload'].get('after_set'))
        self.assertEqual(pre1['elim_payload'].get('after_set'), [1, 2, 3])

    # --- operation id ---
    def test_same_operation_id_once(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        pb_rec, hs = self._playbook_rec()
        ap.record_recommendation(
            self.rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        po1 = self._buy(lines, nonce='same-op')
        po2 = self._buy(lines, nonce='same-op', intentional=True)
        self.assertTrue(po1.ok)
        self.assertTrue(po2.duplicate)
        self.assertEqual(len(self.store.list_purchase_batches(self.rid, committed_only=True)), 1)

    def test_intentional_new_operation_second_batch(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None, {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        po1 = self._buy(lines, nonce='op-a')
        po2 = self._buy(lines, nonce='op-b', intentional=True)
        self.assertTrue(po1.ok and po2.ok)
        self.assertEqual(len(self.store.list_purchase_batches(self.rid, committed_only=True)), 2)


if __name__ == '__main__':
    unittest.main()
