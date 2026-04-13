# -*- coding: utf-8 -*-
"""
騎手成績DB操作モジュール（CRUD）
================================
jockey_stats テーブルへの読み書きを行う。
DBが存在しない場合は SQLite で data/keiba.db に新規作成する。

N指数は使用しない。
"""

import os
import sqlite3
import logging
from typing import List, Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)

# デフォルトDBパス（プロジェクトルートからの相対パス）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_BASE_DIR, "data", "keiba.db")

# テーブル作成SQL
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jockey_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jockey_id TEXT NOT NULL,
    jockey_name TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('course', 'trainer', 'horse')),
    target_id TEXT NOT NULL,
    target_name TEXT NOT NULL,
    ride_count INTEGER NOT NULL DEFAULT 0,
    win_count INTEGER NOT NULL DEFAULT 0,
    top2_count INTEGER NOT NULL DEFAULT 0,
    top3_count INTEGER NOT NULL DEFAULT 0,
    win_rate REAL NOT NULL DEFAULT 0.0,
    top2_rate REAL NOT NULL DEFAULT 0.0,
    top3_rate REAL NOT NULL DEFAULT 0.0,
    return_win REAL NOT NULL DEFAULT 0.0,
    return_place REAL NOT NULL DEFAULT 0.0,
    running_style TEXT DEFAULT NULL,
    track_condition TEXT DEFAULT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(jockey_id, target_type, target_id, running_style, track_condition)
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_jockey_target ON jockey_stats(jockey_id, target_type);",
    "CREATE INDEX IF NOT EXISTS idx_target ON jockey_stats(target_type, target_id);",
]


