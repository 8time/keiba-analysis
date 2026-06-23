# -*- coding: utf-8 -*-
"""本丸: 消去軸1頭+検証エッジ流し の3連複ROI検証(追い上げ無し)。
仮説(ユーザー): 相手を人気順でなく『検証エッジで過小評価された穴』で選べばROIが上がる。
最強の穴エッジ=末脚偏差([[verified_spurt_index]]: 6番人気以下×末脚top3が複勝/ROIでベース超)。

比較(同一レース・同一構造で穴の選び方だけ変える):
  軸=1番人気・相手5頭={2番,3番人気}+{穴3頭}。10点×100円。
  - EDGE流し : 穴3頭 = 6番人気以下のうち末脚指数(直近3走の上がり3F偏差)上位3頭
  - NINKI流し: 穴3頭 = 6,7,8番人気(人気順で機械的)
  - 参考)本命型: 相手=2-6番人気(穴なし)
末脚指数はリーク無し(対象レースより前の走のみ)。spurt_index_backtest.pyと同一定義。
ROIが EDGE>NINKI なら末脚エッジは3連複ROIに変換される。2021-25 平地 tosu>=8。"""
import os
import sys
import sqlite3
import statistics
from itertools import combinations
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import value_scanner as vs

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
K = 3            # 末脚指数の直近走数
TRAIN_FROM = 2018


