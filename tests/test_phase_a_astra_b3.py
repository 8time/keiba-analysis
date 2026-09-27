# -*- coding: utf-8 -*-
"""Astra 敵対監査 ①〜⑦ 回帰。"""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core import audit_pipeline as ap
from core import audit_reconstruct as arcon
from core import audit_review as ar
from core import audit_store
from core import money
from core import playbook_tickets as pb


def _counts(con):
    return {
        'runs': con.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0],
        'events': con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
        'batches': con.execute("SELECT COUNT(*) FROM purchase_batches").fetchone()[0],
        'bets': con.execute("SELECT COUNT(*) FROM bets").fetchone()[0],
    }


class AstraB3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901210101'

    def tearDown(self):
        self.store.close()
        self.lg.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _hs(self):
        return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]

    def _rec(self):
        return ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)

    def _buy(self, lines, nonce='op1', store=None, session=None, **kw):
        return ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg,
            session=session or self.ss, store=store or self.store,
            submit_nonce=nonce, **kw)

    # ① manual settle
    def test_manual_settle_tansho_only(self):
        race = '209901210199'
        specs = [
            ('単勝', '1', 100),
            ('複勝', '1', 100),
            ('馬連', '1-2', 100),
            ('馬単', '1-2', 100),
            ('3連複', '1-2-3', 100),
            ('3連単', '1-2-3', 100),
        ]
        for kind, label, stake in specs:
            self.lg.record_prediction(
                race, money.Ledger.parse_first_umaban(label), label,
                None, 5.0, stake, bet_type=kind,
                bet_purpose=money.BET_PURPOSE_ACTUAL)
        out = self.lg.settle(race, 1, 300)
        self.assertEqual(out['settled'], 1)
        rows = [money.bet_row_dict(r) for r in self.lg.con.execute(
            "SELECT * FROM bets WHERE race_id=? ORDER BY bet_id", (race,))]
        self.assertEqual(rows[0]['settled'], 1)
        self.assertEqual(rows[0]['won'], 1)
        self.assertEqual(int(rows[0]['payout']), 300)
        for r in rows[1:]:
            self.assertEqual(r['settled'], 0)
        log_n = self.lg.con.execute(
            "SELECT COUNT(*) FROM bet_settlement_log WHERE race_id=?",
            (race,)).fetchone()[0]
        self.assertEqual(log_n, 1)

    def test_manual_settle_miss(self):
        race = '209901210198'
        self.lg.record_prediction(
            race, 2, '2', None, 5.0, 100, bet_type='単勝',
            bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle(race, 1, 250)
        row = money.bet_row_dict(self.lg.con.execute(
            "SELECT * FROM bets").fetchone())
        self.assertEqual(row['settled'], 1)
        self.assertEqual(row['won'], 0)

    # ② refund-only
    def _refund_matrix(self, btype, label, rkey, buy_combo, other_combo):
        race = self.rid + btype
        self.lg.record_prediction(
            race, money.Ledger.parse_first_umaban(label), label,
            None, 5.0, 100, bet_type=btype,
            bet_purpose=money.BET_PURPOSE_ACTUAL)
        self.lg.settle_multi(race, {rkey: [{'combo': other_combo, 'refund': True}]})
        row = money.bet_row_dict(self.lg.con.execute(
            "SELECT * FROM bets WHERE race_id=?", (race,)).fetchone())
        self.assertEqual(row['settled'], 0, btype)

    def test_refund_only_unsettled_all_combo_types(self):
        self._refund_matrix('馬連', '1-2', 'umaren', [1, 2], [3, 4])
        self._refund_matrix('馬単', '1-2', 'umatan', [1, 2], [3, 4])
        self._refund_matrix('ワイド', '1-2', 'wide', [1, 2], [3, 4])
        self._refund_matrix('3連複', '1-2-3', 'trio', [1, 2, 3], [4, 5, 6])
        self._refund_matrix('3連単', '1-2-3', 'trifecta', [1, 2, 3], [4, 5, 6])

    # ③ connection
    def test_reject_separate_db_store(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        other = audit_store.AuditStore(
            db=tempfile.NamedTemporaryFile(suffix='.db', delete=False).name)
        try:
            before = _counts(self.lg.con)
            po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}],
                           'conn1', store=other)
            after = _counts(self.lg.con)
            self.assertFalse(po.ok)
            self.assertEqual(po.error, 'audit_connection_mismatch')
            self.assertEqual(before, after)
        finally:
            other.close()

    def test_reject_same_file_other_connection(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        other = audit_store.AuditStore(db=self.tmp.name)
        try:
            before = _counts(self.lg.con)
            po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}],
                           'conn2', store=other)
            after = _counts(self.lg.con)
            self.assertFalse(po.ok)
            self.assertEqual(before, after)
            self.assertFalse(self.lg.con.in_transaction)
        finally:
            other.close()

    # ④ operation state
    def test_pending_operation_not_duplicate_success(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        bid = self.store.create_purchase_batch(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            record_status=audit_store.BATCH_PENDING,
            purchase_operation_id='pend-x')
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'pend-x')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'purchase_incomplete')
        self.assertEqual(
            self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0], 0)
        self.assertEqual(bid, self.store.get_purchase_batch(bid)['purchase_batch_id'])

    def test_committed_replay_ok(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        po1 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'com-x')
        po2 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'com-x')
        self.assertTrue(po1.ok and po2.duplicate)

    def test_inconsistent_committed_no_bets(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        self.store.create_purchase_batch(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            record_status=audit_store.BATCH_COMMITTED_NEW,
            purchase_operation_id='bad-x',
            meta={'ledger_linked': True, 'total_stake': 100})
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'bad-x')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'purchase_inconsistent')

    # ⑤ operation validation
    def test_operation_id_required(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        for raw in (None, '', '   '):
            po = ap.confirm_app_purchase_with_bets(
                self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
                self.lg, session=self.ss, store=self.store, submit_nonce=raw)
            self.assertFalse(po.ok)
            self.assertEqual(po.error, 'operation_id_required')

    # ⑥ no run on bad rec
    def test_bad_rec_no_side_effects(self):
        before = _counts(self.lg.con)
        po = ap.confirm_app_purchase_with_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session={}, store=self.store,
            recommendation_id='no-such-id', submit_nonce='side1')
        after = _counts(self.lg.con)
        self.assertFalse(po.ok)
        self.assertEqual(before, after)

    # ⑦ scanner stages
    def test_scanner_stages_separate_restore(self):
        ap.begin_new_run(self.rid, 'scanner', session=self.ss, store=self.store)
        ap.record_event(
            self.rid, 'scanner', {'vscore': 62}, session=self.ss, store=self.store)
        ap.record_event(
            self.rid, 'scanner_display',
            {'displayed': True, 'exclusion_reason': None},
            session=self.ss, store=self.store)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'sc-st')
        pre = ar.load_pre_race_snapshot(
            self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['scanner_payload']['vscore'], 62)
        self.assertTrue(pre['scanner_display_payload']['displayed'])
        story = arcon.reconstruct_race_story(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            ledger=self.lg, store=self.store)
        self.assertEqual(story['scanner']['vscore'], 62)
        self.assertTrue(story['scanner_display']['displayed'])

    def test_scanner_slot_wrong_stage_rejected(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ev = ap.record_event(
            self.rid, 'scanner_display', {'displayed': True},
            session=self.ss, store=self.store)
        self._rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'sc-bad')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['snapshot_event_ids']['scanner'] = ev.event_id
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        pre = ar.load_pre_race_snapshot(
            self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['status'], 'unavailable')
        self.assertIn('snapshot_stage_mismatch:scanner', pre['reason'])

    # ⑧ index verify
    def test_fake_index_fails_verify(self):
        path = self.tmp.name + '.fakeidx.db'
        lg = money.Ledger(db=path)
        lg.close()
        con = sqlite3.connect(path)
        con.execute("DROP INDEX IF EXISTS idx_purchase_operation_global")
        con.execute(
            "CREATE INDEX idx_purchase_operation_global ON purchase_batches(race_id)")
        con.commit()
        con.close()
        vcon = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(vcon)
        finally:
            vcon.close()
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
