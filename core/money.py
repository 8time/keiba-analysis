# -*- coding: utf-8 -*-
"""
資金管理ライブラリ（BetSync 配線用の正本）

⑤「資金管理システムで長期回収率を上げる」の数理コア。
Streamlit/予測モデルから `from core import money` で読む想定。
（scripts/kelly.py・scripts/betting_ledger.py は本モジュールを import する薄いデモ）

収録:
- kelly_multi        : 多肢選択ケリー（同一レース単勝への同時賭け）
- ruin_probability   : 繰り返し賭けの破産確率（モンテカルロ）
- bankroll_cap       : 1レース上限 = 現在残高の X%（鉄則）
- session_guard      : セッション損切り / 利確の自動判定（感情の遮断）
- Ledger             : 収支台帳（予測→賭け→結果→ROI/Brier/反省）

理論的裏付け:
- Whelan (2025) 多排他事象の最適ベット
- Smoczyński & Tomkins (2010) 競馬同時単勝ケリーの閉形式
"""
import os
import math
import random
import sqlite3
import datetime

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DB = os.path.join(_BASE, 'data', 'ledger.db')


# ──────────────────────────────────────────────
# ① 多肢選択ケリー
# ──────────────────────────────────────────────
def kelly_multi(horses, kelly_fraction=1.0):
    """
    多肢選択ケリー（同一レース単勝への同時賭け）。
    horses: [{'umaban','p','odds'}, ...]  p=勝率(0-1), odds=単勝払戻倍率(例3.5)
    kelly_fraction: 1.0=フルケリー, 0.25=1/4ケリー（推奨）
    戻り: {'bets':[{umaban,p,odds,ev,frac}], 'cash':現金比率, 'sum_bet':賭け総比率,
           'reserve_rate':R, 'exp_log_growth':期待対数成長率}
    """
    cand = [h for h in horses if h.get('p', 0) > 0 and h.get('odds', 0) > 1]
    cand.sort(key=lambda h: h['p'] * h['odds'], reverse=True)

    # Smoczyński-Tomkins: 追加してもなお p*o > 留保レートR を満たす間だけ含める
    P = 0.0; S = 0.0; chosen = []
    for h in cand:
        P2 = P + h['p']; S2 = S + 1.0 / h['odds']
        if S2 >= 1.0:
            break
        R2 = (1.0 - P2) / (1.0 - S2)
        if h['p'] * h['odds'] > R2:
            P, S = P2, S2
            chosen.append(h)
        else:
            break
    R = (1.0 - P) / (1.0 - S) if S < 1.0 else 1.0

    bets = []
    for h in chosen:
        f_full = max(0.0, h['p'] - R / h['odds'])
        f = f_full * kelly_fraction
        bets.append({'umaban': h['umaban'], 'p': h['p'], 'odds': h['odds'],
                     'ev': round(h['p'] * h['odds'], 3), 'frac': f})
    sum_bet = sum(b['frac'] for b in bets)
    cash = 1.0 - sum_bet

    # 期待対数成長率（フルケリー基準・参考値）
    fr = {h['umaban']: max(0.0, h['p'] - R / h['odds']) for h in chosen}
    cash_full = 1.0 - sum(fr.values())
    P_all = sum(h['p'] for h in chosen)
    g = 0.0
    for h in chosen:
        wealth_if_win = cash_full + fr[h['umaban']] * h['odds']
        if wealth_if_win > 0:
            g += h['p'] * math.log(wealth_if_win)
    if cash_full > 0:
        g += (1.0 - P_all) * math.log(cash_full)

    return {'bets': bets, 'cash': cash, 'sum_bet': sum_bet,
            'reserve_rate': R, 'exp_log_growth': g}


# ──────────────────────────────────────────────
# ② 破産確率（モンテカルロ）
# ──────────────────────────────────────────────
def ruin_probability(p, odds, kelly_fraction=0.25, n_bets=1000, ruin_level=0.3,
                     trials=2000, start=1.0, seed=0):
    """
    勝率p・オッズodds・指定ケリー率の繰り返し賭けを n_bets 回続けた場合に、
    資金が start×ruin_level 以下へ落ちる確率をモンテカルロ推定。穴馬の非対称リスク可視化用。
    """
    f_full = max(0.0, p - (1.0 - p) / (odds - 1.0))
    f = f_full * kelly_fraction
    if f <= 0:
        return {'bet_fraction': 0.0, 'ruin_prob': 0.0, 'note': 'EV<=0またはf<=0で賭けない'}
    rng = random.Random(seed)
    ruin = 0
    finals = []
    for _ in range(trials):
        w = start
        busted = False
        for _ in range(n_bets):
            if rng.random() < p:
                w *= (1 + f * (odds - 1))
            else:
                w *= (1 - f)
            if w <= start * ruin_level:
                busted = True; break
        if busted:
            ruin += 1
        finals.append(w)
    finals.sort()
    return {'bet_fraction': round(f, 4), 'ruin_prob': ruin / trials,
            'median_final': round(finals[len(finals) // 2], 3),
            'p5_final': round(finals[int(trials * 0.05)], 3)}


# ──────────────────────────────────────────────
# ③ バンクロール上限（鉄則: 1レース = 残高の1〜5%）
# ──────────────────────────────────────────────
def bankroll_cap(balance, pct=2.0, unit=100):
    """
    現在残高 balance に対する 1レース投資上限を返す。
    pct: 上限割合(%)。鉄則は1〜5%（保守=1〜2 / 標準=2〜3 / 攻め=5）。
    unit: 馬券単位(円)で切り下げ。
    戻り: {'cap':上限円(unit切り下げ), 'cap_raw':切り下げ前, 'pct':pct}
    """
    raw = balance * pct / 100.0
    cap = int(raw // unit) * unit
    return {'cap': max(0, cap), 'cap_raw': raw, 'pct': pct}


def cap_check(next_bet, balance, pct=2.0, unit=100):
    """
    進行系が出した次回ベット next_bet が上限を超えていないか判定。
    戻り: {'ok':bool, 'cap':上限, 'over':超過額, 'bet_pct':残高比%, 'recommended':推奨ベット}
    """
    bc = bankroll_cap(balance, pct=pct, unit=unit)
    cap = bc['cap']
    over = max(0, next_bet - cap)
    bet_pct = (next_bet / balance * 100.0) if balance > 0 else 0.0
    return {'ok': next_bet <= cap, 'cap': cap, 'over': over,
            'bet_pct': bet_pct, 'recommended': min(next_bet, cap), 'pct': pct}


def dutch_stakes(legs, budget, unit=100):
    """ダッチング(均等回収)配分。複数馬に賭けて『どれが的中しても同額戻る』配分を返す。

    legs: [{'um':馬番, 'odds':複勝/単勝オッズ(倍)}, ...]（オッズは的中時の払戻倍率）。
    budget: 総予算(円)。unit: 馬券単位(円)で各stakeを丸める。

    ★重要: これは+EVを作らない。合成回収率(payout_ratio)が100%未満なら賭けるほど負ける。
    的中率を上げて分散(資金曲線のブレ)を下げるための"買い方"であって、儲けの魔法ではない。

    戻り: {
      'stakes': [{'um','odds','stake','payout','ret_pct'}...],  # 各馬のstakeと的中時払戻
      'total': 実際の総投資(unit丸め後),
      'payout_ratio': 合成回収率(=どれか的中時の払戻/総投資・<1なら-EV),
      'implied_hit': 合成的中率の目安(=Σ1/odds・>1なら全通り買い過ぎ=不成立),
      'note': 説明,
    }
    合成的中率 Σ(1/odds) >= 1 のときはダッチング不成立(オッズ的に均等回収で利益が出ない/
    そもそも全馬の勝率合計が1超=矛盾)。その場合は payout_ratio<=1 を返し note で警告。
    """
    legs = [l for l in (legs or []) if l.get('odds') and float(l['odds']) > 0]
    if not legs or budget <= 0:
        return {'stakes': [], 'total': 0, 'payout_ratio': 0.0,
                'implied_hit': 0.0, 'note': '対象馬なし'}
    inv_sum = sum(1.0 / float(l['odds']) for l in legs)   # Σ(1/oi)
    # 各馬の理想stake比 = (1/oi) / Σ(1/oi)。均等回収になる配分。
    raw = [(budget * (1.0 / float(l['odds'])) / inv_sum) for l in legs]
    stakes = [max(unit, int(round(s / unit)) * unit) for s in raw]  # unit丸め(最低1単位)
    total = sum(stakes)
    out_legs = []
    payouts = []
    for l, s in zip(legs, stakes):
        po = s * float(l['odds'])            # この馬が的中したときの払戻
        payouts.append(po)
        out_legs.append({'um': l.get('um'), 'odds': float(l['odds']), 'stake': s,
                         'payout': int(po), 'ret_pct': round(po / total * 100, 1) if total else 0.0})
    # payout_ratio = 『どれか1頭が的中したときの戻り/総投資』(条件付き回収率)。
    # 均等配分なので各馬の払戻はほぼ同額 → 保守的に最小払戻/総投資。
    payout_ratio = (min(payouts) / total) if (total and payouts) else 0.0
    hit_pct = inv_sum * 100.0    # 市場想定のヒット率(Σ1/o・控除率で上振れ気味)
    if inv_sum >= 1.0:
        # 複勝を3頭など=Σ1/o≥1: 的中しても総投資割れ(トリガミ)が確定
        note = (f"⚠トリガミ確定(Σ1/オッズ={inv_sum:.2f}≥1)。"
                f"どれか来ても戻りは{payout_ratio*100:.0f}%＝必ず負ける組合せ。")
    else:
        # 単勝で人気馬を数頭=Σ1/o<1: 的中時は{payout_ratio}%戻るが、来る確率は約{hit_pct}%。
        # 控除率(約20-25%)ぶん-EVなのは変わらない(市場効率的)。
        note = (f"どれか来れば戻り{payout_ratio*100:.0f}%／来る確率は市場想定で約{hit_pct:.0f}%。"
                "的中率を上げて分散を下げる買い方で、控除率ぶん-EVなのは変わりません(儲けの魔法ではない)。")
    return {'stakes': out_legs, 'total': total,
            'payout_ratio': round(payout_ratio, 4),
            'implied_hit': round(inv_sum, 4),
            'hit_pct': round(hit_pct, 1), 'note': note}


# ──────────────────────────────────────────────
# ③b 帯別ステーク助言（買い方研究の実配当ROIに基づく資金配分・見送り）
# ──────────────────────────────────────────────
# 検証済み実配当ROI(verified_formation_roi・scripts/formation_pointopt.py・帯ごとの最良買い方):
#   堅(book) 74% / 中(wide) 85% / 荒れ(wide) 81%。全帯<100%=負EV。
#   →ケリーは「賭けない」が正解だが、賭けるなら『損の最も少ない中波乱に厚く/最悪の帯は薄く or 見送り』。
_BAND_ROI = {'tight': 0.74, 'mid': 0.85, 'arare': 0.81}
_BAND_LABEL = {'tight': '堅い(book少点)', 'mid': '中波乱(wide/最良)', 'arare': '荒れ(wide広角)'}


def formation_stake_advice(arare_prob, bankroll, entertainment_pct=2.0, unit=100):
    """荒れ確率→帯別の3連単ステーク助言。3連単は全帯で負EV(実配当検証)なので、
    上限=残高×entertainment_pct内で『損の最も少ない中波乱に厚く/最悪帯は薄く』配分し、
    floor(75%)未満の帯は見送りを促す。利益を約束するものではない(期待損失を明示)。
    戻り: {'band','label','exp_roi','cap','stake','exp_loss','verdict'}。arare_prob=NoneでNone。
    """
    if arare_prob is None:
        return None
    band = 'tight' if arare_prob < 0.42 else ('mid' if arare_prob < 0.60 else 'arare')
    roi = _BAND_ROI[band]
    cap = bankroll_cap(bankroll, pct=entertainment_pct, unit=unit)['cap']
    # 中波乱(最良)を基準1.0、期待ROIが低い帯ほど賭け金を絞る(0.75floor未満は0=見送り)
    best = max(_BAND_ROI.values())
    scale = max(0.0, min(1.0, (roi - 0.75) / (best - 0.75))) if best > 0.75 else 0.0
    stake = int((cap * scale) // unit) * unit
    exp_loss = int(round(stake * (1 - roi)))
    if roi < 0.75 or stake < unit:
        verdict = '見送り推奨(この帯は控除率floor以下＝賭ける根拠が薄い)'
        stake = 0
    else:
        verdict = f'エンタメ範囲で少額可(期待ROI{roi*100:.0f}%＝長期では負け)'
    return {'band': band, 'label': _BAND_LABEL[band], 'exp_roi': roi,
            'cap': cap, 'stake': stake, 'exp_loss': exp_loss, 'verdict': verdict}


# ──────────────────────────────────────────────
# ④ セッション・ガードレール（損切り/利確で感情を遮断）
# ──────────────────────────────────────────────
def session_guard(start_balance, current_balance, stop_loss_pct=25.0, take_profit_pct=30.0):
    """
    セッション開始残高に対する損益で「継続/撤退/利確」を自動判定。
    stop_loss_pct: 損切りライン(%) 推奨20〜30
    take_profit_pct: 利確ライン(%) 推奨30〜50
    戻り: {'status':'継続'|'撤退(損切り)'|'利確', 'pnl':損益, 'pnl_pct':%,
           'stop_line':撤退残高, 'tp_line':利確残高, 'to_stop':撤退まで, 'to_tp':利確まで}
    """
    pnl = current_balance - start_balance
    pnl_pct = (pnl / start_balance * 100.0) if start_balance > 0 else 0.0
    stop_line = start_balance * (1 - stop_loss_pct / 100.0)
    tp_line = start_balance * (1 + take_profit_pct / 100.0)
    if current_balance <= stop_line:
        status = '撤退(損切り)'
    elif current_balance >= tp_line:
        status = '利確'
    else:
        status = '継続'
    return {'status': status, 'pnl': pnl, 'pnl_pct': pnl_pct,
            'stop_line': stop_line, 'tp_line': tp_line,
            'to_stop': current_balance - stop_line, 'to_tp': tp_line - current_balance}


def clip_yen(amount, unit=100):
    """馬券単位で切り下げ。0未満は0。"""
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return int(n // unit) * unit


def apply_stake_caps(kelly_yen, balance, race_cap_pct=5.0, ticket_cap_pct=3.0,
                     daily_spent=0, daily_cap_pct=15.0, race_spent=0, unit=100):
    """理論ケリー額に1点・1レース・1日の上限をかけて実投資額を返す。

    kelly_multi は変えない。こちらは『出た金額を実際に賭けてよいか』の柵。
    """
    race_cap = bankroll_cap(balance, pct=race_cap_pct, unit=unit)['cap']
    ticket_cap = bankroll_cap(balance, pct=ticket_cap_pct, unit=unit)['cap']
    daily_cap = bankroll_cap(balance, pct=daily_cap_pct, unit=unit)['cap']
    daily_left = max(0, daily_cap - int(daily_spent or 0))
    race_left = max(0, race_cap - int(race_spent or 0))
    theoretical = clip_yen(kelly_yen, unit)
    stake = min(theoretical, ticket_cap, race_left, daily_left)
    reasons = []
    if theoretical > ticket_cap:
        reasons.append('1点上限')
    if theoretical > race_left:
        reasons.append('1レース上限')
    if theoretical > daily_left:
        reasons.append('今日の投資上限')
    return {
        'theoretical': theoretical,
        'ticket_cap': ticket_cap,
        'race_cap': race_cap,
        'daily_cap': daily_cap,
        'daily_left': daily_left,
        'race_left': race_left,
        'stake': max(0, stake),
        'capped': stake < theoretical,
        'reasons': reasons,
    }


def ops_light(start_balance, current_balance, daily_spent=0, daily_cap=0,
              stop_loss_pct=25.0, take_profit_pct=30.0):
    """今日買ってよいかを3色で返す。session_guard の判定に『今日の使いすぎ』を足す。"""
    g = session_guard(start_balance, current_balance,
                      stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct)
    daily_spent = int(daily_spent or 0)
    daily_cap = int(daily_cap or 0)
    if g['status'] == '撤退(損切り)':
        return {'code': 'stop', 'emoji': '🔴', 'title': '本日は停止',
                'detail': '開始資金からの下落が上限に達した。今日の新規購入を止める。',
                'new_race_cap': 0, **g}
    if daily_cap > 0 and daily_spent >= daily_cap:
        return {'code': 'stop', 'emoji': '🔴', 'title': '本日は停止',
                'detail': '今日の投資上限に達した。新規購入を止める。',
                'new_race_cap': 0, **g}
    if g['status'] == '利確':
        return {'code': 'ok', 'emoji': '🟢', 'title': '利確ライン到達',
                'detail': '目標まで来た。欲を出さず、ここで終えるのが安全。',
                'new_race_cap': None, **g}
    if daily_cap > 0 and daily_spent >= daily_cap * 0.8:
        remain = max(0, daily_cap - daily_spent)
        return {'code': 'caution', 'emoji': '🟡', 'title': '投資を抑える',
                'detail': f'今日はすでに上限の{daily_spent / daily_cap * 100:.0f}%を使っている。'
                          f'この先は1レース ¥{remain:,.0f} まで。',
                'new_race_cap': remain, **g}
    return {'code': 'ok', 'emoji': '🟢', 'title': '通常どおり',
            'detail': f'残高 ¥{current_balance:,.0f} ／ 今日の投資 ¥{daily_spent:,.0f}'
                      + (f'（上限 ¥{daily_cap:,.0f}）' if daily_cap else ''),
            'new_race_cap': None, **g}


def equity_stats(start_balance, balances):
    """開始資金と各レース後残高から、最高残高と最大下落率を返す。"""
    series = [float(start_balance)]
    for b in (balances or []):
        try:
            series.append(float(b))
        except (TypeError, ValueError):
            continue
    peak = max(series)
    peak_so_far = series[0]
    max_dd_pct = 0.0
    for b in series:
        peak_so_far = max(peak_so_far, b)
        if peak_so_far > 0:
            max_dd_pct = min(max_dd_pct, (b - peak_so_far) / peak_so_far * 100.0)
    return {
        'start': series[0],
        'current': series[-1],
        'peak': peak,
        'max_dd_pct': max_dd_pct,
    }


def points_budget(n_points, cap, unit=100):
    """SRAで決めた点数に、1レース上限を割り振る。的中率は使わない。

    1点は unit 円（通常100円）。上限に入らなければ total=0, fits=False。
    """
    try:
        n = max(0, int(n_points or 0))
    except (TypeError, ValueError):
        n = 0
    try:
        cap = max(0, int(cap or 0))
    except (TypeError, ValueError):
        cap = 0
    unit = max(0, int(unit or 0))
    max_points = (cap // unit) if unit else 0
    need = n * unit
    if n <= 0 or cap <= 0 or unit <= 0:
        return {'n': n, 'cap': cap, 'unit': 0, 'total': 0,
                'max_points': max_points, 'fits': True, 'need': need,
                'leftover': cap}
    if need <= cap:
        return {'n': n, 'cap': cap, 'unit': unit, 'total': need,
                'max_points': max_points, 'fits': True, 'need': need,
                'leftover': cap - need}
    return {'n': n, 'cap': cap, 'unit': 0, 'total': 0,
            'max_points': max_points, 'fits': False, 'need': need,
            'leftover': 0}


# 券種別の安全マージン目安（未検証。ONにしたときだけ表示オッズを割り引く）
KIND_SLIP = {
    '3連単': 0.30, '3連複': 0.25, '馬連': 0.20, '馬単': 0.20,
    'ワイド': 0.20, '単勝': 0.10, '複勝': 0.10,
}


def slip_pct_for(kind, enabled=False):
    if not enabled:
        return 0.0
    return float(KIND_SLIP.get(str(kind or '').strip(), 0.20))


def haircut_odds(odds, slip_pct):
    """表示オッズを安全マージンで割り引く。予測ではなく資金管理用。"""
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return 0.0
    try:
        s = max(0.0, min(0.9, float(slip_pct or 0)))
    except (TypeError, ValueError):
        s = 0.0
    if o <= 1.0:
        return o
    return max(1.01, o * (1.0 - s))


def ticket_line(kind, odds, p=None, balance=0, kelly_frac=0.25,
                race_cap=0, ticket_cap=0, race_spent=0,
                min_ev_pct=5.0, min_p_pct=1.0, slip_on=False,
                default_unit=100, unit=100):
    """買い目1行の推奨額。的中率が空なら1点分（default_unit）を上限内で返す。"""
    slip = slip_pct_for(kind, slip_on)
    ev_odds = haircut_odds(odds, slip)
    out = {
        'kind': str(kind or ''),
        'odds': float(odds or 0),
        'eval_odds': round(ev_odds, 2) if ev_odds else 0.0,
        'slip_pct': round(slip * 100, 1),
        'p': None, 'ev_pct': None,
        'full_pct': 0.0, 'rec_pct': 0.0,
        'full_yen': 0, 'kelly_yen': 0, 'stake': 0,
        'status': '見送り', 'reasons': [],
    }
    halt = int(race_cap or 0) <= 0
    if halt:
        out['reasons'] = ['今日は停止']
        return out
    p_val = None
    try:
        if p is not None and p != '' and float(p) > 0:
            p_val = float(p)
            if p_val > 1.0:
                p_val = p_val / 100.0
    except (TypeError, ValueError):
        p_val = None
    out['p'] = p_val
    left = max(0, int(race_cap or 0) - int(race_spent or 0))
    tcap = int(ticket_cap or 0) if ticket_cap else left

    if p_val is None:
        stake = min(int(default_unit or 100), tcap, left)
        stake = clip_yen(stake, unit)
        out['stake'] = stake
        out['status'] = '枠で買う' if stake > 0 else '上限いっぱい'
        out['reasons'] = ['的中率なし＝1点分']
        return out

    if p_val * 100.0 < float(min_p_pct or 0):
        out['status'] = '見送り'
        out['reasons'] = ['的中率が下限未満']
        return out
    if ev_odds <= 1.0:
        out['status'] = '見送り'
        out['reasons'] = ['オッズ不足']
        return out
    ev_mult = p_val * ev_odds
    ev_pct = (ev_mult - 1.0) * 100.0
    out['ev_pct'] = round(ev_pct, 1)
    if ev_pct < float(min_ev_pct or 0):
        out['status'] = '見送り'
        out['reasons'] = ['期待値が下限未満']
        return out
    b = ev_odds - 1.0
    full_f = max(0.0, (p_val * ev_odds - 1.0) / b) if b > 0 else 0.0
    rec_f = full_f * float(kelly_frac or 0)
    out['full_pct'] = round(full_f * 100.0, 2)
    out['rec_pct'] = round(rec_f * 100.0, 2)
    full_yen = clip_yen(float(balance or 0) * full_f, unit)
    kelly_yen = clip_yen(float(balance or 0) * rec_f, unit)
    out['full_yen'] = full_yen
    out['kelly_yen'] = kelly_yen
    stake = min(kelly_yen, tcap, left)
    stake = clip_yen(stake, unit)
    out['stake'] = stake
    if kelly_yen > stake:
        if kelly_yen > tcap:
            out['reasons'].append('1点上限')
        if kelly_yen > left:
            out['reasons'].append('1レース上限')
    if stake <= 0:
        out['status'] = '見送り'
    elif stake < 200:
        out['status'] = '少額'
    else:
        out['status'] = '推奨'
    return out


# ──────────────────────────────────────────────
# ⑤ 収支台帳（予測→結果→反省 / ROI・Brier）
# ──────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS bets (
  bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, race_id TEXT, umaban INTEGER, bamei TEXT,
  pred_prob REAL,
  odds REAL,
  stake INTEGER,
  bet_type TEXT,
  settled INTEGER DEFAULT 0,
  won INTEGER,
  payout INTEGER
);

-- ②見送ったレースの台帳。
--    台帳が「買ったもの」しか持たないと「見送って正解だったか」が永久に分からない。
--    スキャナーの🔴見送り推奨や自分の判断で見送ったレースをここに残し、
--    後から「見送りは正しかったか」を集計する。
CREATE TABLE IF NOT EXISTS skips (
    skip_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, race_id TEXT, reason TEXT, vscore REAL,
    zone TEXT, mood TEXT,
    settled INTEGER DEFAULT 0,
    would_hit INTEGER,      -- 買っていたら当たっていたか(1/0)
    would_payout INTEGER,   -- 買っていた場合の払戻(100円あたり換算)
    note TEXT
);
"""


class Ledger:
    def __init__(self, db=LEDGER_DB):
        os.makedirs(os.path.dirname(db), exist_ok=True)
        self.con = sqlite3.connect(db)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_DDL)
        # #8 Gate結果列＋#1 買い目メタ列(設計ミス分類用)を後方互換で追加
        # ①感情 ②逸脱の記録も後方互換で追加。
        #   mood: 冷静/やや熱/熱くなっている（自己申告・検証済みシグナルではなく
        #         「熱くなった時だけ負けている」かを後から数字で見るための実観測台帳）
        #   deviation: 上限超え/追い上げ/見送り推奨を購入 など、ルールからの逸脱
        for _col, _typ in (('gate_status', 'TEXT'), ('gate_lean', 'TEXT'),
                           ('gate_severity', 'INTEGER'),
                           ('n_points', 'INTEGER'), ('synth_odds', 'REAL'),
                           ('has_danger', 'INTEGER'), ('has_value_ana', 'INTEGER'),
                           ('mood', 'TEXT'), ('deviation', 'TEXT')):
            try:
                self.con.execute(f"ALTER TABLE bets ADD COLUMN {_col} {_typ}")
            except Exception:
                pass  # 既に存在
        self.con.commit()

    def record_prediction(self, race_id, umaban, bamei, pred_prob, odds, stake=100, bet_type='単勝',
                          gate_status=None, gate_lean=None, gate_severity=None,
                          n_points=None, synth_odds=None, has_danger=None, has_value_ana=None,
                          mood=None, deviation=None):
        self.con.execute(
            """INSERT INTO bets(ts,race_id,umaban,bamei,pred_prob,odds,stake,bet_type,
                                gate_status,gate_lean,gate_severity,
                                n_points,synth_odds,has_danger,has_value_ana,
                                mood,deviation)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.datetime.now().isoformat(timespec='seconds'), race_id, umaban, bamei,
             pred_prob, odds, stake, bet_type, gate_status, gate_lean, gate_severity,
             n_points, synth_odds,
             None if has_danger is None else int(bool(has_danger)),
             None if has_value_ana is None else int(bool(has_value_ana)),
             mood, deviation))
        self.con.commit()

    def settle(self, race_id, win_umaban, win_payout):
        """race_id の結果を反映（単勝）。win_payout=100円あたり配当"""
        for b in self.con.execute("SELECT * FROM bets WHERE race_id=? AND settled=0", (race_id,)):
            won = 1 if b['umaban'] == win_umaban else 0
            payout = int(win_payout * b['stake'] / 100) if won else 0
            self.con.execute("UPDATE bets SET settled=1, won=?, payout=? WHERE bet_id=?",
                             (won, payout, b['bet_id']))
        self.con.commit()

    def settle_multi(self, race_id, results):
        """券種別の結果を反映。
        results: {'tan': [{'combo': [5], 'odds': 3.5}], 'trio': [{'combo': [3,5,8], 'odds': 12.0}], ...}
        スクレイパーの fetch_race_payouts の戻り値をそのまま使う。
        """
        for b in self.con.execute("SELECT * FROM bets WHERE race_id=? AND settled=0", (race_id,)):
            btype = b['bet_type'] or '単勝'
            matched = None
            # 券種に対応する結果キー
            key_map = {'単勝': 'tan', '複勝': 'fuku', '馬連': 'umaren', '馬単': 'umatan',
                       'ワイド': 'wide', '3連複': 'trio', '3連単': 'trifecta', '枠連': 'wakuren'}
            rkey = key_map.get(btype)
            if rkey and rkey in results:
                for r in results[rkey]:
                    combo = r.get('combo', [])
                    if btype in ('単勝', '複勝'):
                        if len(combo) == 1 and int(combo[0]) == b['umaban']:
                            matched = r
                            break
                    else:
                        # 買い目文字列（bameiに保存されている想定）と比較
                        combo_str = '-'.join(str(c) for c in sorted(combo))
                        if str(b.get('bamei', '')) == combo_str:
                            matched = r
                            break
            if matched:
                payout = int(matched.get('odds', 0) * 100 * b['stake'] / 100)
                self.con.execute("UPDATE bets SET settled=1, won=1, payout=? WHERE bet_id=?",
                                 (payout, b['bet_id']))
            else:
                self.con.execute("UPDATE bets SET settled=1, won=0, payout=0 WHERE bet_id=?",
                                 (b['bet_id'],))
        self.con.commit()

    def settled_rows(self):
        """精算済みベットを古い順に返す（ROI推移グラフ用）"""
        return list(self.con.execute(
            "SELECT bet_id,ts,race_id,pred_prob,odds,stake,won,payout,"
            "gate_status,gate_lean,gate_severity FROM bets "
            "WHERE settled=1 ORDER BY bet_id"))

    def roi_by_gate(self):
        """Gate判定(gate_status)別の的中率/ROI/件数を返す(運用検証: buy/axis_warn/skip無視の比較)。"""
        out = {}
        for r in self.con.execute(
                "SELECT gate_status AS g, COUNT(*) n, SUM(won) w, "
                "SUM(stake) inv, SUM(payout) ret FROM bets WHERE settled=1 "
                "GROUP BY gate_status"):
            g = r['g'] or '(未タグ)'
            inv = r['inv'] or 0
            out[g] = {'n': r['n'], 'win_rate': (r['w'] or 0) / r['n'] if r['n'] else 0,
                      'roi': (r['ret'] or 0) / inv if inv else 0}
        return out

    @staticmethod
    def classify_loss(won, gate_status, gate_lean=None, pred_prob=None,
                      n_points=None, synth_odds=None, has_danger=None, has_value_ana=None):
        """⑥回顧: 外れたベットの『負け理由』を自動分類(改善ループの種)。的中(won)はNone。
        優先順=是正効果の大きい運用事故→買い目設計ミス→想定内のブレ。
        運用事故(Gate無視/危険軸/危険人気含み)はGate遵守で直接減らせる。"""
        if won:
            return None
        gs = (gate_status or '').strip()
        lean = (gate_lean or '').strip()
        # ① 運用事故(最優先・Gate遵守で減る)
        if gs == 'skip':
            return 'Gate無視(見送りレースを購入)'
        if gs == 'axis_warn':
            return '危険軸(安全な軸が無いのに購入)'
        if has_danger:
            return '危険人気馬を含めて購入'
        # ② 買い目設計ミス
        if lean == '②穴妙味向き' and has_value_ana == 0:
            return '盲目②(穴妙味向きなのに妙味穴なし)'
        if lean == '本線向き' and n_points is not None and n_points >= 12:
            return '本線向きで点数過多({}点)'.format(n_points)
        if synth_odds is not None and 0 < synth_odds < 1.5:
            return 'トリガミ設計(合成オッズ{:.1f}が低すぎ)'.format(synth_odds)
        # ③ 根拠薄/想定内のブレ
        if gs == 'wait':
            return '様子見レースを購入(根拠薄)'
        if pred_prob is not None and pred_prob >= 0.5:
            return '本命級が飛んだ(想定tier外/能力)'
        if gs == 'buy':
            return 'buyで不的中(想定内のハズレ)'
        return '未タグ(Gate記録なし)'

    def loss_breakdown(self):
        """精算済みの負けを理由別に集計: {reason: {'n','loss'}}。"""
        out = {}
        for r in self.con.execute(
                "SELECT won,gate_status,gate_lean,pred_prob,stake,payout,"
                "n_points,synth_odds,has_danger,has_value_ana FROM bets WHERE settled=1"):
            if r['won']:
                continue
            reason = self.classify_loss(
                r['won'], r['gate_status'], r['gate_lean'], r['pred_prob'],
                r['n_points'], r['synth_odds'], r['has_danger'], r['has_value_ana'])
            d = out.setdefault(reason, {'n': 0, 'loss': 0})
            d['n'] += 1
            d['loss'] += (r['stake'] or 0) - (r['payout'] or 0)
        return out

    def improvement_rules(self):
        """⑥回顧→次回ルールの自動生成。負けの最大要因とGate別ROIから『次にやめること』をstr listで返す。"""
        rules = []
        lb = self.loss_breakdown()
        if lb:
            k, v = sorted(lb.items(), key=lambda kv: -kv[1]['loss'])[0]
            _map = {
                'Gate無視': '🚫 見送り(skip)レースを買わない＝最大の損失源',
                '危険軸': '⚠ axis_warn(安全な軸が無い)レースは軸固定で買わない',
                '危険人気馬を含めて購入': '⚠ 危険人気馬(severity≥2)を買い目に入れない',
                '盲目②': '🎯 ②穴妙味は妙味穴(末脚/単複乖離/厩舎当コース)がいる時だけ',
                '本線向きで点数過多': '📉 本線向きは点数を絞る(8点目安)',
                'トリガミ設計': '💸 合成オッズが低い買い目は点数削減 or ワイド/馬連へ',
            }
            for pre, msg in _map.items():
                if k.startswith(pre):
                    rules.append(f"{msg}（{v['n']}件/損失¥{v['loss']:,}）")
                    break
        rbg = {g: x for g, x in self.roi_by_gate().items() if g != '(未タグ)' and x['n'] >= 5}
        if rbg:
            worst_g, worst = min(rbg.items(), key=lambda kv: kv[1]['roi'])
            if worst['roi'] < 0.6:
                rules.append(f"📊 Gate『{worst_g}』の回収率{worst['roi']*100:.0f}%が低い"
                             f"({worst['n']}件)→このGateは見送り寄りに")
        return rules

    def max_drawdown(self):
        """精算済みP/L推移の最大ドローダウン(円・0以下。0=DD無し)。"""
        cum = 0; peak = 0; dd = 0
        for r in self.settled_rows():
            cum += (r['payout'] or 0) - (r['stake'] or 0)
            peak = max(peak, cum)
            dd = min(dd, cum - peak)
        return dd

    def report(self):
        rows = list(self.con.execute("SELECT * FROM bets WHERE settled=1"))
        if not rows:
            return {'note': '精算済みベットなし'}
        n = len(rows); wins = sum(r['won'] for r in rows)
        staked = sum(r['stake'] for r in rows); returned = sum(r['payout'] for r in rows)
        brier = sum((r['pred_prob'] - r['won']) ** 2 for r in rows) / n
        return {'bets': n, 'hit_rate': round(wins / n * 100, 1),
                'roi': round(returned / staked * 100, 1) if staked else 0.0,
                'profit': returned - staked, 'brier': round(brier, 4)}

    # ── ② 見送りレースの記録・集計 ─────────────────────
    def record_skip(self, race_id, reason='', vscore=None, zone=None,
                    mood=None, note=''):
        """見送ったレースを記録する。買った記録と対にして初めて判断が評価できる。"""
        self.con.execute(
            "INSERT INTO skips(ts,race_id,reason,vscore,zone,mood,note) "
            "VALUES(?,?,?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec='seconds'),
             str(race_id), reason, vscore, zone, mood, note))
        self.con.commit()

    def settle_skip(self, race_id, would_hit, would_payout=0):
        """見送ったレースの答え合わせ。would_hit=買っていたら当たっていたか。"""
        self.con.execute(
            "UPDATE skips SET settled=1, would_hit=?, would_payout=? WHERE race_id=?",
            (int(bool(would_hit)), int(would_payout or 0), str(race_id)))
        self.con.commit()

    def skip_report(self):
        """見送りの成績。'見送って正解だった率'と、買っていた場合のROIを出す。

        ⚠買っていた場合のROIが100%を割っていれば見送りは正しかったということ。
          [[verified_hot_hand_selective]]の通り、最大のレバーは「買わないこと」。
        """
        rows = list(self.con.execute("SELECT * FROM skips"))
        done = [r for r in rows if r['settled']]
        if not done:
            return {'n': len(rows), 'settled': 0}
        hit = sum(1 for r in done if r['would_hit'])
        spend = len(done) * 100
        ret = sum(int(r['would_payout'] or 0) for r in done)
        by_zone = {}
        for r in done:
            z = r['zone'] or '(未設定)'
            d = by_zone.setdefault(z, [0, 0, 0])
            d[0] += 1
            d[1] += 1 if r['would_hit'] else 0
            d[2] += int(r['would_payout'] or 0)
        return {'n': len(rows), 'settled': len(done),
                'hit_rate': hit / len(done) * 100,
                'would_roi': ret / spend * 100 if spend else 0,
                'correct_rate': (len(done) - hit) / len(done) * 100,
                'by_zone': {z: {'n': v[0], 'hit': v[1] / v[0] * 100,
                                'roi': v[2] / (v[0] * 100) * 100}
                            for z, v in by_zone.items()}}

    # ── ① 感情別の成績 ────────────────────────────
    def mood_report(self):
        """気分(冷静/やや熱/熱い)別の的中率とROI。

        自己申告なので検証済みシグナルではない。「熱くなった時だけ負けている」
        かどうかを**自分のデータで**確かめるための実観測台帳。
        """
        out = {}
        for r in self.con.execute(
                "SELECT mood, COUNT(*) n, SUM(won) w, SUM(payout) p, SUM(stake) s "
                "FROM bets WHERE settled=1 GROUP BY mood"):
            k = r['mood'] or '(未記録)'
            n = r['n'] or 0
            if not n:
                continue
            out[k] = {'n': n, 'hit': (r['w'] or 0) / n * 100,
                      'roi': (r['p'] or 0) / (r['s'] or 1) * 100,
                      'stake_avg': (r['s'] or 0) / n}
        return out

    # ── ③ ルールからの逸脱 ───────────────────────────
    def deviation_report(self):
        """逸脱の種類別の件数・ROI。資料の核心「修正すべきはルールからの逸脱のみ」。"""
        out = {}
        for r in self.con.execute(
                "SELECT deviation, COUNT(*) n, SUM(won) w, SUM(payout) p, SUM(stake) s "
                "FROM bets WHERE settled=1 AND deviation IS NOT NULL "
                "AND deviation<>'' GROUP BY deviation"):
            n = r['n'] or 0
            if not n:
                continue
            out[r['deviation']] = {
                'n': n, 'hit': (r['w'] or 0) / n * 100,
                'roi': (r['p'] or 0) / (r['s'] or 1) * 100}
        # 逸脱なしの対照群
        r0 = self.con.execute(
            "SELECT COUNT(*) n, SUM(won) w, SUM(payout) p, SUM(stake) s FROM bets "
            "WHERE settled=1 AND (deviation IS NULL OR deviation='')").fetchone()
        if r0 and r0['n']:
            out['（逸脱なし）'] = {
                'n': r0['n'], 'hit': (r0['w'] or 0) / r0['n'] * 100,
                'roi': (r0['p'] or 0) / (r0['s'] or 1) * 100}
        return out

    def reflection(self):
        """予測勝率の帯ごとに『予測 vs 実際』を比較→較正のズレと次回ルールを生成"""
        rows = list(self.con.execute(
            "SELECT pred_prob,won,odds,payout,stake FROM bets WHERE settled=1"))
        if len(rows) < 10:
            return ["（サンプル不足。10件以上の精算で反省が有効に）"]
        buckets = {}
        for r in rows:
            b = min(4, int(r['pred_prob'] * 5))
            buckets.setdefault(b, []).append(r)
        rules = []
        for b in sorted(buckets):
            g = buckets[b]
            pred_avg = sum(x['pred_prob'] for x in g) / len(g)
            actual = sum(x['won'] for x in g) / len(g)
            roi = sum(x['payout'] for x in g) / sum(x['stake'] for x in g) * 100
            band = f"予測{b * 20}-{b * 20 + 20}%帯"
            diff = actual - pred_avg
            if abs(diff) >= 0.05:
                verdict = "過大評価→割引け" if diff < 0 else "過小評価→もっと狙え"
                rules.append(f"{band}: 予測{pred_avg * 100:.0f}% vs 実際{actual * 100:.0f}%({verdict}) 回収{roi:.0f}%")
            else:
                rules.append(f"{band}: 較正良好(予測{pred_avg * 100:.0f}%≒実際{actual * 100:.0f}%) 回収{roi:.0f}%")
        return rules

    def pending_races(self):
        """未精算のレースIDリスト(古い順)"""
        return [r[0] for r in self.con.execute(
            "SELECT DISTINCT race_id FROM bets WHERE settled=0 ORDER BY ts")]

    def pending_count(self):
        """未精算ベット件数"""
        return self.con.execute("SELECT COUNT(*) FROM bets WHERE settled=0").fetchone()[0]

    def auto_settle_race(self, race_id):
        """スクレイパーでrace_idの結果を取得し自動精算。
        戻り値: {'winner': umaban, 'payout': 100円あたり配当, 'settled': n} or None"""
        unsettled = self.con.execute(
            "SELECT COUNT(*) FROM bets WHERE race_id=? AND settled=0",
            (race_id,)).fetchone()[0]
        if unsettled == 0:
            return None
        from core.scraper import fetch_race_payouts
        payouts = fetch_race_payouts(race_id)
        if not payouts or 'tan' not in payouts or not payouts['tan']:
            return None
        winner = payouts['tan'][0]['combo'][0]
        win_payout = int(payouts['tan'][0]['odds'] * 100)
        # 単勝以外の券種もまとめて精算
        self.settle_multi(race_id, payouts)
        return {'winner': winner, 'payout': win_payout, 'settled': unsettled}

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass
