# -*- coding: utf-8 -*-
"""騎手分析Pro ユニットテスト"""
import os
import sys

print("=== ベイズ補正テスト ===")
from utils.jockey_bayesian import bayesian_adjusted_rate

r1 = bayesian_adjusted_rate(1.0, 3, 0.16, 20)
print(f"  3回100% -> {r1:.4f} (期待: ~0.27)")
assert 0.25 < r1 < 0.30

r2 = bayesian_adjusted_rate(0.40, 100, 0.16, 20)
print(f"  100回40% -> {r2:.4f} (期待: ~0.36)")
assert 0.35 < r2 < 0.40

r3 = bayesian_adjusted_rate(0.50, 0, 0.16, 20)
print(f"  0回 -> {r3:.4f} (期待: 0.16)")
assert r3 == 0.16

print()
print("=== スクリーニングテスト ===")
from utils.jockey_screening import screen_entry

r = screen_entry(0.45, 35, 110, 0.30, 20, 90)
print(f"  鉄板テスト: {r.label} ({r.reason})")
assert r.flag == "iron"

r = screen_entry(0.20, 20, 150, 0.15, 10, 80)
print(f"  妙味テスト: {r.label} ({r.reason})")
assert r.flag == "value"

r = screen_entry(0.10, 15, 80, 0.20, 10, 90, popularity=2)
print(f"  危険テスト: {r.label} ({r.reason})")
assert r.flag == "danger"

r = screen_entry(0.10, 30, 80, 0.50, 30, 90, popularity=1)
print(f"  危険優先テスト: {r.label} ({r.reason})")
assert r.flag == "danger"

r = screen_entry(0.15, 10, 80, 0.15, 10, 80)
print(f"  フラグなしテスト: flag={r.flag}")
assert r.flag is None

# カスタム閾値テスト
custom_th = {"iron_top2_rate": 0.30, "iron_min_rides": 20, "value_return_win": 100.0, "value_min_rides": 10, "danger_top2_rate": 0.20, "danger_min_rides": 5, "danger_max_popularity": 3}
r = screen_entry(0.35, 25, 80, 0.20, 10, 80, thresholds=custom_th)
print(f"  カスタム閾値テスト: {r.label} ({r.reason})")
assert r.flag == "iron"

print()
print("=== DB操作テスト ===")
from utils.jockey_stats_db import JockeyStatsDB

test_db_path = os.path.join(os.getcwd(), "data", "test_jockey.db")
db = JockeyStatsDB(test_db_path)
db.init_table()
print("  テーブル作成: OK")
assert db.table_exists()

records = [
    {"jockey_id": "01170", "jockey_name": "ルメール", "target_type": "course",
     "target_id": "05-1600", "target_name": "東京芝1600",
     "ride_count": 50, "win_count": 15, "top2_count": 25, "top3_count": 30,
     "win_rate": 0.30, "top2_rate": 0.50, "top3_rate": 0.60,
     "return_win": 130, "return_place": 95},
    {"jockey_id": "01088", "jockey_name": "川田将雅", "target_type": "course",
     "target_id": "05-1600", "target_name": "東京芝1600",
     "ride_count": 30, "win_count": 8, "top2_count": 12, "top3_count": 18,
     "win_rate": 0.267, "top2_rate": 0.40, "top3_rate": 0.60,
     "return_win": 110, "return_place": 88},
    {"jockey_id": "01170", "jockey_name": "ルメール", "target_type": "trainer",
     "target_id": "T001", "target_name": "国枝栄",
     "ride_count": 40, "win_count": 12, "top2_count": 20, "top3_count": 28,
     "win_rate": 0.30, "top2_rate": 0.50, "top3_rate": 0.70,
     "return_win": 145, "return_place": 100},
]
count = db.upsert(records)
print(f"  upsert {count}件: OK")

df = db.query_by_jockey("ルメール")
print(f"  query ルメール (全): {len(df)}件")
assert len(df) == 2

df = db.query_by_jockey("ルメール", "course")
print(f"  query ルメール (course): {len(df)}件")
assert len(df) == 1

df = db.query_by_target("course", min_rides=20)
print(f"  query course min20: {len(df)}件")
assert len(df) == 2

df = db.query_combo("ルメール", "trainer", "国枝")
print(f"  query combo ルメール×国枝: {len(df)}件")
assert len(df) == 1

avgs = db.get_global_averages()
print(f"  平均連対率: {avgs['avg_top2_rate']:.3f}")
assert avgs["avg_top2_rate"] > 0

rc = db.get_record_count()
print(f"  レコード数: {rc}")
assert rc == 3

os.remove(test_db_path)
print()
print("ALL TESTS PASSED!")
