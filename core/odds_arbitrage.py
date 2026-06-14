# -*- coding: utf-8 -*-
"""
オッズの歪み検知・資金配分最適化・抑え（カバーリング）提案モジュール。

netkeiba JSON API（api_get_jra_odds / api_get_nar_odds）から全券種のオッズを
取得し、以下を計算する:
  - 合成オッズ（複数買い目に均等払戻で資金配分した時の実効オッズ）
  - 券種間の歪み比較（馬連 vs 3連複2頭軸流し、単勝 vs 馬単1着固定流し 等）
  - 払戻均等型 / 期待値傾斜型の資金配分
  - 本線が崩れた時の抑え（タテ目プロテクション）の元返しコスト計算

オッズ辞書の形式:
  {kind: {combo(tuple): {'odds': float, 'odds_max': float|None, 'rank': int}}}
  combo は馬番タプル。win/place=(u,), quinella/wide/exacta=(a,b), trio=(a,b,c)。
  exacta のみ順序あり（1着→2着）。それ以外はソート済み。
"""
import json
import zlib
import base64
import re
import time
import logging
from itertools import combinations

logger = logging.getLogger(__name__)

# netkeiba API の type コード
ODDS_TYPE_CODES = {
    'win': '1',        # 単勝
    'place': '2',      # 複勝
    'quinella': '4',   # 馬連
    'wide': '5',       # ワイド
    'exacta': '6',     # 馬単
    'trio': '7',       # 3連複
    'trifecta': '8',   # 3連単
}

KIND_LABELS = {
    'win': '単勝', 'place': '複勝', 'quinella': '馬連',
    'wide': 'ワイド', 'exacta': '馬単', 'trio': '3連複',
    'trifecta': '3連単',
}

# 順序あり券種（combo をソートしない）
_ORDERED_KINDS = {'exacta', 'trifecta'}


def _f(v):
    """オッズ文字列 → float。'---.-' 等は 0.0"""
    try:
        s = str(v).replace(',', '').strip()
        if s in ('', '---.-', '---', '0', 'None'):
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def _parse_combo(combo_str, kind):
    """'0512' → (5, 12)。2桁刻みで分割し馬番タプルに。"""
    try:
        nums = tuple(int(combo_str[i:i + 2]) for i in range(0, len(combo_str), 2))
        if any(n <= 0 for n in nums):
            return None
        if kind not in _ORDERED_KINDS and len(nums) > 1:
            nums = tuple(sorted(nums))
        return nums
    except Exception:
        return None


