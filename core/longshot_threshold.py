# -*- coding: utf-8 -*-
"""穴馬しきい値と『相手候補帯』の共通ヘルパー。

## 設計の要点(検証で判断が変わった経緯を残す)
当初『少頭数×堅いレースでは穴馬しきい値を6番人気以降→4番人気以降に自動で下げる』
という案があった。しかし scripts/longshot_threshold_backtest.py で検証したところ:

  ① 下げると確かに当たりは増える(少頭数×堅い: VH上位2頭の的中 31.5%→59.1%)
  ② **しかし多頭数でも+14.7pp改善する**(38.9%→53.6%)＝「少頭数だから」ではなく
     単に4-5番人気が入るぶん当たりやすくなる母数効果
  ③ 決定的: 同じ候補プール内で『VH上位2頭』と『単なる人気上位2頭』を比べると
     | 区分 | th | VH2頭 | 人気2頭 | 差 |
     |---|---|---|---|---|
     | 少頭数×堅い | **4** | 59.1% | 59.6% | **-0.5pp** |
     | 少頭数×堅い | 6 | 32.2% | 30.8% | +1.4pp |
     | 多頭数 | 6 | 38.9% | 36.4% | +2.5pp |
     **しきい値4ではVHが人気に負ける**。穴馬ハンターの主成分は市場情報なので
     ([[project_value_horse_hunter]])、人気馬を含めるとVHは人気順の劣化版になる。

→ 結論: **穴馬しきい値は6のまま動かさない**。
   代わりに『少頭数×堅い』では4-5番人気を**別枠の相手候補**として案内する。
   穴(市場の見落とし)と相手(市場が既に評価済み)は役割が違うので混ぜない。

## 相手候補帯(4-5番人気)の実測 — scripts/longshot_threshold_backtest.py
| 区分 | R数 | 4-5人気の3着内率 | 4-5人気が1頭以上3着内 | 3着内が全て5人気以内 |
|---|---|---|---|---|
| **少頭数×堅い** | 4,991 | **33.2%** | **59.4%** | **60.1%** |
| 多頭数 | 29,784 | 29.4% | 52.5% | 32.1% |

少頭数×堅いは『3着内が全て5番人気以内』が60.1%(多頭数の約2倍)＝
ここでは穴を掘るより上位人気の取りこぼしを防ぐ方が現実に合う。
"""

from __future__ import annotations

import math

# 穴馬の定義は動かさない(6番人気以降)。VHが人気を超える情報を持つのはこの帯だけ。
LONGSHOT_MIN = 6

# 相手候補帯(少頭数×堅いレースでのみ案内する)
COMPANION_LO, COMPANION_HI = 4, 5

SMALL_FIELD_MAX = 10          # 「少頭数」の上限
FIRM_FAV1 = 3.5               # 1番人気がこれ以下なら堅い
FIRM_SYN3 = 4.0               # 上位3頭の合成オッズがこれ以下なら堅い


def _to_float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _field_size(df=None, n_horses=None):
    if n_horses:
        try:
            return int(n_horses)
        except (TypeError, ValueError):
            pass
    try:
        return int(len(df)) if df is not None else None
    except Exception:
        return None


def _odds_list(df=None, odds_list=None):
    if odds_list is not None:
        return sorted(x for x in (_to_float(o) for o in odds_list) if x and x > 0)
    if df is None or "Odds" not in getattr(df, "columns", []):
        return []
    vals = []
    try:
        for o in df["Odds"]:
            x = _to_float(o)
            if x and 0 < x < 9999:
                vals.append(x)
    except Exception:
        return []
    return sorted(vals)


def default_threshold(df=None, meta=None, n_horses=None, odds_list=None):
    """穴馬しきい値。**常に6**(検証の結果、下げるとVHが人気順の劣化版になるため)。

    戻り値: (6, 理由文字列)。互換のためタプルのまま。
    """
    n = _field_size(df, n_horses)
    return LONGSHOT_MIN, (f"{n}頭" if n else "default")


def is_small_firm(df=None, meta=None, n_horses=None, odds_list=None):
    """『少頭数(10頭以下)×堅い市場』か。判定できなければ None。

    ⚠ オッズ未取得(発走前にレースIDを入れた直後など)は **None を返す**。
      旧実装はここで『堅い』と決め打ちして4を返しており、実運用では
      オッズが入る前は常にその分岐に入ってしまう不具合があった。
      分からないときは何も主張しないのが正しい。
    """
    n = _field_size(df, n_horses)
    if not n or n > SMALL_FIELD_MAX:
        return False
    o = _odds_list(df, odds_list)
    if len(o) < 3:
        return None                   # オッズ未取得＝判定不能(決め打ちしない)
    inv = (1.0 / o[0]) + (1.0 / o[1]) + (1.0 / o[2])
    syn3 = 3.0 / inv if inv else None
    return (o[0] <= FIRM_FAV1) or (syn3 is not None and syn3 <= FIRM_SYN3)


def companion_band(df=None, meta=None, n_horses=None, odds_list=None):
    """少頭数×堅いレースでのみ『相手候補帯』を返す。該当しなければ None。

    戻り値: {'lo':4, 'hi':5, 'n':頭数, 'reason':str} or None
    ⚠ これは**穴馬ではない**。市場が既に評価している馬なので、
      選び方はVHではなく**人気順**が正しい(検証で VH は人気に-0.5pp 負けた)。
    """
    sf = is_small_firm(df, meta, n_horses, odds_list)
    if sf is not True:
        return None
    n = _field_size(df, n_horses)
    return {
        'lo': COMPANION_LO, 'hi': COMPANION_HI, 'n': n,
        'reason': f"{n}頭立て・上位人気が堅い",
    }
