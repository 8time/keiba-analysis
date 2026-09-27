# -*- coding: utf-8 -*-
"""Astra B5: canonical 入力・umaban・legacy・duplicate context・MAGI・COLLATE。"""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core import audit_pipeline as ap
from core import audit_purchase as apur
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


class AstraB5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901230101'

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

    def _buy(self, lines, nonce='op1', intentional_repurchase=False, **ledger_kw):
        return ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg, session=self.ss, store=self.store,
            submit_nonce=nonce, intentional_repurchase=intentional_repurchase,
            **ledger_kw)

    def _assert_ok_implies_validator(self, po):
        self.assertTrue(po.ok, po.error)
        val = apur.validate_committed_actual_purchase(
            self.store, self.lg, po.purchase_batch_id)
        self.assertTrue(val['valid'], val)
        self.assertEqual(val['state'], 'committed_actual')

    # --- umaban ---
    def test_tansho_umaban_mismatch_inconsistent(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'u1')
        self.lg.con.execute(
            "UPDATE bets SET umaban=9 WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        val = apur.validate_committed_actual_purchase(
            self.store, self.lg, po.purchase_batch_id)
        self.assertEqual(val['state'], 'inconsistent')
        self.assertEqual(val['reason'], 'umaban_mismatch')

    def test_fukusho_umaban_mismatch_inconsistent(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '複勝', 'label': '2', 'stake': 100}], 'u2')
        self.lg.con.execute(
            "UPDATE bets SET umaban=9 WHERE purchase_batch_id=?",
            (po.purchase_batch_id,))
        self.lg.con.commit()
        self.assertEqual(
            apur.validate_committed_actual_purchase(
                self.store, self.lg, po.purchase_batch_id)['reason'],
            'umaban_mismatch')

    # --- manifest schema ---
    def test_lines_json_only_change_inconsistent(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'm1')
        self.store.con.execute(
            "UPDATE purchase_batches SET lines_json=? WHERE purchase_batch_id=?",
            (json.dumps([{'kind': '単勝', 'label': '2', 'stake': 100}]),
             po.purchase_batch_id))
        self.store.con.commit()
        self.assertEqual(
            apur.validate_committed_actual_purchase(
                self.store, self.lg, po.purchase_batch_id)['reason'],
            'manifest_lines_mismatch')

    def test_hash_removed_inconsistent(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'm2')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['purchase_manifest_hash'] = ''
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        self.assertEqual(
            apur.validate_committed_actual_purchase(
                self.store, self.lg, po.purchase_batch_id)['reason'],
            'missing_manifest_hash')

    def test_manifest_removed_legacy_unverified(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'm3')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        del meta['purchase_manifest']
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        val = apur.validate_committed_actual_purchase(
            self.store, self.lg, po.purchase_batch_id)
        self.assertEqual(val['state'], 'legacy_unverified')

    def test_ledger_linked_string_not_actual(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'm4')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['ledger_linked'] = 'false'
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        val = apur.validate_committed_actual_purchase(
            self.store, self.lg, po.purchase_batch_id)
        self.assertNotEqual(val['state'], 'committed_actual')
        self.assertEqual(val['reason'], 'invalid_ledger_linked')

    def test_manifest_null_entry_no_crash(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'm5')
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['purchase_manifest'] = [None]
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        val = apur.validate_committed_actual_purchase(
            self.store, self.lg, po.purchase_batch_id)
        self.assertFalse(val['valid'])
        self.assertEqual(val['state'], 'inconsistent')
        self.assertEqual(val['reason'], 'manifest_null_entry')

    # --- first purchase ---
    def test_nonsense_label_rejected_before_write(self):
        self._setup_run_rec()
        before = _counts(self.lg.con)
        po = self._buy([{'kind': '単勝', 'label': 'nonsense', 'stake': 100}], 'bad1')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'invalid_purchase_line')
        self.assertEqual(_counts(self.lg.con), before)

    def test_ambiguous_japanese_keys_rejected(self):
        self._setup_run_rec()
        before = _counts(self.lg.con)
        po = self._buy([{'kind': '単勝', '券種': '複勝', 'label': '1', 'stake': 100}], 'bad2')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'purchase_line_ambiguous_keys')
        self.assertEqual(_counts(self.lg.con), before)

    def test_japanese_keys_only_accepted(self):
        self._setup_run_rec()
        po = self._buy([{'券種': '馬連', '買い目': '3-4', 'stake': 100}], 'jp1')
        self._assert_ok_implies_validator(po)
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        self.assertEqual(meta['purchase_manifest'][0]['combo'], [3, 4])

    def test_first_purchase_ok_implies_validator(self):
        self._setup_run_rec()
        po = self._buy([
            {'kind': '単勝', 'label': '1', 'stake': 100},
            {'kind': '単勝', 'label': '2', 'stake': 100},
        ], 'ok1')
        self._assert_ok_implies_validator(po)

    def test_pre_commit_validator_fail_rollback(self):
        self._setup_run_rec()
        before = _counts(self.lg.con)
        with patch.object(
                apur, 'assert_api_success_implies_committed_actual',
                side_effect=apur.PurchaseIntegrityError('forced')):
            po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'pre1')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'purchase_inconsistent')
        self.assertEqual(_counts(self.lg.con), before)
        po2 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'pre1')
        self.assertTrue(po2.ok)

    # --- duplicate context ---
    def test_session_nonce_wrong_race_batch(self):
        rid_a = self.rid
        rid_b = self.rid + 'B'
        ap.begin_new_run(rid_b, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            rid_b, pb.build_tickets('R', 55, self._hs(), None,
                                     {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        po_b = ap.confirm_app_purchase_with_bets(
            rid_b, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=self.ss, store=self.store, submit_nonce='BX')
        self.assertTrue(po_b.ok)
        ap.begin_new_run(rid_a, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            rid_a, pb.build_tickets('R', 55, self._hs(), None,
                                    {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        self.ss[ap._purchase_nonce_session_key(rid_a, 'AY')] = po_b.purchase_batch_id
        before = _counts(self.lg.con)
        po = ap.confirm_app_purchase_with_bets(
            rid_a, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=self.ss, store=self.store, submit_nonce='AY')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'duplicate_context_mismatch')
        self.assertEqual(_counts(self.lg.con), before)

    def test_session_nonce_wrong_operation(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'op-good')
        self.ss[ap._purchase_nonce_session_key(self.rid, 'op-bad')] = po.purchase_batch_id
        before = _counts(self.lg.con)
        po2 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'op-bad')
        self.assertFalse(po2.ok)
        self.assertEqual(po2.error, 'duplicate_context_mismatch')
        self.assertEqual(_counts(self.lg.con), before)

    def test_session_nonce_wrong_run(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'run1')
        ap.begin_new_run(self.rid, 'sra2', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        self.ss[ap._purchase_nonce_session_key(self.rid, 'run2')] = po.purchase_batch_id
        before = _counts(self.lg.con)
        po2 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'run2')
        self.assertFalse(po2.ok)
        self.assertEqual(po2.error, 'duplicate_context_mismatch')
        self.assertEqual(_counts(self.lg.con), before)

    # --- MAGI ---
    def _seed_noise_batches(self, n, *, status, scope):
        for i in range(n):
            meta = {
                'ledger_linked': scope == 'ledger',
                'completion_scope': (
                    apur.COMPLETION_SCOPE_BATCH_ONLY if scope == 'batch'
                    else apur.COMPLETION_SCOPE_LEDGER_LINKED),
                'record_kind': (
                    apur.RECORD_KIND_AUDIT_BATCH if scope == 'batch'
                    else apur.RECORD_KIND_ACTUAL_PURCHASE),
                'purchase_manifest': [{'bet_type': '単勝', 'combo': [1], 'stake': 1}],
                'purchase_manifest_hash': 'deadbeef',
                'total_stake': 1,
            }
            self.store.create_purchase_batch(
                self.rid, [{'kind': '単勝', 'label': '1', 'stake': 1}],
                record_status=status,
                meta=meta,
                purchase_operation_id=f'noise-{scope}-{i}',
            )

    def test_magi_finds_actual_after_51_pending(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'actual0')
        self._seed_noise_batches(51, status=audit_store.BATCH_PENDING, scope='ledger')
        bid = ar._find_latest_committed_actual_batch_id(
            self.store, self.lg, self.rid)
        self.assertEqual(bid, po.purchase_batch_id)

    def test_magi_finds_actual_after_51_batch_only(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'actual1')
        self._seed_noise_batches(51, status=audit_store.BATCH_COMMITTED_NEW, scope='batch')
        bid = ar._find_latest_committed_actual_batch_id(
            self.store, self.lg, self.rid)
        self.assertEqual(bid, po.purchase_batch_id)

    def test_magi_finds_actual_after_51_inconsistent(self):
        self._setup_run_rec()
        po = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'actual2')
        self._seed_noise_batches(51, status=audit_store.BATCH_COMMITTED_NEW, scope='ledger')
        bid = ar._find_latest_committed_actual_batch_id(
            self.store, self.lg, self.rid)
        self.assertEqual(bid, po.purchase_batch_id)

    def test_aggregate_120_actual_bets(self):
        self._setup_run_rec()
        for i in range(120):
            horse = (i % 8) + 1
            self._buy(
                [{'kind': '単勝', 'label': str(horse), 'stake': 100 + i}],
                nonce=f'a120-{i}', intentional_repurchase=True)
        settled = ar.load_settled_result(
            self.lg, self.rid, '__all__', store=self.store)
        expected = sum(100 + i for i in range(120))
        self.assertEqual(settled['total_stake'], expected)

    # --- index COLLATE ---
    def test_nocase_index_verify_fails(self):
        path = self.tmp.name + '.nocase.db'
        lg = money.Ledger(db=path)
        con = lg.con
        audit_store.ensure_schema(con)
        con.execute("DROP INDEX IF EXISTS idx_purchase_operation_global")
        con.execute(
            """CREATE UNIQUE INDEX idx_purchase_operation_global
               ON purchase_batches(purchase_operation_id COLLATE NOCASE)
               WHERE purchase_operation_id IS NOT NULL
                 AND purchase_operation_id != ''""")
        con.commit()
        lg.close()
        vcon = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.verify_audit_schema(vcon)
        finally:
            vcon.close()
            os.unlink(path)

    def test_operation_id_case_sensitive_coexist(self):
        self._setup_run_rec()
        po1 = self._buy([{'kind': '単勝', 'label': '1', 'stake': 100}], 'CaseX')
        po2 = self._buy(
            [{'kind': '単勝', 'label': '2', 'stake': 100}],
            'casex')
        self.assertTrue(po1.ok and po2.ok)
        self.assertNotEqual(po1.purchase_batch_id, po2.purchase_batch_id)

    def test_operation_id_same_case_unique_fails(self):
        path = self.tmp.name + '.dup.db'
        con = sqlite3.connect(path)
        audit_store.ensure_schema(con)
        con.execute(
            """INSERT INTO purchase_batches(
                 purchase_batch_id, race_id, created_ts, record_status,
                 purchase_operation_id)
               VALUES('b1', 'r1', 't', 'committed', 'SAME')""")
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                """INSERT INTO purchase_batches(
                     purchase_batch_id, race_id, created_ts, record_status,
                     purchase_operation_id)
                   VALUES('b2', 'r1', 't', 'committed', 'SAME')""")
        con.close()
        os.unlink(path)

    def test_integrity_error_handler_path(self):
        self._setup_run_rec()
        manifest = [{'bet_type': '単勝', 'combo': [1], 'stake': 100}]
        mh = apur.purchase_manifest_hash(manifest)
        self.store.create_purchase_batch(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            analysis_run_id='run-x',
            recommended_ref={'recommendation_id': 'rec-x', 'analysis_run_id': 'run-x'},
            meta={
                'ledger_linked': True,
                'completion_scope': apur.COMPLETION_SCOPE_LEDGER_LINKED,
                'record_kind': apur.RECORD_KIND_ACTUAL_PURCHASE,
                'purchase_manifest': manifest,
                'purchase_manifest_hash': mh,
                'total_stake': 100,
            },
            record_status=audit_store.BATCH_COMMITTED_NEW,
            purchase_operation_id='ie-new',
        )
        calls = {'ie': 0}

        def create_then_ie(*args, **kwargs):
            calls['ie'] += 1
            raise sqlite3.IntegrityError('dup op')

        find_calls = {'n': 0}
        real_find = self.store.find_purchase_batch_by_operation_id

        def find_none_once(op_id):
            find_calls['n'] += 1
            if find_calls['n'] == 1:
                return None
            return real_find(op_id)

        before = _counts(self.lg.con)
        with patch.object(
                self.store, 'find_purchase_batch_by_operation_id',
                side_effect=find_none_once):
            with patch.object(self.store, 'create_purchase_batch', side_effect=create_then_ie):
                po2 = self._buy(
                    [{'kind': '単勝', 'label': '1', 'stake': 100}],
                    'ie-new', intentional_repurchase=True)
        self.assertGreaterEqual(calls['ie'], 1)
        self.assertFalse(po2.ok)
        self.assertEqual(po2.error, 'purchase_inconsistent')
        self.assertEqual(_counts(self.lg.con), before)


if __name__ == '__main__':
    unittest.main()
