# -*- coding: utf-8 -*-
"""Vマトリクス pos4 整合 — 純関数と build_v_matrix の契約テスト。"""
import unittest

from core.pace_map import (
    V_FINISH_PUSH_MIN,
    build_v_matrix,
    finish_push_delta,
    resolve_v_pos,
)


class TestResolveVPos(unittest.TestCase):
    def test_pos4_priority(self):
        pos, src = resolve_v_pos(1, 'A', 0.5, profiles={'A': {'ten': 0.2}}, pos4={1: 0.1})
        self.assertEqual(src, 'pos4')
        self.assertAlmostEqual(pos, 0.1)
        pos2, src2 = resolve_v_pos(2, 'B', 0.5, pos4={1: 0.1, 2: 0.9})
        self.assertEqual(src2, 'pos4')
        self.assertAlmostEqual(pos2, 0.9)

    def test_pos4_string_key(self):
        pos, src = resolve_v_pos(3, 'C', 0.5, pos4={'3': 0.25})
        self.assertEqual(src, 'pos4')
        self.assertAlmostEqual(pos, 0.25)

    def test_ten_fallback(self):
        pos, src = resolve_v_pos(1, 'A', 0.8, profiles={'A': {'ten': 0.2}}, pos4=None)
        self.assertEqual(src, 'ten')
        self.assertAlmostEqual(pos, 0.2)

    def test_score_fallback(self):
        pos, src = resolve_v_pos(1, 'A', 0.35, profiles={}, pos4=None)
        self.assertEqual(src, 'score')
        self.assertAlmostEqual(pos, 0.35)


class TestFinishPushDelta(unittest.TestCase):
    def test_push_when_pos4_ahead(self):
        d = finish_push_delta(0.4, 0.0, 'pos4')
        self.assertAlmostEqual(d, 0.4)
        self.assertGreaterEqual(d, V_FINISH_PUSH_MIN)

    def test_no_push_on_ten_source(self):
        self.assertIsNone(finish_push_delta(0.4, 0.0, 'ten'))

    def test_no_push_when_finish_none(self):
        self.assertIsNone(finish_push_delta(0.4, None, 'pos4'))


class TestBuildVMatrixPos4(unittest.TestCase):
    def _horses(self):
        return [
            {'umaban': 1, 'name': '前', 'score': 0.5, 'style': '逃げ'},
            {'umaban': 2, 'name': '後', 'score': 0.5, 'style': '追込'},
        ]

    def test_v_list_differs_ten_vs_pos4(self):
        horses = self._horses()
        profiles = {'前': {'ten': 0.5}, '後': {'ten': 0.5}}
        pos4 = {1: 0.1, 2: 0.9}
        _, v_ten = build_v_matrix(
            horses, profiles=profiles, pace='スロー', baba='フラット', pos4=None)
        _, v_pos4 = build_v_matrix(
            horses, profiles=profiles, pace='スロー', baba='フラット', pos4=pos4)
        umas_ten = {v['umaban'] for v in v_ten}
        umas_pos4 = {v['umaban'] for v in v_pos4}
        self.assertIn(1, umas_pos4)
        self.assertNotIn(1, umas_ten)
        self.assertNotEqual(umas_ten, umas_pos4)

    def test_sashikiri_does_not_move_y(self):
        horses = self._horses()
        profiles = {'前': {'ten': 0.1}, '後': {'ten': 0.9}}
        pos4 = {1: 0.1, 2: 0.9}
        sk = [{'umaban': 2, 'margin': 3.0, 'rank4': 8}]
        fig0, _ = build_v_matrix(
            horses, profiles=profiles, pace='ミドル', baba='フラット',
            pos4=pos4, sashikiri=None)
        fig1, _ = build_v_matrix(
            horses, profiles=profiles, pace='ミドル', baba='フラット',
            pos4=pos4, sashikiri=sk)
        y0 = fig0.data[0].y
        y1 = fig1.data[0].y
        self.assertEqual(list(y0), list(y1))


if __name__ == '__main__':
    unittest.main()
