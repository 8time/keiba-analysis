# -*- coding: utf-8 -*-
"""Phase 2 ユニットテスト"""
import os
import sys

print("=== Phase 2 モジュールインポートテスト ===")

# 1. jockey_scraper
from utils.jockey_scraper import JockeyScraper, TOP_JOCKEYS
print(f"  jockey_scraper: OK (TOP_JOCKEYS={len(TOP_JOCKEYS)}名)")
scraper = JockeyScraper(interval=0)
assert len(TOP_JOCKEYS) >= 20

# 2. jockey_ml
from utils.jockey_ml import train_weights, get_weights, _default_weights, prepare_training_data
print(f"  jockey_ml: OK")
dw = _default_weights()
assert abs(sum(dw.values()) - 1.0) < 0.01
print(f"  デフォルトウェイト合計: {sum(dw.values()):.4f}")

# 3. jockey_track_condition
from utils.jockey_track_condition import (
    TrackCondition, fetch_track_conditions,
    get_condition_for_venue, fetch_track_conditions_jra
)
print(f"  jockey_track_condition: OK")

# TrackCondition テスト
tc = TrackCondition(venue="東京", surface="芝", condition="良", updated_at="2025-01-01")
assert tc.venue == "東京"
assert tc.condition == "良"

# get_condition_for_venue テスト
conditions = [
    TrackCondition(venue="東京", surface="芝", condition="良", updated_at="now"),
    TrackCondition(venue="中山", surface="ダート", condition="重", updated_at="now"),
]
assert get_condition_for_venue(conditions, "東京") == "良"
assert get_condition_for_venue(conditions, "中山") == "重"
assert get_condition_for_venue(conditions, "阪神") is None
assert get_condition_for_venue(conditions, "東京", "芝") == "良"
print(f"  get_condition_for_venue: OK")

# 4. jockey_batch スクリプトの存在確認
batch_path = os.path.join("scripts", "jockey_batch.py")
assert os.path.exists(batch_path)
print(f"  jockey_batch.py: OK (存在確認)")

print()
print("=== LightGBM学習テスト（DB空の場合） ===")
# DB空の場合はデフォルトウェイトが返る
test_db = os.path.join("data", "test_phase2.db")
from utils.jockey_stats_db import JockeyStatsDB
db = JockeyStatsDB(test_db)
db.init_table()
weights = get_weights(db_path=test_db)
print(f"  空DB時ウェイト: {len(weights)}個")
assert len(weights) > 0

# テストデータを挿入して学習テスト
import random
records = []
for jid in ["01", "02", "03", "04", "05"]:
    for venue in ["東京", "中山", "阪神", "京都", "新潟", "小倉", "中京"]:
        records.append({
            "jockey_id": jid, "jockey_name": f"J{jid}",
            "target_type": "course", "target_id": venue, "target_name": venue,
            "ride_count": random.randint(20, 100),
            "win_count": random.randint(2, 15),
            "top2_count": random.randint(5, 25),
            "top3_count": random.randint(8, 35),
            "win_rate": random.uniform(0.05, 0.25),
            "top2_rate": random.uniform(0.15, 0.45),
            "top3_rate": random.uniform(0.25, 0.60),
            "return_win": random.uniform(50, 180),
            "return_place": random.uniform(60, 120),
        })
    for trainer in ["T1", "T2", "T3"]:
        records.append({
            "jockey_id": jid, "jockey_name": f"J{jid}",
            "target_type": "trainer", "target_id": trainer, "target_name": trainer,
            "ride_count": random.randint(10, 50),
            "win_count": random.randint(1, 10),
            "top2_count": random.randint(3, 15),
            "top3_count": random.randint(5, 20),
            "win_rate": random.uniform(0.05, 0.25),
            "top2_rate": random.uniform(0.15, 0.45),
            "top3_rate": random.uniform(0.25, 0.60),
            "return_win": random.uniform(50, 180),
            "return_place": random.uniform(60, 120),
        })

db.upsert(records)
print(f"  テストデータ挿入: {len(records)}件")

# 学習実行
weights = train_weights(target="return_win", db_path=test_db)
print(f"  学習後ウェイト: {len(weights)}個")
for k, v in list(weights.items())[:3]:
    print(f"    {k}: {v:.4f}")
assert len(weights) > 0
assert abs(sum(weights.values()) - 1.0) < 0.05

# 保存されたウェイトを読み込み
saved = get_weights(db_path=test_db)
assert len(saved) > 0
print(f"  保存ウェイト読み込み: OK ({len(saved)}個)")

# クリーンアップ
os.remove(test_db)
print()
print("ALL PHASE 2 TESTS PASSED!")