def dkey(y, md):
    try:
        return int(y) * 10000 + int(md)
    except Exception:
        return 0


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
    res = con.execute(
        "SELECT race_key, year, monthday, ketto_num, umaban, chakujun, ninki, win_odds, ato3f "
        "FROM results WHERE CAST(year AS INTEGER)>=? AND chakujun>0", (TRAIN_FROM,)).fetchall()
    meta_rows = con.execute(
        """SELECT race_id, race_key, shusso_tosu, juryo, kyori, surface, baba_shiba, baba_dirt
           FROM races WHERE CAST(year AS INTEGER) BETWEEN 2021 AND 2025
             AND shubetsu IN ('11','12','13','14') AND shusso_tosu>=8""").fetchall()
    prows = con.execute(
        """SELECT race_id, combo, payout FROM payouts WHERE bet_type='3連複'
           AND (race_id LIKE '2021%' OR race_id LIKE '2022%' OR race_id LIKE '2023%'
                OR race_id LIKE '2024%' OR race_id LIKE '2025%')""").fetchall()
    con.close()

    pay = {}
    for rid, combo, p in prows:
        try:
            pay[rid] = (frozenset(int(combo[i:i+2]) for i in range(0, 6, 2)), p)
        except Exception:
            pass

    # ── 末脚偏差(レース内z)とリーク無し履歴 ──
    by_race = defaultdict(list)
    for r in res:
        by_race[r[0]].append(r)
    spurt = {}            # (race_key, ketto) -> dev
    hist = defaultdict(list)   # ketto -> [(dk, dev)]
    for rk, rs in by_race.items():
        vals = [r[8] for r in rs if r[8] and r[8] > 0]
        if len(vals) < 5:
            continue
        m = statistics.mean(vals); sd = statistics.pstdev(vals)
        if sd <= 0:
            continue
        for r in rs:
            if not r[8] or r[8] <= 0:
                continue
            dev = (m - r[8]) / sd
            spurt[(rk, r[3])] = dev
            hist[r[3]].append((dkey(r[1], r[2]), dev))
    for k in hist:
        hist[k].sort()

    def prior_idx(ketto, dk):
        h = hist.get(ketto)
        if not h:
            return None
        past = [d for (d2, d) in h if d2 < dk]
        if not past:
            return None
        return sum(past[-K:]) / len(past[-K:])

    rk2meta = {m[1]: m for m in meta_rows}
    _BABA = {'3': '重', '4': '不良'}
    cell = defaultdict(lambda: [0, 0, 0, 0])   # [invested, returned, n, hits]
    FILTERS = ['全レース', '②穴妙味向き', '②+中立']

    def add(strat, filt_tags, won, pp):
        for ft in filt_tags:
            c = cell[(strat, ft)]
            c[0] += 1000; c[2] += 1
            if won:
                c[1] += pp; c[3] += 1

    for m in meta_rows:
        rid, rk, tosu, juryo, kyori, surf, bsh, bdt = m
        if rid not in pay or rk not in by_race:
            continue
        win_tri, pp = pay[rid]
        rs = by_race[rk]
        dk = dkey(rs[0][1], rs[0][2])
        by_ninki = {r[6]: r[4] for r in rs if r[6]}        # ninki -> umaban
        if not all(n in by_ninki for n in (1, 2, 3)):
            continue
        axis = by_ninki[1]
        # 穴プール(6番人気以下・末脚指数あり)
        ana = []
        for r in rs:
            if r[6] and r[6] >= 6:
                pi = prior_idx(r[3], dk)
                if pi is not None:
                    ana.append((r[4], r[6], pi))   # (umaban, ninki, spurt)
        edge3 = [u for (u, _, _) in sorted(ana, key=lambda x: -x[2])[:3]]
        ninki3 = [by_ninki[n] for n in (6, 7, 8) if n in by_ninki]
        pop5 = [by_ninki[n] for n in (2, 3, 4, 5, 6) if n in by_ninki]
        # フェア比較: 穴の深さを固定(6-12番人気)した中で末脚上位3 vs 下位3
        ana_fix = [(u, n, pi) for (u, n, pi) in ana if 6 <= n <= 12]
        fair_top = [u for (u, _, _) in sorted(ana_fix, key=lambda x: -x[2])[:3]]
        fair_bot = [u for (u, _, _) in sorted(ana_fix, key=lambda x: x[2])[:3]]
        odds = [r[7] for r in rs if r[7] and r[7] > 0]
        lean = vs.trio_lean(meta={'is_handicap': juryo == '1'}, n_horses=tosu,
                            fav_odds=min(odds) if odds else None, dist=kyori,
                            baba=_BABA.get(str((bsh if surf == '芝' else bdt) or '')),
                            odds_list=odds)['lean']
        ftags = ['全レース']
        if lean == '②穴妙味向き':
            ftags.append('②穴妙味向き')
        if lean in ('②穴妙味向き', '中立'):
            ftags.append('②+中立')

        def trio_won(partners):
            if len({axis, *partners}) != 6:   # axis+5相手が相異なる
                return None
            pts = [frozenset(c) for c in combinations(partners, 2)]
            return (axis in win_tri) and ((win_tri - {axis}) in pts)

        # 同一レースで両方組めるときだけ比較(穴3頭が確保できる)
        p_edge = [by_ninki[2], by_ninki[3]] + edge3
        p_ninki = [by_ninki[2], by_ninki[3]] + ninki3
        if len(set(p_edge)) == 5 and len(set(p_ninki)) == 5 and len(set(pop5)) == 5:
            w_e = trio_won(p_edge); w_n = trio_won(p_ninki); w_p = trio_won(pop5)
            if w_e is not None and w_n is not None and w_p is not None:
                add('EDGE流し(末脚穴)', ftags, w_e, pp)
                add('NINKI流し(6-8番)', ftags, w_n, pp)
                add('本命型(2-6番)', ftags, w_p, pp)
        # フェア比較(穴深さ6-12固定で末脚上位vs下位): 同一レースで両方組める時のみ
        pf_top = [by_ninki[2], by_ninki[3]] + fair_top
        pf_bot = [by_ninki[2], by_ninki[3]] + fair_bot
        if len(set(pf_top)) == 5 and len(set(pf_bot)) == 5:
            wt = trio_won(pf_top); wb = trio_won(pf_bot)
            if wt is not None and wb is not None:
                add('★末脚上位(6-12穴)', ftags, wt, pp)
                add('★末脚下位(6-12穴)', ftags, wb, pp)

    print("=" * 92)
    print("本丸: 検証エッジ(末脚)流し vs 人気順流し の3連複ROI (軸1番人気・10点×100円・2021-25)")
    print("同一レース・同一構造(相手=2,3番+穴3頭)で『穴の選び方』だけ変えた比較")
    print("=" * 92)
    print(f"{'戦略':<20}{'フィルター':<12}{'n':>7}{'的中%':>8}{'平均配当':>9}{'ROI%':>8}")
    print("-" * 92)
    for strat in ('本命型(2-6番)', 'NINKI流し(6-8番)', 'EDGE流し(末脚穴)',
                  '★末脚上位(6-12穴)', '★末脚下位(6-12穴)'):
        for ft in FILTERS:
            c = cell[(strat, ft)]
            if c[2] < 100:
                continue
            roi = c[1] / c[0] * 100 if c[0] else 0
            hitr = c[3] / c[2] * 100
            avgp = c[1] / c[3] if c[3] else 0
            mark = ' ★100%超' if roi >= 100 else (' ◎85%超' if roi >= 85 else '')
            print(f"{strat:<20}{ft:<12}{c[2]:>7}{hitr:>8.1f}{avgp:>9.0f}{roi:>8.1f}{mark}")
        print()
    print("-" * 92)
    print("→ EDGE流し の ROI が NINKI流し を明確に上回れば、末脚エッジは3連複ROIに変換される。")
    print("  同水準なら『穴の中での選別』も市場に織込まれている(=ROIは動かない)。")


if __name__ == '__main__':
    main()