def fetch_odds_kind(race_id, kind):
    """
    1券種のオッズを netkeiba API から取得。
    戻り値: {combo(tuple): {'odds': float, 'odds_max': float|None, 'rank': int}}
    """
    from core.scraper import _is_nar, get_shared_fetcher

    type_code = ODDS_TYPE_CODES[kind]
    is_nar = _is_nar(race_id)
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
    prefix = "nar" if is_nar else "jra"
    api_url = f"https://{domain}/api/api_get_{prefix}_odds.html"

    cb = f"jQuery_{int(time.time() * 1000)}"
    params = {
        "callback": cb,
        "pid": f"api_get_{prefix}_odds",
        "input": "UTF-8",
        "output": "jsonp",
        "race_id": race_id,
        "type": type_code,
        "action": "init",
        "sort": "ninki",
        "compress": "1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": f"https://{domain}/odds/index.html?type=b{type_code}&race_id={race_id}",
    }

    try:
        fetcher = get_shared_fetcher()
        if fetcher is None:
            import requests as _req
            resp_text = _req.get(api_url, params=params, headers=headers, timeout=15).text
        else:
            _resp = fetcher.get(api_url, params=params, headers=headers, timeout=15)
            if not (_resp and _resp.body):
                return {}
            resp_text = _resp.body.decode('utf-8', errors='ignore') if isinstance(_resp.body, bytes) else str(_resp.body)

        m = re.search(r'jQuery[^(]*\((.+)\)\s*$', resp_text, re.DOTALL)
        data = json.loads(m.group(1)) if m else json.loads(resp_text)

        # status='result' は確定オッズ（過去レース）。データ形式は発売中と同一なのでそのまま使う
        raw = data.get('data', '')
        if not raw or data.get('status') == 'NG':
            return {}

        if isinstance(raw, str) and len(raw) > 10:
            decoded = base64.b64decode(raw)
            try:
                decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except Exception:
                decompressed = zlib.decompress(decoded)
            odds_data = json.loads(decompressed.decode('utf-8'))
        elif isinstance(raw, dict):
            odds_data = raw
        else:
            return {}

        odds_by_type = odds_data.get('odds', odds_data)
        kind_data = odds_by_type.get(type_code, odds_by_type)
        result = {}

        if isinstance(kind_data, dict):
            for key, val in kind_data.items():
                try:
                    if isinstance(val, list) and len(val) >= 1:
                        o_min = _f(val[0])
                        o_max = _f(val[1]) if len(val) >= 2 and val[1] not in (None, '') else None
                        rank = int(val[2]) if len(val) >= 3 and str(val[2]).isdigit() else 0
                        combo_str = str(val[3]) if len(val) >= 4 and val[3] else str(key)
                    else:
                        o_min = _f(val)
                        o_max = None
                        rank = 0
                        combo_str = str(key)
                    if o_min <= 0:
                        continue
                    # combo文字列が偶数桁でなければ key を試す
                    if len(combo_str) % 2 != 0:
                        combo_str = str(key)
                    combo = _parse_combo(combo_str, kind)
                    if combo is None:
                        continue
                    result[combo] = {
                        'odds': o_min,
                        'odds_max': (o_max if o_max and o_max > 0 else None),
                        'rank': rank,
                    }
                except Exception:
                    continue

        if result:
            logger.info(f"[OddsArb] {kind}({type_code}): {len(result)}組 取得 ({race_id})")
        return result

    except Exception as e:
        logger.warning(f"[OddsArb] {kind} 取得失敗 ({race_id}): {e}")
        return {}


def fetch_all_odds(race_id, kinds=('win', 'place', 'quinella', 'wide', 'exacta', 'trio', 'trifecta')):
    """全券種のオッズをまとめて取得。失敗した券種は空dict。"""
    out = {}
    for kind in kinds:
        out[kind] = fetch_odds_kind(race_id, kind)
        time.sleep(0.3)  # API連打防止
    return out


# ──────────────────────────────────────────────
# 合成オッズ・資金配分
# ──────────────────────────────────────────────

def synthetic_odds(odds_list):
    """合成オッズ = 1 / Σ(1/o)。払戻均等配分時の実効オッズ。"""
    inv = sum(1.0 / o for o in odds_list if o and o > 0)
    return round(1.0 / inv, 2) if inv > 0 else 0.0


