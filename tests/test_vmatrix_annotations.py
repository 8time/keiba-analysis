# -*- coding: utf-8 -*-
"""Vエリア P1 注記集約の契約テスト。"""
import unittest

from core import vmatrix_annotations as va
from core.pace_map import V_FINISH_PUSH_MIN


class TestVMatrixAnnotations(unittest.TestCase):
    def test_spurt_tag(self):
        horses = [{'umaban': 6, 'name': 'A', 'score': 0.5}]
        rows = [{'Umaban': 6, 'Popularity': 8}]
        prof = {'A': {'agari': 0.2}}
        ann = va.collect_horse_annotations(
            horses, prof, rows, '202606040101', pos4={6: 0.5}, finish={})
        self.assertIn(6, ann)
        self.assertIn(va.TAG_SPURT, ann[6]['tags'])

    def test_tag_order_fixed(self):
        tags = [va.TAG_VENUE, va.TAG_DRAW, va.TAG_DANGER, va.TAG_SPURT]
        order = {va.TAG_SPURT: 0, va.TAG_DANGER: 1, va.TAG_DRAW: 2, va.TAG_VENUE: 3}
        tags.sort(key=lambda t: order.get(t, 99))
        self.assertEqual(tags, [va.TAG_SPURT, va.TAG_DANGER, va.TAG_DRAW, va.TAG_VENUE])

    def test_format_v_before_tags(self):
        ann = {6: {'name': 'A', 'in_v': True, 'push': True, 'tags': [va.TAG_SPURT]}}
        line = va.format_annotation_lines(ann)[0]
        self.assertLess(line.index('🏆V'), line.index('≫'))
        self.assertLess(line.index('≫'), line.index('🔥末脚'))

    def test_v_outside_horse_with_danger_only(self):
        class TB:
            @staticmethod
            def danger_popular_inner(emp, u, tosu, pop):
                return {'flag': 'x'} if pop == 2 else None

        horses = [{'umaban': 9, 'name': 'B', 'score': 0.5}]
        rows = [{'Umaban': 9, 'Popularity': 2}]
        emp = {'lane_label': '外有利', 'confident': True}
        ann = va.collect_horse_annotations(
            horses, {}, rows, '202606040101', tb_emp=emp,
            track_bias_mod=TB(), v_umaban_set=set())
        self.assertIn(9, ann)
        self.assertFalse(ann[9]['in_v'])
        self.assertIn(va.TAG_DANGER, ann[9]['tags'])

    def test_push_uses_finish_push_delta(self):
        horses = [{'umaban': 1, 'name': 'C', 'score': 0.5}]
        ann = va.collect_horse_annotations(
            horses, {}, [], '202606040101',
            pos4={1: 0.5}, finish={1: 0.2}, v_umaban_set={1})
        self.assertTrue(ann[1]['push'])

    def test_no_recompute_threshold(self):
        horses = [{'umaban': 1, 'name': 'D', 'score': 0.5}]
        rows = [{'Umaban': 1, 'Popularity': 3}]
        prof = {'D': {'agari': 0.9}}
        ann = va.collect_horse_annotations(horses, prof, rows, '202606040101')
        self.assertEqual(ann, {})


if __name__ == '__main__':
    unittest.main()
