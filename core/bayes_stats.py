# -*- coding: utf-8 -*-
"""ベイズ的な『少サンプルの過信を防ぐ』補正ユーティリティ。

このモジュールは新しい予測エッジを作るものではない。既存の割合(勝率・的中率・生還率)を
「その数字をどれだけ信じてよいか」で補正するだけの道具箱。

- shrink_rate(): 縮小推定。「5戦1勝=勝率20%」を鵜呑みにせず全体平均へ引き寄せる。
- wilson_lower(): Wilson信頼区間の下限。「最悪でもこのくらいはある」という保守的な下限。

依存は標準mathのみ(scipy等は使わない)。
"""
import math


def shrink_rate(k, n, prior_mean, prior_strength=20.0):
    """縮小推定(ベータ二項の事後平均)。少ない実績を『全体平均』へ引き寄せる。

    直感的な意味:
      「5戦1勝(=20%)」と「100戦20勝(=20%)」は同じ20%でも信頼度が違う。
      前者は偶然かもしれないので全体平均(prior_mean)寄りに、後者は実測値のまま残す。
      prior_strength は『事前分布の重み＝仮想的なサンプル数』。デフォルト20は
      「20戦ぶんの実績が貯まると、全体平均と実測が同じ重みで混ざる」という意味。

    数式: p~ = (k + a0) / (n + a0 + b0)
          a0 = prior_mean * S,  b0 = (1 - prior_mean) * S   (S = prior_strength)

    引数:
      k: 成功回数(勝ち数など)
      n: 試行回数(出走数など)
      prior_mean: 事前の平均(母集団の平均勝率など・0〜1)
      prior_strength: 事前分布の重み(仮想サンプル数)。大きいほど強く引き寄せる。

    戻り値: 補正後の割合(float・0〜1)。n=0 のときは prior_mean をそのまま返す。
    例外: k<0 / n<0 / k>n / prior_mean が 0〜1 の外 / prior_strength<0 は ValueError。
    """
    try:
        k = float(k)
        n = float(n)
        prior_mean = float(prior_mean)
        prior_strength = float(prior_strength)
    except (TypeError, ValueError):
        raise ValueError('shrink_rate: 数値に変換できない引数があります')
    if k < 0 or n < 0:
        raise ValueError(f'shrink_rate: k/n は非負が必要 (k={k}, n={n})')
    if k > n:
        raise ValueError(f'shrink_rate: k は n 以下が必要 (k={k}, n={n})')
    if not (0.0 <= prior_mean <= 1.0):
        raise ValueError(f'shrink_rate: prior_mean は0〜1が必要 (got {prior_mean})')
    if prior_strength < 0:
        raise ValueError(f'shrink_rate: prior_strength は非負が必要 (got {prior_strength})')

    if n == 0:
        return prior_mean
    a0 = prior_mean * prior_strength
    b0 = (1.0 - prior_mean) * prior_strength
    denom = n + a0 + b0
    if denom <= 0:
        return prior_mean
    return (k + a0) / denom


def wilson_lower(k, n, z=1.96):
    """Wilsonスコア区間の下限。『最悪でもこのくらいはある』という保守的な下限値。

    単純な割合(k/n)は標本が少ないと大きくブレる。Wilson下限は標本の少なさを
    ペナルティとして織り込み、「95%の確からしさで、少なくともこの値以上」を返す。
    実績アピールに使う数字を『盛らない』ための道具。

    引数:
      k: 成功回数 / n: 試行回数 / z: 信頼水準のz値(1.96=95%、1.645=90%)
    戻り値: 下限(float・0〜1)。n=0 のときは None。
    例外: k<0 / n<0 / k>n は ValueError。
    """
    try:
        k = float(k)
        n = float(n)
        z = float(z)
    except (TypeError, ValueError):
        raise ValueError('wilson_lower: 数値に変換できない引数があります')
    if k < 0 or n < 0:
        raise ValueError(f'wilson_lower: k/n は非負が必要 (k={k}, n={n})')
    if k > n:
        raise ValueError(f'wilson_lower: k は n 以下が必要 (k={k}, n={n})')
    if n == 0:
        return None

    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    margin = z * math.sqrt(max(0.0, (p * (1.0 - p) / n) + (z2 / (4.0 * n * n))))
    lo = (center - margin) / denom
    return max(0.0, min(1.0, lo))
