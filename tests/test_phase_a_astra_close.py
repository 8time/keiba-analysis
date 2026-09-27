# -*- coding: utf-8 -*-
"""Astra P1 再監査反例の回帰固定。"""
import json
import os
import sqlite3
import tempfile
import unittest

from core import audit_pipeline as ap
from core import audit_reconstruct as arcon
from core import audit_review as ar
from core import audit_snapshot
from core import audit_store
from core import money
from core import playbook_tickets as pb
from scripts import ledger_compliance_report as lcr


def _perf_bundle(lg, rid, batch_id=None):
    rep = lg.report()
    settled = ar.load_settled_result(lg, rid, batch_id or '__all__')
    return {
        'actual_stake': rep['actual_staked'],
        'actual_payout': rep['actual_returned'],
        'actual_pnl': rep['profit'],
        'actual_roi': rep['roi'],
        'gate': lg.roi_by_gate(),
        'dd': lg.max_drawdown(),
        'loss': lg.loss_breakdown(),
        'mood': lg.mood_report(),
        'deviation': lg.deviation_report(),
        'reflection_len': len(lg.reflection()),
        'magi_stake': settled['confirmed_stake'] + settled['unsettled_stake'],
        'magi_pnl': settled['confirmed_pnl'],
        'compliance_roi_gap': lcr.build_report(lg)[1].get('roi_gap'),
    }


class AstraCloseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901160101'

    def tearDown(self):
        self.lg.close()
        self.store.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _hs(self):
        return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]

    def _rec_and_buy(self, nonce='op1'):
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        return ap.confirm_app_purchase_with_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=self.ss, submit_nonce=nonce)

    def test_actual_metrics_unchanged_by_calibration_noise(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        po = self._rec_and_buy('perf1')
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [1], 'odds': 2.0}]})
        before = _perf_bundle(self.lg, self.rid)
        self.assertEqual(before['actual_stake'], 100)
        self.assertEqual(before['actual_payout'], 200)
        self.assertEqual(before['actual_pnl'], 100)
        self.assertEqual(before['actual_roi'], 200.0)
        for i in range(100):
            self.lg.record_prediction(
                self.rid, (i % 9) + 1, 'x', 0.1, 50.0, 100,
                bet_purpose=money.BET_PURPOSE_CALIBRATION)
            self.lg.settle_multi(self.rid, {'tan': [{'combo': [9], 'odds': 10.0}]})
        after = _perf_bundle(self.lg, self.rid)
        self.assertEqual(before, after)

    def test_virtual_and_legacy_do_not_change_actual(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec_and_buy('perf2')
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [1], 'odds': 2.0}]})
        before = _perf_bundle(self.lg, self.rid)
        self.lg.record_prediction(self.rid, 2, '2', 0.2, 3.0, 100,
                                  bet_purpose=money.BET_PURPOSE_VIRTUAL)
        self.lg.record_prediction(self.rid, 3, '3', None, 4.0, 100)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [3], 'odds': 4.0}]})
        self.assertEqual(_perf_bundle(self.lg, self.rid), before)

    def test_calibration_with_batch_id_stays_calibration(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        po = self._rec_and_buy('perf3')
        self.lg.record_prediction(
            self.rid, 5, '5', 0.1, 9.0, 100,
            bet_purpose=money.BET_PURPOSE_CALIBRATION,
            purchase_batch_id=po.purchase_batch_id)
        row = money.bet_row_dict(self.lg.con.execute(
            "SELECT * FROM bets WHERE umaban=5").fetchone())
        self.assertEqual(row['bet_purpose'], money.BET_PURPOSE_CALIBRATION)

    def test_unknown_payout_cases(self):
        self.lg.record_prediction(
            self.rid, 1, '1', None, 5.0, 100, bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [2], 'pay_raw': '???'}]})
        self.assertEqual(self.lg.con.execute(
            "SELECT settled FROM bets").fetchone()[0], 0)
        self.lg.con.execute("UPDATE bets SET settled=0")
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [1], 'pay_raw': '???'}]})
        self.assertEqual(self.lg.con.execute(
            "SELECT settled FROM bets").fetchone()[0], 0)
        self.lg.con.execute("UPDATE bets SET settled=0")
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [2], 'odds': 5.0}]})
        row = money.bet_row_dict(self.lg.con.execute("SELECT * FROM bets").fetchone())
        self.assertEqual(row['settled'], 1)
        self.assertEqual(row['won'], 0)
        self.lg.con.execute("UPDATE bets SET settled=0, won=NULL, payout=0")
        self.lg.settle_multi(self.rid, {'tan': []})
        self.assertEqual(self.lg.con.execute(
            "SELECT settled FROM bets").fetchone()[0], 0)

    def test_explicit_wrong_run_recommendation_fails(self):
        hs = self._hs()
        ltr = {i: float(i) for i in range(1, 9)}
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec_a = ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, hs, None, ltr, 3),
            hs, 3, 55, session=self.ss, store=self.store)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 60, hs, None, ltr, 4),
            hs, 4, 60, session=self.ss, store=self.store)
        nb = len(self.store.list_purchase_batches(self.rid))
        nbets = self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
        po = ap.confirm_app_purchase_with_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, recommendation_id=rec_a.event_id, session=self.ss,
            submit_nonce='badrec')
        self.assertFalse(po.ok)
        self.assertEqual(len(self.store.list_purchase_batches(self.rid)), nb)
        self.assertEqual(self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0], nbets)

    def test_elim_not_run_at_purchase(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        po = self._rec_and_buy('snap-elim')
        pre = ar.load_pre_race_snapshot(self.rid, purchase_batch_id=po.purchase_batch_id,
                                          store=self.store)
        self.assertEqual(
            pre['snapshot_event_ids'].get('elim'),
            audit_snapshot.SNAPSHOT_NOT_RUN)
        ap.record_event(self.rid, 'elim', {'after_set': [8, 9]},
                        session=self.ss, store=self.store)
        pre2 = ar.load_pre_race_snapshot(self.rid, purchase_batch_id=po.purchase_batch_id,
                                         store=self.store)
        self.assertEqual(pre2['elim_payload'], {})

    def test_parent_scanner_fixed(self):
        r_a = ap.begin_new_run(self.rid, 'scanner', session=self.ss, store=self.store)
        ev_scan = ap.record_event(
            self.rid, 'scanner', {'vscore': 77}, session=self.ss, store=self.store)
        r_b = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        po = self._rec_and_buy('parent-sc')
        pre = ar.load_pre_race_snapshot(self.rid, purchase_batch_id=po.purchase_batch_id,
                                        store=self.store)
        self.assertEqual(pre['snapshot_event_ids'].get('scanner'), ev_scan.event_id)
        self.assertEqual(pre['scanner_payload'].get('vscore'), 77)

    def test_operation_id_db_idempotent(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        ss2 = {}
        po1 = ap.confirm_app_purchase_with_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=self.ss, submit_nonce='op-x')
        po2 = ap.confirm_app_purchase_with_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=ss2, submit_nonce='op-x')
        self.assertTrue(po1.ok)
        self.assertTrue(po2.duplicate)
        self.assertEqual(
            len(self.store.list_purchase_batches(self.rid, committed_only=True)), 1)
        self.assertEqual(self.lg.con.execute(
            "SELECT COUNT(*) FROM bets").fetchone()[0], 1)

    def test_new_operation_id_second_batch(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 100}]
        self.assertTrue(ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg, session=self.ss,
            submit_nonce='y1', intentional_repurchase=True).ok)
        self.assertTrue(ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg, session=self.ss,
            submit_nonce='y2', intentional_repurchase=True).ok)
        self.assertEqual(
            len(self.store.list_purchase_batches(self.rid, committed_only=True)), 2)

    def test_migration_idempotent(self):
        money.Ledger(db=self.tmp.name).close()
        money.Ledger(db=self.tmp.name).close()

    def test_migration_error_not_swallowed(self):
        with self.assertRaises(money.LedgerSchemaError):
            money._migrate_add_column(
                sqlite3.connect(':memory:'), 'no_such_table', 'x', 'TEXT')


if __name__ == '__main__':
    unittest.main()
