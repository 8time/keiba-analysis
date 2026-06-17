# -*- coding: utf-8 -*-
"""券種EV比較・資金配分エンジン（6段サイクルの④「AI連携による買い方」）。

設計(ユーザー選択=モデル確率でEV%を出す):
- 予測確率: Projected Score の softmax を勝率 p_i とする(温度tempで尖り調整)。
  ※この確率モデルは未検証なので EV は『目安』。馬券の優劣比較ツールとして使う。
- 連系の的中確率: Harville モデル(p_i から逐次サンプリング)で厳密算出。
  馬連=2頭が1-2着 / ワイド=2頭が3着内 / 3連複=3頭が3着内 / 複勝=1頭が3着内。
- EV = 的中確率 × オッズ (>1.0 で理論プラス)。
- 資金配分: ハーフケリー f=(p*odds-1)/(odds-1) ×0.5。破産回避のため穴ほど比率を絞る。

純粋関数のみ。スクレイピング/Streamlitに非依存。
"""
from itertools import combinations
from math import exp


# ───────────────────────── 勝率(モデル確率) ─────────────────────────
def softmax_win_probs(score_by_um, temp=8.0):
    """{umaban: ProjectedScore} → {umaban: 勝率}。softmax(score/temp)。
    temp小=尖る(本命集中) / temp大=平坦。"""
    items = [(u, float(s)) for u, s in (score_by_um or {}).items() if s is not None]
    if not items:
        return {}
    mx = max(s for _, s in items)
    exps = {u: exp((s - mx) / max(0.1, temp)) for u, s in items}
    z = sum(exps.values()) or 1.0
    return {u: v / z for u, v in exps.items()}


def market_implied(odds_by_um):
    """単勝オッズ → 控除込みを除いた市場含意勝率 q_i = (1/odds_i)/Σ(1/odds)。"""
    inv = {u: 1.0 / float(o) for u, o in (odds_by_um or {}).items() if o and float(o) > 0}
    z = sum(inv.values()) or 1.0
    return {u: v / z for u, v in inv.items()}


def blended_win_probs(score_by_um, win_odds_by_um, alpha=0.5):
    """市場を事前分布にしたモデル確率(幾何ブレンド)。p_i ∝ q_i^(1-α) · m_i^α。
    q=市場含意勝率、m=市場スケールに較正したモデルsoftmax。
    α=0で純市場(EVほぼ平坦) / α=1で純モデル(外れ馬で暴発)。既定0.5。
    モデルが市場と『中庸に』乖離した馬だけEVに反映され、外れ馬の極端乖離は市場prior で抑制される。"""
    q = market_implied(win_odds_by_um)
    if not q:
        return softmax_win_probs(score_by_um)
    T = calibrate_temp(score_by_um, win_odds_by_um)
    m = softmax_win_probs(score_by_um, temp=T)
    if not m:
        return q
    out = {}
    for u, qi in q.items():
        mi = m.get(u, 1e-9)
        out[u] = (max(qi, 1e-12) ** (1.0 - alpha)) * (max(mi, 1e-12) ** alpha)
    z = sum(out.values()) or 1.0
    return {u: v / z for u, v in out.items()}


def calibrate_temp(score_by_um, win_odds_by_um, lo=0.5, hi=300.0, iters=44):
    """softmaxの温度を、モデル本命の勝率が『市場本命の勝率』に一致するよう自動調整。
    → 確率は市場スケールのまま、順位はモデルが決める(=モデルvs市場の乖離だけがEVに出る)。
    これによりEVが非現実的に膨らむのを防ぐ。市場オッズが無ければ既定temp。"""
    q = market_implied(win_odds_by_um)
    if not q or not score_by_um:
        return 8.0
    target = min(0.45, max(0.15, max(q.values())))
    for _ in range(iters):
        mid = (lo + hi) / 2
        p = softmax_win_probs(score_by_um, temp=mid)
        if not p:
            return mid
        # 温度↑で平坦化(top↓)。topがtargetを上回れば温度を上げる。
        if max(p.values()) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ───────────────────────── Harville 連系確率 ─────────────────────────
def _p2(p, a, b):
    """a,b がこの順(a→b)で1-2着になる確率。"""
    pa = p.get(a, 0.0)
    rem = 1.0 - pa
    if rem <= 1e-9:
        return 0.0
    return pa * (p.get(b, 0.0) / rem)


def _p3(p, a, b, c):
    """a→b→c の順で1-2-3着になる確率。"""
    pa = p.get(a, 0.0)
    r1 = 1.0 - pa
    if r1 <= 1e-9:
        return 0.0
    pb = p.get(b, 0.0)
    r2 = r1 - pb
    if r2 <= 1e-9:
        return 0.0
    return pa * (pb / r1) * (p.get(c, 0.0) / r2)


def umaren_prob(p, a, b):
    """馬連: a,b が(順不同で)1-2着。"""
    return _p2(p, a, b) + _p2(p, b, a)


def trio_prob(p, a, b, c):
    """3連複: a,b,c が(順不同で)1-2-3着 = この3頭が表彰台を独占。"""
    s = 0.0
    for x, y, z in ((a, b, c), (a, c, b), (b, a, c), (b, c, a), (c, a, b), (c, b, a)):
        s += _p3(p, x, y, z)
    return s


def wide_prob(p, a, b, all_um):
    """ワイド: a,b がともに3着内。= 表彰台が {a,b,第3頭} になる確率の総和。"""
    s = 0.0
    for c in all_um:
        if c == a or c == b:
            continue
        s += trio_prob(p, a, b, c)
    return s


