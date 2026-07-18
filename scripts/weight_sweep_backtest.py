# -*- coding: utf-8 -*-
"""影響率(ウェイト)を上げると本当に精度が上がるのかを全レースで測る。

発端: 1レース(202603020611・結果11→6→9→10→1)の結果に合わせて
「Lap33の上位3頭に+15、末脚指数の上位3頭に+20…」というウェイト調整案が出た。
これは典型的な後知恵の過学習なので、**同じ調整を全レースに適用して汎化するか**を測る。

測るもの(1レース1回・馬をスコア降順に並べた時の):
  recall@7 : 勝ち馬がスコア上位7頭に入る率(既存LTRの評価軸と同じ)
  recall@3 : 勝ち馬がスコア上位3頭に入る率
  top1_win : スコア1位の馬の勝率
  top3_fuku: スコア上位3頭の複勝率(3着内率)

比較する設定:
  base      : 加点なし(ベースライン=ability_scoreの素の順位)
  +Lap33    : 33ラップ適合の上位3頭に+N
  +Spurt    : 末脚指数の上位3頭に+N
  +CorrT    : 補正タイムの上位3頭に+N
  +JPower   : 騎手力の上位3頭に+N
  +GPT案    : Lap33/末脚/強さ を同時に加点(元の提案の再現)
  各項目の連続ウェイト版(上位3頭ではなくレース内percentileに比例して加点)も併記。

★重要: 上位3頭に加点する量Nは『素点のレース内ばらつき』に対して相対的に効く。
  ここでは素点をレース内で0-100に正規化してから加点するので、Nはそのまま「何点分」の意味。

train(≤2024)/holdout(2025)の両方で改善しなければ採用しない。
"""
import os
import sys
from collections import defaultdict

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd

# CSVの列 → (表示名, 大きいほど良いか)
SIGNALS = {
    'h7_pct':      ('🔵補正T',   False),   # 補正Tのレース内percentile(小=速い=良い)
    'spurt_idx':   ('🔥末脚指数', True),
    'lap_align':   ('🌀33ラップ', True),    # コース平均との適合(大=適合)
    'jockey_form_t3': ('👑騎手力', True),
    'blood_race_pct': ('🧬血統',   True),
}
BONUS_PTS = (5, 10, 15, 20, 30)


def norm01(v, higher_better):
    """レース内で0-100に正規化(大きいほど良い向きに揃える)。"""
    a = np.asarray(v, dtype=float)
    ok = ~np.isnan(a)
    out = np.full(len(a), 50.0)
    if ok.sum() < 2:
        return out
    lo, hi = a[ok].min(), a[ok].max()
    if hi <= lo:
        return out
    s = (a[ok] - lo) / (hi - lo) * 100.0
    if not higher_better:
        s = 100.0 - s
    out[ok] = s
    return out


def top3_mask(v, higher_better):
    a = np.asarray(v, dtype=float)
    ok = ~np.isnan(a)
    m = np.zeros(len(a), dtype=bool)
    if ok.sum() == 0:
        return m
    idx = np.where(ok)[0]
    order = idx[np.argsort(a[idx] * (-1 if higher_better else 1))]
    m[order[:3]] = True
    return m


def main():
    cols = ['race_key', 'day', 'umaban', 'chakujun', 'win', 'top3', 'ability_score',
            'ninki'] + list(SIGNALS)
    df = cd.load_horses(cols=cols)
    df = df[df['ability_score'].notna() & (df['chakujun'] > 0)]
    print(f"母集団: {len(df):,}頭")

    by_race = defaultdict(list)
    for r in df.itertuples(index=False):
        by_race[str(r.race_key)].append(r)

    # 設定: name -> [(signal_col, bonus_pts), ...]  空=ベースライン
    setups = {'base(加点なし)': []}
    for c, (nm, _) in SIGNALS.items():
        for p in (10, 20):
            setups[f'+{nm}上位3頭 +{p}'] = [(c, p)]
    # GPT案の再現: 33ラップ+15 / 末脚+20 / 強さ(=ability素点なので代理に補正T)+10
    setups['GPT案(33+15/末脚+20/補正T+10)'] = [('lap_align', 15), ('spurt_idx', 20), ('h7_pct', 10)]

    agg = {p: {s: [0, 0, 0, 0, 0, 0] for s in setups} for p in ('train', 'holdout')}
    # [races, win_in_top7, win_in_top3, top1_win, top3_slots, top3_fuku_hits]

    for rk, rows in by_race.items():
        n = len(rows)
        if n < 8:
            continue
        y = rows[0].day // 10000
        period = 'train' if y <= cd.TRAIN_END else ('holdout' if y == cd.HOLDOUT_YEAR else None)
        if period is None:
            continue
        # 素点: ability_score(小=良い) をレース内0-100へ
        base = norm01([r.ability_score for r in rows], higher_better=False)
        wins = np.array([1 if r.win == 1 else 0 for r in rows])
        t3 = np.array([1 if r.top3 == 1 else 0 for r in rows])
        sig_cache = {}
        for c, (_, hb) in SIGNALS.items():
            sig_cache[c] = top3_mask([getattr(r, c) for r in rows], hb)

        for sname, adds in setups.items():
            score = base.copy()
            for c, p in adds:
                score = score + sig_cache[c] * float(p)
            order = np.argsort(-score)
            a = agg[period][sname]
            a[0] += 1
            top7 = order[:7]
            top3 = order[:3]
            a[1] += int(wins[top7].sum() > 0)
            a[2] += int(wins[top3].sum() > 0)
            a[3] += int(wins[order[0]] == 1)
            a[4] += len(top3)
            a[5] += int(t3[top3].sum())

    for period in ('train', 'holdout'):
        print(f"\n{'='*82}\n=== {period} ===")
        print(f"  {'設定':30s} {'R数':>6s} {'recall@7':>9s} {'recall@3':>9s} "
              f"{'1位の勝率':>9s} {'上位3頭の複勝率':>14s}")
        b = agg[period]['base(加点なし)']
        for s in setups:
            a = agg[period][s]
            if a[0] < 100:
                continue
            r7, r3 = a[1] / a[0], a[2] / a[0]
            t1 = a[3] / a[0]
            f3 = a[5] / a[4] if a[4] else 0
            d7 = (r7 - b[1] / b[0]) * 100 if b[0] else 0
            mark = ''
            if s != 'base(加点なし)':
                mark = f"  ({d7:+.2f}pp)"
            print(f"  {s:30s} {a[0]:6d} {r7:8.2%} {r3:8.2%} {t1:8.2%} {f3:13.2%}{mark}")

    print("\n[判定] recall@7(勝ち馬を上位7頭に入れる率)が train/holdout の両方で改善して初めて採用。"
          "\n       ※baseは ability_score(4シグナルの平均=強適Rankのオフライン代理)。"
          "\n         実アプリの予測スコアとは完全一致しないが、加点の『効き方の向き』は同じ。")


if __name__ == '__main__':
    main()
