# -*- coding: utf-8 -*-
"""フェーズA step6: IDチェーン・MAGI pre/post 分離・精算逆引き。"""
import json
import os
import tempfile
import unittest

import pandas as pd

from core import audit_pipeline as ap
from core import audit_review as ar
from core import audit_store
from core import magi_chat as mc
from core import money
from core import playbook_tickets as pb


class PhaseAStep6Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.lg = money.Ledger(db=self.tmp.name)
        self.store = audit_store.AuditStore(con=self.lg.con)
        self.ss = {}
        self.rid = '209901020202'
        self.rid2 = '209901020203'

    def tearDown(self):
        self.lg.close()
        self.store.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _playbook_rec(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        return pb.build_tickets('R', 55, hs, None, ltr, cross_n=3), hs

    def _full_chain(self, rid=None, extra_line=None):
        rid = rid or self.rid
        pb_rec, hs = self._playbook_rec()
        ap.begin_new_run(rid, 'sra', session=self.ss, store=self.store)
        rec = ap.record_recommendation(
            rid, pb_rec, hs, 3, 55, session=self.ss, store=self.store)
        lines = [{'kind': '3連複', 'label': '1-2-3', 'stake': 200}]
        if extra_line:
            lines.append(extra_line)
        import uuid
        po = ap.confirm_app_purchase_with_bets(
            rid, lines, self.lg,
            recommendation_id=rec.event_id,
            session=self.ss, store=self.store,
            submit_nonce=f'chain-{uuid.uuid4().hex}')
        self.assertTrue(po.ok)
        return rec, po

    def test_chain_run_to_settlement(self):
        rec, po = self._full_chain()
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE race_id=?", (self.rid,)).fetchone()[0]
        chain = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.assertEqual(chain['analysis_run_id'], po.analysis_run_id)
        self.assertEqual(chain['recommendation_id'], po.recommendation_id)
        self.assertEqual(chain['purchase_batch_id'], po.purchase_batch_id)
        self.assertEqual(chain['audit_link'], ar.AUDIT_LINK_LINKED)

    def test_bet_reverse_to_purchase_batch(self):
        _, po = self._full_chain()
        row = self.lg.con.execute(
            "SELECT purchase_batch_id FROM bets WHERE race_id=?", (self.rid,)).fetchone()
        self.assertEqual(row[0], po.purchase_batch_id)

    def test_legacy_bet_not_linked_to_new_run(self):
        self.lg.record_prediction(self.rid, 1, '1-2-3', None, 10.0, stake=100, bet_type='3連複')
        ap.begin_new_run(self.rid, 'sra', session=self.ss, store=self.store)
        rec = ap.record_recommendation(
            self.rid, self._playbook_rec()[0], self._playbook_rec()[1], 3, 55,
            session=self.ss, store=self.store)
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE purchase_batch_id IS NULL").fetchone()[0]
        chain = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.assertEqual(chain['audit_link'], ar.AUDIT_LINK_LEGACY)
        self.assertNotEqual(chain['recommendation_id'], rec.event_id)

    def test_pre_race_preferred_in_magi_context(self):
        _, po = self._full_chain()
        df = pd.DataFrame({'Umaban': [1], 'Name': ['A'], 'Popularity': [1], 'Odds': [2.0],
                           'Projected Score': [90]})
        bundle = ar.assemble_magi_review_bundle(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            post_df=df, post_magi_pred={'final_prediction': {'horses': [{'umaban': 9, 'name': 'X'}]}},
            ledger=self.lg, store=self.store)
        ctx = mc.build_context(
            df, {'final_prediction': {'horses': [{'umaban': 9, 'name': 'X'}]}},
            None, review_bundle=bundle)
        self.assertTrue(ctx['used_pre_race_snapshot'])
        self.assertIn('PRE-RACE SNAPSHOT', ctx['text'])
        self.assertIn('POST-RACE RECALCULATION', ctx['text'])
        self.assertNotIn('MAGIが本命にした馬(事前)', ctx['text'])

    def test_post_not_labeled_as_pre(self):
        bundle = ar.assemble_magi_review_bundle(
            self.rid2, post_df=pd.DataFrame({'Umaban': [1], 'Name': ['A']}),
            ledger=self.lg, store=self.store)
        self.assertEqual(bundle['pre_race_snapshot']['status'], 'unavailable')
        ctx = mc.build_context(
            pd.DataFrame({'Umaban': [1], 'Name': ['A']}),
            {'final_prediction': {'horses': [{'umaban': 1, 'name': 'A'}]}},
            None, review_bundle=bundle)
        self.assertFalse(ctx['used_pre_race_snapshot'])
        self.assertIn('unavailable', ctx['text'])

    def test_pre_unavailable_without_guess(self):
        pre = ar.load_pre_race_snapshot(self.rid2, store=self.store)
        self.assertEqual(pre['status'], 'unavailable')

    def test_diff_in_review_bundle(self):
        rec, po = self._full_chain(extra_line={'kind': 'ワイド', 'label': '1-2', 'stake': 100})
        bundle = ar.assemble_magi_review_bundle(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            ledger=self.lg, store=self.store)
        diff = bundle['pre_race_snapshot'].get('diff') or {}
        self.assertTrue(diff.get('flags', {}).get('added_not_in_recommendation'))

    def test_settlement_states(self):
        _, po = self._full_chain()
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE race_id=?", (self.rid,)).fetchone()[0]
        self.assertEqual(ar.classify_bet_settlement({'settled': 0}), 'pending')
        self.lg.con.execute(
            "UPDATE bets SET settled=1, won=1, payout=400 WHERE bet_id=?", (bet_id,))
        self.lg.con.commit()
        row = money.bet_row_dict(self.lg.con.execute(
            "SELECT * FROM bets WHERE bet_id=?", (bet_id,)).fetchone())
        self.assertEqual(ar.classify_bet_settlement(row), 'hit')
        settled = ar.load_settled_result(self.lg, self.rid, po.purchase_batch_id)
        self.assertEqual(settled['bets'][0]['settlement_state'], 'hit')

    def test_settlement_correction_link_preserved(self):
        _, po = self._full_chain()
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE race_id=?", (self.rid,)).fetchone()[0]
        self.lg.con.execute(
            "UPDATE bets SET settled=1, won=0, payout=0 WHERE bet_id=?", (bet_id,))
        self.lg.con.commit()
        chain_before = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.lg.void_settlement(bet_id, note='test_void')
        chain_after = ar.resolve_id_chain(bet_id=bet_id, ledger=self.lg, store=self.store)
        self.assertEqual(chain_before['purchase_batch_id'], chain_after['purchase_batch_id'])

    def test_correction_after_review_detectable(self):
        _, po = self._full_chain()
        bet_id = self.lg.con.execute(
            "SELECT bet_id FROM bets WHERE race_id=?", (self.rid,)).fetchone()[0]
        review_ts = '2000-01-01T10:00:00'
        self.lg.con.execute(
            "UPDATE bets SET settled=1, won=0, payout=0 WHERE bet_id=?", (bet_id,))
        self.lg.con.commit()
        self.lg._log_settlement(
            bet_id, self.rid, '2099-06-01T12:00:00', 1, 500,
            'correct_settlement', 'after review fix', action='correct')
        det = ar.detect_settlement_correction_after_review(bet_id, review_ts, ledger=self.lg)
        self.assertTrue(det['corrected_after_review'])

    def test_no_cross_race_mix(self):
        self._full_chain(self.rid)
        self._full_chain(self.rid2)
        settled = ar.load_settled_result(self.lg, self.rid)
        for b in settled['bets']:
            self.assertTrue(b.get('purchase_batch_id'))
            row = self.lg.con.execute(
                "SELECT race_id FROM bets WHERE bet_id=?", (b['bet_id'],)).fetchone()
            self.assertEqual(row[0], self.rid)

    def test_magi_review_audit_record(self):
        _, po = self._full_chain()
        bundle = ar.assemble_magi_review_bundle(
            self.rid, purchase_batch_id=po.purchase_batch_id,
            ledger=self.lg, store=self.store)
        out, ts = ar.save_magi_review_record(
            self.rid, bundle, used_pre_race_snapshot=True,
            used_post_race_recalc=False, store=self.store)
        self.assertTrue(out.ok)
        ev = self.store.get_event(out.event_id)
        pl = json.loads(ev['payload_json'])
        self.assertEqual(pl['purchase_batch_id'], po.purchase_batch_id)
        self.assertTrue(pl['used_pre_race_snapshot'])
        self.assertIn('review_created_ts', pl)


if __name__ == '__main__':
    unittest.main()
