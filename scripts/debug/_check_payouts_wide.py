# -*- coding: utf-8 -*-
"""payouts テーブルの券種カバレッジ確認"""
import sys
import sqlite3

sys.path.insert(0, r"C:\Users\kimnhaty\.gemini\antigravity\scratch\keiba_analysis")
from core import jockey_jv as jj

print("DB:", jj.JV_DB_PATH)
con = sqlite3.connect(f"file:{jj.JV_DB_PATH}?mode=ro", uri=True)
print("--- bet_type 別件数 ---")
for bt, n in con.execute("SELECT bet_type, COUNT(*) FROM payouts GROUP BY bet_type ORDER BY 2 DESC"):
    print(f"{bt}: {n:,}")
print("--- ワイド sample ---")
for row in con.execute("SELECT race_key, combo, payout FROM payouts WHERE bet_type='ワイド' LIMIT 5"):
    print(row)
print("--- ワイドの1レース分(複数combo払戻の確認) ---")
rk = con.execute("SELECT race_key FROM payouts WHERE bet_type='ワイド' LIMIT 1").fetchone()[0]
for row in con.execute("SELECT combo, payout FROM payouts WHERE bet_type='ワイド' AND race_key=?", (rk,)):
    print(rk, row)
con.close()