def place_prob(p, a, all_um):
    """複勝: a が3着内。= a を含む表彰台3頭組の確率総和。"""
    others = [u for u in all_um if u != a]
    s = 0.0
    for b, c in combinations(others, 2):
        s += trio_prob(p, a, b, c)
    return s


# ───────────────────────── ケリー / EV ─────────────────────────
def kelly_fraction(p, odds, frac=0.5, cap=0.25):
    """ハーフケリー比率。f=(p*odds-1)/(odds-1)。負(=不利)は0。capで上限。"""
    if not odds or odds <= 1.0:
        return 0.0
    f = (p * odds - 1.0) / (odds - 1.0)
    if f <= 0:
        return 0.0
    return min(cap, f * frac)


def ev(p, odds):
    return (p or 0.0) * (odds or 0.0)


# ───────────────────────── 券種ごとの買い目列挙 ─────────────────────────
def enumerate_bets(kind, axis, mates, win_p, odds_map, all_um, max_points=12):
    """kind: 'umaren'|'wide'|'trio'|'tan'|'fuku'。
    axis: 軸の馬番list、mates: 相手の馬番list。
    odds_map: 2頭/3頭=frozenset→odds、tan/fuku=umaban→odds。
    戻り: [{combo,label,prob,odds,ev,kelly}] EV降順。"""
    axis = [int(u) for u in (axis or [])]
    mates = [int(u) for u in (mates or [])]
    pool = list(dict.fromkeys(axis + mates))
    rows = []

    if kind in ('tan', 'fuku'):
        for u in pool:
            o = (odds_map or {}).get(u)
            if not o:
                continue
            pr = win_p.get(u, 0.0) if kind == 'tan' else place_prob(win_p, u, all_um)
            rows.append({'combo': (u,), 'label': f"{u}", 'prob': pr, 'odds': o,
                         'ev': ev(pr, o), 'kelly': kelly_fraction(pr, o)})
    elif kind in ('umaren', 'wide'):
        seen = set()
        pairs = []
        for a in (axis or pool):
            for b in (mates or pool):
                if a == b:
                    continue
                fs = frozenset((a, b))
                if fs in seen:
                    continue
                seen.add(fs)
                pairs.append((a, b))
        for a, b in pairs:
            o = (odds_map or {}).get(frozenset((a, b)))
            if not o:
                continue
            pr = umaren_prob(win_p, a, b) if kind == 'umaren' else wide_prob(win_p, a, b, all_um)
            x, y = sorted((a, b))
            rows.append({'combo': (x, y), 'label': f"{x}-{y}", 'prob': pr, 'odds': o,
                         'ev': ev(pr, o), 'kelly': kelly_fraction(pr, o)})
    elif kind == 'trio':
        seen = set()
        for a in axis or pool:
            base = mates or [u for u in pool if u != a]
            for b, c in combinations([u for u in (axis + base) if u != a], 2):
                trio = frozenset((a, b, c))
                if len(trio) != 3 or trio in seen:
                    continue
                seen.add(trio)
                o = (odds_map or {}).get(trio)
                if not o:
                    continue
                pr = trio_prob(win_p, *trio)
                t = tuple(sorted(trio))
                rows.append({'combo': t, 'label': '-'.join(map(str, t)), 'prob': pr, 'odds': o,
                             'ev': ev(pr, o), 'kelly': kelly_fraction(pr, o)})
    rows.sort(key=lambda r: -r['ev'])
    return rows[:max_points]


# ───────────────────────── 配分(払戻均等/ケリー) + 合成オッズ ─────────────────────────
def allocate(bets, budget, mode='kelly', unit=100, bankroll=None):
    """bets各点に購入額/払戻/トリガミを付与。
    mode='kelly'(各点ハーフケリー比×bankroll) / '払戻均等'(オッズ逆比) / '均等'。
    戻り: {'total','synthetic_odds','mode','expected_value'}。"""
    bets = [b for b in bets if b.get('odds')]
    n = len(bets)
    if not bets or not budget:
        for b in bets:
            b['stake'] = 0
        return {'total': 0, 'synthetic_odds': None, 'mode': mode, 'expected_value': None}
    budget = int(budget)
    if mode == 'kelly':
        bk = bankroll or budget
        raw = [max(0.0, b.get('kelly', 0.0)) * bk for b in bets]
        sraw = sum(raw)
        if sraw <= 0:
            raw = [budget / n] * n
            sraw = budget
        scale = min(1.0, budget / sraw) if sraw > budget else 1.0
        stakes = [max(0, int(round(r * scale / unit)) * unit) for r in raw]
    elif mode == '払戻均等':
        w = [1.0 / b['odds'] for b in bets]
        sw = sum(w) or 1.0
        stakes = [max(unit, int(round(budget * wi / sw / unit)) * unit) for wi in w]
    else:
        per = max(unit, budget // n // unit * unit)
        stakes = [per] * n
    total = sum(stakes) or 0
    exp_ret = 0.0
    for b, s in zip(bets, stakes):
        b['stake'] = s
        b['payout_if_hit'] = int(round(b['odds'] * s))
        b['toriga'] = b['payout_if_hit'] < total
        exp_ret += b.get('prob', 0.0) * b['payout_if_hit']
    inv = sum(1.0 / b['odds'] for b in bets if b['stake'] > 0)
    syn = round(total / (sum(b['stake'] / b['odds'] for b in bets if b['stake'] > 0)), 1) if inv else None
    return {'total': total, 'synthetic_odds': syn, 'mode': mode,
            'expected_value': round(exp_ret / total, 3) if total else None}
