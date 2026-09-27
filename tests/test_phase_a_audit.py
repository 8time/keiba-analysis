# -*- coding: utf-8 -*-
"""フェーズA 実装順 1〜3: 戦略不変基準・精算・監査スキーマ。"""
import json
import os
import sqlite3
import tempfile
import unittest

from core import bettype_selector as bts
from core import elim_engine as ee
from core import money
from core import playbook_tickets as pb
from core import audit_store

_FIXTURE = os.path.join(
    os.path.dirname(__file__), 'fixtures', 'phase_a_strategy_golden.json')


def _load_golden():
    with open(_FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def _standard_horses():
    return [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]


def _standard_ltr():
    return {i: float(i) for i in range(1, 9)}


class PhaseAStrategyInvariantTests(unittest.TestCase):
    """Step1: 固定入力 → 期待出力（Scanner/消去/SRA/VH/券種は触らない経路の代表）。"""

    @classmethod
    def setUpClass(cls):
        cls.golden = _load_golden()

    def test_playbook_matches_golden(self):
        hs = _standard_horses()
        ltr = _standard_ltr()
        for case in self.golden['playbook_cases']:
            rec = pb.build_tickets(
                case['zone'], case['vscore'], hs, None, ltr, cross_n=case['cross_n'])
            exp = case['expected']
            self.assertEqual(rec['selected_playbook'], exp['selected_playbook'], case['id'])
            if 'n_points' in exp:
                self.assertEqual(rec['n_points'], exp['n_points'], case['id'])
            self.assertEqual(bool(rec.get('skip')), exp['skip'], case['id'])
            if 'has_trio' in exp:
                self.assertEqual(bool(rec.get('trio')), exp['has_trio'], case['id'])
            if 'has_trifecta' in exp:
                self.assertEqual(bool(rec.get('trifecta')), exp['has_trifecta'], case['id'])

    def test_bettype_select_matches_golden(self):
        for case in self.golden['bettype_select_cases']:
            sel = bts.select(case['zone'], case['cross_n'])
            self.assertEqual(sel['selected_bet_type'], case['bet_type'])
            self.assertEqual(sel['selected_playbook'], case['playbook'])

    def test_elim_keep_matches_golden(self):
        spec = self.golden['elim_verdict']
        erows = []
        for um in range(1, spec['n_horses'] + 1):
            erows.append({
                '馬番': um, '馬名': f'H{um}', 'score': float(9 - um),
                'pos': False, 'neg': False, '_tags': [],
            })
        edf = ee.apply_verdict(
            erows, spec['race_id'], border_cnt=spec['border_cnt'],
            record_fired=False, apply_learning=False)
        keep = ee.keep_umaban_from_edf(edf)
        self.assertEqual(sorted(keep), spec['expected_keep_umaban'])
        elim = [u for u in range(1, spec['n_horses'] + 1) if u not in keep]
        self.assertEqual(sorted(elim), spec['expected_eliminated_umaban'])


class SettleMultiTests(unittest.TestCase):
    """Step2: 精算照合・未取得時未精算・順序あり券種。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.ledger = money.Ledger(db=self.tmp.name)

    def tearDown(self):
        self.ledger.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _insert(self, btype, label, uma, stake=100):
        self.ledger.record_prediction(
            '209901010101', uma, label, None, 10.0, stake=stake, bet_type=btype)

    def test_row_dict_and_match_helpers(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE t(a INT)')
        con.execute('INSERT INTO t VALUES(1)')
        row = con.execute('SELECT * FROM t').fetchone()
        d = money.bet_row_dict(row)
        self.assertEqual(d['a'], 1)
        self.assertIsNone(money.bet_row_dict(row).get('missing'))

    def test_trifecta_order_matters(self):
        self._insert('3連単', '3→5→7', 3)
        self._insert('3連単', '7-5-3', 7)
        results = {
            'trifecta': [{'combo': [3, 5, 7], 'odds': 120.0}],
        }
        self.ledger.settle_multi('209901010101', results)
        rows = [money.bet_row_dict(r) for r in self.ledger.con.execute(
            'SELECT * FROM bets ORDER BY bet_id')]
        self.assertEqual(rows[0]['won'], 1)
        self.assertEqual(rows[0]['payout'], 12000)
        self.assertEqual(rows[1]['won'], 0)

    def test_umatan_order_matters(self):
        self._insert('馬単', '5-3', 5)
        results = {'umatan': [{'combo': [5, 3], 'odds': 50.0}]}
        self.ledger.settle_multi('209901010101', results)
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['won'], 1)
        self.assertEqual(row['payout'], 5000)

    def test_trio_unordered(self):
        self._insert('3連複', '8-3-5', 3)
        results = {'trio': [{'combo': [3, 5, 8], 'odds': 12.0}]}
        self.ledger.settle_multi('209901010101', results)
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['won'], 1)

    def test_missing_payout_key_stays_unsettled(self):
        self._insert('3連複', '1-2-3', 1)
        self.ledger.settle_multi('209901010101', {'tan': [{'combo': [1], 'odds': 2.0}]})
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['settled'], 0)

    def test_empty_results_no_settlement(self):
        self._insert('単勝', '5', 5)
        out = self.ledger.settle_multi('209901010101', {})
        self.assertEqual(out['settled'], 0)
        self.assertEqual(out['pending'], 1)

    def test_settlement_log_append_only(self):
        self._insert('単勝', '5', 5, stake=200)
        self.ledger.settle_multi('209901010101', {
            'tan': [{'combo': [5], 'odds': 3.5}],
        })
        logs = list(self.ledger.con.execute('SELECT * FROM bet_settlement_log'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['won'], 1)
        self.assertEqual(logs[0]['payout'], 700)

    def test_resettle_skips_already_settled(self):
        self._insert('単勝', '5', 5)
        self.ledger.settle_multi('209901010101', {
            'tan': [{'combo': [5], 'odds': 3.0}],
        })
        self.ledger.settle_multi('209901010101', {
            'tan': [{'combo': [5], 'odds': 99.0}],
        })
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['payout'], 300)
        self.assertEqual(
            self.ledger.con.execute(
                'SELECT COUNT(*) FROM bet_settlement_log').fetchone()[0], 1)

    def test_refund_tan_returns_stake(self):
        self._insert('単勝', '4', 4, stake=500)
        self.ledger.settle_multi('209901010101', {
            'tan': [{'combo': [4], 'refund': True, 'odds': 0}],
        })
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['settled'], 1)
        self.assertEqual(row['won'], 0)
        self.assertEqual(row['payout'], 500)

    def test_scratch_combo_without_refund_row_unsettled(self):
        self._insert('3連複', '3-4-5', 3, stake=100)
        self.ledger.settle_multi('209901010101', {
            'scratch_umaban': [4],
            'trio': [{'combo': [1, 2, 3], 'odds': 10.0}],
        })
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['settled'], 0)

    def test_multiple_hit_rows_summed(self):
        self._insert('複勝', '3', 3, stake=100)
        self.ledger.settle_multi('209901010101', {
            'fuku': [
                {'combo': [3], 'odds': 2.0},
                {'combo': [3], 'odds': 1.5},
            ],
        })
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets').fetchone())
        self.assertEqual(row['won'], 1)
        self.assertEqual(row['payout'], 350)

    def test_refund_and_hit_conflict_unsettled(self):
        self._insert('単勝', '7', 7, stake=100)
        match = money.match_bet_to_payout(
            {'bet_type': '単勝', 'umaban': 7, 'stake': 100},
            {'tan': [
                {'combo': [7], 'refund': True, 'odds': 0},
                {'combo': [7], 'odds': 5.0},
            ]},
        )
        self.assertIsNone(match)

    def test_correct_settlement_fixes_wrong_loss(self):
        self._insert('単勝', '2', 2, stake=100)
        self.ledger.settle_multi('209901010101', {
            'tan': [{'combo': [9], 'odds': 10.0}],
        })
        bid = self.ledger.con.execute(
            'SELECT bet_id FROM bets').fetchone()[0]
        out = self.ledger.correct_settlement(bid, {
            'tan': [{'combo': [2], 'odds': 4.0}],
        }, note='fix false miss')
        self.assertTrue(out['ok'])
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets WHERE bet_id=?', (bid,)).fetchone())
        self.assertEqual(row['won'], 1)
        self.assertEqual(row['payout'], 400)
        actions = [r[0] for r in self.ledger.con.execute(
            "SELECT action FROM bet_settlement_log ORDER BY log_id")]
        self.assertIn('reversal', actions)
        self.assertIn('correct', actions)

    def test_void_then_correct_no_double_count(self):
        self._insert('ワイド', '3-5', 3, stake=200)
        self.ledger.settle_multi('209901010101', {
            'wide': [{'combo': [3, 5], 'odds': 8.0}],
        })
        bid = self.ledger.con.execute('SELECT bet_id FROM bets').fetchone()[0]
        v = self.ledger.void_settlement(bid, note='manual void')
        self.assertTrue(v['ok'])
        self.assertEqual(
            money.bet_row_dict(self.ledger.con.execute(
                'SELECT * FROM bets WHERE bet_id=?', (bid,)).fetchone())['settled'],
            0)
        self.ledger.settle_multi('209901010101', {
            'wide': [{'combo': [3, 5], 'odds': 8.0}],
        })
        row = money.bet_row_dict(self.ledger.con.execute(
            'SELECT * FROM bets WHERE bet_id=?', (bid,)).fetchone())
        self.assertEqual(row['payout'], 1600)
        self.assertEqual(
            self.ledger.con.execute(
                'SELECT COUNT(*) FROM bet_settlement_log WHERE bet_id=?',
                (bid,)).fetchone()[0], 3)


class AuditStoreTests(unittest.TestCase):
    """Step3: 追記スキーマ・再分析で run が分離される。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.store = audit_store.AuditStore(db=self.tmp.name)

    def tearDown(self):
        self.store.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_two_runs_same_race(self):
        r1 = self.store.create_analysis_run('209901010101', input_hash='h1')
        r2 = self.store.create_analysis_run('209901010101', input_hash='h2')
        self.assertNotEqual(r1, r2)
        runs = self.store.list_analysis_runs('209901010101')
        self.assertEqual(len(runs), 2)
        hashes = {r['input_hash'] for r in runs}
        self.assertEqual(hashes, {'h1', 'h2'})

    def test_events_and_snapshots_append(self):
        run = self.store.create_analysis_run('209901010101')
        e1 = self.store.append_event(run, '209901010101', 'scanner', {'n': 3})
        e2 = self.store.append_event(
            run, '209901010101', 'elim', status='not_run')
        self.assertTrue(e1 and e2)
        self.store.append_snapshot(run, '209901010101', 'pre_input', {'umaban': [1, 2]})
        evs = self.store.list_events(run)
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[1]['status'], 'not_run')

    def test_purchase_batch_record(self):
        run = self.store.create_analysis_run('209901010101')
        batch = self.store.create_purchase_batch(
            '209901010101', [{'kind': '3連複', 'stake': 100}],
            analysis_run_id=run,
            recommended_ref={'analysis_run_id': run},
        )
        row = self.store.con.execute(
            'SELECT * FROM purchase_batches WHERE purchase_batch_id=?',
            (batch,)).fetchone()
        self.assertEqual(row['race_id'], '209901010101')
        self.assertEqual(row['record_status'], 'ok')

    def test_ledger_init_creates_audit_tables(self):
        self.store.close()
        lg = money.Ledger(db=self.tmp.name)
        tables = {
            r[0] for r in lg.con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        lg.close()
        for t in ('analysis_runs', 'audit_events', 'audit_snapshots', 'purchase_batches'):
            self.assertIn(t, tables)


if __name__ == '__main__':
    unittest.main()
