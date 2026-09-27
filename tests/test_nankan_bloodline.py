# -*- coding: utf-8 -*-
"""nankankeiba 馬情報 → SRA血統列の配線テスト（ネット不要）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.nankan_scraper import fill_bloodline_from_nankan


class NankanBloodlineTests(unittest.TestCase):
    def test_fill_from_enriched_dict(self):
        df = pd.DataFrame([{
            'Name': 'トウキョーバサラ', 'Umaban': 1,
            'sire': '-', 'broodmareSire': '-', 'Bloodline': '-',
        }])
        n = fill_bloodline_from_nankan(df, enriched={
            'トウキョーバサラ': {
                'sire': 'フリオーソ',
                'dam': 'マイルズアハード',
                'dam_sire': 'ロージズインメイ',
                'horse_id': '2021107324',
            }
        })
        self.assertEqual(n, 1)
        self.assertEqual(df.loc[0, 'sire'], 'フリオーソ')
        self.assertEqual(df.loc[0, 'broodmareSire'], 'ロージズインメイ')
        self.assertEqual(df.loc[0, 'Bloodline'], 'フリオーソ / ロージズインメイ')

    def test_fill_skips_empty_enriched(self):
        df = pd.DataFrame([{
            'Name': '不明馬', 'Umaban': 2, 'HorseId': '',
            'sire': '-', 'broodmareSire': '-',
        }])
        n = fill_bloodline_from_nankan(df, enriched={})
        self.assertEqual(n, 0)
        self.assertEqual(df.loc[0, 'sire'], '-')


if __name__ == '__main__':
    unittest.main()
