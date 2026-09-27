# -*- coding: utf-8 -*-
"""Astra P1 最終再監査 B2 反例の回帰固定。"""
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
from scripts import ledger_compliance_report as lcr


def _compliance_ops(lg):
    _, s = lcr.build_report(lg)
    return {
        'bets': s['bets'],
        'bets_settled': s['bets_settled'],
        'compliance_rate': s['compliance_rate'],
        'compliance_n': s['compliance_n'],
        'deviation_n': s['deviation_n'],
        'gate_counts': dict(s['gate_counts']),
        'roi_gap': s['roi_gap'],
        'roi_all_pct': s['roi_all_pct'],
        'stake_settled': s['stake_settled'],
        'payout_settled': s['payout_settled'],
        'profit_settled': s['profit_settled'],
    }


def _settle_row(lg, rid, btype, label, stake, results):
    lg.record_prediction(
        rid, money.Ledger.parse_first_umaban(label), label, None, 5.0, stake,
        bet_type=btype, bet_purpose=money.BET_PURPOSE_ACTUAL,
        gate_status='buy', has_danger=0, deviation='なし')
    lg.settle_multi(rid, results)
    row = money.bet_row_dict(lg.con.execute(
        "SELECT * FROM bets ORDER BY bet_id DESC LIMIT 1").fetchone())
    return row


