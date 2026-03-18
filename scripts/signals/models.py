"""
models.py — ◎●シグナル用データモデル
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Entry:
    """スキャン結果の1馬単位。既存スキャナーの出力を拡張する。"""
    date: str
    venue: str
    race_id: str
    race_number: int
    field_size: int
    horse_number: int
    horse_name: str
    jockey: str
    trainer: str
    odds: float
    odds_rank: int
    ura_number: int = 0
    # 既存パターン
    patterns_detected: str = ""
    match_details: str = ""
    existing_score: int = 0
    # ◎シグナル
    jockey_double_circle_flag: bool = False
    jockey_double_circle_rule_type: Optional[str] = None
    trainer_double_circle_flag: bool = False
    trainer_double_circle_rule_type: Optional[str] = None
    # ●シグナル
    trainer_bullet_flag: bool = False
    trainer_bullet_rule_types: List[str] = field(default_factory=list)
    # 表示用
    special_marks: str = ""
    # 最終スコア
    total_score: int = 0

    def __post_init__(self):
        if self.ura_number == 0 and self.field_size > 0:
            self.ura_number = (self.field_size - self.horse_number) + 1


@dataclass
class EntityDailyVenueGroup:
    """◎判定の単位: 同一日・同一場・同一entity"""
    date: str
    venue: str
    entity_type: str  # "jockey" or "trainer"
    entity_name: str
    entries: List[Entry] = field(default_factory=list)


@dataclass
class TrainerCrossVenueRaceGroup:
    """●判定の単位: 同一日・同一厩舎・同一R番号"""
    date: str
    trainer: str
    race_number: int
    entries: List[Entry] = field(default_factory=list)


@dataclass
class DoubleCircleResult:
    """◎判定の結果"""
    flag: bool
    rule_type: Optional[str] = None
    target_value: object = None  # str | int | None
    entry_count: int = 0
    race_numbers: List[int] = field(default_factory=list)
    horse_numbers: List[int] = field(default_factory=list)


@dataclass
class PairMatch:
    """●判定のペア一致結果"""
    venue_a: str
    venue_b: str
    race_number: int
    horse_number_a: int
    horse_number_b: int
    matched_rule_types: List[str] = field(default_factory=list)


@dataclass
class BulletResult:
    """●判定の結果"""
    flag: bool
    matched_rule_types: List[str] = field(default_factory=list)
    matched_pairs: List[PairMatch] = field(default_factory=list)
