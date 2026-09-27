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
import re
import math
import random
import sqlite3
import datetime

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DB = os.path.join(_BASE, 'data', 'ledger.db')

BET_TYPE_RESULT_KEY = {
    '単勝': 'tan', '複勝': 'fuku', '馬連': 'umaren', '馬単': 'umatan',
    'ワイド': 'wide', '3連複': 'trio', '3連単': 'trifecta', '枠連': 'wakuren',
}
ORDERED_BET_TYPES = frozenset({'馬単', '3連単'})

# bets.bet_purpose — 実購入ROIと較正用予測を分離（legacy NULL は legacy_unknown）
BET_PURPOSE_ACTUAL = 'actual_purchase'
BET_PURPOSE_CALIBRATION = 'calibration'
BET_PURPOSE_VIRTUAL = 'virtual_eval'
BET_PURPOSE_LEGACY = 'legacy_unknown'


def yen_payout_from_odds(odds, stake):
    """100円あたり odds 形式の払戻を円整数で計算（浮動小数誤差を避ける）。"""
    from decimal import Decimal, ROUND_HALF_UP
    try:
        o = Decimal(str(odds))
        s = Decimal(int(stake or 0))
    except Exception:
        return 0
    if o <= 0 or s <= 0:
        return 0
    return int((o * s).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def bet_row_effective_purpose(row):
    """推測で legacy を実購入認定しない。"""
    row = bet_row_dict(row)
    p = (row.get('bet_purpose') or '').strip()
    if p in (BET_PURPOSE_ACTUAL, BET_PURPOSE_CALIBRATION, BET_PURPOSE_VIRTUAL):
        return p
    if p:
        return p
    return BET_PURPOSE_LEGACY


def is_actual_purchase_bet(row):
    return bet_row_effective_purpose(row) == BET_PURPOSE_ACTUAL


# 実購入成績集計の唯一条件（SQL / Python 共通）
ACTUAL_PURCHASE_SQL = 'bet_purpose = ?'


def actual_purchase_sql_where(prefix=''):
    """WHERE 断片: ``... AND bet_purpose = 'actual_purchase'``"""
    p = f'{prefix}.' if prefix else ''
    return f'{p}bet_purpose = ?'


class LedgerSchemaError(RuntimeError):
    """ledger.db スキーマ migration 失敗。"""


def _migrate_add_column(con, table, col, typ):
    try:
        con.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if 'duplicate column' in msg or 'already exists' in msg:
            return
        raise LedgerSchemaError(f'ALTER {table}.{col} failed: {e}') from e


def classify_payout_entry(entry):
    """払戻1行の種別。推測で hit/refund にしない。"""
    if not entry or not isinstance(entry, dict):
        return 'unknown'
    if entry.get('refund') is True or entry.get('status') == 'refund':
        return 'refund'
    raw = str(entry.get('pay_raw') or '')
    if '返還' in raw:
        return 'refund'
    try:
        odds = float(entry.get('odds', 0) or 0)
    except (TypeError, ValueError):
        odds = 0.0
    if odds > 0:
        return 'hit'
    if odds == 0 and entry.get('refund') is False:
        return 'miss'
    return 'unknown'


def _entry_matches_bet(btype, bet, entry):
    """ベットと払戻行の組合せが一致するか。"""
    combo = entry.get('combo') or []
    if btype in ('単勝', '複勝'):
        try:
            uma = int(bet.get('umaban') or 0)
        except (TypeError, ValueError):
            return False
        return len(combo) == 1 and int(combo[0]) == uma
    label_key = parse_bet_label(btype, bet.get('bamei'))
    if not label_key:
        return False
    ck = _payout_combo_key(btype, combo)
    return ck == label_key


def _bet_touches_scratch(btype, bet, scratch_umaban):
    """取消馬リストにベットが関与するか（组合券は確定返還行なしでは未精算用）。"""
    if not scratch_umaban:
        return False
    scr = {int(x) for x in scratch_umaban}
    if btype in ('単勝', '複勝'):
        try:
            return int(bet.get('umaban') or 0) in scr
        except (TypeError, ValueError):
            return False
    label_key = parse_bet_label(btype, bet.get('bamei'))
    if not label_key:
        return False
    return any(u in scr for u in label_key)


def bet_row_dict(row):
    """sqlite3.Row / dict を dict に統一（Row に .get は無い）。"""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        return dict(row)


def parse_bet_label(btype, label):
    """買い目文字列を馬番タプルに。順序あり券種は左→右、順不同は sorted。"""
    s = str(label or '').strip()
    if not s:
        return None
    if '→' in s:
        parts = [p.strip() for p in s.split('→')]
    elif '-' in s:
        parts = [p.strip() for p in s.split('-')]
    else:
        parts = re.findall(r'\d+', s)
    nums = []
    for p in parts:
        if str(p).isdigit():
            nums.append(int(p))
    if not nums:
        return None
    btype = (btype or '単勝').strip()
    if btype in ORDERED_BET_TYPES:
        return tuple(nums)
    if btype in ('馬連', '3連複', 'ワイド', '枠連'):
        return tuple(sorted(nums))
    return tuple(nums)


def _payout_combo_key(btype, combo):
    combo = [int(x) for x in (combo or [])]
    if not combo:
        return None
    btype = (btype or '').strip()
    if btype in ORDERED_BET_TYPES:
        return tuple(combo)
    if btype in ('馬連', '3連複', 'ワイド', '枠連'):
        return tuple(sorted(combo))
    return tuple(combo)


def match_bet_to_payout(bet, results):
    """1ベットと fetch_race_payouts 形式 results の照合。

    戻り値:
      None … 払戻データ不足・判定不能（未精算のまま）
      {'won', 'payout', 'status', 'matched_count'?} … hit / miss / refund
    """
    bet = bet_row_dict(bet)
    btype = (bet.get('bet_type') or '単勝').strip()
    rkey = BET_TYPE_RESULT_KEY.get(btype)
    if not results or rkey is None:
        return None
    if rkey not in results:
        return None
    entries = results[rkey]
    if entries is None:
        return None
    if isinstance(entries, (list, tuple)) and len(entries) == 0:
        return None
    try:
        stake = int(bet.get('stake') or 0)
    except (TypeError, ValueError):
        stake = 0

    scratch = results.get('scratch_umaban') or results.get('refund_umaban')
    if _bet_touches_scratch(btype, bet, scratch):
        has_refund_row = any(
            classify_payout_entry(r) == 'refund' and _entry_matches_bet(btype, bet, r)
            for r in (entries or []))
        if not has_refund_row:
            return None

    hit_rows = []
    refund_rows = []
    saw_unknown = False
    for r in (entries or []):
        cls = classify_payout_entry(r)
        if cls == 'unknown':
            if _entry_matches_bet(btype, bet, r):
                saw_unknown = True
            continue
        if not _entry_matches_bet(btype, bet, r):
            continue
        if cls == 'refund':
            refund_rows.append(r)
        elif cls == 'hit':
            hit_rows.append(r)

    if saw_unknown and not hit_rows and not refund_rows:
        return None
    if refund_rows and hit_rows:
        return None
    if refund_rows:
        return {
            'won': 0,
            'payout': stake,
            'status': 'refund',
            'matched_count': len(refund_rows),
        }
    if hit_rows:
        total = 0
        for r in hit_rows:
            odds = float(r.get('odds', 0) or 0)
            if odds <= 0:
                return None
            total += yen_payout_from_odds(odds, stake)
        return {
            'won': 1,
            'payout': total,
            'status': 'hit',
            'matched_count': len(hit_rows),
        }
    if btype in ('単勝', '複勝'):
        if _payout_pool_has_unknown(entries):
            return None
        winners = _definitive_hit_umabans(entries)
        if winners is None:
            return None
        try:
            uma = int(bet.get('umaban') or 0)
        except (TypeError, ValueError):
            return None
        if uma in winners:
            return None
        if winners:
            return {'won': 0, 'payout': 0, 'status': 'miss'}
        return None
    if _payout_pool_has_unknown(entries):
        return None
    if not _pool_has_definitive_hit(entries):
        return None
    return {'won': 0, 'payout': 0, 'status': 'miss'}


def _pool_has_definitive_hit(entries):
    """正常な確定払戻(hit)が1件以上あるときのみ combo の miss 確定可。"""
    return any(classify_payout_entry(r) == 'hit' for r in (entries or []))


def _payout_pool_has_unknown(entries):
    """券種の払戻集合に unknown が1行でもあれば miss 確定不可。"""
    return any(classify_payout_entry(r) == 'unknown' for r in (entries or []))


def _definitive_hit_umabans(entries):
    """単勝/複勝: 確定 hit の馬番集合（同着・複勝複数 winner 可）。"""
    winners = set()
    for r in (entries or []):
        if classify_payout_entry(r) != 'hit':
            continue
        combo = r.get('combo') or []
        if len(combo) != 1:
            return None
        try:
            winners.add(int(combo[0]))
        except (TypeError, ValueError):
            return None
    return winners


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
CREATE TABLE IF NOT EXISTS bet_settlement_log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  bet_id INTEGER NOT NULL,
  race_id TEXT,
  ts TEXT NOT NULL,
  won INTEGER,
  payout INTEGER,
  source TEXT,
  note TEXT
);

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
        from core import audit_store as _audit
        _audit.ensure_schema(self.con)
        _audit.verify_audit_schema(self.con)
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
            _migrate_add_column(self.con, 'bets', _col, _typ)
        _migrate_add_column(self.con, 'bet_settlement_log', 'action', 'TEXT')
        for _col, _typ in (('purchase_batch_id', 'TEXT'), ('recommendation_id', 'TEXT'),
                           ('analysis_run_id', 'TEXT'), ('audit_link', 'TEXT'),
                           ('bet_purpose', 'TEXT')):
            _migrate_add_column(self.con, 'bets', _col, _typ)
        self.con.commit()

    @staticmethod
    def parse_first_umaban(label):
        """買い目文字列 '7-4-12' 等から先頭の馬番を返す（複式券は bamei に全文を残す）。"""
        for n in re.findall(r'\d+', str(label or '')):
            try:
                u = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= u <= 18:
                return u
        return 0

    def record_prediction(self, race_id, umaban, bamei, pred_prob, odds, stake=100, bet_type='単勝',
                          gate_status=None, gate_lean=None, gate_severity=None,
                          n_points=None, synth_odds=None, has_danger=None, has_value_ana=None,
                          mood=None, deviation=None,
                          purchase_batch_id=None, recommendation_id=None,
                          analysis_run_id=None, audit_link=None,
                          bet_purpose=BET_PURPOSE_CALIBRATION, _commit=True):
        link = audit_link
        if link is None and purchase_batch_id and bet_purpose == BET_PURPOSE_ACTUAL:
            link = 'linked'
        purpose = bet_purpose if bet_purpose is not None else BET_PURPOSE_CALIBRATION
        self.con.execute(
            """INSERT INTO bets(ts,race_id,umaban,bamei,pred_prob,odds,stake,bet_type,
                                gate_status,gate_lean,gate_severity,
                                n_points,synth_odds,has_danger,has_value_ana,
                                mood,deviation,
                                purchase_batch_id,recommendation_id,analysis_run_id,audit_link,
                                bet_purpose)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.datetime.now().isoformat(timespec='seconds'), race_id, umaban, bamei,
             pred_prob, odds, stake, bet_type, gate_status, gate_lean, gate_severity,
             n_points, synth_odds,
             None if has_danger is None else int(bool(has_danger)),
             None if has_value_ana is None else int(bool(has_value_ana)),
             mood, deviation,
             purchase_batch_id, recommendation_id, analysis_run_id, link, purpose))
        if _commit:
            self.con.commit()

    def record_kelly_bets(self, race_id, lines, gate_status=None, gate_lean=None,
                        gate_severity=None, n_points=None, synth_odds=None,
                        has_danger=None, has_value_ana=None, mood=None, deviation=None,
                        purchase_batch_id=None, recommendation_id=None,
                        analysis_run_id=None, audit_link=None,
                        bet_purpose=BET_PURPOSE_ACTUAL, _commit=True):
        """BetSync ケリー買い目（ticket_line の list）を bets に1行ずつ記録。stake>0 のみ。
        戻り値=記録件数。"""
        rid = str(race_id or '').strip()
        if not rid:
            return 0
        n = 0
        for ln in (lines or []):
            try:
                stake = int(ln.get('stake') or 0)
            except (TypeError, ValueError):
                stake = 0
            if stake <= 0:
                continue
            kind = str(ln.get('kind') or ln.get('bet_type') or ln.get('券種') or '単勝')
            label = str(ln.get('label') or ln.get('bamei') or ln.get('買い目') or '')
            try:
                odds = float(ln.get('odds') or ln.get('eval_odds') or 0)
            except (TypeError, ValueError):
                odds = 0.0
            p_val = ln.get('p')
            try:
                if p_val is not None and p_val != '':
                    p_val = float(p_val)
                    if p_val > 1.0:
                        p_val = p_val / 100.0
                else:
                    p_val = None
            except (TypeError, ValueError):
                p_val = None
            if ln.get('umaban') is not None:
                try:
                    umaban = int(ln.get('umaban'))
                except (TypeError, ValueError):
                    umaban = self.parse_first_umaban(label)
            else:
                umaban = self.parse_first_umaban(label)
            self.record_prediction(
                rid, umaban, label, p_val, odds,
                stake=stake, bet_type=kind,
                gate_status=gate_status, gate_lean=gate_lean, gate_severity=gate_severity,
                n_points=n_points, synth_odds=synth_odds,
                has_danger=has_danger, has_value_ana=has_value_ana,
                mood=mood, deviation=deviation,
                purchase_batch_id=purchase_batch_id, recommendation_id=recommendation_id,
                analysis_run_id=analysis_run_id, audit_link=audit_link,
                bet_purpose=bet_purpose, _commit=False)
            n += 1
        if _commit:
            self.con.commit()
        return n

    def settle(self, race_id, win_umaban, win_payout):
        """単勝・actual_purchase 専用手動精算。win_payout=100円あたり配当(円)。

        他券種は更新しない。match_bet_to_payout + settlement log と整合。
        """
        try:
            uma = int(win_umaban)
        except (TypeError, ValueError):
            return {'settled': 0, 'skipped': 0}
        try:
            pay_per_100 = float(win_payout or 0)
        except (TypeError, ValueError):
            pay_per_100 = 0.0
        odds = pay_per_100 / 100.0 if pay_per_100 > 0 else 0.0
        results = {'tan': [{'combo': [uma], 'odds': odds}]}
        settled = skipped = 0
        q = f"""SELECT * FROM bets WHERE race_id=? AND settled=0
                AND bet_type='単勝' AND {ACTUAL_PURCHASE_SQL}"""
        for b in self.con.execute(q, (race_id, BET_PURPOSE_ACTUAL)):
            match = match_bet_to_payout(b, results)
            if match is None:
                skipped += 1
                continue
            self._apply_bet_settlement(
                b['bet_id'], race_id, match,
                source='manual_settle', note='Ledger.settle', action='settle')
            settled += 1
        self.con.commit()
        return {'settled': settled, 'skipped': skipped}

    def _log_settlement(self, bet_id, race_id, ts, won, payout, source='',
                        note='', action='settle'):
        try:
            self.con.execute(
                """INSERT INTO bet_settlement_log(
                       bet_id,race_id,ts,won,payout,source,note,action)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (bet_id, race_id, ts, won, payout, source or '', note or '',
                 action or 'settle'))
        except Exception:
            try:
                self.con.execute(
                    """INSERT INTO bet_settlement_log(
                           bet_id,race_id,ts,won,payout,source,note)
                       VALUES(?,?,?,?,?,?,?)""",
                    (bet_id, race_id, ts, won, payout, source or '', note or ''))
            except Exception:
                pass

    def _apply_bet_settlement(self, bet_id, race_id, match, source='settle_multi',
                              note='', action='settle'):
        ts = datetime.datetime.now().isoformat(timespec='seconds')
        won = int(match['won'])
        payout = int(match['payout'])
        self.con.execute(
            "UPDATE bets SET settled=1, won=?, payout=? WHERE bet_id=?",
            (won, payout, bet_id))
        self._log_settlement(
            bet_id, race_id, ts, won, payout, source, note, action=action)
        return {'won': won, 'payout': payout, 'status': match.get('status')}

    def void_settlement(self, bet_id, note=''):
        """精算済み1件を未精算に戻す（訂正の前半）。二重加算はしない。"""
        row = bet_row_dict(self.con.execute(
            "SELECT * FROM bets WHERE bet_id=?", (bet_id,)).fetchone())
        if not row:
            return {'ok': False, 'reason': 'not_found'}
        if not int(row.get('settled') or 0):
            return {'ok': False, 'reason': 'not_settled'}
        ts = datetime.datetime.now().isoformat(timespec='seconds')
        prev_won = row.get('won')
        prev_payout = row.get('payout')
        self._log_settlement(
            bet_id, row.get('race_id'), ts, prev_won, prev_payout,
            'void_settlement', note or f'void was won={prev_won} payout={prev_payout}',
            action='reversal')
        self.con.execute(
            "UPDATE bets SET settled=0, won=NULL, payout=0 WHERE bet_id=?",
            (bet_id,))
        self.con.commit()
        return {'ok': True, 'prev_won': prev_won, 'prev_payout': prev_payout}

    def correct_settlement(self, bet_id, results, note=''):
        """1ベットの精算を訂正。既精算は reversal ログ後に再適用。一括再精算はしない。"""
        row = bet_row_dict(self.con.execute(
            "SELECT * FROM bets WHERE bet_id=?", (bet_id,)).fetchone())
        if not row:
            return {'ok': False, 'reason': 'not_found'}
        race_id = row.get('race_id')
        prev = None
        if int(row.get('settled') or 0):
            prev = {'won': row.get('won'), 'payout': row.get('payout')}
            ts = datetime.datetime.now().isoformat(timespec='seconds')
            self._log_settlement(
                bet_id, race_id, ts, prev['won'], prev['payout'],
                'correct_settlement',
                note or f"before correct won={prev['won']} payout={prev['payout']}",
                action='reversal')
        match = match_bet_to_payout(row, results)
        if match is None:
            if int(row.get('settled') or 0):
                self.con.execute(
                    "UPDATE bets SET settled=0, won=NULL, payout=0 WHERE bet_id=?",
                    (bet_id,))
                self.con.commit()
            return {'ok': False, 'reason': 'insufficient_data', 'prev': prev, 'voided': bool(prev)}
        new_val = self._apply_bet_settlement(
            bet_id, race_id, match, source='correct_settlement',
            note=note or '', action='correct')
        self.con.commit()
        return {'ok': True, 'prev': prev, 'new': new_val}

    def settle_multi(self, race_id, results, source='settle_multi', note=''):
        """券種別の結果を反映。
        results: {'tan': [{'combo': [5], 'odds': 3.5}], 'trio': [{'combo': [3,5,8], 'odds': 12.0}], ...}
        スクレイパーの fetch_race_payouts の戻り値をそのまま使う。
        払戻キーが無い券種は未精算のまま（外れ扱いにしない）。
        戻り値: {'settled': n, 'pending': m}
        """
        if not results:
            pending = self.con.execute(
                "SELECT COUNT(*) FROM bets WHERE race_id=? AND settled=0",
                (race_id,)).fetchone()[0]
            return {'settled': 0, 'pending': pending}
        settled = pending = 0
        for b in self.con.execute("SELECT * FROM bets WHERE race_id=? AND settled=0", (race_id,)):
            match = match_bet_to_payout(b, results)
            if match is None:
                pending += 1
                continue
            self._apply_bet_settlement(
                b['bet_id'], race_id, match, source=source, note=note, action='settle')
            settled += 1
        self.con.commit()
        return {'settled': settled, 'pending': pending}

    def verified_actual_bet_rows(self, settled_only=False):
        """validate_committed_actual_purchase が committed_actual の batch に属する actual bets。

        bet_purpose だけでは足りない。legacy_unverified や batch 無しは含めない。
        """
        from core import audit_purchase as apur
        from core import audit_store
        q = f"SELECT * FROM bets WHERE {ACTUAL_PURCHASE_SQL}"
        params = [BET_PURPOSE_ACTUAL]
        if settled_only:
            q += " AND settled=1"
        q += " ORDER BY bet_id"
        raw = [bet_row_dict(r) for r in self.con.execute(q, params)]
        if not raw:
            return []
        st = audit_store.AuditStore(con=self.con)
        cache = {}
        out = []
        for row in raw:
            bid = str(row.get('purchase_batch_id') or '').strip()
            if not bid:
                continue
            if bid not in cache:
                val = apur.validate_committed_actual_purchase(st, self, bid)
                cache[bid] = bool(
                    val.get('valid') and val.get('state') == 'committed_actual')
            if cache[bid]:
                out.append(row)
        return out

    def _actual_settled_rows_raw(self):
        return self.verified_actual_bet_rows(settled_only=True)

    def settled_rows(self):
        """精算済みの検証済み実購入を古い順に返す（ROI推移グラフ用）"""
        return self.verified_actual_bet_rows(settled_only=True)

    def actual_purchase_totals(self, settled_only=True):
        """検証済み実購入の stake / payout / pnl / roi(%)。"""
        rows = self.verified_actual_bet_rows(settled_only=settled_only)
        staked = sum(int(r.get('stake') or 0) for r in rows)
        returned = sum(int(r.get('payout') or 0) for r in rows)
        roi = (returned / staked * 100.0) if staked else 0.0
        return {
            'stake': staked,
            'payout': returned,
            'pnl': returned - staked,
            'roi_pct': roi,
            'count': len(rows),
        }

    def roi_by_gate(self):
        """Gate判定(gate_status)別の的中率/ROI/件数（検証済み実購入のみ）。"""
        buckets = {}
        for r in self.verified_actual_bet_rows(settled_only=True):
            g = r.get('gate_status') or '(未タグ)'
            d = buckets.setdefault(g, {'n': 0, 'w': 0, 'inv': 0, 'ret': 0})
            d['n'] += 1
            d['w'] += int(r.get('won') or 0)
            d['inv'] += int(r.get('stake') or 0)
            d['ret'] += int(r.get('payout') or 0)
        out = {}
        for g, d in buckets.items():
            n = d['n']
            inv = d['inv']
            out[g] = {
                'n': n,
                'win_rate': (d['w'] / n) if n else 0,
                'roi': (d['ret'] / inv) if inv else 0,
            }
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
        for r in self.verified_actual_bet_rows(settled_only=True):
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
        """実購入ROIと較正(Brier)を分離。legacy NULL は実購入に含めない。"""
        all_settled = [bet_row_dict(r) for r in self.con.execute(
            "SELECT * FROM bets WHERE settled=1")]
        if not all_settled:
            return {'note': '精算済みベットなし'}
        actual = [bet_row_dict(r) for r in self._actual_settled_rows_raw()]
        calib = [r for r in all_settled if bet_row_effective_purpose(r) == BET_PURPOSE_CALIBRATION]
        out = {'scope': 'split', 'legacy_settled': sum(
            1 for r in all_settled if bet_row_effective_purpose(r) == BET_PURPOSE_LEGACY)}
        if actual:
            n = len(actual)
            wins = sum(int(r.get('won') or 0) for r in actual)
            staked = sum(int(r.get('stake') or 0) for r in actual)
            returned = sum(int(r.get('payout') or 0) for r in actual)
            out.update({
                'bets': n,
                'hit_rate': round(wins / n * 100, 1),
                'roi': round(returned / staked * 100, 1) if staked else 0.0,
                'profit': returned - staked,
                'actual_staked': staked,
                'actual_returned': returned,
                'roi_denominator': 'actual_purchase_settled_stake',
            })
        else:
            out.update({'bets': 0, 'hit_rate': 0.0, 'roi': 0.0, 'profit': 0,
                        'actual_staked': 0, 'actual_returned': 0,
                        'roi_denominator': 'actual_purchase_settled_stake',
                        'note_actual': '精算済み実購入なし'})
        brier_rows = [r for r in (calib or all_settled)
                      if r.get('pred_prob') is not None]
        if brier_rows:
            brier = sum(
                (float(r['pred_prob']) - int(r.get('won') or 0)) ** 2
                for r in brier_rows) / len(brier_rows)
            out['brier'] = round(brier, 4)
            out['brier_n'] = len(brier_rows)
        else:
            out['brier'] = None
            out['brier_n'] = 0
        out['calibration_settled'] = len(calib)
        return out

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
        buckets = {}
        for r in self.verified_actual_bet_rows(settled_only=True):
            k = r.get('mood') or '(未記録)'
            d = buckets.setdefault(k, {'n': 0, 'w': 0, 'p': 0, 's': 0})
            d['n'] += 1
            d['w'] += int(r.get('won') or 0)
            d['p'] += int(r.get('payout') or 0)
            d['s'] += int(r.get('stake') or 0)
        out = {}
        for k, d in buckets.items():
            n = d['n']
            if not n:
                continue
            out[k] = {
                'n': n,
                'hit': d['w'] / n * 100,
                'roi': d['p'] / (d['s'] or 1) * 100,
                'stake_avg': d['s'] / n,
            }
        return out

    # ── ③ ルールからの逸脱 ───────────────────────────
    def deviation_report(self):
        """逸脱の種類別の件数・ROI。資料の核心「修正すべきはルールからの逸脱のみ」。"""
        grouped = {}
        plain = {'n': 0, 'w': 0, 'p': 0, 's': 0}
        for r in self.verified_actual_bet_rows(settled_only=True):
            dev = r.get('deviation')
            if dev is not None and str(dev) != '':
                d = grouped.setdefault(dev, {'n': 0, 'w': 0, 'p': 0, 's': 0})
            else:
                d = plain
            d['n'] += 1
            d['w'] += int(r.get('won') or 0)
            d['p'] += int(r.get('payout') or 0)
            d['s'] += int(r.get('stake') or 0)
        out = {}
        for name, d in grouped.items():
            n = d['n']
            if not n:
                continue
            out[name] = {
                'n': n, 'hit': d['w'] / n * 100,
                'roi': d['p'] / (d['s'] or 1) * 100}
        if plain['n']:
            out['（逸脱なし）'] = {
                'n': plain['n'],
                'hit': plain['w'] / plain['n'] * 100,
                'roi': plain['p'] / (plain['s'] or 1) * 100}
        return out

    def reflection(self):
        """予測勝率の帯ごとに『予測 vs 実際』を比較→較正のズレと次回ルールを生成"""
        rows = [
            r for r in self.verified_actual_bet_rows(settled_only=True)
            if r.get('pred_prob') is not None]
        if len(rows) < 10:
            return ["（サンプル不足。10件以上の精算で反省が有効に）"]
        buckets = {}
        for r in rows:
            b = min(4, int(float(r['pred_prob']) * 5))
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
        if not payouts:
            return None
        has_data = any(payouts.get(k) for k in payouts)
        if not has_data:
            return None
        winner = win_payout = None
        if payouts.get('tan'):
            winner = payouts['tan'][0]['combo'][0]
            win_payout = int(payouts['tan'][0]['odds'] * 100)
        summary = self.settle_multi(race_id, payouts, source='auto_settle_race')
        if summary.get('settled', 0) == 0 and summary.get('pending', 0) == unsettled:
            return None
        return {
            'winner': winner,
            'payout': win_payout,
            'settled': summary.get('settled', 0),
            'pending': summary.get('pending', 0),
        }

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass
