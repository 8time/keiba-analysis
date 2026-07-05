# -*- coding: utf-8 -*-
"""妙味度(race_value_score)で3連複の狙い目価格帯(オッズ帯)を動かす案の検証。

ユーザー案: レースの妙味度(荒れ度)に応じて3連複の狙い目オッズ帯を可変にしたい。
検証すべき前提: 『妙味度が高いレースほど、実際の勝ち3連複の配当が系統的に高いか』。
  YESなら→高妙味度で帯を上(高配当狙い)にシフトする根拠あり。
  NO(配当が妙味度で動かない)なら→可変帯は無意味(固定でよい)。

方法: jravan.dbの各JRAレースで race_value_score を算出し、実際の勝ち3連複配当(payouts)と
突き合わせ。妙味度ラベル(S/A/B/C/D)別に配当の中央値/四分位、およびSpearman相関を見る。
2016-2025・JRA平地。リーク無し(事前オッズ分布と構造条件のみ・結果は配当のみ参照)。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import value_scanner as vs
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def spearman(pairs):
    n = len(pairs)
    if n < 10:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    return num / (dx * dy) if dx and dy else None


def pct(vals, p):
    if not vals:
        return 0
    s = sorted(vals)
    k = (len(s) - 1) * p
    f = int(k)
    return s[f] if f + 1 >= len(s) else s[f] + (s[f + 1] - s[f]) * (k - f)


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    # レース属性
    races = con.execute(
        "SELECT race_key, jyo, surface, kyori, shusso_tosu, juryo, "
        "COALESCE(baba_shiba,baba_dirt) baba, kigo "
        "FROM races WHERE jyo<='10' AND CAST(year AS INT)>=2016").fetchall()
    # 各レースの単勝オッズ list
    odds_rows = con.execute(
        "SELECT race_key, win_odds FROM results WHERE jyo<='10' AND win_odds>0").fetchall()
    # 3連複配当
    pay_rows = con.execute(
        "SELECT race_key, payout FROM payouts WHERE bet_type='3連複'").fetchall()
    con.close()

    odds_by = defaultdict(list)
    for rk, o in odds_rows:
        odds_by[rk].append(o / 10.0)
    pay_by = {}
    for rk, p in pay_rows:
        if p and p > 0:
            pay_by[rk] = p / 100.0  # 円→倍(100円=1倍)

    baba_map = {'1': '良', '2': '稍重', '3': '重', '4': '不良'}
    by_label = defaultdict(list)   # label -> [payout倍]
    corr_pairs = []                # (value_score, payout倍)
    n = 0
    for (rk, jyo, surf, kyori, tosu, juryo, baba, kigo) in races:
        pay = pay_by.get(rk)
        ol = odds_by.get(rk)
        if not pay or not ol or len(ol) < 5:
            continue
        meta = {'is_handicap': str(juryo) == '1',
                'condition': baba_map.get(str(baba), '良'),
                'class': ''}
        rv = vs.race_value_score(ol, meta=meta, jyo=str(jyo), surface=str(surf),
                                 dist=kyori, n_horses=tosu)
        by_label[str(rv['label'])[:1]].append(pay)
        corr_pairs.append((rv['score'], pay))
        n += 1

    print(f"対象: {n:,}レース (JRA平地 2016-2025・3連複配当あり)\n")
    print("妙味度ラベル別 勝ち3連複配当(倍):")
    print(f"{'ラベル':10s} {'n':>7s} {'中央値':>8s} {'25%':>8s} {'75%':>8s} {'平均':>8s} {'>=100倍率':>9s}")
    for lb in ['S', 'A', 'B', 'C', 'D']:
        v = by_label.get(lb, [])
        if not v:
            continue
        big = sum(1 for x in v if x >= 100) / len(v)
        print(f"{lb:10s} {len(v):>7d} {pct(v,0.5):>8.1f} {pct(v,0.25):>8.1f} "
              f"{pct(v,0.75):>8.1f} {sum(v)/len(v):>8.1f} {big:>8.1%}")

    sp = spearman(corr_pairs)
    print(f"\n妙味度スコア vs 3連複配当 の Spearman順位相関: {sp:+.4f}" if sp is not None else "相関計算不可")
    print("\n[判定] ラベルS→Dで配当中央値が単調に下がり、相関が明確に正(例>+0.15)なら"
          "『妙味度で狙い目帯を動かす』案に根拠あり(高妙味度=高配当を狙う帯へ)。"
          "相関がほぼ0/配当が動かないなら、可変帯は無意味＝固定帯でよい。")


if __name__ == '__main__':
    main()
