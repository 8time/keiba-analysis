# -*- coding: utf-8 -*-
"""カジノ式の資金管理法(オスカーズグラインド/ダランベール/パーレー/マーチン)を
実際の3連複4点(D鉄板)の結果列で回し、フラットベットと比較する。

きっかけ: 「3連複4点の的中31.5%はルーレットのダズン32.43%とほぼ同じだから
          ダズン用の資金管理が流用できるのでは」という提案。

⚠その類推には**決定的な穴**がある:
  ルーレットのダズンは**配当が常に3倍固定**。
  競馬の3連複は配当が毎回違い、平均と中央値が大きく乖離する(裾が重い)。
  進行法(オスカー/ダランベール等)は「1単位勝てば取り返せる」ことを前提に
  賭け金を組み立てるので、配当が固定でない時点で設計が崩れる。
  それが実際どう効くのかを、実データの並びで確かめるのが本スクリプト。

前提: 資金管理は期待値を変えない(これは数学的事実)。見るのは
  最終ROI・最大ドローダウン・破産率・賭け金の暴れ方。

Usage:
  python scripts/staking_systems_backtest.py
"""
import os
import sys
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import axis_vh_trio_backtest as AV
from scripts import axis_vh_zone_split as ZS

UNIT = 400          # 1単位 = 4点×100円
BANKROLL = 100_000  # 初期資金
MAX_UNITS = 50      # 1回の賭けの上限(現実的な歯止め)


def build_series():
    """D鉄板ゾーンの◎〇固定4点を時系列で: (払戻/投資)の倍率列を作る。"""
    base = AV.build()
    trio = AV.load_payouts('3連複')
    rows = []
    for r in base.itertuples(index=False):
        if r.year < 2025:
            continue
        lg = ZS.legs_of(r.pop, r.c1, r.c2)
        pl = trio.get(r.rk)
        if not lg or not pl:
            continue
        win = {tuple(sorted(c)): p for c, p in pl}
        got = next((win[t] for t in (tuple(sorted((r.a, r.b, x))) for x in lg)
                    if t in win), 0.0)
        rows.append({'rk': r.rk, 'day': r.day, 'year': r.year,
                     'mult': got / UNIT})      # 1単位賭けた時の払戻倍率
    d = ZS.add_vscore(pd.DataFrame(rows)).dropna(subset=['vscore'])
    d = d[(d['vscore'] >= 0) & (d['vscore'] < 50)].sort_values('day')
    return d['mult'].to_numpy()


# ── 各資金管理法: 直前までの結果を見て「今回何単位賭けるか」を返す ──
def flat(_state):
    return 1


def martingale(st):
    return min(2 ** st['losses'], MAX_UNITS)


def dalembert(st):
    return max(1, min(st['level'], MAX_UNITS))


def parlay(st):
    return min(st['parlay_units'], MAX_UNITS)


def oscar(st):
    return max(1, min(st['osc_units'], MAX_UNITS))


SYSTEMS = [('フラットベット', flat), ('マーチンゲール', martingale),
           ('ダランベール', dalembert), ('パーレー(逆マーチン)', parlay),
           ('オスカーズグラインド', oscar)]


def run(mults, fn, bankroll=BANKROLL):
    st = {'losses': 0, 'level': 1, 'parlay_units': 1,
          'osc_units': 1, 'osc_cycle': 0.0}
    bal = float(bankroll)
    peak = bal
    dd = 0.0
    spend = ret = 0.0
    busted = False
    max_bet = 0
    for m in mults:
        u = fn(st)
        bet = u * UNIT
        if bet > bal:                     # 賭けられない=事実上の退場
            busted = True
            break
        max_bet = max(max_bet, u)
        payout = m * bet
        bal += payout - bet
        spend += bet
        ret += payout
        peak = max(peak, bal)
        dd = max(dd, peak - bal)
        won = m > 0
        # 状態更新
        st['losses'] = 0 if won else st['losses'] + 1
        st['level'] = max(1, st['level'] - 1) if won else st['level'] + 1
        st['parlay_units'] = min(st['parlay_units'] * 2, MAX_UNITS) if won else 1
        if won:
            st['osc_cycle'] += payout - bet
            if st['osc_cycle'] >= UNIT:
                st['osc_units'], st['osc_cycle'] = 1, 0.0
            else:
                st['osc_units'] += 1
        else:
            st['osc_cycle'] -= bet
        if bal <= 0:
            busted = True
            break
    return {'bal': bal, 'roi': ret / spend * 100 if spend else 0,
            'dd': dd, 'busted': busted, 'max_bet': max_bet,
            'n': len(mults) if not busted else 0}


def main():
    print('読込中...', file=sys.stderr)
    m = build_series()
    hit = (m > 0).mean() * 100
    print(f'D鉄板ゾーンの3連複4点: {len(m):,}レース / 的中{hit:.1f}%')
    print(f'1単位={UNIT}円 / 初期資金={BANKROLL:,}円\n')

    print('■ ルーレットのダズンとの決定的な違い（配当のばらつき）')
    w = m[m > 0]
    print(f'  ルーレットのダズン : 当たれば**必ず**3.00倍（ばらつきゼロ）')
    print(f'  この3連複4点      : 平均{w.mean():.2f}倍 / 中央値{np.median(w):.2f}倍 '
          f'/ 最小{w.min():.2f}倍 / 最大{w.max():.1f}倍')
    print(f'  → 当たっても**{(w < 1).mean()*100:.0f}%は投資割れ**(トリガミ)。'
          '進行法が前提にする「1回勝てば取り返す」が成立しない。\n')

    print('■ 実データの並びで各手法を1回通した結果')
    print(f'{"手法":24s}{"最終残高":>12}{"ROI":>7}{"最大DD":>11}{"最大賭け":>9}{"退場":>6}')
    print('-' * 72)
    for name, fn in SYSTEMS:
        r = run(m, fn)
        print(f'{name:24s}{r["bal"]:>12,.0f}{r["roi"]:>6.0f}%{r["dd"]:>11,.0f}'
              f'{r["max_bet"]:>8}倍{"  退場" if r["busted"] else "     -"}')

    print('\n■ 並び順をブートストラップして退場率を測る（500回試行・各1,200レース）')
    rng = np.random.default_rng(3)
    print(f'{"手法":24s}{"退場率":>9}{"ROI中央":>9}{"最大DD中央":>12}')
    print('-' * 56)
    for name, fn in SYSTEMS:
        outs = []
        for _ in range(500):
            s = rng.choice(m, size=1200, replace=True)
            outs.append(run(s, fn))
        bust = np.mean([o['busted'] for o in outs]) * 100
        rois = [o['roi'] for o in outs if o['roi'] > 0]
        dds = [o['dd'] for o in outs]
        print(f'{name:24s}{bust:>8.1f}%{np.median(rois):>8.0f}%'
              f'{np.median(dds):>12,.0f}')

    print('\n※ROIがどの手法でもほぼ同じなのが答え。資金管理は期待値を1円も変えない。')
    print('※変わるのは「どれだけ荒れるか」と「途中で退場するか」だけ。')


if __name__ == '__main__':
    main()
