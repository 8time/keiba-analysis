# -*- coding: utf-8 -*-
"""
フラグ判定ロジック（スクリーニングエンジン）
============================================
騎手×コース・騎手×厩舎の実績データから、
鉄板 / 妙味 / 危険 の3フラグを自動判定する。

N指数は使用しない。回収率・連対率ベースのスクリーニング。

優先順位: 危険(最優先) > 鉄板 > 妙味
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScreeningResult:
    """スクリーニング判定結果"""

    flag: Optional[str]  # "iron" / "value" / "danger" / None
    label: str  # "🔴 鉄板" / "🟡 妙味" / "🔵 危険" / ""
    reason: str  # 判定理由テキスト
    detail: dict = field(default_factory=dict)  # 詳細数値（展開表示用）


# デフォルト閾値（設定タブから変更可能）
DEFAULT_THRESHOLDS = {
    "iron_top2_rate": 0.40,  # 🔴 鉄板: 連対率 40%以上
    "iron_min_rides": 30,  # 🔴 鉄板: 最低騎乗回数
    "value_return_win": 120.0,  # 🟡 妙味: 単回収 120%以上
    "value_min_rides": 15,  # 🟡 妙味: 最低騎乗回数
    "danger_top2_rate": 0.15,  # 🔵 危険: 連対率 15%未満
    "danger_min_rides": 10,  # 🔵 危険: 最低騎乗回数
    "danger_max_popularity": 3,  # 🔵 危険: 人気 1-3位
}


def screen_entry(
    jockey_course_top2_rate: float,
    jockey_course_ride_count: int,
    jockey_course_return_win: float,
    jockey_trainer_top2_rate: float,
    jockey_trainer_ride_count: int,
    jockey_trainer_return_win: float,
    popularity: Optional[int] = None,
    thresholds: Optional[dict] = None,
) -> ScreeningResult:
    """
    フラグ判定。優先順位：危険 > 鉄板 > 妙味

    Args:
        jockey_course_top2_rate: 騎手×コースの連対率（0.0〜1.0）
        jockey_course_ride_count: 騎手×コースの騎乗回数
        jockey_course_return_win: 騎手×コースの単勝回収率（%）
        jockey_trainer_top2_rate: 騎手×厩舎の連対率（0.0〜1.0）
        jockey_trainer_ride_count: 騎手×厩舎の騎乗回数
        jockey_trainer_return_win: 騎手×厩舎の単勝回収率（%）
        popularity: 当日人気（1始まり、未確定ならNone）
        thresholds: カスタム閾値辞書（Noneならデフォルト使用）

    Returns:
        ScreeningResult: 判定結果
    """
    th = thresholds or DEFAULT_THRESHOLDS

    iron_top2 = th.get("iron_top2_rate", 0.40)
    iron_rides = th.get("iron_min_rides", 30)
    value_ret = th.get("value_return_win", 120.0)
    value_rides = th.get("value_min_rides", 15)
    danger_top2 = th.get("danger_top2_rate", 0.15)
    danger_rides = th.get("danger_min_rides", 10)
    danger_pop = th.get("danger_max_popularity", 3)

    # === 🔵 危険フラグ（最優先チェック） ===
    if popularity is not None and popularity <= danger_pop:
        if jockey_course_ride_count >= danger_rides and jockey_course_top2_rate < danger_top2:
            return ScreeningResult(
                flag="danger",
                label="🔵 危険",
                reason=f"{popularity}番人気 / コース連対{jockey_course_top2_rate * 100:.0f}%",
                detail={
                    "人気": popularity,
                    "コース連対率": jockey_course_top2_rate,
                    "コース騎乗回数": jockey_course_ride_count,
                },
            )

    # === 🔴 鉄板フラグ ===
    iron_reasons = []
    if jockey_course_top2_rate >= iron_top2 and jockey_course_ride_count >= iron_rides:
        iron_reasons.append(
            f"コース連対{jockey_course_top2_rate * 100:.0f}%（{jockey_course_ride_count}回）"
        )
    if jockey_trainer_top2_rate >= iron_top2 and jockey_trainer_ride_count >= iron_rides:
        iron_reasons.append(
            f"厩舎連対{jockey_trainer_top2_rate * 100:.0f}%（{jockey_trainer_ride_count}回）"
        )
    if iron_reasons:
        return ScreeningResult(
            flag="iron",
            label="🔴 鉄板",
            reason=" / ".join(iron_reasons),
            detail={
                "コース連対率": jockey_course_top2_rate,
                "コース騎乗回数": jockey_course_ride_count,
                "厩舎連対率": jockey_trainer_top2_rate,
                "厩舎騎乗回数": jockey_trainer_ride_count,
            },
        )

    # === 🟡 妙味フラグ ===
    value_reasons = []
    if jockey_course_return_win >= value_ret and jockey_course_ride_count >= value_rides:
        value_reasons.append(
            f"コース単回収{jockey_course_return_win:.0f}%（{jockey_course_ride_count}回）"
        )
    if jockey_trainer_return_win >= value_ret and jockey_trainer_ride_count >= value_rides:
        value_reasons.append(
            f"厩舎単回収{jockey_trainer_return_win:.0f}%（{jockey_trainer_ride_count}回）"
        )
    if value_reasons:
        return ScreeningResult(
            flag="value",
            label="🟡 妙味",
            reason=" / ".join(value_reasons),
            detail={
                "コース単回収": jockey_course_return_win,
                "コース騎乗回数": jockey_course_ride_count,
                "厩舎単回収": jockey_trainer_return_win,
                "厩舎騎乗回数": jockey_trainer_ride_count,
            },
        )

    # === フラグなし ===
    return ScreeningResult(flag=None, label="", reason="", detail={})
