# -*- coding: utf-8 -*-
"""買い方研究 第3弾: 「人気2+穴1」ブック型フォーメーション+穴頭カットの点数最適化。

前提(検証済み・verified_formation_roi): 荒れ確率≥62%帯で可変フォーメーションはROI中央90%
(控除率floor75%は有意超え・但し100%未満)。狙いは『取りこぼしと点数の最適化』でROIを100%へ寄せる
(EVで市場を超えるのではなく、無駄な買い目を削って回収率を上げる)。

書籍/動画の核心(検証済: 人気馬=1-4で人気2+穴1=49.9%が最頻): 3連単を「人気2+穴1」の3型に絞る。
  subA 人気→人気→穴 / subB 人気→穴→人気 / subC 穴→人気→人気(=穴頭)
穴頭(subC・人気薄1着)は1着率が極めて低い(5+番人気の1着率2.5%=40回に1回)ので切ると点数半減。
ただし荒れ帯では穴頭も起きうる→実配当でsubC込み(book) vs subC無し(book_nohead) を直接比較。

pop=top3人気(R1-3=◎〇＋), ana=妙味穴top2(6番人気以下×combo上位)。実配当+bootstrap 90%CIで判定。
"""
import os
import sys
import sqlite3
import random
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 10
# 帯: 堅(ap<0.42)/中(0.42-0.60)/荒れ(≥0.62)。ブックが効く帯を特定する。


def load_trifecta_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[rk] = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
    con.close()
    return out


def ordered(slots):
    """slots=(list1着,list2着,list3着)→順序付き相異の3連単combo集合。"""
    out = set()
    for a in slots[0]:
        for b in slots[1]:
            if b == a:
                continue
            for c in slots[2]:
                if c == a or c == b:
                    continue
                out.add((a, b, c))
    return out


def book_formations(pop, ana):
    """pop=人気馬(R1-3), ana=妙味穴(top2)。人気2+穴1の3型からフォーメーション集合を返す。"""
    A = ordered((pop, pop, ana))   # 人気→人気→穴
    B = ordered((pop, ana, pop))   # 人気→穴→人気
    C = ordered((ana, pop, pop))   # 穴→人気→人気(穴頭)
    return {'book': A | B | C, 'book_nohead': A | B}


def main():
    print("payouts読み込み...")
    payout = load_trifecta_payouts()
    df = cd.load_horses(cols=['race_key', 'day', 'ninki', 'win_odds', 'combo',
                              'chakujun', 'umaban', 'is_handi1'])
    df = df[df['umaban'].notna()]
    by_race = defaultdict(list)
    for r in df.itertuples(index=False):
        by_race[str(r.race_key)].append(r)

    STRATS = ('wide', 'book', 'book_nohead')
    BANDS = ('堅(ap<42%)', '中(42-60%)', '荒れ(≥62%)')
    agg = {ft: {s: [0.0, 0.0, 0, 0, 0] for s in STRATS} for ft in BANDS}
    boot = defaultdict(list)

    for rk, rows in by_race.items():
        if rk not in payout or len(rows) < MIN_HORSES:
            continue
        odds_list = [r.win_odds for r in rows if r.win_odds and r.win_odds > 0]
        if len(odds_list) < 3:
            continue
        ap = vs.arare_prob(odds_list, {'is_handicap': bool(rows[0].is_handi1)}, len(rows))
        if ap is None:
            continue
        band = '堅(ap<42%)' if ap < 0.42 else ('中(42-60%)' if ap < 0.60 else '荒れ(≥62%)')
        win, pay = payout[rk]

        ranked = sorted(rows, key=lambda x: (x.ninki if x.ninki else 99))
        R = [int(r.umaban) for r in ranked]
        pop = R[:3]                                     # 人気馬 = 1-3番人気(◎〇＋)
        # 妙味穴 = 6番人気以下×combo上位 top2。無ければ人気薄4-8番で代替。
        ana = [int(r.umaban) for r in sorted(rows, key=lambda x: -(x.combo or 0))
               if r.ninki and r.ninki >= 6 and (r.combo or 0) >= 1][:2]
        if len(ana) < 2:
            extra = [int(r.umaban) for r in ranked if r.ninki and 5 <= r.ninki <= 9
                     and int(r.umaban) not in ana]
            ana = (ana + extra)[:2]
        if len(ana) < 2:
            continue

        forms = book_formations(pop, ana)
        forms['wide'] = ordered((pop[:2] + ana, R[:5], R[:7]))   # 前回の荒れ用wide(穴1着込み)

        for s in STRATS:
            combos = forms[s]
            pts = len(combos)
            if pts <= 0:
                continue
            h = 1 if win in combos else 0
            a = agg[band][s]
            a[0] += pts * 100
            a[1] += pay if h else 0.0
            a[2] += h
            a[3] += pts
            a[4] += 1
            boot[(band, s)].append((pts * 100, pay if h else 0.0))

    for band in BANDS:
        print(f"\n{'='*70}\n=== 帯: {band} ===")
        print(f"  {'買い方':13s} {'参加':>6s} {'的中率':>7s} {'平均点数':>7s} {'平均購入':>8s} {'回収率':>8s}")
        for s in STRATS:
            cost, ret, hits, pts, n = agg[band][s]
            if n < 30:
                continue
            print(f"  {s:13s} {n:6d} {hits/n:6.1%} {pts/n:7.1f} ¥{pts/n*100:7.0f} "
                  f"{ret/cost if cost else 0:7.1%}")

    print(f"\n{'='*70}\n=== raw ROI bootstrap(1000回・90%CI) ===")
    random.seed(42)
    for (band, s), recs in sorted(boot.items()):
        if len(recs) < 100:
            continue
        rois = []
        m = len(recs)
        for _ in range(1000):
            samp = [recs[random.randrange(m)] for _ in range(m)]
            c = sum(x[0] for x in samp); r = sum(x[1] for x in samp)
            rois.append(r / c if c else 0)
        rois.sort()
        lo, mid, hi = rois[50], rois[500], rois[950]
        v = '★★利益(100%超)' if lo > 1.0 else ('★floor超(<100%)' if lo > 0.75 else '75%跨ぐ/未達')
        print(f"  {band:11s} {s:13s} n={m:5d} 中央{mid:6.1%} 90%CI[{lo:5.1%},{hi:6.1%}] {v}")
    print("\n[判定] ブック(人気2+穴1)が効く帯を特定。堅い帯でwide>bookなら点数最適化も無力=市場効率的。"
          "どの帯・買い方も100%CI下限を出さなければ、3連単は買い方で利益化できない(見送り/資金管理が主戦場)。")


if __name__ == '__main__':
    main()