class JockeyStatsDB:
    """騎手成績DBのCRUD操作クラス"""

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: SQLiteデータベースのパス。Noneの場合はデフォルトパスを使用。
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        # dataディレクトリが存在しない場合は作成
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """DB接続を取得する（UTF-8対応）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def init_table(self) -> bool:
        """
        jockey_statsテーブルを初期化する（CREATE TABLE IF NOT EXISTS）。

        Returns:
            True: 成功
        """
        try:
            conn = self._get_conn()
            conn.execute(CREATE_TABLE_SQL)
            for idx_sql in CREATE_INDEX_SQL:
                conn.execute(idx_sql)
            conn.commit()
            conn.close()
            logger.info(f"[JockeyStatsDB] テーブル初期化完了: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"[JockeyStatsDB] テーブル初期化エラー: {e}")
            raise

    def upsert(self, records: List[Dict[str, Any]]) -> int:
        """
        レコードをINSERT OR REPLACEする。

        Args:
            records: 辞書のリスト。各辞書のキーはテーブルカラム名に対応。

        Returns:
            挿入/更新されたレコード数
        """
        if not records:
            return 0

        sql = """
        INSERT OR REPLACE INTO jockey_stats
        (jockey_id, jockey_name, target_type, target_id, target_name,
         ride_count, win_count, top2_count, top3_count,
         win_rate, top2_rate, top3_rate, return_win, return_place,
         running_style, track_condition, updated_at)
        VALUES
        (:jockey_id, :jockey_name, :target_type, :target_id, :target_name,
         :ride_count, :win_count, :top2_count, :top3_count,
         :win_rate, :top2_rate, :top3_rate, :return_win, :return_place,
         :running_style, :track_condition, datetime('now'))
        """

        conn = self._get_conn()
        count = 0
        try:
            for rec in records:
                # デフォルト値を補完
                params = {
                    "jockey_id": rec.get("jockey_id", ""),
                    "jockey_name": rec.get("jockey_name", ""),
                    "target_type": rec.get("target_type", "course"),
                    "target_id": rec.get("target_id", ""),
                    "target_name": rec.get("target_name", ""),
                    "ride_count": rec.get("ride_count", 0),
                    "win_count": rec.get("win_count", 0),
                    "top2_count": rec.get("top2_count", 0),
                    "top3_count": rec.get("top3_count", 0),
                    "win_rate": rec.get("win_rate", 0.0),
                    "top2_rate": rec.get("top2_rate", 0.0),
                    "top3_rate": rec.get("top3_rate", 0.0),
                    "return_win": rec.get("return_win", 0.0),
                    "return_place": rec.get("return_place", 0.0),
                    "running_style": rec.get("running_style"),
                    "track_condition": rec.get("track_condition"),
                }
                conn.execute(sql, params)
                count += 1
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[JockeyStatsDB] upsertエラー: {e}")
            raise
        finally:
            conn.close()

        logger.info(f"[JockeyStatsDB] {count}件 upsert完了")
        return count

    def query_by_jockey(
        self,
        jockey_name: str,
        target_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        騎手名でレコードを検索する（部分一致）。

        Args:
            jockey_name: 騎手名（部分一致検索）
            target_type: 'course' / 'trainer' / 'horse'（Noneなら全て）

        Returns:
            DataFrame
        """
        conn = self._get_conn()
        try:
            if target_type:
                sql = """
                SELECT * FROM jockey_stats
                WHERE jockey_name LIKE ? AND target_type = ?
                ORDER BY ride_count DESC
                """
                df = pd.read_sql_query(sql, conn, params=[f"%{jockey_name}%", target_type])
            else:
                sql = """
                SELECT * FROM jockey_stats
                WHERE jockey_name LIKE ?
                ORDER BY target_type, ride_count DESC
                """
                df = pd.read_sql_query(sql, conn, params=[f"%{jockey_name}%"])
            return df
        finally:
            conn.close()

    def query_by_target(
        self,
        target_type: str,
        target_name: Optional[str] = None,
        min_rides: int = 0,
    ) -> pd.DataFrame:
        """
        ターゲットタイプ（course/trainer/horse）でレコードを検索する。

        Args:
            target_type: 'course' / 'trainer' / 'horse'
            target_name: ターゲット名（部分一致、Noneなら全て）
            min_rides: 最低騎乗回数フィルタ

        Returns:
            DataFrame
        """
        conn = self._get_conn()
        try:
            if target_name:
                sql = """
                SELECT * FROM jockey_stats
                WHERE target_type = ? AND target_name LIKE ? AND ride_count >= ?
                ORDER BY ride_count DESC
                """
                df = pd.read_sql_query(
                    sql, conn, params=[target_type, f"%{target_name}%", min_rides]
                )
            else:
                sql = """
                SELECT * FROM jockey_stats
                WHERE target_type = ? AND ride_count >= ?
                ORDER BY ride_count DESC
                """
                df = pd.read_sql_query(sql, conn, params=[target_type, min_rides])
            return df
        finally:
            conn.close()

    def query_combo(
        self,
        jockey_name: str,
        target_type: str,
        target_name: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        騎手×ターゲットのコンビネーションを検索する。

        Args:
            jockey_name: 騎手名（部分一致）
            target_type: 'course' / 'trainer' / 'horse'
            target_name: ターゲット名（部分一致、Noneなら全て）

        Returns:
            DataFrame
        """
        conn = self._get_conn()
        try:
            if target_name:
                sql = """
                SELECT * FROM jockey_stats
                WHERE jockey_name LIKE ? AND target_type = ? AND target_name LIKE ?
                ORDER BY ride_count DESC
                """
                df = pd.read_sql_query(
                    sql, conn, params=[f"%{jockey_name}%", target_type, f"%{target_name}%"]
                )
            else:
                sql = """
                SELECT * FROM jockey_stats
                WHERE jockey_name LIKE ? AND target_type = ?
                ORDER BY ride_count DESC
                """
                df = pd.read_sql_query(sql, conn, params=[f"%{jockey_name}%", target_type])
            return df
        finally:
            conn.close()

    def get_global_averages(self) -> Dict[str, float]:
        """
        全レコードの平均値を算出する（ベイズ補正の事前分布として使用）。

        Returns:
            {
                'avg_win_rate': float,
                'avg_top2_rate': float,
                'avg_top3_rate': float,
                'avg_return_win': float,
                'avg_return_place': float,
            }
        """
        conn = self._get_conn()
        try:
            sql = """
            SELECT
                AVG(win_rate) as avg_win_rate,
                AVG(top2_rate) as avg_top2_rate,
                AVG(top3_rate) as avg_top3_rate,
                AVG(return_win) as avg_return_win,
                AVG(return_place) as avg_return_place
            FROM jockey_stats
            WHERE ride_count >= 5
            """
            row = conn.execute(sql).fetchone()
            if row and row["avg_win_rate"] is not None:
                return {
                    "avg_win_rate": row["avg_win_rate"],
                    "avg_top2_rate": row["avg_top2_rate"],
                    "avg_top3_rate": row["avg_top3_rate"],
                    "avg_return_win": row["avg_return_win"],
                    "avg_return_place": row["avg_return_place"],
                }
            # DBが空の場合はJRA平均的な値を返す
            return {
                "avg_win_rate": 0.08,
                "avg_top2_rate": 0.16,
                "avg_top3_rate": 0.24,
                "avg_return_win": 80.0,
                "avg_return_place": 80.0,
            }
        finally:
            conn.close()

    def import_csv(self, df: pd.DataFrame) -> int:
        """
        CSVから読み込んだDataFrameをDBにインポートする。

        Args:
            df: カラム名がテーブルカラムに対応するDataFrame

        Returns:
            インポートされたレコード数
        """
        records = df.to_dict("records")
        return self.upsert(records)

    def get_record_count(self) -> int:
        """テーブル内のレコード数を取得する。"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM jockey_stats").fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def table_exists(self) -> bool:
        """jockey_statsテーブルが存在するかチェックする。"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jockey_stats'"
            ).fetchone()
            return row is not None
        except Exception:
            return False
        finally:
            conn.close()
