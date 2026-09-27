# -*- coding: utf-8 -*-
"""part8: 調教師 名→コードの橋渡し可否 + 新馬戦での resolve_horse 挙動確認。"""
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
DB = os.path.join(ROOT, 'data', 'jravan.db')
con = sqlite3.connect(DB)

print('=== テーブル一覧 ===')
for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(' ', t)

print()
print('=== 調教師コード→名 の対応を results から作れるか ===')
# results に trainer_name は無い(trainer_code のみ)。races 側にも無いか確認
cols_r = [c[1] for c in con.execute('PRAGMA table_info(races)')]
print('races cols:', [c for c in cols_r if 'tr' in c.lower() or 'chok' in c.lower()])

# 直近の新馬(2026)で resolve_horse が効くか
from core import jockey_jv as jj
con.close()

print()
print('=== resolve_horse: 2026年新馬デビュー馬で試行 ===')
q_db = sqlite3.connect(DB)
maiden_names = [r[0] for r in q_db.execute(
    "SELECT DISTINCT rs.bamei FROM results rs JOIN races ra ON ra.race_key=rs.race_key "
    "WHERE ra.year='2026' AND ra.shubetsu='11' LIMIT 5")]
for nm in maiden_names:
    kt, tc = jj.resolve_horse(nm)
    print(f'  {nm}: ketto={kt}, trainer_code={tc}')
q_db.close()
