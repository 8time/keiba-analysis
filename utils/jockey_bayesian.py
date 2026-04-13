# -*- coding: utf-8 -*-
"""
ベイズ補正計算モジュール
========================
サンプル数が少ないデータを全体平均に寄せて補正する。
N指数は使用しない。

騎乗回数が少ない騎手×条件の組み合わせは信頼性が低いため、
全体平均（事前分布）との加重平均を取ることで、
過大評価・過小評価を防ぐ。
"""


def bayesian_adjusted_rate(
    observed_rate: float,
    sample_size: int,
    prior_rate: float,
    prior_strength: int = 20,
) -> float:
    """
    ベイズ推定による補正勝率。

    sample_sizeが小さいほどprior_rateに近づき、
    大きくなるほどobserved_rateそのものに近づく。

    Args:
        observed_rate: 観測された勝率/連対率/回収率
        sample_size: 観測されたサンプル数（騎乗回数）
        prior_rate: 全体平均（事前分布の中心値）
        prior_strength: 事前分布の強さ（擬似サンプル数）。
                        数値が大きいほど少数サンプルが全体平均に強く引き寄せられる。

    Returns:
        補正後の推定値

    Examples:
        >>> bayesian_adjusted_rate(1.0, 3, 0.16, 20)  # 3回騎乗で連対率100%
        0.2278...  # → 全体平均16%に大きく引き寄せられる
        >>> bayesian_adjusted_rate(0.40, 100, 0.16, 20)  # 100回騎乗で連対率40%
        0.36...    # → 実績値40%にほぼ近い
    """
    if sample_size <= 0:
        return prior_rate
    return (prior_rate * prior_strength + observed_rate * sample_size) / (
        prior_strength + sample_size
    )
