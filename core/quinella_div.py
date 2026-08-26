# -*- coding: utf-8 -*-
"""馬連の支持順位と単勝人気のズレ — core/quinella_div.py

単勝人気は「この馬が1着」の票。馬連は「この2頭が1・2着」の票。
同じ馬でも券種で支持がずれることがある（ガラス人気＝単勝と複勝のズレ、と同型）。

ここでは計算だけを置く。印（お宝/消し）をUIに出すかどうかは
scripts/quinella_ninki_div_backtest.py の holdout 残差が決める。
残差がゲート未達なら表示しない。

入力の馬連オッズは確定1枚で足りる（時系列は不要）。
"""


def pair_umabans(combo):
    """'0105' / '105' → (1, 5)。不正は None。"""
    s = ''.join(ch for ch in str(combo or '') if ch.isdigit())
    if len(s) < 4:
        s = s.zfill(4)
    if len(s) < 4:
        return None
    a, b = int(s[0:2]), int(s[2:4])
    if a <= 0 or b <= 0 or a == b:
        return None
    return a, b


def support_mass(quinella_odds):
    """馬連オッズから馬ごとの支持量 {馬番: Σ 1/オッズ}。

    quinella_odds: {(u1,u2): odds} / {frozenset: odds} / [{'combo','odds'}, ...]
    """
    mass = {}
    if quinella_odds is None:
        return mass
    if isinstance(quinella_odds, dict):
        items = quinella_odds.items()
        for key, odds in items:
            try:
                o = float(odds)
            except (TypeError, ValueError):
                continue
            if o <= 0:
                continue
            if isinstance(key, (list, tuple, set, frozenset)) and len(key) == 2:
                pair = tuple(int(x) for x in key)
            else:
                pair = pair_umabans(key)
            if not pair:
                continue
            w = 1.0 / o
            for u in pair:
                mass[u] = mass.get(u, 0.0) + w
        return mass
    for row in quinella_odds:
        if not isinstance(row, dict):
            continue
        pair = pair_umabans(row.get('combo'))
        try:
            o = float(row.get('odds'))
        except (TypeError, ValueError):
            continue
        if not pair or o <= 0:
            continue
        w = 1.0 / o
        for u in pair:
            mass[u] = mass.get(u, 0.0) + w
    return mass


def support_rank(mass):
    """支持量が多い順の順位 {馬番: 1=最も支持}。同量は馬番が若い方を先。"""
    if not mass:
        return {}
    ordered = sorted(mass.items(), key=lambda x: (-x[1], x[0]))
    return {u: i + 1 for i, (u, _) in enumerate(ordered)}


def ninki_minus_qrank(ninki_map, qrank_map):
    """単勝人気 − 馬連支持順位。正=馬連の方が支持、負=単勝の方が支持。"""
    out = {}
    for u, nk in (ninki_map or {}).items():
        try:
            u, nk = int(u), int(nk)
            qr = qrank_map.get(u)
            if qr is None:
                qr = qrank_map.get(str(u))
            if qr is None or nk <= 0:
                continue
            out[u] = nk - int(qr)
        except (TypeError, ValueError):
            continue
    return out


def fade_umabans(ninki_map, qrank_map, min_delta=2):
    """単勝の方が支持が強い馬（馬連ではいまいち）。delta <= -min_delta。

    holdout 2025: 複勝残差約-4pp (z-3.9)。お宝側(馬連の方が支持)はゲート未達。
    買い目の自動除外には使わない。表示の注意だけ。
    """
    div = ninki_minus_qrank(ninki_map, qrank_map)
    return sorted(u for u, d in div.items() if d <= -int(min_delta))
