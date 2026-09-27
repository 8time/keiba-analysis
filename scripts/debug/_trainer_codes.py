# -*- coding: utf-8 -*-
"""part10: netkeiba 調教師ID と jravan trainer_code の一致確認（オフライン推論用）。

jravan 側: 有名調教師のコードを「その厩舎の有名馬の trainer_code」から逆引き。
netkeiba 側: /trainer/XXXXX/ の ID が JRA 調教師コードと一致するかはライブで要確認。
ここでは jravan 側の有名厩舎コード一覧を出す。
"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

# 有名馬 → trainer_code（2023-2025）
famous = {
    'ドウデュース': '友道康夫', 'イクイノックス': '木村哲也', 'ソダシ': '須貝尚介',
    'タイトルホルダー': '栗田徹', 'スターズオンアース': '高柳瑞樹',
    'リバティアイランド': '中内田充正', 'ジャスティンパレス': '杉山晴紀',
}
for horse, trainer in famous.items():
    r = con.execute(
        "SELECT trainer_code, COUNT(*) FROM results WHERE bamei=? "
        "GROUP BY trainer_code ORDER BY 2 DESC LIMIT 1", (horse,)).fetchone()
    if r:
        print(f'  {horse}（{trainer}）→ trainer_code={r[0]} ({r[1]}走)')
con.close()