class AstraB2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901200101'
        self.other = '209901200102'

    def tearDown(self):
        self.store.close()
        self.lg.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _hs(self):
        return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]

    def _rec(self, rid=None):
        rid = rid or self.rid
        return ap.record_recommendation(
            rid, pb.build_tickets('R', 55, self._hs(), None,
                                  {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)

    def _buy(self, rid, lines, nonce='op', analysis_run_id=None, recommendation_id=None):
        return ap.confirm_app_purchase_with_bets(
            rid, lines, self.lg, session=self.ss, store=self.store,
            submit_nonce=nonce, analysis_run_id=analysis_run_id,
            recommendation_id=recommendation_id)

    # --- compliance ---
    def test_compliance_unaffected_by_non_actual(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        po = self._buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], 'c1')
        self.assertTrue(po.ok)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [1], 'odds': 2.0}]})
        before = _compliance_ops(self.lg)
        self.assertEqual(before['bets'], 1)
        self.assertEqual(before['stake_settled'], 100)
        self.assertEqual(before['payout_settled'], 200)
        self.assertEqual(before['profit_settled'], 100)
        self.assertEqual(before['roi_all_pct'], 200.0)
        for i in range(100):
            self.lg.record_prediction(
                self.rid, (i % 9) + 1, 'x', 0.1, 50.0, 100,
                bet_purpose=money.BET_PURPOSE_CALIBRATION)
            self.lg.settle_multi(self.rid, {'tan': [{'combo': [9], 'odds': 10.0}]})
        self.lg.record_prediction(
            self.rid, 2, '2', 0.2, 3.0, 100, bet_purpose=money.BET_PURPOSE_VIRTUAL)
        self.lg.record_prediction(self.rid, 3, '3', None, 4.0, 100)
        self.lg.settle_multi(self.rid, {'tan': [{'combo': [3], 'odds': 4.0}]})
        after = _compliance_ops(self.lg)
        self.assertEqual(before, after)

    # --- settlement ---
    def test_fuku_miss_with_multiple_winners(self):
        row = _settle_row(self.lg, self.rid, '複勝', '4', 100, {
            'fuku': [
                {'combo': [1], 'odds': 1.2},
                {'combo': [2], 'odds': 1.3},
                {'combo': [3], 'odds': 1.5},
            ]})
        self.assertEqual(row['settled'], 1)
        self.assertEqual(row['won'], 0)

    def test_tan_miss_with_dead_heat(self):
        row = _settle_row(self.lg, self.rid, '単勝', '4', 100, {
            'tan': [
                {'combo': [1], 'odds': 4.0},
                {'combo': [2], 'odds': 4.0},
            ]})
        self.assertEqual(row['settled'], 1)
        self.assertEqual(row['won'], 0)

    def _test_combo_unknown_unsettled(self, btype, label, rkey, our_combo, other_combo):
        row = _settle_row(self.lg, self.rid, btype, label, 100, {
            rkey: [
                {'combo': other_combo, 'pay_raw': '???'},
                {'combo': [9, 8, 7][:len(other_combo)], 'odds': 9.0},
            ]})
        self.assertEqual(row['settled'], 0)

    def test_umaren_unknown_other_combo(self):
        self._test_combo_unknown_unsettled('馬連', '1-2', 'umaren', [1, 2], [3, 4])

    def test_umatan_unknown_other_combo(self):
        self._test_combo_unknown_unsettled('馬単', '1-2', 'umatan', [1, 2], [3, 4])

    def test_wide_unknown_other_combo(self):
        self._test_combo_unknown_unsettled('ワイド', '1-2', 'wide', [1, 2], [3, 4])

    def test_trio_unknown_other_combo(self):
        self._test_combo_unknown_unsettled('3連複', '1-2-3', 'trio', [1, 2, 3], [4, 5, 6])

    def test_trifecta_unknown_other_combo(self):
        self._test_combo_unknown_unsettled('3連単', '1-2-3', 'trifecta', [1, 2, 3], [4, 5, 6])

    def test_settlement_matrix_all_types(self):
        cases = [
            ('単勝', '1', 'tan', {'tan': [{'combo': [1], 'odds': 3.0}]}, 1, 300),
            ('単勝', '2', 'tan', {'tan': [{'combo': [1], 'odds': 3.0}]}, 1, 0),
            ('単勝', '1', 'tan', {'tan': [{'combo': [1], 'pay_raw': '???'}]}, 0, None),
            ('単勝', '1', 'tan', {'tan': []}, 0, None),
            ('馬連', '1-2', 'umaren', {'umaren': [{'combo': [1, 2], 'odds': 5.0}]}, 1, 500),
            ('馬単', '2-1', 'umatan', {'umatan': [{'combo': [2, 1], 'odds': 8.0}]}, 1, 800),
            ('馬単', '1-2', 'umatan', {'umatan': [{'combo': [2, 1], 'odds': 8.0}]}, 1, 0),
        ]
        for btype, label, rkey, res, exp_settled, exp_payout in cases:
            with self.subTest(btype=btype, label=label, res=res):
                row = _settle_row(self.lg, self.rid + str(label), btype, label, 100, res)
                self.assertEqual(row['settled'], exp_settled)
                if exp_payout is not None:
                    self.assertEqual(int(row['payout'] or 0), exp_payout)

    # --- lineage ---
    def test_other_race_wrong_run_explicit(self):
        run_b = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        nb = len(self.store.list_purchase_batches(self.other))
        nbt = self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
        po = self._buy(
            self.other, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            'lin1', analysis_run_id=run_b)
        self.assertFalse(po.ok)
        self.assertEqual(len(self.store.list_purchase_batches(self.other)), nb)
        self.assertEqual(self.lg.con.execute("SELECT COUNT(*) FROM bets").fetchone()[0], nbt)

    def test_other_race_session_hint(self):
        run_b = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec = self._rec()
        ss_o = {}
        ap.begin_new_run(self.other, 'sra', session=ss_o, store=self.store)
        ss_o[ap._recommendation_key(self.other)] = rec.event_id
        ss_o[ap._run_key(self.other)] = run_b
        po = ap.confirm_app_purchase_with_bets(
            self.other, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=ss_o, store=self.store, submit_nonce='lin2')
        self.assertFalse(po.ok)

    def test_other_race_latest_auto(self):
        run_b = ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        ss_o = {}
        ss_o[ap._run_key(self.other)] = run_b
        po = ap.confirm_app_purchase_with_bets(
            self.other, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=ss_o, store=self.store, submit_nonce='lin3',
            analysis_run_id=run_b)
        self.assertFalse(po.ok)

    # --- snapshot / anabaka ---
    def test_anabaka_payload_all_paths(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        hunter_pl = {
            'evaluated_count': 1,
            'candidates': [{
                'horse_no': 7, 'umaban': 7, 'VH': 88, 'vh_score': 88,
                'category': 'elite', 'score': 91,
            }],
        }
        ap.record_event(
            self.rid, 'anabaka_hunter', hunter_pl, session=self.ss, store=self.store)
        self._rec()
        po = self._buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], 'snap1')
        pre = ar.load_pre_race_snapshot(
            self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['status'], 'available')
        cand = pre['hunter_payload']['candidates'][0]
        self.assertEqual(cand['umaban'], 7)
        self.assertEqual(cand['vh_score'], 88)
        story = arcon.reconstruct_race_story(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            ledger=self.lg, store=self.store)
        self.assertEqual(story['anabaka_hunter']['candidates'][0]['vh_score'], 88)
        bundle = ar.assemble_magi_review_bundle(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            ledger=self.lg, store=self.store)
        self.assertEqual(
            bundle['pre_race_snapshot']['hunter_payload']['candidates'][0]['score'], 91)

    def test_snapshot_rejects_other_race_batch(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        po = self._buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], 'snap2')
        self.assertTrue(po.ok)
        pre = ar.load_pre_race_snapshot(
            self.other, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['status'], 'unavailable')
        self.assertEqual(pre['reason'], 'purchase_batch_race_mismatch')

    def test_snapshot_rejects_stage_mismatch(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ev_scan = ap.record_event(
            self.rid, 'scanner', {'v': 1}, session=self.ss, store=self.store)
        self._rec()
        po = self._buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], 'snap3')
        self.assertTrue(po.ok)
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['snapshot_event_ids']['elim'] = ev_scan.event_id
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        pre = ar.load_pre_race_snapshot(
            self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['status'], 'unavailable')
        self.assertIn('snapshot_stage_mismatch', pre['reason'])

    def test_snapshot_rejects_scanner_outside_parent_chain(self):
        ap.begin_new_run(self.rid, 'scanner', session=self.ss, store=self.store)
        r_foreign = ap.begin_new_run(self.rid, 'scanner', session={}, store=self.store)
        ev_foreign = ap.record_event(
            self.rid, 'scanner', {'v': 99}, session={}, store=self.store)
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        po = self._buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], 'snap4')
        self.assertTrue(po.ok)
        batch = self.store.get_purchase_batch(po.purchase_batch_id)
        meta = json.loads(batch['meta_json'])
        meta['snapshot_event_ids']['scanner'] = ev_foreign.event_id
        self.store.con.execute(
            "UPDATE purchase_batches SET meta_json=? WHERE purchase_batch_id=?",
            (json.dumps(meta), po.purchase_batch_id))
        self.store.con.commit()
        pre = ar.load_pre_race_snapshot(
            self.rid, purchase_batch_id=po.purchase_batch_id, store=self.store)
        self.assertEqual(pre['status'], 'unavailable')
        self.assertIn('snapshot_scanner_not_in_parent_chain', pre['reason'])
        self.assertTrue(r_foreign)

    # --- operation id global ---
    def test_operation_id_conflict_across_races(self):
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        self._rec()
        po1 = self._buy(self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}], 'glob-x')
        self.assertTrue(po1.ok)
        ap.begin_new_run(self.other, 'sra', session={}, store=self.store)
        ap.record_recommendation(
            self.other, pb.build_tickets('R', 55, self._hs(), None,
                                         {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session={}, store=self.store)
        nb = len(self.store.list_purchase_batches(self.other))
        po2 = ap.confirm_app_purchase_with_bets(
            self.other, [{'kind': '単勝', 'label': '2', 'stake': 100}],
            self.lg, session={}, store=self.store, submit_nonce='glob-x')
        self.assertFalse(po2.ok)
        self.assertEqual(po2.error, 'operation_id_race_conflict')
        self.assertEqual(len(self.store.list_purchase_batches(self.other)), nb)

    def test_legacy_meta_operation_backfill_and_replay(self):
        self.lg.close()
        self.store.close()
        con = sqlite3.connect(self.tmp.name)
        con.executescript(audit_store._AUDIT_DDL)
        con.execute(
            """INSERT INTO analysis_runs(analysis_run_id,race_id,created_ts)
               VALUES('run1',?,datetime('now'))""", (self.rid,))
        meta = json.dumps({'purchase_operation_id': 'legacy-x'})
        con.execute(
            """INSERT INTO purchase_batches(
                 purchase_batch_id,analysis_run_id,race_id,created_ts,
                 lines_json,recommended_ref_json,meta_json,record_status)
               VALUES('b1','run1',?,datetime('now'),'[]','{}',?,'committed')""",
            (self.rid, meta))
        con.commit()
        con.close()
        c = sqlite3.connect(self.tmp.name)
        audit_store.ensure_schema(c)
        c.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        row = self.store.con.execute(
            "SELECT purchase_operation_id FROM purchase_batches WHERE purchase_batch_id='b1'"
        ).fetchone()
        self.assertEqual(row[0], 'legacy-x')
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        ap.record_recommendation(
            self.rid, pb.build_tickets('R', 55, self._hs(), None,
                                       {i: float(i) for i in range(1, 9)}, 3),
            self._hs(), 3, 55, session=self.ss, store=self.store)
        po = ap.confirm_app_purchase_with_bets(
            self.rid, [{'kind': '単勝', 'label': '1', 'stake': 100}],
            self.lg, session=self.ss, store=self.store, submit_nonce='legacy-x')
        self.assertFalse(po.ok)
        self.assertEqual(po.error, 'purchase_inconsistent')
        self.assertEqual(po.purchase_batch_id, None)
        self.assertEqual(
            len(self.store.list_purchase_batches(self.rid, committed_only=True)), 1)

    def test_legacy_operation_conflict_detected(self):
        path = self.tmp.name + '.conflict.db'
        con = sqlite3.connect(path)
        con.executescript(audit_store._AUDIT_DDL)
        for i, rid in enumerate(['R1', 'R2']):
            con.execute(
                """INSERT INTO purchase_batches(
                     purchase_batch_id,analysis_run_id,race_id,created_ts,
                     lines_json,recommended_ref_json,meta_json,record_status)
                   VALUES(?,?,?,datetime('now'),'[]','{}',?,'committed')""",
                (f'b{i}', f'run{i}', rid, json.dumps({'purchase_operation_id': 'dup-op'})))
        con.commit()
        con.close()
        con = sqlite3.connect(path)
        try:
            with self.assertRaises(audit_store.AuditSchemaError):
                audit_store.ensure_schema(con)
        finally:
            con.close()
            os.unlink(path)

    # --- audit fail-fast ---
    def test_ledger_fails_if_audit_schema_breaks(self):
        with patch('core.audit_store.ensure_schema', side_effect=audit_store.AuditSchemaError('boom')):
            with self.assertRaises(audit_store.AuditSchemaError):
                money.Ledger(db=self.tmp.name + '.fail.db')

    def test_ledger_fails_if_required_index_missing(self):
        path = self.tmp.name + '.idx.db'
        money.Ledger(db=path).close()
        with patch('core.audit_store.verify_audit_schema') as mock_verify:
            mock_verify.side_effect = audit_store.AuditSchemaError('missing index')
            with self.assertRaises(audit_store.AuditSchemaError):
                money.Ledger(db=path)


if __name__ == '__main__':
    unittest.main()
