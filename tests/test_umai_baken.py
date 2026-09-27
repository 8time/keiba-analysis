# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import umai_baken as ub


LIST_HTML = '''
<html><body>
<a href="https://yoso.netkeiba.com/?pid=yoso_detail&id=6076267">予想をみる</a>
<a href="/?id=6051613&pid=yoso_detail">予想をみる</a>
</body></html>
'''

DETAIL_HTML = '''
<html><body>
<table>
<tr><th>券種・買い目</th><th>組み合わせ・点数</th></tr>
<tr><td>3連複(通常)</td><td>5 - 7 - 12 4,000円</td></tr>
<tr><td>3連複(通常)</td><td>7 - 11 - 12 3,000円 的中</td></tr>
<tr><td>3連複(通常)</td><td>7 - 8 - 12 3,000円</td></tr>
<tr><td>合計</td><td>10,000円</td></tr>
</table>
<table>
<tr><th>払い戻し金額</th><th>収支</th></tr>
<tr><td>68,100円</td><td>+58,100円</td></tr>
</table>
</body></html>
'''

NAGASHI_HTML = '''
<html><body>
<table>
<tr><th>券種・買い目</th><th>組み合わせ・点数</th></tr>
<tr><td>馬連(流し)</td><td>軸 2 相手 9 10 2通り 各1,000円</td></tr>
<tr><td>ワイド(通常)</td><td>2−12 1,500円</td></tr>
<tr><td>合計</td><td>3,500円</td></tr>
</table>
<p>払い戻し金額 0円 収支 -3,500円</p>
</body></html>
'''


class UmaiBakenTest(unittest.TestCase):
    def test_extract_ids(self):
        self.assertEqual(ub.extract_yoso_ids(LIST_HTML), ['6076267', '6051613'])

    def test_parse_trio_box(self):
        p = ub.parse_detail_tickets(DETAIL_HTML)
        self.assertEqual(len(p['tickets']), 3)
        self.assertEqual(p['tickets'][0]['kind'], '3連複')
        self.assertEqual(p['tickets'][0]['style'], '通常')
        self.assertEqual(p['total_stake'], 10000)
        self.assertEqual(p['payout'], 68100)
        self.assertEqual(p['pl'], 58100)
        rec = ub.shape_record('202606040206', '1', p)
        self.assertTrue(rec['hit'])
        self.assertEqual(rec['n_points'], 3)
        self.assertIn('3連複', rec['app_near'])

    def test_parse_nagashi(self):
        p = ub.parse_detail_tickets(NAGASHI_HTML)
        kinds = {t['kind'] for t in p['tickets']}
        self.assertEqual(kinds, {'馬連', 'ワイド'})
        self.assertEqual(p['tickets'][0]['n_points'], 2)
        rec = ub.shape_record('x', '2', p)
        self.assertIn('対連', rec['app_near'])

    def test_nearest_app(self):
        self.assertIn('D寄り', ub.nearest_app_playbook(['3連複'], ['通常'], 2))
        self.assertIn('Cクロス多', ub.nearest_app_playbook(['3連複'], ['通常'], 10))
        self.assertIn('Cクロス少', ub.nearest_app_playbook(['3連単'], ['通常'], 30))


if __name__ == '__main__':
    unittest.main()
