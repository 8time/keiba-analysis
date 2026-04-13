# -*- coding: utf-8 -*-
"""
LightGBM 特徴量重要度算出モジュール
====================================
騎手×コース連対率、騎手×厩舎勝率 等の特徴量が
「着順」や「回収率」にどれだけ影響するかを客観的に算出する。

恣意的なポイント加算を避け、データドリブンでウェイトを決める。
N指数は使用しない。

学習データが不足する場合はデフォルトウェイト（均等配分）を返す。
"""

import os
import json
import sqlite3
import logging
from typing import Dict, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# デフォルトDBパス
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_BASE_DIR, "data", "keiba.db")

# 特徴量カラム定義
FEATURE_COLUMNS = [
    "jockey_course_win_rate",
    "jockey_course_top2_rate",
    "jockey_course_return_win",
    "jockey_trainer_win_rate",
    "jockey_trainer_top2_rate",
    "jockey_trainer_return_win",
    "jockey_horse_win_rate",
    "jockey_horse_ride_count",
    "is_continuous_ride",
    "running_style_match",
    "track_condition_boost",
]


def _default_weights() -> Dict[str, float]:
    """学習データ不足時のデフォルトウェイト（均等配分）"""
    n = len(FEATURE_COLUMNS)
    return {feat: round(1.0 / n, 4) for feat in FEATURE_COLUMNS}


def _init_weights_table(db_path: str):
    """ml_weightsテーブルを初期化する"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ml_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weights_json TEXT NOT NULL,
            target TEXT NOT NULL,
            n_samples INTEGER NOT NULL DEFAULT 0,
            rmse REAL DEFAULT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def save_weights(weights: Dict[str, float], target: str,
                 n_samples: int = 0, rmse: float = None,
                 db_path: str = DEFAULT_DB_PATH):
    """算出したウェイトをDBに保存する"""
    _init_weights_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO ml_weights (weights_json, target, n_samples, rmse)
           VALUES (?, ?, ?, ?)""",
        (json.dumps(weights, ensure_ascii=False), target, n_samples, rmse)
    )
    conn.commit()
    conn.close()
    logger.info(f"[JockeyML] ウェイト保存完了: target={target}, n={n_samples}")


