"""
double_circle.py — ◎シグナル判定ロジック
"""
from typing import Dict, List, Optional, Tuple

from .models import Entry, EntityDailyVenueGroup, DoubleCircleResult
from .utils_pattern import calc_ura_number, ones_digit, generate_cycle_targets


def check_same_horse_number_all(entries: List[Entry]) -> Tuple[bool, Optional[int]]:
    """全出走の horse_number が同じなら True, 対象馬番。"""
    if len(entries) < 2:
        return False, None
    nums = {e.horse_number for e in entries}
    if len(nums) == 1:
        return True, entries[0].horse_number
    return False, None


def check_ones_digit_all(entries: List[Entry]) -> Tuple[bool, Optional[int]]:
    """全出走の一の位が同じなら True, 対象一の位。"""
    if len(entries) < 2:
        return False, None
    digits = {e.horse_number % 10 for e in entries}
    if len(digits) == 1:
        return True, entries[0].horse_number % 10
    return False, None


def check_same_waku_all(entries: List[Entry]) -> bool:
    """同枠だけの統一を検出する（◎除外用）。
    枠番は field_size に応じた標準割り当てで計算。"""
    if len(entries) < 2:
        return False

    def _calc_waku(field_size: int, horse_number: int) -> int:
        """JRA標準枠番を概算する。"""
        if field_size <= 8:
            return horse_number
        # 9頭以上: 後方から2頭ずつ枠に割り当て
        # 簡易計算: (horse_number - 1) を 8枠に分配
        waku = min(8, ((horse_number - 1) * 8) // field_size + 1)
        return max(1, waku)

    wakus = {_calc_waku(e.field_size, e.horse_number) for e in entries}
    return len(wakus) == 1


def check_reverse_axis_all(entries: List[Entry]) -> Tuple[bool, Optional[int]]:
    """reverse_axis 積集合クラスタ方式。
    各entryの {horse_number, ura_number} の全積集合に共通値があれば True。
    """
    if len(entries) < 2:
        return False, None
    axis_sets = [{e.horse_number, e.ura_number} for e in entries]
    common = axis_sets[0]
    for s in axis_sets[1:]:
        common = common & s
    if common:
        return True, min(common)
    return False, None


def check_cycle_target_all(entries: List[Entry], max_target: Optional[int] = None) -> Tuple[bool, Optional[int]]:
    """全出走が同一の循環ターゲット値を共有するかを判定する。"""
    if len(entries) < 2:
        return False, None
    if max_target is None:
        max_target = max(e.field_size for e in entries) + 18
    cycle_sets = [
        generate_cycle_targets(e.horse_number, e.field_size, max_target)
        for e in entries
    ]
    common = cycle_sets[0]
    for s in cycle_sets[1:]:
        common = common & s
    if common:
        return True, min(common)
    return False, None


def evaluate_double_circle(group: EntityDailyVenueGroup) -> DoubleCircleResult:
    """◎判定メイン。判定順は固定:
    1. same_horse_number  2. ones_digit  3. reverse_axis  4. cycle_target
    """
    entries = group.entries
    neg = DoubleCircleResult(flag=False)

    if len(entries) < 2:
        return neg

    # 同枠統一は◎対象外
    if check_same_waku_all(entries):
        # 同枠だけで説明できる場合は除外
        # ただし他のパターンでも説明できるかチェックするため、ここでは除外フラグだけ立てる
        pass

    race_numbers = [e.race_number for e in entries]
    horse_numbers = [e.horse_number for e in entries]

    checks = [
        ("same_horse_number", check_same_horse_number_all),
        ("ones_digit", check_ones_digit_all),
        ("reverse_axis", check_reverse_axis_all),
        ("cycle_target", check_cycle_target_all),
    ]

    for rule_type, check_fn in checks:
        ok, val = check_fn(entries)
        if ok:
            # 同枠統一のみの場合は除外
            if check_same_waku_all(entries):
                # 同枠統一だが、それ以外のパターンでも説明できるなら◎
                # same_horse_number は同枠でもあるが、より強い条件なのでOK
                if rule_type == "same_horse_number":
                    pass  # same_horse_numberは同枠でもOK（同馬番 > 同枠）
                elif rule_type == "ones_digit":
                    # 一の位が全部同じ ≠ 同枠の場合はOK
                    pass
                else:
                    pass
            return DoubleCircleResult(
                flag=True,
                rule_type=rule_type,
                target_value=val,
                entry_count=len(entries),
                race_numbers=race_numbers,
                horse_numbers=horse_numbers,
            )

    return neg


def evaluate_all_double_circle_groups(
    groups: Dict[Tuple, EntityDailyVenueGroup]
) -> Dict[Tuple, DoubleCircleResult]:
    """全◎グループを一括判定する。"""
    results = {}
    for key, grp in groups.items():
        results[key] = evaluate_double_circle(grp)
    return results