def allocate_equal_payout(combo_odds, budget, unit=100):
    """
    払戻均等型配分（ガミり防止）。どれが当たってもほぼ同額の払戻になるよう
    1/オッズ比例で配分。
    combo_odds: {combo: odds}
    戻り値: (rows, summary)
      rows: [{'combo', 'odds', 'stake', 'payout', 'profit'}]
      summary: {'total', 'min_payout', 'min_profit', 'synthetic'}
    """
    valid = {c: o for c, o in combo_odds.items() if o and o > 0}
    if not valid or budget < unit:
        return [], {}
    inv_sum = sum(1.0 / o for o in valid.values())
    rows = []
    total = 0
    for c, o in sorted(valid.items(), key=lambda x: x[1]):
        raw = budget * (1.0 / o) / inv_sum
        stake = max(unit, int(raw // unit) * unit)
        rows.append({'combo': c, 'odds': o, 'stake': stake})
        total += stake
    # 予算オーバー時は高オッズ側（stake最小側）から削る
    rows_sorted = sorted(rows, key=lambda r: r['stake'])
    i = 0
    while total > budget and i < len(rows_sorted) * 4:
        r = rows_sorted[i % len(rows_sorted)]
        if r['stake'] > unit:
            r['stake'] -= unit
            total -= unit
        i += 1
    for r in rows:
        r['payout'] = int(r['stake'] * r['odds'])
        r['profit'] = r['payout'] - total
    summary = {
        'total': total,
        'min_payout': min(r['payout'] for r in rows),
        'min_profit': min(r['profit'] for r in rows),
        'synthetic': synthetic_odds(list(valid.values())),
    }
    return rows, summary


def allocate_ev_weighted(combo_odds, combo_probs, budget, unit=100):
    """
    期待値傾斜型配分。EV=prob×odds が 1.0 超の買い目に prob×(EV-1) 比例で厚く配分
    （ケリー基準の簡易版）。EV<=1 の買い目は最小単位のみ。
    combo_probs: {combo: 推定的中確率(0-1)}
    """
    valid = {c: o for c, o in combo_odds.items() if o and o > 0}
    if not valid or budget < unit:
        return [], {}
    weights = {}
    for c, o in valid.items():
        p = combo_probs.get(c, 0.0)
        ev = p * o
        # ケリー比率: f = (p*o - 1) / (o - 1)。マイナスは0
        kelly = max(0.0, (ev - 1.0) / (o - 1.0)) if o > 1 else 0.0
        weights[c] = kelly
    w_sum = sum(weights.values())
    rows = []
    total = 0
    if w_sum <= 0:
        # 全買い目EVマイナス → 均等で最小確認だけ
        for c, o in sorted(valid.items(), key=lambda x: x[1]):
            rows.append({'combo': c, 'odds': o, 'stake': unit,
                         'ev': round(combo_probs.get(c, 0.0) * o, 2)})
            total += unit
    else:
        for c, o in sorted(valid.items(), key=lambda x: -weights[x[0]]):
            raw = budget * weights[c] / w_sum
            stake = int(raw // unit) * unit
            if stake < unit:
                continue
            rows.append({'combo': c, 'odds': o, 'stake': stake,
                         'ev': round(combo_probs.get(c, 0.0) * o, 2)})
            total += stake
    for r in rows:
        r['payout'] = int(r['stake'] * r['odds'])
        r['profit'] = r['payout'] - total
    summary = {
        'total': total,
        'synthetic': synthetic_odds([r['odds'] for r in rows]) if rows else 0.0,
    }
    return rows, summary


# ──────────────────────────────────────────────
# 確率推定（Harvilleモデル）
# ──────────────────────────────────────────────

def estimate_win_probs(all_odds):
    """単勝オッズ → 市場含意の勝率分布（控除率を正規化で除去）。{umaban: p}"""
    win = all_odds.get('win', {})
    inv = {c[0]: 1.0 / v['odds'] for c, v in win.items() if v['odds'] > 0}
    s = sum(inv.values())
    return {u: x / s for u, x in inv.items()} if s > 0 else {}


def estimate_win_probs_from_scores(scores, gamma=2.0):
    """
    アプリの指数（強適/U指数/BattleScore等）→ 勝率分布。
    市場オッズ由来の確率だと EV≒払戻率で一定になり期待値比較が無意味になるため、
    自前モデルの確率を使うことで「市場とモデルの乖離」= 妙味 を検出できる。
    scores: {umaban: スコア値}。gamma: 傾斜（大きいほど上位に集中）。
    """
    vals = {u: s for u, s in scores.items() if s is not None}
    if not vals:
        return {}
    mn = min(vals.values())
    # 最下位馬にもわずかな確率を残すため +5% シフト
    rng = max(vals.values()) - mn
    shift = rng * 0.05 if rng > 0 else 1.0
    powed = {u: ((s - mn + shift) ** gamma) for u, s in vals.items()}
    total = sum(powed.values())
    return {u: p / total for u, p in powed.items()} if total > 0 else {}


def combo_prob(win_probs, combo, kind):
    """
    Harvilleモデルで各券種の的中確率を推定。
    win_probs: {umaban: 勝率}
    """
    p = win_probs

    def _ex(a, b):  # a が1着, b が2着
        pa, pb = p.get(a, 0.0), p.get(b, 0.0)
        return pa * pb / (1.0 - pa) if pa < 1.0 else 0.0

    def _trifecta(a, b, c):  # a→b→c
        pa, pb, pc = p.get(a, 0.0), p.get(b, 0.0), p.get(c, 0.0)
        if pa >= 1.0 or (pa + pb) >= 1.0:
            return 0.0
        return pa * (pb / (1.0 - pa)) * (pc / (1.0 - pa - pb))

    if kind == 'win':
        return p.get(combo[0], 0.0)
    if kind == 'place':  # 3着内: Harville展開の近似（上位3着合算は重いので簡易係数）
        pw = p.get(combo[0], 0.0)
        return min(1.0, pw * 2.8)
    if kind == 'exacta':
        return _ex(combo[0], combo[1])
    if kind == 'quinella':
        a, b = combo
        return _ex(a, b) + _ex(b, a)
    if kind == 'wide':  # 2頭とも3着内: 3連複合算が正確だが、簡易に馬連確率×2.4
        a, b = combo
        return min(1.0, (_ex(a, b) + _ex(b, a)) * 2.4)
    if kind == 'trio':
        from itertools import permutations
        return sum(_trifecta(x, y, z) for x, y, z in permutations(combo))
    return 0.0


# ──────────────────────────────────────────────
# 券種間の歪み比較
# ──────────────────────────────────────────────

def compare_quinella_vs_trio_axis(all_odds, axis_a, axis_b):
    """
    馬連(a-b) vs 3連複2頭軸(a,b)総流し の比較。
    3連複側は軸2頭を含む全組み合わせへの払戻均等配分＝合成オッズで評価。
    戻り値: dict（quinella_odds, trio_synthetic, trio_count, verdict, wide_odds 等）
    """
    q = all_odds.get('quinella', {})
    t = all_odds.get('trio', {})
    w = all_odds.get('wide', {})
    pair = tuple(sorted((axis_a, axis_b)))
    q_odds = q.get(pair, {}).get('odds', 0.0)
    w_odds = w.get(pair, {}).get('odds', 0.0)

    trio_sub = {c: v['odds'] for c, v in t.items() if axis_a in c and axis_b in c and v['odds'] > 0}
    t_syn = synthetic_odds(list(trio_sub.values())) if trio_sub else 0.0

    verdict = None
    if q_odds > 0 and t_syn > 0:
        if q_odds > t_syn:
            verdict = 'quinella'  # 馬連の方が得
        else:
            verdict = 'trio'
    return {
        'pair': pair,
        'quinella_odds': q_odds,
        'wide_odds': w_odds,
        'trio_synthetic': t_syn,
        'trio_count': len(trio_sub),
        'trio_sub': trio_sub,
        'verdict': verdict,
    }


def compare_win_vs_exacta_first(all_odds, axis):
    """
    単勝(a) vs 馬単(a→総流し) の比較。
    馬単側は a が1着の全組み合わせの合成オッズ。
    """
    win = all_odds.get('win', {})
    ex = all_odds.get('exacta', {})
    w_odds = win.get((axis,), {}).get('odds', 0.0)

    ex_sub = {c: v['odds'] for c, v in ex.items() if c[0] == axis and v['odds'] > 0}
    ex_syn = synthetic_odds(list(ex_sub.values())) if ex_sub else 0.0

    verdict = None
    if w_odds > 0 and ex_syn > 0:
        verdict = 'win' if w_odds >= ex_syn else 'exacta'
    return {
        'axis': axis,
        'win_odds': w_odds,
        'exacta_synthetic': ex_syn,
        'exacta_count': len(ex_sub),
        'exacta_sub': ex_sub,
        'verdict': verdict,
    }


def compare_trio_vs_trifecta_multi(all_odds, a, b, c, win_probs=None):
    """
    3連複1点 (a,b,c) vs 3連単マルチ6点 vs 1着固定2点 の比較。
    3つともカバー範囲は「a,b,cが3着内（固定系は1着条件付き）」で、的中条件が同じか
    狭くなる方向のみ。買い目を増やさず「どの形で買うのが一番得か」を1つ推奨する。

    win_probs: {umaban: 勝率}（強適スコア等のモデル確率）。指定時は
      ・各並び順の的中確率(Harville)
      ・1着候補の確信度に基づく「1着固定2点」絞り提案
    を含めて判定。

    戻り値 dict:
      trio_odds, multi_synthetic, multi_perms{order:odds},
      fixed_best{first, perms, synthetic, prob_share}（win_probs時のみ）,
      verdict('trio'|'multi'|'fixed'), reasons[list]
    """
    from itertools import permutations
    trio = all_odds.get('trio', {})
    tft = all_odds.get('trifecta', {})
    combo = tuple(sorted((a, b, c)))
    trio_odds = trio.get(combo, {}).get('odds', 0.0)

    perms = {}
    for order in permutations((a, b, c)):
        v = tft.get(order)
        if v and v['odds'] > 0:
            perms[order] = v['odds']

    multi_syn = synthetic_odds(list(perms.values())) if len(perms) == 6 else 0.0

    result = {
        'combo': combo,
        'trio_odds': trio_odds,
        'multi_synthetic': multi_syn,
        'multi_perms': perms,
        'fixed_best': None,
        'verdict': None,
        'reasons': [],
    }

    # ── モデル確率があれば1着固定の絞り判定 ──
    order_probs = {}
    if win_probs:
        p = win_probs
        for (x, y, z) in perms.keys():
            px, py, pz = p.get(x, 0.0), p.get(y, 0.0), p.get(z, 0.0)
            if px < 1.0 and (px + py) < 1.0:
                order_probs[(x, y, z)] = px * (py / (1.0 - px)) * (pz / (1.0 - px - py))
        total_p = sum(order_probs.values())
        if total_p > 0 and len(perms) == 6:
            # 1着馬ごとの確率シェア
            first_share = {}
            for u in (a, b, c):
                share = sum(pr for o, pr in order_probs.items() if o[0] == u) / total_p
                first_share[u] = share
            best_first, best_share = max(first_share.items(), key=lambda x: x[1])
            fixed_perms = {o: perms[o] for o in perms if o[0] == best_first}
            fixed_syn = synthetic_odds(list(fixed_perms.values()))
            result['fixed_best'] = {
                'first': best_first,
                'perms': fixed_perms,
                'synthetic': fixed_syn,
                'prob_share': best_share,
                'first_share': first_share,
            }

    # ── 判定 ──
    # 原則: 同一カバーなら合成オッズが高い方。1着固定はモデル確信度60%以上の時のみ提案
    if trio_odds > 0 and multi_syn > 0:
        fixed = result['fixed_best']
        if fixed and fixed['prob_share'] >= 0.60 and fixed['synthetic'] > trio_odds and fixed['synthetic'] > multi_syn:
            result['verdict'] = 'fixed'
            result['reasons'].append(
                f"モデル上、{fixed['first']}番が1着になる確率がこの3頭決着内の{fixed['prob_share']:.0%}を占める。"
                f"1着固定2点の合成{fixed['synthetic']:.1f}倍 ＞ マルチ6点{multi_syn:.1f}倍 ＞ 3連複{trio_odds:.1f}倍。"
                f"点数も6点→2点に減る。"
            )
        elif trio_odds >= multi_syn:
            result['verdict'] = 'trio'
            result['reasons'].append(
                f"3連複1点（{trio_odds:.1f}倍）≧ 3連単マルチ6点の合成（{multi_syn:.1f}倍）。"
                f"同じ的中条件なら3連複1点が最も効率的（点数最小・トリガミなし）。"
            )
        else:
            result['verdict'] = 'multi'
            result['reasons'].append(
                f"3連単マルチ6点の合成（{multi_syn:.1f}倍）＞ 3連複1点（{trio_odds:.1f}倍）。"
                f"3連単側に歪みあり。ただし均等買いではなく払戻均等配分を推奨。"
            )
        if fixed and result['verdict'] != 'fixed' and fixed['prob_share'] >= 0.50:
            result['reasons'].append(
                f"参考: {fixed['first']}番1着固定2点なら合成{fixed['synthetic']:.1f}倍"
                f"（モデル確信度{fixed['prob_share']:.0%}）。確信があるなら絞る選択肢も。"
            )
    elif trio_odds > 0:
        result['verdict'] = 'trio'
        result['reasons'].append("3連単オッズが取得できないため3連複のみ評価。")

    return result


def scan_quinella_wide_inversion(all_odds, min_ratio=0.85):
    """
    ワイドオッズ(下限)が馬連オッズの min_ratio 以上ある「逆転・接近」ペアを検出。
    ワイドは3着内2頭でOKなのに配当が馬連に近い＝ワイドが過剰に美味しいペア。
    """
    q = all_odds.get('quinella', {})
    w = all_odds.get('wide', {})
    findings = []
    for pair, qv in q.items():
        wv = w.get(pair)
        if not wv:
            continue
        qo, wo = qv['odds'], wv['odds']
        if qo > 0 and wo > 0 and (wo / qo) >= min_ratio:
            findings.append({
                'pair': pair, 'quinella_odds': qo, 'wide_odds': wo,
                'ratio': round(wo / qo, 2),
            })
    findings.sort(key=lambda x: -x['ratio'])
    return findings


def scan_all_distortions(all_odds, top_k=8, min_advantage=0.10):
    """
    レース内の券種間歪みを全自動スキャンしてランキングで返す。
    対象:
      1. 馬連 vs 3連複2頭軸（人気上位 top_k 頭の全ペア）
      2. 単勝 vs 馬単1着固定（人気上位 top_k 頭）
      3. ワイド/馬連 接近ペア
    min_advantage: この割合以上の優位がある歪みのみ報告（0.10 = 10%）。
    戻り値: [{'category', 'description', 'advantage', 'detail'}] advantage降順。
    """
    findings = []
    win = all_odds.get('win', {})
    top_horses = sorted(
        (c[0] for c in win.keys() if win[c]['odds'] > 0),
        key=lambda u: win[(u,)]['odds']
    )[:top_k]

    # 1. 馬連 vs 3連複2頭軸
    if all_odds.get('quinella') and all_odds.get('trio'):
        for a, b in combinations(top_horses, 2):
            cmp = compare_quinella_vs_trio_axis(all_odds, a, b)
            qo, ts = cmp['quinella_odds'], cmp['trio_synthetic']
            if qo <= 0 or ts <= 0:
                continue
            if qo > ts * (1 + min_advantage):
                adv = qo / ts - 1
                findings.append({
                    'category': '馬連>3連複軸',
                    'description': f"馬連 {a}-{b}（{qo:.1f}倍）が3連複2頭軸合成（{ts:.1f}倍）より{adv:.0%}高効率",
                    'advantage': adv,
                    'detail': cmp,
                })
            elif ts > qo * (1 + min_advantage):
                adv = ts / qo - 1
                findings.append({
                    'category': '3連複軸>馬連',
                    'description': f"3連複2頭軸 {a}-{b} 合成（{ts:.1f}倍）が馬連（{qo:.1f}倍）より{adv:.0%}おいしい",
                    'advantage': adv,
                    'detail': cmp,
                })

    # 2. 単勝 vs 馬単1着固定
    n_starters = len(win)
    if all_odds.get('exacta'):
        for u in top_horses:
            cmp = compare_win_vs_exacta_first(all_odds, u)
            wo, es = cmp['win_odds'], cmp['exacta_synthetic']
            if wo <= 0 or es <= 0:
                continue
            # 馬単データが欠けていると合成が過大評価される → 総流し分が揃っている時のみ判定
            if cmp['exacta_count'] < n_starters - 1:
                continue
            if es > wo * (1 + min_advantage):
                adv = es / wo - 1
                findings.append({
                    'category': '馬単>単勝',
                    'description': f"馬番{u} 馬単1着固定合成（{es:.1f}倍）が単勝（{wo:.1f}倍）より{adv:.0%}おいしい",
                    'advantage': adv,
                    'detail': cmp,
                })
            elif wo > es * (1 + min_advantage):
                adv = wo / es - 1
                findings.append({
                    'category': '単勝>馬単',
                    'description': f"馬番{u} 単勝（{wo:.1f}倍）が馬単総流し合成（{es:.1f}倍）より{adv:.0%}高効率",
                    'advantage': adv,
                    'detail': cmp,
                })

    # 3. ワイド/馬連 接近
    for f in scan_quinella_wide_inversion(all_odds, min_ratio=0.80):
        findings.append({
            'category': 'ワイド≒馬連',
            'description': f"ペア {f['pair'][0]}-{f['pair'][1]}: ワイド（{f['wide_odds']:.1f}倍）が馬連（{f['quinella_odds']:.1f}倍）の{f['ratio']:.0%}。ワイド優位",
            'advantage': f['ratio'],
            'detail': f,
        })

    findings.sort(key=lambda x: -x['advantage'])
    return findings


_COVER_THRESHOLDS = {
    # (見送り推奨しきい値, 得意レース認定しきい値)
    # 1枚まともな買い目のカバー率から逆算した券種別適正値
    'win':       (0.20, 0.40),
    'place':     (0.30, 0.55),
    'quinella':  (0.10, 0.25),
    'wide':      (0.15, 0.35),
    'exacta':    (0.08, 0.18),
    'trio':      (0.06, 0.15),
    'trifecta':  (0.02, 0.07),
}


def concierge_review(rows, kind, combo_probs=None, budget=None, bankroll=None):
    """
    馬券コンシェルジュ診断。成功している馬券購入者に共通する「型」
    （点数を絞る・期待値プラスのみ買う・資金管理・見送りも戦略）をルール化し、
    現在の買い目プランを採点してアドバイスを返す。

    rows: allocate_* の出力（combo/odds/stake/payout 含む）
    combo_probs: {combo: モデル的中確率}（あれば期待値・カバー率診断が有効になる）
    budget: 今回の投資額。bankroll: 総資金（あれば資金管理診断）。
    戻り値: {'grade': 'S'|'A'|'B'|'C', 'label': str, 'advice': list, 'cover': float|None}
    """
    advice = []
    if not rows:
        return {'grade': '-', 'label': '-', 'advice': [], 'cover': None}
    n = len(rows)
    odds_list = [r['odds'] for r in rows]
    syn = synthetic_odds(odds_list)
    total = sum(r['stake'] for r in rows)
    score = 100

    cover_warn, cover_good = _COVER_THRESHOLDS.get(kind, (0.10, 0.25))

    # 1. 点数過多（勝ち組は点数を絞る。広げるほど控除率を多重に払う）
    if n > 10:
        advice.append({'level': 'warn', 'icon': '✂️',
                       'msg': f"点数{n}点は多すぎます。成功者の多くは1レース10点以下。自信のない目を削るほど回収率は上がります。"})
        score -= 20
    elif n <= 3:
        advice.append({'level': 'good', 'icon': '👍',
                       'msg': f"点数{n}点。絞れています（勝ち組の型）。"})

    # 2. 合成オッズ（実効リターン）
    if syn < 1.0:
        advice.append({'level': 'bad', 'icon': '🚨',
                       'msg': f"合成オッズ{syn:.2f}倍＝全的中でも損失確定。この形では買ってはいけません。"})
        score -= 50
    elif syn < 2.0:
        advice.append({'level': 'warn', 'icon': '⚠️',
                       'msg': f"合成オッズ{syn:.2f}倍。当たっても2倍未満＝2回に1回以上当て続けないと赤字。的中率に自信がなければ絞るか見送りを。"})
        score -= 15

    # 3. 期待値・カバー率（成功者はEVプラスの目しか買わない）
    cover = None
    if combo_probs:
        ev_minus = [(r['combo'], combo_probs.get(r['combo'], 0) * r['odds'])
                    for r in rows if combo_probs.get(r['combo'], 0) * r['odds'] < 1.0]
        cover = sum(combo_probs.get(r['combo'], 0) for r in rows)
        if ev_minus:
            combos_s = ", ".join("-".join(str(x) for x in c) for c, _ in ev_minus[:5])
            advice.append({'level': 'warn', 'icon': '📉',
                           'msg': f"期待値1.0未満の買い目が{len(ev_minus)}点あります（{combos_s}…）。長期回収率を下げる目。削る候補です。"})
            score -= 5 * min(len(ev_minus), 4)
        else:
            advice.append({'level': 'good', 'icon': '💎',
                           'msg': "全買い目が期待値プラス。理想形です。"})
        if cover < cover_warn:
            advice.append({'level': 'warn', 'icon': '🎲',
                           'msg': f"的中カバー率{cover:.1%}（{KIND_LABELS.get(kind, kind)}の見送り基準: {cover_warn:.0%}）＝モデルが捉えにくい混戦。**見送りも買い方のうち**（成功者はレースを選びます）。"})
            score -= 15
        elif cover >= cover_good:
            advice.append({'level': 'good', 'icon': '🎯',
                           'msg': f"的中カバー率{cover:.1%}。モデルの得意なレースです。"})

    # 4. 低オッズ買い（1.5倍未満の単複は控除率の壁で長期マイナスになりやすい）
    low = [r for r in rows if r['odds'] < 1.5]
    if low and kind in ('win', 'place'):
        advice.append({'level': 'warn', 'icon': '🧱',
                       'msg': "1.5倍未満のオッズは控除率(20-25%)の壁で長期プラスがほぼ不可能なゾーン。バックテストでも1番人気ベタ買いは回収率76.8%でした。"})
        score -= 10

    # 5. 資金管理（1レースに総資金の5%超はケリー基準的に過大）
    if bankroll and bankroll > 0 and total > 0:
        ratio = total / bankroll
        if ratio > 0.10:
            advice.append({'level': 'bad', 'icon': '💸',
                           'msg': f"総資金の{ratio:.0%}を1レースに投入は過大（破産リスク域）。成功者は1レース1〜5%。"})
            score -= 25
        elif ratio > 0.05:
            advice.append({'level': 'warn', 'icon': '💰',
                           'msg': f"総資金の{ratio:.0%}。やや厚め。連敗時に耐えられる範囲か確認を。"})
            score -= 8
        else:
            advice.append({'level': 'good', 'icon': '🏦',
                           'msg': f"総資金の{ratio:.1%}。健全な資金管理です。"})

    # ハードキャップ: スコア合算後に強制格下げ（「A判定＝買っていい」の誤解を防ぐ）
    has_ev_minus = combo_probs and any(
        combo_probs.get(r['combo'], 0) * r['odds'] < 1.0 for r in rows
    )

    raw_grade = 'S' if score >= 95 else 'A' if score >= 80 else 'B' if score >= 60 else 'C'

    if cover is not None and cover < cover_warn:
        grade = 'C'
        label = 'C（見送り推奨）'
    elif has_ev_minus:
        grade = max(raw_grade, 'B', key=lambda g: 'SABC'.index(g))
        label = f'{grade}（要調整）' if grade != 'C' else 'C（要改善）'
    else:
        grade = raw_grade
        label = {'S': 'S（理想形）', 'A': 'A（良好）', 'B': 'B（要調整）', 'C': 'C（要改善）'}[grade]

    return {'grade': grade, 'label': label, 'advice': advice, 'cover': cover}


def build_bet_sheet_text(rows, kind):
    """資金配分結果を投票メモ用テキストに整形。"""
    label = KIND_LABELS.get(kind, kind)
    lines = [f"=== {label} 買い目シート ==="]
    total = 0
    for r in rows:
        combo = "-".join(str(x) for x in r['combo'])
        lines.append(f"{label} {combo} {r['stake']:,}円 (オッズ{r['odds']:.1f} 払戻{r['payout']:,}円)")
        total += r['stake']
    lines.append(f"合計 {total:,}円")
    return "\n".join(lines)


def suggest_protection(all_odds, main_total, axis_a, axis_b, partners, unit=100):
    """
    タテ目の抑え提案。
    本線=軸2頭(a,b)で総額 main_total 円投資している時、
    軸の片方が飛んで相手馬同士で決着するケース（partners同士の馬連）について、
    元返し（本線投資額の回収）に必要な購入額を計算。
    戻り値: [{'pair', 'odds', 'stake', 'payout', 'note'}] オッズ降順（安く抑えられる順）
    """
    q = all_odds.get('quinella', {})
    rows = []
    for pa, pb in combinations(sorted(set(partners) - {axis_a, axis_b}), 2):
        pair = tuple(sorted((pa, pb)))
        v = q.get(pair)
        if not v or v['odds'] <= 0:
            continue
        odds = v['odds']
        # 元返し: stake * odds >= main_total + stake → stake >= main_total/(odds-1)
        if odds <= 1.0:
            continue
        need = main_total / (odds - 1.0)
        stake = max(unit, int(-(-need // unit)) * unit)  # ceil to unit
        rows.append({
            'pair': pair,
            'odds': odds,
            'stake': stake,
            'payout': int(stake * odds),
            'cost_ratio': round(stake / main_total, 2) if main_total > 0 else 0.0,
        })
    rows.sort(key=lambda r: r['stake'])
    return rows
