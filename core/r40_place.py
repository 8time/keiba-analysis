# -*- coding: utf-8 -*-
"""複勝EV（r=40モデル）— 単勝オッズから複勝的中確率を数理逆算し、割安な複勝を探す。

検証済み（scripts/r40_place_model.py ほか・48万頭/34,212R・2016-2026）:
  ・理論θと実際の3着内率の差は全帯で -1.9〜+1.4pp ＝ 較正が優秀
  ・単勝支持率20%以上 × 較正EV>1.02 で **複勝回収率106.4%**（90%CI 101〜112%）
  ・着地位置を学習窓(≤2021)で推定し評価窓(2022-2026)に適用した out-of-sample
  ・最大払戻620円＝高配当1本に依存しない。上位20本を除いても100%超
  ・11年中8年プラス。直近3年(2024-26)は113/113/106%

⚠まだ実運用に入れる段階ではない。検証は**確定オッズ**で行っており、
  ライブで見えるのは締切前オッズ。そのズレは未検証。
  → 本モジュールは**紙トレード（記録して後で答え合わせ）**のために作られている。

⚠ガラス人気馬との関係（scripts/glass_vs_r40_overlap.py で解決済み）:
  ここで選ばれる馬の94.3%はガラス人気馬に該当する。
  ガラス人気馬は複勝率が低い(残差-0.70pp)ので**軸にはしない**のが正しいが、
  複勝ROIは非該当より高い(85.4% vs 78.7%)＝**複勝券としては買い**。
  「3着に入りやすいか」と「オッズに見合うか」は別問題。
"""
import numpy as np

LAM2, LAM3 = 0.81, 0.70     # r=40 に対応するパラメータ(Lo et al. 1995)
TAKEOUT = 0.80              # 単勝払戻率
LAND_POS = 0.306            # 実配当がレンジのどこに着地するかの実測平均(≤2021で推定)
PI_MIN = 0.20               # 単勝支持率の下限(これ未満は対象外＝検証済みの適用範囲)
EV_MIN = 1.02               # 較正EVのしきい値


def theta_r40(win_odds):
    """単勝オッズの配列 → 各馬の複勝的中確率θ。

    θ_i = π_i
        + Σ_{j≠i} π_j·[π_i^λ2 / Σ_{n≠j} π_n^λ2]
        + Σ_{j≠i} Σ_{k≠i,j} π_j·[π_k^λ2/Σ_{n≠j}π_n^λ2]·[π_i^λ3/Σ_{m≠j,k}π_m^λ3]
    """
    o = np.asarray([float(x) if x and float(x) > 0 else np.nan for x in win_odds],
                   dtype=float)
    if np.isnan(o).any() or len(o) < 4:
        return None, None
    raw = TAKEOUT / o
    pi = raw / raw.sum()
    a, b = pi ** LAM2, pi ** LAM3
    Sa, Sb = a.sum(), b.sum()
    da = Sa - a
    t2 = a * ((pi / da).sum() - pi / da)
    denom = Sb - b[:, None] - b[None, :]
    with np.errstate(divide='ignore', invalid='ignore'):
        M = (pi[:, None] * a[None, :] / da[:, None]) / denom
    np.fill_diagonal(M, 0.0)
    M[~np.isfinite(M)] = 0.0
    t3 = b * (M.sum() - M.sum(axis=0) - M.sum(axis=1))
    return np.clip(pi + t2 + t3, 0.0, 1.0), pi


def expected_place_odds(pl_min, pl_max, pos=LAND_POS):
    """複勝の期待払戻オッズ。

    複勝オッズはmin〜maxのレンジで示され、実配当は同時入線馬次第で決まる。
    実測では**平均0.31の位置**にしか着地しない(中央値0.03)ので、
    中央値(=0.5)を使うとEVを体系的に過大評価する。ここは必ずposで較正する。
    """
    try:
        lo = float(pl_min)
        hi = float(pl_max) if pl_max else lo
    except (TypeError, ValueError):
        return None
    if lo <= 0:
        return None
    return lo + max(0.0, hi - lo) * pos


def screen(rows, ev_min=EV_MIN, pi_min=PI_MIN):
    """1レース分を判定する。

    rows: [{'umaban':int,'name':str,'win_odds':float,'pl_min':float,'pl_max':float}, ...]
    戻り値: 全馬に theta/pi/exp_odds/ev/pick を付けたリスト（pick=買い候補）。
    """
    if not rows:
        return []
    th, pi = theta_r40([r.get('win_odds') for r in rows])
    if th is None:
        return []
    out = []
    for r, t, p in zip(rows, th, pi):
        eo = expected_place_odds(r.get('pl_min'), r.get('pl_max'))
        ev = (t * eo) if eo else None
        d = dict(r)
        d.update({'theta': float(t), 'pi': float(p), 'exp_odds': eo, 'ev': ev,
                  'pick': bool(ev is not None and ev > ev_min and p >= pi_min)})
        out.append(d)
    return out


def why_not(row, ev_min=EV_MIN, pi_min=PI_MIN):
    """買い候補にならなかった理由を平易な日本語で返す（UIの説明用）。"""
    if row.get('pick'):
        return ''
    if row.get('pi') is not None and row['pi'] < pi_min:
        return f"人気が足りない（単勝の支持率{row['pi']*100:.0f}%・{pi_min*100:.0f}%以上が対象）"
    if row.get('ev') is None:
        return '複勝オッズが取れていない'
    return f"複勝オッズが安すぎる（期待値{row['ev']:.2f}・{ev_min:.2f}超が対象）"
