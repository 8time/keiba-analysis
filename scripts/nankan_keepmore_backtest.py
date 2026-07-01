# -*- coding: utf-8 -*-
"""NAR(大井)版「ボーダー残しは何頭まで得か」逓減検証(JRA版scripts/keepmore_backtest.pyの対応版)。

JRA版はオッズ帯別期待値(calibrate_odds_expectation)を基準残差にしているが、
nankankeiba.comの確定レース結果ページには単勝オッズが載っておらず(人気のみ)、
同じ方法は再現できない。代わりに「人気番号ごとの実測複勝率」を市場効率の代理指標として使い、
ボーダー群(人気rank=keep_base+k)の実際の複勝率がこの代理基準に対してどれだけ残差を持つかを見る。

データ: scripts/nankan_pci_legtype_backtest.pyが生成したscripts/debug/nankan_backtest_rows.json
(大井5開催・263レース・3197頭、2026-07拡大版)。
"""
import sys
import io
import json
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('scripts/debug/nankan_backtest_rows.json', encoding='utf-8') as f:
    rows = json.load(f)

# --- 人気番号ごとの実測複勝率テーブル(オッズ帯の代理・市場効率の基準) ---
by_pop = defaultdict(lambda: [0, 0])  # pop -> [n, top3_hits]
for r in rows:
    p = r.get('popularity')
    if not p or p <= 0:
        continue
    by_pop[p][0] += 1
    if r.get('rank') and 1 <= r['rank'] <= 3:
        by_pop[p][1] += 1
expected_by_pop = {p: h / n for p, (n, h) in by_pop.items() if n >= 20}

print("=== 人気番号別 実測複勝率(基準テーブル, n>=20のみ) ===")
for p in sorted(expected_by_pop):
    n, h = by_pop[p]
    print(f"  {p:2d}番人気: {expected_by_pop[p]:.1%} (n={n})")

# --- レースごとにグルーピング ---
races = defaultdict(list)
for r in rows:
    races[r['race_id']].append(r)

KMAX = 4
marg = {k: [0, 0, 0.0] for k in range(1, KMAX + 1)}  # n, top3_hits, residual_sum
t3_tot = 0
miss = {k: 0 for k in range(0, KMAX + 1)}
n_races = 0

for rid, horses in races.items():
    n = len(horses)
    if n < 6:
        continue
    n_races += 1
    hs = sorted(horses, key=lambda x: x.get('popularity') or 999)
    keep_base = (n + 1) // 2
    for idx, h in enumerate(hs):
        rank_pos = idx + 1
        chaku = h.get('rank')
        is_t3 = bool(chaku and 1 <= chaku <= 3)
        if is_t3:
            t3_tot += 1
            for k in range(0, KMAX + 1):
                if rank_pos > keep_base + k:
                    miss[k] += 1
        for k in range(1, KMAX + 1):
            if rank_pos == keep_base + k:
                d = marg[k]
                d[0] += 1
                pop = h.get('popularity')
                exp_rate = expected_by_pop.get(pop)
                if exp_rate is not None:
                    d[2] += (1 if is_t3 else 0) - exp_rate
                if is_t3:
                    d[1] += 1

print(f"\n対象: {n_races} レース / 3着内総数 {t3_tot}")
print("\n=== 累積 3着内取りこぼし(半分カット後、残しに入らない割合) ===")
for k in range(0, KMAX + 1):
    lbl = "現行(半分)" if k == 0 else f"+{k}頭戻す"
    print(f"  keep+{k} {lbl:10s}: {miss[k]/max(t3_tot,1):.2%}")

print("\n=== 戻すk頭目(消去ゾーンk番目・人気rank基準)単体の成績 ===")
print("  k  |   n   | 3着内率 | 人気番号別基準との残差(z)")
for k in range(1, KMAX + 1):
    n_, t3, res = marg[k]
    se = (0.22 * 0.78 / n_) ** 0.5 if n_ else 0
    z = (res / n_) / se if se and n_ else 0
    print(f"  +{k} | {n_:5d} | {t3/max(n_,1):6.2%} | 残差{res/max(n_,1):+.4f} (z={z:+.2f})")

print("\n→ JRA版と同じ読み方: 残差が+→0→−に潰れる手前までが『戻す価値』。")
print("  ※NAR版はオッズ不在のため基準を人気番号別実測率で代用(JRA版のオッズ帯較正とは非同一)。")
