"""
utils_pattern.py — パターン判定ユーティリティ関数
"""


def calc_ura_number(field_size: int, horse_number: int) -> int:
    return (field_size - horse_number) + 1


def ones_digit(horse_number: int) -> int:
    return horse_number % 10


def is_outermost(field_size: int, horse_number: int) -> bool:
    return horse_number == field_size


def generate_cycle_targets(horse_number: int, field_size: int, max_target: int) -> set:
    """循環ターゲットの候補集合を生成する。"""
    targets = set()
    v = horse_number
    while v <= max_target:
        targets.add(v)
        v += field_size
    return targets


def is_cycle_match(horse_number_a: int, field_size_a: int,
                   horse_number_b: int, field_size_b: int) -> bool:
    """片方循環で一致するかを判定する。"""
    if field_size_a == field_size_b:
        return False
    # 頭数の少ない方を循環させる
    if field_size_a <= field_size_b:
        small_n, small_f, big_n = horse_number_a, field_size_a, horse_number_b
    else:
        small_n, small_f, big_n = horse_number_b, field_size_b, horse_number_a
    projected = ((big_n - 1) % small_f) + 1
    return projected == small_n


def is_reverse_match(horse_number_a: int, field_size_a: int,
                     horse_number_b: int, field_size_b: int) -> bool:
    """裏表逆で一致するかを判定する。"""
    ura_a = calc_ura_number(field_size_a, horse_number_a)
    ura_b = calc_ura_number(field_size_b, horse_number_b)
    return ura_a == horse_number_b or horse_number_a == ura_b


def is_ura_match(horse_number_a: int, field_size_a: int,
                 horse_number_b: int, field_size_b: int) -> bool:
    """裏同士で一致するかを判定する（異なる頭数のみ）。"""
    if field_size_a == field_size_b:
        return False
    ura_a = calc_ura_number(field_size_a, horse_number_a)
    ura_b = calc_ura_number(field_size_b, horse_number_b)
    return ura_a == ura_b


def is_ones_digit_match(horse_number_a: int, horse_number_b: int) -> bool:
    return horse_number_a % 10 == horse_number_b % 10
