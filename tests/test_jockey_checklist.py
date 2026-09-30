"""画像の主張と馬券判断を混同しない参考表示のガード。"""
import copy
import unittest

from core import jockey_checklist as jc


class ChecklistTests(unittest.TestCase):
    def test_full_catalogue(self):
        rows = jc.catalogue()
        self.assertEqual(len(rows), 35)
        self.assertEqual([r['番号'] for r in rows], list(range(1, 36)))
        self.assertTrue(all('画像の主張' in r for r in rows))

    def test_explicit_abbreviations_and_decorations(self):
        for name in ('岩田望', '岩田望来', '☆岩田望'):
            self.assertEqual(jc.lookup(name)['label'], '岩田（息子）')
        self.assertEqual(jc.lookup('Ｃ．ルメール')['label'], 'ルメール')
        self.assertEqual(jc.lookup('丹内祐次')['label'], '丹内')
        self.assertEqual(jc.lookup('横山和')['label'], 'カズオ')

    def test_no_guessing_ambiguous_names(self):
        for name in ('岩田', '横山', '北村', '北村宏司', '北村友一', '吉村',
                     '西村', '石川', '角田', '菅原', '荻野', '小牧', '田山', '', None):
            with self.subTest(name=name):
                self.assertIsNone(jc.lookup(name))
        self.assertIsNone(jc.lookup('小牧太'))
        self.assertIsNotNone(jc.lookup('小牧加矢太'))
        self.assertIsNone(jc.lookup('鮫島良太'))

    def test_image_opinion_is_not_current_race_recommendation(self):
        text = jc.display_text('松山弘平')
        self.assertIn('画像×', text)
        self.assertIn('未検証', text)
        self.assertIn('条件未判定', text)
        self.assertIn('既存検証で不採用', jc.display_text('池添謙一'))

    def test_j5_compact_display(self):
        self.assertEqual(
            jc.display_text('岩田望来', for_j5=True),
            '◎：人気していたら全部軸（阪神・京都・中京）。【未検証・条件未判定】')
        self.assertEqual(jc.display_text('北村', for_j5=True), '')
        self.assertEqual(jc.display_text('画像にない騎手', for_j5=True), '')
        self.assertTrue(jc.display_text('岩田望来').startswith('画像◎：'))

    def test_input_unchanged_and_no_score_output(self):
        records = [dict(Umaban=1, Name='試験馬', Jockey='松若',
                        Waku=1, Popularity=1, **{'Projected Score': 123})]
        original = copy.deepcopy(records)
        result = jc.race_rows(records)
        self.assertEqual(records, original)
        self.assertEqual(result[0]['馬番'], 1)
        self.assertIn('8枠', result[0]['騎手チェック表'])
        self.assertIn('条件未判定', result[0]['騎手チェック表'])
        self.assertNotIn('score', result[0])
        self.assertNotIn('Projected Score', result[0])


if __name__ == '__main__':
    unittest.main()
