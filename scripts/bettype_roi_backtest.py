# -*- coding: utf-8 -*-
"""
券種別ROI検証 — 単勝以外(複勝/馬連/ワイド/馬単/3連複/3連単)に市場の歪み(+ROI)が
残っていないか。人気で機械的に買う標準戦略を実払戻(payouts)でバックテスト。
scripts/bettype_roi_backtest.py  2016-2026

payout=100円あたりの払戻円。ROI = Σ払戻 / (100×点数) ×100%。100%超=理論プラス。
combo形式: 複勝'06' / 馬連・ワイド・3連複=昇順2桁連結 / 馬単・3連単=着順2桁連結。
リーク無し: 人気・組番はすべて事前確定。
"""
import os
import sys
import sqlite3
import time as _time
from collections import defaultdict
from itertools import combinations

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
Y_FROM, Y_TO = 2016, 2026


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro()
    print("loading results...", file=sys.stderr)
    res = con.execute(
        f"""SELECT ra.race_key, r.ninki, r.umaban
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN {Y_FROM} AND {Y_TO}
              AND ra.surface IN ('芝','ダート') AND r.ninki>0 AND r.umaban>0""").fetchall()
    pop2um = defaultdict(dict)
    for rk, ninki, um in res:
        pop2um[rk][int(ninki)] = int(um)
    print("loading payouts...", file=sys.stderr)
    pay = con.execute(
        f"""SELECT ra.race_key, p.bet_type, p.combo, p.payout
            FROM races ra JOIN payouts p ON p.race_key=ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN {Y_FROM} AND {Y_TO}
              AND ra.surface IN ('芝','ダート') AND p.payout>0""").fetchall()
    con.close()
    win = defaultdict(lambda: defaultdict(dict))  # race_key -> bet_type -> {combo: payout}
    for rk, bt, combo, p in pay:
        win[rk][bt][str(combo)] = int(p)
    races = [rk for rk in pop2um if rk in win]
    print(f"races={len(races):,}", file=sys.stderr)

    def um(rk, n):
        return pop2um[rk].get(n)

    def c_sorted(*us):
        return ''.join(f'{u:02d}' for u in sorted(us))

    def c_order(*us):
        return ''.join(f'{u:02d}' for u in us)

    # strategy(rk) -> (cost_points, payout_received). None if not applicable.
    def s_place(n):
        def f(rk):
            u = um(rk, n)
            if u is None:
                return None
            return (1, win[rk].get('複勝', {}).get(f'{u:02d}', 0))
        return f

    def s_combo(bt, builder, fmt):
        def f(rk):
            combos = builder(rk)
            if not combos:
                return None
            w = win[rk].get(bt, {})
            ret = sum(w.get(fmt(*c), 0) for c in combos)
            return (len(combos), ret)
        return f

    def need(rk, ns):
        us = [um(rk, n) for n in ns]
        return us if all(u is not None for u in us) else None

    STRATS = []
    # 複勝 人気別
    for n in range(1, 11):
        STRATS.append((f'複勝 {n}番人気', s_place(n)))
    # 馬連
    STRATS.append(('馬連 1-2番人気(1点)', s_combo('馬連',
        lambda rk: ([tuple(need(rk, [1, 2]))] if need(rk, [1, 2]) else []), c_sorted)))
    STRATS.append(('馬連 1-3番人気BOX(3点)', s_combo('馬連',
        lambda rk: (list(combinations(need(rk, [1, 2, 3]), 2)) if need(rk, [1, 2, 3]) else []), c_sorted)))
    STRATS.append(('馬連 1番軸-2~5番(4点)', s_combo('馬連',
        lambda rk: ([(um(rk, 1), um(rk, k)) for k in range(2, 6)] if need(rk, [1, 2, 3, 4, 5]) else []), c_sorted)))
    # ワイド
    STRATS.append(('ワイド 1-2番人気(1点)', s_combo('ワイド',
        lambda rk: ([tuple(need(rk, [1, 2]))] if need(rk, [1, 2]) else []), c_sorted)))
    STRATS.append(('ワイド 1番軸-2~4番(3点)', s_combo('ワイド',
        lambda rk: ([(um(rk, 1), um(rk, k)) for k in range(2, 5)] if need(rk, [1, 2, 3, 4]) else []), c_sorted)))
    # 馬単
    STRATS.append(('馬単 1→2番人気(1点)', s_combo('馬単',
        lambda rk: ([(um(rk, 1), um(rk, 2))] if need(rk, [1, 2]) else []), c_order)))
    STRATS.append(('馬単 1着固定→2~4番(3点)', s_combo('馬単',
        lambda rk: ([(um(rk, 1), um(rk, k)) for k in range(2, 5)] if need(rk, [1, 2, 3, 4]) else []), c_order)))
    # 3連複
    STRATS.append(('3連複 1-2-3番人気(1点)', s_combo('3連複',
        lambda rk: ([tuple(need(rk, [1, 2, 3]))] if need(rk, [1, 2, 3]) else []), c_sorted)))
    STRATS.append(('3連複 1-2軸-3~6番(4点)', s_combo('3連複',
        lambda rk: ([(um(rk, 1), um(rk, 2), um(rk, k)) for k in range(3, 7)] if need(rk, [1, 2, 3, 4, 5, 6]) else []), c_sorted)))
    STRATS.append(('3連複 1-4番人気BOX(4点)', s_combo('3連複',
        lambda rk: (list(combinations(need(rk, [1, 2, 3, 4]), 3)) if need(rk, [1, 2, 3, 4]) else []), c_sorted)))
    # 3連単
    STRATS.append(('3連単 1→2→3番人気(1点)', s_combo('3連単',
        lambda rk: ([(um(rk, 1), um(rk, 2), um(rk, 3))] if need(rk, [1, 2, 3]) else []), c_order)))
    STRATS.append(('3連単 1着固定→2-3番マルチ(6点)', s_combo('3連単',
        lambda rk: ([(um(rk, 1), a, b) for a in [um(rk, 2), um(rk, 3)] for b in [um(rk, 2), um(rk, 3)] if a != b]
                    + [(a, um(rk, 1), b) for a in [um(rk, 2), um(rk, 3)] for b in [um(rk, 2), um(rk, 3)] if a != b and um(rk, 1) != b]
                    if need(rk, [1, 2, 3]) else []), c_order)))

    print("=" * 76)
    print(f"券種別ROI {Y_FROM}-{Y_TO}  races={len(races):,}  (payout=100円あたり/ROI100%=損益分岐)")
    print("=" * 76)
    print(f"{'戦略':<28}{'対象R':>8}{'点/R':>6}{'的中R%':>8}{'ROI%':>8}")
    print("-" * 76)
    for name, fn in STRATS:
        n_races = 0; total_cost = 0; total_ret = 0; hit_races = 0
        for rk in races:
            r = fn(rk)
            if r is None:
                continue
            pts, ret = r
            n_races += 1
            total_cost += pts * 100
            total_ret += ret
            if ret > 0:
                hit_races += 1
        if n_races < 300 or total_cost == 0:
            continue
        roi = total_ret / total_cost * 100
        ppr = total_cost / n_races / 100
        mark = ' ★+ROI' if roi >= 100 else ''
        print(f"{name:<28}{n_races:>8}{ppr:>6.0f}{hit_races / n_races * 100:>8.1f}{roi:>8.1f}{mark}")
    print("-" * 76)
    print("★=ROI100%超(歪み)。控除率20-27.5%があるので大半は70-80%台で横並びの想定。")
    print("券種を変えても+ROIが出ない＝『買い方(見送り/点数)』で勝つしかない(コンシェルジュ方針)。")


if __name__ == '__main__':
    main()
