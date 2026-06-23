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
"""


class Ledger:
    def __init__(self, db=LEDGER_DB):
        os.makedirs(os.path.dirname(db), exist_ok=True)
        self.con = sqlite3.connect(db)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_DDL)
        # #8 Gate結果列＋#1 買い目メタ列(設計ミス分類用)を後方互換で追加
        for _col, _typ in (('gate_status', 'TEXT'), ('gate_lean', 'TEXT'),
                           ('gate_severity', 'INTEGER'),
                           ('n_points', 'INTEGER'), ('synth_odds', 'REAL'),
                           ('has_danger', 'INTEGER'), ('has_value_ana', 'INTEGER')):
            try:
                self.con.execute(f"ALTER TABLE bets ADD COLUMN {_col} {_typ}")
            except Exception:
                pass  # 既に存在
        self.con.commit()

    def record_prediction(self, race_id, umaban, bamei, pred_prob, odds, stake=100, bet_type='単勝',
                          gate_status=None, gate_lean=None, gate_severity=None,
                          n_points=None, synth_odds=None, has_danger=None, has_value_ana=None):
        self.con.execute(
            """INSERT INTO bets(ts,race_id,umaban,bamei,pred_prob,odds,stake,bet_type,
                                gate_status,gate_lean,gate_severity,
                                n_points,synth_odds,has_danger,has_value_ana)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datetime.datetime.now().isoformat(timespec='seconds'), race_id, umaban, bamei,
             pred_prob, odds, stake, bet_type, gate_status, gate_lean, gate_severity,
             n_points, synth_odds,
             None if has_danger is None else int(bool(has_danger)),
             None if has_value_ana is None else int(bool(has_value_ana))))
        self.con.commit()

    def settle(self, race_id, win_umaban, win_payout):
        """race_id の結果を反映（単勝）。win_payout=100円あたり配当"""
        for b in self.con.execute("SELECT * FROM bets WHERE race_id=? AND settled=0", (race_id,)):
            won = 1 if b['umaban'] == win_umaban else 0
            payout = int(win_payout * b['stake'] / 100) if won else 0
            self.con.execute("UPDATE bets SET settled=1, won=?, payout=? WHERE bet_id=?",
                             (won, payout, b['bet_id']))
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

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass
