import os
import sqlite3
import pandas as pd
from datetime import datetime
import sys

# パス設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from core.magi_trainer import load_kaggle_data

DB_PATH = os.path.join(BASE_DIR, "data", "bloodline.db")

def create_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 馬テーブル（再帰ツリーベース）
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS horses (
        horse_id TEXT PRIMARY KEY,
        name TEXT,
        sire_id TEXT,    -- 父
        dam_id TEXT,     -- 母
        scraped INTEGER DEFAULT 0, -- 0:未取得, 1:取得済
        last_updated TIMESTAMP
    )
    ''')
    
    # 血統特徴量キャッシュテーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bloodline_features (
        horse_id TEXT PRIMARY KEY,
        inbreeding_coeff REAL, -- F係数
        dosage_index REAL,     -- ドサージュDI
        dosage_profile TEXT,   -- DP (例: 1-2-3-0-0)
        last_calculated TIMESTAMP
    )
    ''')
    
    conn.commit()
    return conn

def import_from_kaggle(conn):
    print("Kaggleデータから初期の馬IDベクトルを抽出しています...")
    dfs = load_kaggle_data()
    if not dfs or 'results' not in dfs:
        print("Kaggleデータが見つかりません。")
        return
        
    df_results = dfs['results']
    if 'horse_id' not in df_results.columns:
        print("データに 'horse_id' が存在しません。")
        return
        
    # ユニークな馬リストを作成
    unique_horses = df_results[['horse_id', 'horse_name']].drop_duplicates(subset=['horse_id'])
    
    cursor = conn.cursor()
    count = 0
    
    for _, row in unique_horses.iterrows():
        # ON CONFLICT DO NOTHING で新規追加のみ行う
        cursor.execute('''
        INSERT INTO horses (horse_id, name, last_updated) 
        VALUES (?, ?, ?)
        ON CONFLICT(horse_id) DO NOTHING
        ''', (str(row['horse_id']), row['horse_name'], datetime.now().isoformat()))
        count += cursor.rowcount
        
    conn.commit()
    print(f"✅ Kaggleから新規に {count} 頭の馬のID・名前をデータベースに登録しました！")
    print(f"現在、総計 {len(unique_horses)} 頭が登録されています。")

def main():
    print("=== 血統再帰グラフDB 初期化スクリプト ===")
    conn = create_db()
    import_from_kaggle(conn)
    conn.close()
    
    print("\n【次のステップ案】")
    print("1. 未収集(scraped=0)の馬IDを対象に、netkeiba等の血統ページから sire_id (父) と dam_id (母) をスクレイピングするスクリプトを回す。")
    print("   ※親が見つかれば horses テーブルに随時追加。")
    print("2. WITH RECURSIVE を使った再帰クエリで、任意の馬から5代前までを一瞬で取得する関数を作る。")
    print("3. F係数やDosageを計算する関数を作り、bloodline_features にキャッシュする。")

if __name__ == '__main__':
    main()
