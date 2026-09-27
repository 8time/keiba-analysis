# -*- coding: utf-8 -*-
"""bet_selector_v1 単体テスト（境界 cross_n=2/3 含む）。"""
import unittest

from core import bettype_selector as bts
from core import playbook_tickets as pb
from core import trio_engine as te


class BettypeSelectorTests(unittest.TestCase):
    def test_select_bet_type_boundaries(self):
        self.assertEqual(bts.select_bet_type('D', 0), bts.BET_TRIO)
        self.assertEqual(bts.select_bet_type('D', 5), bts.BET_TRIO)
        self.assertEqual(bts.select_bet_type('C', 0), bts.BET_TRIFECTA)
        self.assertEqual(bts.select_bet_type('C', 2), bts.BET_TRIFECTA)
        self.assertEqual(bts.select_bet_type('C', 3), bts.BET_TRIO)
        self.assertEqual(bts.select_bet_type('C', 5), bts.BET_TRIO)
        self.assertIsNone(bts.select_bet_type('BA', 0))

    def test_select_playbook(self):
        self.assertEqual(bts.select_playbook(bts.BET_TRIO, 'D', 0), bts.PLAYBOOK_D_TRIO_2)
        self.assertEqual(
            bts.select_playbook(bts.BET_TRIO, 'C', 3), bts.PLAYBOOK_C_TRIO_236)
        self.assertEqual(
            bts.select_playbook(bts.BET_TRIFECTA, 'C', 2), bts.PLAYBOOK_C_TRIFECTA_247)
        self.assertEqual(bts.select_playbook(None, 'BA', 0), bts.PLAYBOOK_BA_SKIP)

    def test_selection_reason(self):
        self.assertEqual(bts.selection_reason('D', 0), 'D → 3連複')
        self.assertEqual(bts.selection_reason('C', 2), 'C + cross_n < 3 → 3連単 RRR')
        self.assertEqual(bts.selection_reason('C', 3), 'C + cross_n >= 3 → 3連複')
        self.assertEqual(bts.selection_reason('BA', 0), 'BA → 見送り')

    def test_diag_family_is_label_not_ticket(self):
        d = bts.diag_family('D鉄板', 4)
        self.assertEqual(d['code'], 'NNV')
        self.assertEqual(d['plain'], '人気＋穴')
        c_rrv = bts.diag_family('C中庸', 3)
        self.assertEqual(c_rrv['code'], 'RRV')
        self.assertIn('3連複', c_rrv['verdict'])
        c_rrr = bts.diag_family('C', 2)
        self.assertEqual(c_rrr['code'], 'RRR')
        self.assertIn('3連単', c_rrr['verdict'])
        ba = bts.diag_family('荒れ', 1)
        self.assertIsNone(ba['code'])
        sel = bts.select('C', 3)
        self.assertEqual(sel['diag_family'], 'RRV')
        self.assertEqual(sel['selected_bet_type'], bts.BET_TRIO)

    def test_compute_cross_n_matches_consensus(self):
        from core import consensus_view as cv
        rows = [
            {'umaban': 1, 'proj': 90.0}, {'umaban': 2, 'proj': 80.0},
            {'umaban': 3, 'proj': 70.0}, {'umaban': 4, 'proj': 60.0},
            {'umaban': 5, 'proj': 50.0}, {'umaban': 6, 'proj': 40.0},
        ]
        vh = {1: 9.0, 2: 8.0, 3: 7.0, 4: 6.0, 5: 5.0, 6: 4.0}
        self.assertEqual(bts.compute_cross_n(
            {r['umaban']: r['proj'] for r in rows}, vh), cv.compute_cross_n(rows, vh))
        self.assertEqual(cv.compute_cross_n(rows, vh), 4)

    def test_build_tickets_integration(self):
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}

        d = pb.build_tickets('R', 30, hs, None, ltr, cross_n=0)
        self.assertEqual(d['selected_playbook'], bts.PLAYBOOK_D_TRIO_2)
        self.assertEqual(d['n_points'], 2)
        self.assertTrue(d['trio'])

        c2 = pb.build_tickets('R', 55, hs, None, ltr, cross_n=2)
        self.assertEqual(c2['selected_playbook'], bts.PLAYBOOK_C_TRIFECTA_247)
        self.assertEqual(c2['n_points'], 30)
        self.assertFalse(c2['trio'])

        c3 = pb.build_tickets('R', 55, hs, None, ltr, cross_n=3)
        self.assertEqual(c3['selected_playbook'], bts.PLAYBOOK_C_TRIO_236)
        self.assertTrue(c3['trio'])
        self.assertFalse(c3['trifecta'])
        order = [8, 7, 6, 5, 4, 3, 2]
        expect = set(te.build_formation(order[:2], order[:3], order[:6]))
        got = {r['combo'] for r in c3['trio']}
        self.assertEqual(got, expect)

        ba = pb.build_tickets('R', 80, hs, None, ltr, cross_n=0)
        self.assertTrue(ba['skip'])
        self.assertEqual(ba['selected_playbook'], bts.PLAYBOOK_BA_SKIP)


