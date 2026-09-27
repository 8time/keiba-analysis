# -*- coding: utf-8 -*-
"""Astra P1 実購入完全性・batch-only・index 厳密検証。"""
import json
import os
import sqlite3
import tempfile
import unittest

from core import audit_pipeline as ap
from core import audit_purchase as apur
from core import audit_review as ar
from core import audit_store
from core import money
from core import playbook_tickets as pb


def _counts(con):
    return {
        'batches': con.execute("SELECT COUNT(*) FROM purchase_batches").fetchone()[0],
        'bets': con.execute("SELECT COUNT(*) FROM bets").fetchone()[0],
    }


class AstraB4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901220101'

    def tearDown(self):
        self.store.close()
        self.lg.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _hs(self):
        return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]

    def _setup_run_rec(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid,
            pb.build_tickets('R', 55, self._hs(), None,
                             {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)

    def _buy(self, lines, nonce='op1', **kw):
        return ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg, session=self.ss, store=self.store,
            submit_nonce=nonce, **kw)

    def _two_tansho(self, nonce='2b'):
        return self._buy([
            {'kind': '単勝', 'label': '1', 'stake': 100},
            {'kind': '単勝', 'label': '2', 'stake': 100},
        ], nonce=nonce)

    def _val(self, batch_id):
        return apur.validate_committed_actual_purchase(
            self.store, self.lg, batch_id)

    # --- committed integrity ---
    def test_committed_actual_two_bets(self):
        self._setup_run_rec()
        po = self._two_tansho()
        self.assertTrue(po.ok)
        v = self._val(po.purchase_batch_id)
        self.assertTrue(v['valid'])
        self.assertEqual(v['state'], 'committed_actual')

    def test_tamper_delete_bet_and_raise_stake(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-a')
        bid = po.purchase_batch_id
        rows = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE purchase_batch_id=? ORDER BY bet_id",
            (bid,)).fetchall()
        self.lg.con.execute("DELETE FROM bets WHERE bet_id=?", (rows[0][0],))
        self.lg.con.execute(
            "UPDATE bets SET stake=200 WHERE purchase_batch_id=?", (bid,))
        self.lg.con.commit()
        v = self._val(bid)
        self.assertFalse(v['valid'])
        self.assertEqual(v['state'], 'inconsistent')

    def test_tamper_meta_total_stake(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-b')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['total_stake'] = 999
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        v = self._val(po.purchase_batch_id)
        self.assertEqual(v['state'], 'inconsistent')
        self.assertEqual(v['reason'], 'stake_totals_mismatch')

    def test_tamper_combo(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-c')
        self.lg.con.execute(
            "UPDATE bets SET bamei='3' WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        self.assertEqual(self._val(po.purchase_batch_id)['state'], 'inconsistent')

    def test_tamper_bet_type(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-d')
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE purchase_batch_id=? ORDER BY bet_id",
            (po.purchase_batch_id,)).fetchone()[0]
        self.lg.con.execute(
            "UPDATE bets SET bet_type='複勝' WHERE bet_id=?",
            (bet_id,))
        self.lg.con.commit()
        self.assertEqual(self._val(po.purchase_batch_id)['state'], 'inconsistent')

    def test_tamper_extra_bet(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-e')
        self.lg.record_kelly_bets(
            self.rid, [{'kind': '単勝', 'label': '3', 'stake': 100}],
            purchase_batch_id=po.purchase_batch_id,
            recommendation_id=po.recommendation_id,
            analysis_run_id=po.analysis_run_id,
            audit_link='linked')
        self.assertEqual(self._val(po.purchase_batch_id)['state'], 'inconsistent')

    def test_tamper_zero_bets(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-f')
        self.lg.con.execute(
            "DELETE FROM bets WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        self.assertEqual(self._val(po.purchase_batch_id)['state'], 'inconsistent')

    def test_tamper_one_bet_only(self):
        self._setup_run_rec()
        po = self._two_tansho('tam-g')
        rows = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE purchase_batch_id=? LIMIT 1",
            (po.purchase_batch_id,)).fetchall()
        self.lg.con.execute("DELETE FROM bets WHERE bet_id=?", (rows[0][0],))
        self.lg.con.commit()
        self.assertEqual(self._val(po.purchase_batch_id)['state'], 'inconsistent')

    # --- duplicate routes ---
    def test_operation_replay_inconsistent_fails(self):
        self._setup_run_rec()
        po = self._two_tansho('dup-op')
        self.lg.con.execute(
            "DELETE FROM bets WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        po2 = self._buy([
            {'kind': '単勝', 'label': '1', 'stake': 100},
            {'kind': '単勝', 'label': '2', 'stake': 100},
        ], nonce='dup-op')
        self.assertFalse(po2.ok)
        self.assertEqual(po2.error, 'purchase_inconsistent')

    def test_fingerprint_replay_inconsistent_fails(self):
        self._setup_run_rec()
        po = self._two_tansho('fp1')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        fp = meta['fingerprint']
        self.lg.con.execute(
            "DELETE FROM bets WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        before = _counts(self.lg.con)
        po2 = self._buy([
            {'kind': '単勝', 'label': '1', 'stake': 100},
            {'kind': '単勝', 'label': '2', 'stake': 100},
        ], nonce='fp-new-op')
        after = _counts(self.lg.con)
        self.assertFalse(po2.ok)
        self.assertEqual(before, after)
        self.assertNotEqual(po2.error, None)
        self.assertFalse(po2.duplicate)
        still = self.store.find_purchase_by_fingerprint(
            self.rid, fp, committed_only=True)
        self.assertEqual(still, po.purchase_batch_id)

    def test_unique_conflict_inconsistent_fails(self):
        """operation replay で弾く（IntegrityError 経路は b5 で検証）。"""
        self._setup_run_rec()
        po = self._two_tansho('uniq1')
        self.lg.con.execute(
            "DELETE FROM bets WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        before = _counts(self.lg.con)
        po2 = self._buy([
            {'kind': '単勝', 'label': '1', 'stake': 100},
            {'kind': '単勝', 'label': '2', 'stake': 100},
        ], nonce='uniq1')
        self.assertFalse(po2.ok)
        self.assertEqual(po2.error, 'purchase_inconsistent')
        self.assertEqual(_counts(self.lg.con), before)

    # --- batch-only ---
    def test_batch_only_then_actual_rejected(self):
        self._setup_run_rec()
        po0 = ap.confirm_app_purchase(
            self.rid,
            [{'kind': '単勝', 'label': '1', 'stake': 100}],
            session=self.ss, store=self.store, ledger=self.lg, submit_nonce='bo-x')
        self.assertTrue(po0.ok)
        po1 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], nonce='bo-x')
        self.assertFalse(po1.ok)
        self.assertEqual(po1.error, 'operation_scope_conflict')

    def test_batch_only_not_in_magi_latest(self):
        self._setup_run_rec()
        ap.confirm_app_purchase(
            self.rid,
            [{'kind': '単勝', 'label': '1', 'stake': 100}],
            session=self.ss, store=self.store, ledger=self.lg, submit_nonce='mag-bo')
        bundle = ar.assemble_magi_review_bundle(
            self.rid, ledger=self.lg, store=self.store)
        self.assertIsNone(bundle['ids']['purchase_batch_id'])
        self.assertEqual(bundle['purchase_batches_committed'], [])

    def test_batch_only_not_in_actual_performance(self):
        self._setup_run_rec()
        ap.confirm_app_purchase(
            self.rid,
            [{'kind': '単勝', 'label': '1', 'stake': 100}],
            session=self.ss, store=self.store, ledger=self.lg, submit_nonce='perf-bo')
        settled = ar.load_settled_result(self.lg, self.rid, '__all__', store=self.store)
        self.assertEqual(settled['total_stake'], 0)

    # --- index verify ---
    def _index_db(self):
        path = self.tmp.name + '.idx.db'
        lg = money.Ledger(db=path)
        con = lg.con
        audit_store.ensure_schema(con)
        lg.close()
        return path

    def _replace_index(self, path, sql):
        con = sqlite3.connect(path)
        con.execute("DROP INDEX IF EXISTS idx_purchase_operation_global")
        con.execute(sql)
        con.commit()
        con.close()

    def test_index_good_pass_and_duplicate_insert_fails(self):
        path = self._index_db()
        con = sqlite3.connect(path)
        try:
            audit_store.verify_audit_schema(con)
            con.execute(
                """INSERT INTO purchase_batches(
                     purchase_batch_id, race_id, created_ts, record_status,
                     purchase_operation_id)
                   VALUES('b1', 'r1', 't', 'committed', 'same-op')""")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    """INSERT INTO purchase_batches(
                         purchase_batch_id, race_id, created_ts, record_status,
                         purchase_operation_id)
                       VALUES('b2', 'r1', 't', 'committed', 'same-op')""")
        finally:
            con.close()
            os.unlink(path)

    def test_index_non_unique_fails(self):
        path = self._index_db()
        self._replace_index(
            path,
            """CREATE INDEX idx_purchase_operation_global
               ON purchase_batches(purchase_operation_id)
               WHERE purchase_operation_id IS NOT NULL AND purchase_operation_id != ''""")
        con = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(con)
        finally:
            con.close()
            os.unlink(path)

    def test_index_wrong_column_fails(self):
        path = self._index_db()
        self._replace_index(
            path,
            """CREATE UNIQUE INDEX idx_purchase_operation_global
               ON purchase_batches(race_id)
               WHERE purchase_operation_id IS NOT NULL AND purchase_operation_id != ''""")
        con = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(con)
        finally:
            con.close()
            os.unlink(path)

    def test_index_composite_fails(self):
        path = self._index_db()
        self._replace_index(
            path,
            """CREATE UNIQUE INDEX idx_purchase_operation_global
               ON purchase_batches(purchase_operation_id, race_id)
               WHERE purchase_operation_id IS NOT NULL AND purchase_operation_id != ''""")
        con = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(con)
        finally:
            con.close()
            os.unlink(path)

    def test_index_wrong_table_fails(self):
        path = self._index_db()
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE other_purchase_batches AS "
            "SELECT * FROM purchase_batches WHERE 0")
        con.execute("DROP INDEX idx_purchase_operation_global")
        con.execute(
            """CREATE UNIQUE INDEX idx_purchase_operation_global
               ON other_purchase_batches(purchase_operation_id)
               WHERE purchase_operation_id IS NOT NULL AND purchase_operation_id != ''""")
        con.commit()
        con.close()
        vcon = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(vcon)
        finally:
            vcon.close()
            os.unlink(path)

    def test_index_where_extra_and_fails(self):
        path = self._index_db()
        self._replace_index(
            path,
            """CREATE UNIQUE INDEX idx_purchase_operation_global
               ON purchase_batches(purchase_operation_id)
               WHERE purchase_operation_id IS NOT NULL
                 AND purchase_operation_id != '' AND 0""")
        con = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(con)
        finally:
            con.close()
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
