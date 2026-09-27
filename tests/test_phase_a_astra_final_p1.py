# -*- coding: utf-8 -*-
"""Astra最終検収で再現した P1-1〜P1-4 と P2 の反例。

期待値は現行実装の出力から作っていない。
成功してよいのは完全同一の実購入要求だけ。
"""
import json
import os
import sqlite3
import tempfile
import unittest

from core import audit_pipeline as ap
from core import audit_purchase as apur
from core import audit_store
from core import money
from core import playbook_tickets as pb
from scripts import ledger_compliance_report as lcr


def _counts(con):
    return {
        'batches': con.execute("SELECT COUNT(*) FROM purchase_batches").fetchone()[0],
        'bets': con.execute("SELECT COUNT(*) FROM bets").fetchone()[0],
    }


class AstraFinalP1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901240101'

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
        return ap.record_recommendation(
            self.rid,
            pb.build_tickets('R', 55, self._hs(), None,
                             {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)

    def _buy(self, lines, nonce='op1', intentional_repurchase=False, **kw):
        return ap.confirm_app_purchase_with_bets(
            self.rid, lines, self.lg, session=self.ss, store=self.store,
            submit_nonce=nonce, intentional_repurchase=intentional_repurchase,
            **kw)

    def _line(self, label='1', stake=100, kind='単勝'):
        return {'kind': kind, 'label': label, 'stake': stake}

    def _assert_purchase_rejected(self, po, before):
        self.assertFalse(po.ok)
        self.assertFalse(po.duplicate)
        self.assertEqual(_counts(self.lg.con), before)
        self.assertFalse(self.lg.con.in_transaction)

    # --- P1-1 operation replay ---
    def test_operation_replay_rejects_different_run(self):
        self._setup_run_rec()
        po1 = self._buy([self._line()], 'OP-RUN')
        self.assertTrue(po1.ok)
        self.assertFalse(po1.duplicate)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._setup_only_rec = ap.record_recommendation(
            self.rid,
            pb.build_tickets('R', 60, self._hs(), None,
                             {i: float(i) for i in range(1, 9)}, 4),
            self._hs(), 4, 60, session=self.ss, store=self.store)
        before = _counts(self.lg.con)
        po2 = self._buy([self._line()], 'OP-RUN')
        self._assert_purchase_rejected(po2, before)
        self.assertIn(po2.error, ('duplicate_context_mismatch', 'operation_conflict'))

    def test_operation_replay_rejects_different_recommendation(self):
        self._setup_run_rec()
        po1 = self._buy([self._line()], 'OP-REC')
        self.assertTrue(po1.ok)
        ap.record_recommendation(
            self.rid,
            pb.build_tickets('R', 60, self._hs(), None,
                             {i: float(i) for i in range(1, 9)}, 4),
            self._hs(), 4, 60, session=self.ss, store=self.store)
        before = _counts(self.lg.con)
        po2 = self._buy([self._line()], 'OP-REC')
        self._assert_purchase_rejected(po2, before)
        self.assertIn(po2.error, ('duplicate_context_mismatch', 'operation_conflict'))

    def test_operation_replay_rejects_different_lines(self):
        self._setup_run_rec()
        po1 = self._buy([self._line('1')], 'OP-LINE')
        self.assertTrue(po1.ok)
        before = _counts(self.lg.con)
        po2 = self._buy([self._line('2')], 'OP-LINE')
        self._assert_purchase_rejected(po2, before)
        self.assertIn(po2.error, ('duplicate_context_mismatch', 'operation_conflict'))

    def test_operation_replay_rejects_different_stake(self):
        self._setup_run_rec()
        po1 = self._buy([self._line(stake=100)], 'OP-STAKE')
        self.assertTrue(po1.ok)
        before = _counts(self.lg.con)
        po2 = self._buy([self._line(stake=200)], 'OP-STAKE')
        self._assert_purchase_rejected(po2, before)
        self.assertIn(po2.error, ('duplicate_context_mismatch', 'operation_conflict'))

    def test_operation_replay_rejects_missing_run(self):
        self._setup_run_rec()
        po1 = self._buy([self._line()], 'OP-NORUN')
        self.assertTrue(po1.ok)
        before = _counts(self.lg.con)
        po2 = self._buy(
            [self._line()], 'OP-NORUN', analysis_run_id='run-does-not-exist')
        self._assert_purchase_rejected(po2, before)
        self.assertIn(po2.error, (
            'analysis_run_not_found', 'duplicate_context_mismatch', 'operation_conflict'))

    def test_operation_replay_rejects_missing_recommendation(self):
        self._setup_run_rec()
        po1 = self._buy([self._line()], 'OP-NOREC')
        self.assertTrue(po1.ok)
        before = _counts(self.lg.con)
        po2 = self._buy(
            [self._line()], 'OP-NOREC', recommendation_id='rec-does-not-exist')
        self._assert_purchase_rejected(po2, before)
        self.assertIn(po2.error, (
            'recommendation_not_found', 'duplicate_context_mismatch', 'operation_conflict'))

    # --- P1-2 strict parser ---
    def _reject_lines(self, lines, nonce, error):
        self._setup_run_rec()
        before = _counts(self.lg.con)
        po = self._buy(lines, nonce)
        self._assert_purchase_rejected(po, before)
        self.assertEqual(po.error, error)
        self.assertIsNone(self.store.find_purchase_batch_by_operation_id(nonce))

    def test_strict_rejects_negative_label(self):
        self._reject_lines([self._line('-1')], 'bad-neg', 'invalid_purchase_line')

    def test_strict_rejects_horse1(self):
        self._reject_lines([self._line('horse1')], 'bad-h1', 'invalid_purchase_line')

    def test_strict_rejects_object_label(self):
        self._reject_lines(
            [{'kind': '単勝', 'label': {'n': 1}, 'stake': 100}],
            'bad-obj', 'invalid_purchase_line')

    def test_strict_rejects_dot_separator(self):
        self._reject_lines(
            [self._line('1.2', kind='馬連')], 'bad-dot', 'invalid_purchase_line')

    def test_strict_rejects_same_horse_pair(self):
        self._reject_lines(
            [self._line('1-1', kind='馬連')], 'bad-same', 'invalid_purchase_line')

    def test_strict_rejects_fractional_stake(self):
        self._reject_lines([self._line(stake=100.9)], 'bad-frac', 'invalid_stake')

    def test_strict_rejects_bool_stake(self):
        self._reject_lines([self._line(stake=True)], 'bad-bool', 'invalid_stake')

    def test_strict_rejects_mixed_valid_invalid_lines(self):
        self._reject_lines(
            [self._line('1', 100), self._line('2', -50)],
            'bad-mix', 'invalid_stake')

    def test_strict_keeps_zero_pad_space_and_fullwidth(self):
        self._setup_run_rec()
        po = self._buy([
            {'kind': '単勝', 'label': '01', 'stake': 100},
            {'kind': '単勝', 'label': ' 2 ', 'stake': 100},
            {'kind': '複勝', 'label': '３', 'stake': 100},
        ], 'ok-norm')
        self.assertTrue(po.ok, po.error)
        self.assertFalse(po.duplicate)
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        combos = sorted(tuple(e['combo']) for e in meta['purchase_manifest'])
        self.assertEqual(combos, [(1,), (2,), (3,)])

    # --- P1-3 fingerprint beyond LIMIT 30 ---
    def _seed_unrelated(self, n):
        for i in range(n):
            horse = (i % 7) + 2
            po = self._buy(
                [self._line(str(horse), stake=100 + i)],
                nonce=f'noise-{n}-{i}',
                intentional_repurchase=True)
            self.assertTrue(po.ok, po.error)
            self.assertFalse(po.duplicate)

    def test_fingerprint_duplicate_after_31_unrelated_batches(self):
        self._setup_run_rec()
        original = [self._line('1', 100)]
        po1 = self._buy(original, 'fp-31')
        self.assertTrue(po1.ok)
        self._seed_unrelated(31)
        before = _counts(self.lg.con)
        self.assertEqual(before['bets'], 32)
        po2 = self._buy(original, 'fp-31-other', intentional_repurchase=False)
        self.assertTrue(po2.ok)
        self.assertTrue(po2.duplicate)
        self.assertEqual(po2.purchase_batch_id, po1.purchase_batch_id)
        self.assertEqual(_counts(self.lg.con), before)
        stake = self.lg.con.execute(
            "SELECT COALESCE(SUM(stake),0) FROM bets WHERE umaban=1 "
            "AND bet_purpose=?",
            (money.BET_PURPOSE_ACTUAL,)).fetchone()[0]
        self.assertEqual(int(stake), 100)

    def test_fingerprint_duplicate_after_100_unrelated_batches(self):
        self._setup_run_rec()
        original = [self._line('1', 100)]
        po1 = self._buy(original, 'fp-100')
        self.assertTrue(po1.ok)
        self._seed_unrelated(100)
        before = _counts(self.lg.con)
        self.assertEqual(before['bets'], 101)
        po2 = self._buy(original, 'fp-100-other', intentional_repurchase=False)
        self.assertTrue(po2.ok)
        self.assertTrue(po2.duplicate)
        self.assertEqual(po2.purchase_batch_id, po1.purchase_batch_id)
        self.assertEqual(_counts(self.lg.con), before)

    def test_same_operation_intentional_does_not_create_second_purchase(self):
        self._setup_run_rec()
        lines = [self._line()]
        po1 = self._buy(lines, 'OP-INTENT')
        before = _counts(self.lg.con)
        po2 = self._buy(lines, 'OP-INTENT', intentional_repurchase=True)
        self.assertTrue(po2.ok)
        self.assertTrue(po2.duplicate)
        self.assertEqual(po2.purchase_batch_id, po1.purchase_batch_id)
        self.assertEqual(_counts(self.lg.con), before)

    # --- P1-4 legacy_unverified must not enter verified ROI ---
    def test_legacy_unverified_does_not_change_verified_report(self):
        self._setup_run_rec()
        po = self._buy([self._line()], 'verified-1')
        self.assertTrue(po.ok)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [9], 'odds': 8.2}]})
        before_rep = self.lg.report()
        before_gate = self.lg.roi_by_gate()
        before_dd = self.lg.max_drawdown()
        before_comp = lcr.build_report(self.lg)[1]
        self.assertEqual(before_rep['bets'], 1)
        self.assertEqual(before_rep['hit_rate'], 0.0)
        self.assertEqual(before_rep['actual_staked'], 100)
        self.assertEqual(before_rep['actual_returned'], 0)
        self.assertEqual(before_rep['profit'], -100)
        self.assertEqual(before_rep['roi'], 0.0)

        legacy_id = self.store.create_purchase_batch(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            record_status='committed',
            meta={'note': 'legacy-without-b4'})
        self.assertEqual(
            apur.validate_committed_actual_purchase(
                self.store, self.lg, legacy_id)['state'],
            'legacy_unverified')
        self.lg.record_prediction(
            self.rid, 1, '1', None, 8.2, 100, bet_type='単勝',
            bet_purpose=money.BET_PURPOSE_ACTUAL,
            purchase_batch_id=legacy_id)
        self.lg.con.execute(
            "UPDATE bets SET settled=1, won=1, payout=820 "
            "WHERE purchase_batch_id=?",
            (legacy_id,))
        self.lg.con.commit()

        after_rep = self.lg.report()
        self.assertEqual(after_rep['bets'], before_rep['bets'])
        self.assertEqual(after_rep['hit_rate'], before_rep['hit_rate'])
        self.assertEqual(after_rep['actual_staked'], before_rep['actual_staked'])
        self.assertEqual(after_rep['actual_returned'], before_rep['actual_returned'])
        self.assertEqual(after_rep['profit'], before_rep['profit'])
        self.assertEqual(after_rep['roi'], before_rep['roi'])
        self.assertEqual(self.lg.roi_by_gate(), before_gate)
        self.assertEqual(self.lg.max_drawdown(), before_dd)
        after_comp = lcr.build_report(self.lg)[1]
        self.assertEqual(after_comp['bets'], before_comp['bets'])
        self.assertEqual(after_comp['stake_settled'], before_comp['stake_settled'])
        self.assertEqual(after_comp['payout_settled'], before_comp['payout_settled'])
        self.assertEqual(after_comp['profit_settled'], before_comp['profit_settled'])
        self.assertEqual(after_comp['roi_all_pct'], before_comp['roi_all_pct'])

    # --- P2 ---
    def test_manifest_inf_returns_invalid_not_exception(self):
        self._setup_run_rec()
        po = self._buy([self._line()], 'inf-op')
        self.assertTrue(po.ok)
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        manifest_txt = json.dumps(
            meta['purchase_manifest'], ensure_ascii=False, separators=(',', ':'))
        broken = manifest_txt.replace('"stake":100', '"stake":1e309', 1)
        self.assertNotEqual(broken, manifest_txt)
        meta_txt = json.dumps(meta, ensure_ascii=False, separators=(',', ':'))
        raw = meta_txt.replace(manifest_txt, broken, 1)
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (raw, po.purchase_batch_id))
        self.store.con.commit()
        try:
            val = apur.validate_committed_actual_purchase(
                self.store, self.lg, po.purchase_batch_id)
        except OverflowError:
            self.fail('OverflowError leaked from validate_committed_actual_purchase')
        self.assertFalse(val['valid'])
        self.assertIn(val['state'], ('inconsistent', 'invalid'))

    def test_operation_index_rejects_rtrim(self):
        path = self.tmp.name + '.rtrim.db'
        lg = money.Ledger(db=path)
        con = lg.con
        audit_store.ensure_schema(con)
        con.execute("DROP INDEX IF EXISTS idx_purchase_operation_global")
        con.execute(
            """CREATE UNIQUE INDEX idx_purchase_operation_global
               ON purchase_batches(purchase_operation_id COLLATE RTRIM)
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

    def test_operation_index_binary_still_passes(self):
        audit_store.verify_audit_schema(self.lg.con)


if __name__ == '__main__':
    unittest.main()