class DecisionChainTests(unittest.TestCase):
    """decision_chain（UI表示用の道筋）。表示のみで計算は select() に委譲。"""

    def test_d_case(self):
        d = bts.decision_chain('D', 0)
        self.assertTrue(d['applied'])
        self.assertFalse(d['skip'])
        self.assertEqual(d['playbook'], bts.PLAYBOOK_D_TRIO_2)
        self.assertIn('3連複', d['plain'])
        self.assertIn('D鉄板', d['steps'][0])
        # D では共通馬チェックを挟まない（Rule B が使わないため）
        self.assertEqual(len(d['steps']), 2)
        self.assertIn('Rule B', d['steps'][-1])

    def test_c_boundary(self):
        # cross_n=2 → 3連単 2-4-7
        c2 = bts.decision_chain('C', 2)
        self.assertEqual(c2['playbook'], bts.PLAYBOOK_C_TRIFECTA_247)
        self.assertIn('3連単', c2['plain'])
        self.assertTrue(any('共通馬 2頭（3頭未満）' in s for s in c2['steps']))
        # cross_n=3 → 3連複 Rank2-3-6
        c3 = bts.decision_chain('C', 3)
        self.assertEqual(c3['playbook'], bts.PLAYBOOK_C_TRIO_236)
        self.assertIn('3連複', c3['plain'])
        self.assertTrue(any('共通馬 3頭（3頭以上）' in s for s in c3['steps']))

    def test_c_unavailable_source(self):
        d = bts.decision_chain('C', None, cross_n_source='unavailable')
        self.assertTrue(any('データ不足' in s for s in d['steps']))
        # 安全側（0頭扱い）で 3連単
        self.assertEqual(d['playbook'], bts.PLAYBOOK_C_TRIFECTA_247)

    def test_ba_skip_display(self):
        ba = bts.decision_chain('BA', 5)
        self.assertTrue(ba['skip'])
        self.assertFalse(ba['applied'])
        self.assertEqual(ba['plain'], '見送り')
        self.assertIn('対象外', ba['steps'][-1])
        # 馬連・ワイド救済を足していないことの明示
        self.assertIn('却下', ba['steps'][-1])

    def test_zone_label_variants(self):
        self.assertEqual(bts.decision_chain('D鉄板', 0)['playbook'],
                         bts.PLAYBOOK_D_TRIO_2)
        self.assertEqual(bts.decision_chain('C中庸', 3)['playbook'],
                         bts.PLAYBOOK_C_TRIO_236)
        self.assertTrue(bts.decision_chain('荒れ', 0)['skip'])

    def test_parity_with_select(self):
        """道筋の結論は select() と常に一致（表示だけがズレないことを保証）。"""
        for z in ('D', 'C', 'BA'):
            for n in range(6):
                d = bts.decision_chain(z, n)
                s = bts.select(z, n)
                self.assertEqual(d['playbook'], s['selected_playbook'], (z, n))
                self.assertEqual(d['bet_type'], s['selected_bet_type'], (z, n))
                self.assertEqual(d['skip'], s['skip'], (z, n))


if __name__ == '__main__':
    unittest.main()