def get_weights(db_path: str = DEFAULT_DB_PATH) -> Dict[str, float]:
    """
    保存済みウェイトを取得する。なければデフォルトを返す。

    Returns:
        {feature_name: importance_score} 合計≒1.0
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT weights_json FROM ml_weights ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row["weights_json"])
    except Exception as e:
        logger.debug(f"[JockeyML] ウェイト読み込みエラー: {e}")
    return _default_weights()


def prepare_training_data(db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """
    jockey_statsテーブルから疑似的な学習データを生成する。

    race_resultsテーブルが存在しないため、
    jockey_stats内のcourse/trainer/horse各レコードを結合し、
    return_winを目的変数として擬似的な学習データを構築する。

    Returns:
        DataFrame: 特徴量＋目的変数(y)を含むデータ
    """
    conn = sqlite3.connect(db_path)
    try:
        # コース成績を主テーブルとして使用
        df_course = pd.read_sql_query(
            """SELECT jockey_id, jockey_name, target_name,
                      win_rate, top2_rate, top3_rate,
                      return_win, return_place, ride_count
               FROM jockey_stats
               WHERE target_type = 'course' AND ride_count >= 5""",
            conn
        )
        if df_course.empty:
            return pd.DataFrame()

        # 同一騎手の厩舎平均成績を結合
        df_trainer_avg = pd.read_sql_query(
            """SELECT jockey_id,
                      AVG(win_rate) as trainer_avg_win_rate,
                      AVG(top2_rate) as trainer_avg_top2_rate,
                      AVG(return_win) as trainer_avg_return_win,
                      SUM(ride_count) as trainer_total_rides
               FROM jockey_stats
               WHERE target_type = 'trainer' AND ride_count >= 3
               GROUP BY jockey_id""",
            conn
        )

        # 同一騎手の馬別平均成績を結合
        df_horse_avg = pd.read_sql_query(
            """SELECT jockey_id,
                      AVG(win_rate) as horse_avg_win_rate,
                      COUNT(*) as horse_variety_count,
                      SUM(ride_count) as horse_total_rides
               FROM jockey_stats
               WHERE target_type = 'horse' AND ride_count >= 2
               GROUP BY jockey_id""",
            conn
        )

        # 結合
        df = df_course.copy()
        df = df.rename(columns={
            "win_rate": "jockey_course_win_rate",
            "top2_rate": "jockey_course_top2_rate",
            "return_win": "jockey_course_return_win",
        })

        if not df_trainer_avg.empty:
            df = df.merge(df_trainer_avg, on="jockey_id", how="left")
            df = df.rename(columns={
                "trainer_avg_win_rate": "jockey_trainer_win_rate",
                "trainer_avg_top2_rate": "jockey_trainer_top2_rate",
                "trainer_avg_return_win": "jockey_trainer_return_win",
            })
        else:
            df["jockey_trainer_win_rate"] = 0.0
            df["jockey_trainer_top2_rate"] = 0.0
            df["jockey_trainer_return_win"] = 0.0

        if not df_horse_avg.empty:
            df = df.merge(df_horse_avg, on="jockey_id", how="left")
            df = df.rename(columns={
                "horse_avg_win_rate": "jockey_horse_win_rate",
                "horse_total_rides": "jockey_horse_ride_count",
            })
        else:
            df["jockey_horse_win_rate"] = 0.0
            df["jockey_horse_ride_count"] = 0

        # 簡易フラグ（データ不足時はゼロ埋め）
        df["is_continuous_ride"] = 0
        df["running_style_match"] = 0
        df["track_condition_boost"] = 0

        # 目的変数
        df["y"] = df["jockey_course_return_win"]

        return df.fillna(0)

    except Exception as e:
        logger.error(f"[JockeyML] 学習データ生成エラー: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def train_weights(target: str = "return_win",
                  db_path: str = DEFAULT_DB_PATH) -> Dict[str, float]:
    """
    LightGBMで学習し、特徴量重要度を返す。

    学習データが100件未満の場合はデフォルトウェイトを返す。

    Args:
        target: 目的変数名（現在は"return_win"のみサポート）
        db_path: SQLiteデータベースパス

    Returns:
        {feature_name: importance_score} 重要度が高い順
    """
    try:
        import lightgbm as lgb
        from sklearn.model_selection import KFold
    except ImportError as e:
        logger.error(f"[JockeyML] LightGBM/sklearn未インストール: {e}")
        logger.error("  pip install lightgbm scikit-learn でインストールしてください")
        return _default_weights()

    df = prepare_training_data(db_path)
    if df.empty or len(df) < 30:
        logger.warning(f"[JockeyML] 学習データ不足（{len(df)}件）。デフォルトウェイトを使用。")
        weights = _default_weights()
        save_weights(weights, target, n_samples=len(df), db_path=db_path)
        return weights

    # 利用可能な特徴量だけ抽出
    available_features = [c for c in FEATURE_COLUMNS if c in df.columns]
    if not available_features:
        logger.warning("[JockeyML] 利用可能な特徴量がありません。")
        return _default_weights()

    X = df[available_features].values
    y = df["y"].values

    params = {
        "objective": "regression",
        "metric": "rmse",
        "verbosity": -1,
        "num_leaves": 15,
        "learning_rate": 0.05,
        "n_estimators": 100,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_samples": 5,
    }

    # KFold交差検証
    kf = KFold(n_splits=min(3, len(df) // 10 + 1), shuffle=True, random_state=42)
    importances = []
    rmse_scores = []

    for train_idx, val_idx in kf.split(X):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]

        model = lgb.LGBMRegressor(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
        )
        importances.append(model.feature_importances_)

        # RMSE計算
        preds = model.predict(X_val)
        rmse = float(np.sqrt(np.mean((y_val - preds) ** 2)))
        rmse_scores.append(rmse)

    # 平均重要度を算出
    avg_importance = np.mean(importances, axis=0)
    avg_rmse = float(np.mean(rmse_scores))

    # 正規化（合計1.0）
    total = float(np.sum(avg_importance))
    if total > 0:
        normalized = avg_importance / total
    else:
        normalized = np.ones(len(available_features)) / len(available_features)

    weights = {feat: round(float(w), 4) for feat, w in zip(available_features, normalized)}

    # 重要度順ソート
    weights = dict(sorted(weights.items(), key=lambda x: -x[1]))

    # DB保存
    save_weights(weights, target, n_samples=len(df), rmse=avg_rmse, db_path=db_path)

    logger.info(f"[JockeyML] ウェイト算出完了: n={len(df)}, RMSE={avg_rmse:.2f}")
    logger.info(f"[JockeyML] Top特徴量: {list(weights.items())[:3]}")

    return weights
