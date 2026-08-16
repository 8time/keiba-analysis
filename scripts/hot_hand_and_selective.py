# -*- coding: utf-8 -*-
"""「ここぞで厚く張る」を2つの問いに分けて検証する。

ユーザーの直感(バカラの勝ち組は"ここぞ"で厚く張る。負けている時ではなく)には
**別々の2つの主張**が混ざっている:

  問い①【流れ】その日ここまで当たっていると、次のレースも当たりやすいか？
        → これが本当なら「勝ちが続いた日に厚く張る」は正しい。
          偽なら典型的なギャンブラーの誤謬(バカラは本当に独立なので誤謬)。

  問い②【選別】「ここぞ」を**レースの質**で定義して厚く張るのは効くか？
        → 妙味度ゾーンで賭け金を変える。こちらは事前情報なので誤謬ではない。

対象: ◎〇固定4点(3連複)・2025-2026。1単位=400円。

⚠資金管理は期待値を変えない。②が効くとしたら「良いレースに多く配分した」
  =実質的にレース選択であり、進行法とは別物。
"""
import os
import sys
import io
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import axis_vh_trio_backtest as AV
from scripts import axis_vh_zone_split as ZS

UNIT = 400


def build():
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
        rows.append({'rk': r.rk, 'day': r.day, 'race_no': int(str(r.rk)[-2:]),
                     'jyo': str(r.rk)[8:10], 'pay': got, 'hit': int(got > 0)})
    d = ZS.add_vscore(pd.DataFrame(rows)).dropna(subset=['vscore'])
    return d.sort_values(['day', 'jyo', 'race_no']).reset_index(drop=True)


def main():
    print('読込中...', file=sys.stderr)
    d = build()
    print(f'対象 {len(d):,}レース / {d["day"].nunique()}日 '
          f'(2025-2026・◎〇固定4点)\n')

    # ── 問い① 流れ(hot hand) ──
    # 同じ日・同じ場で、それまでの的中数に応じて次の的中率が変わるか
    d['prev_hits'] = (d.groupby(['day', 'jyo'])['hit']
                      .transform(lambda s: s.shift().cumsum()))
    d['prev_n'] = (d.groupby(['day', 'jyo'])['hit']
                   .transform(lambda s: s.shift().notna().cumsum()))
    sub = d[d['prev_n'] >= 3].copy()      # 3レース以上こなした後だけ見る
    sub['prev_rate'] = sub['prev_hits'] / sub['prev_n']
    base_hit = d['hit'].mean() * 100

    print('■ 問い①【流れ】その日ここまでの当たり具合で、次の的中率は変わるか')
    print(f'  全体の的中率: {base_hit:.1f}%')
    print(f'{"それまでの的中率":22s}{"n":>8}{"次の的中率":>11}{"差":>9}{"z":>7}')
    print('-' * 60)
    for lbl, lo, hi in (('0%(全部外れ)', -0.01, 0.001), ('1〜25%', 0.001, 0.25),
                        ('25〜40%', 0.25, 0.40), ('40〜60%', 0.40, 0.60),
                        ('60%以上(絶好調)', 0.60, 1.01)):
        s = sub[(sub['prev_rate'] > lo) & (sub['prev_rate'] <= hi)]
        if len(s) < 100:
            continue
        h = s['hit'].mean() * 100
        se = math.sqrt(base_hit / 100 * (1 - base_hit / 100) / len(s)) * 100
        print(f'{lbl:22s}{len(s):>8,}{h:>10.1f}%{h-base_hit:>+9.1f}{(h-base_hit)/se:>+7.2f}')

    # 直前1レースの結果だけで見る
    d['prev1'] = d.groupby(['day', 'jyo'])['hit'].shift()
    for v, lbl in ((1.0, '直前が的中'), (0.0, '直前が外れ')):
        s = d[d['prev1'] == v]
        h = s['hit'].mean() * 100
        se = math.sqrt(base_hit / 100 * (1 - base_hit / 100) / len(s)) * 100
        print(f'{lbl:22s}{len(s):>8,}{h:>10.1f}%{h-base_hit:>+9.1f}'
              f'{(h-base_hit)/se:>+7.2f}')

    # ROIでも見る(的中率でなく収支)
    print(f'\n  ROIで見ると: ', end='')
    for lbl, cond in (('直前的中の次', d['prev1'] == 1), ('直前外れの次', d['prev1'] == 0)):
        s = d[cond]
        print(f'{lbl}={s["pay"].sum()/(len(s)*UNIT)*100:.0f}%  ', end='')
    print('\n  → 差が誤差なら「流れ」は存在しない＝勝った日に厚く張る根拠はない。')

    # ── 問い② 選別(ゾーンで賭け金を変える) ──
    print('\n■ 問い②【選別】妙味度ゾーンで賭け金を変えたら')
    Z = [('D 鉄板', 0, 50), ('C 中庸', 50, 70), ('B/A 荒れ', 70, 201)]
    plans = [
        ('全部フラット(1-1-1)', {0: 1, 1: 1, 2: 1}),
        ('D を厚く (3-1-1)', {0: 3, 1: 1, 2: 1}),
        ('D を厚く・荒れ切り (3-1-0)', {0: 3, 1: 1, 2: 0}),
        ('D のみ (1-0-0)', {0: 1, 1: 0, 2: 0}),
        ('D厚く・C薄く・荒れ切り (5-1-0)', {0: 5, 1: 1, 2: 0}),
    ]
    zi = np.select([(d['vscore'] < 50), (d['vscore'] < 70)], [0, 1], default=2)
    d = d.assign(zi=zi)
    print(f'{"配分":32s}{"投資額":>12}{"払戻":>12}{"ROI":>7}{"買うR数":>9}')
    print('-' * 74)
    for name, w in plans:
        u = d['zi'].map(w)
        spend = (u * UNIT).sum()
        ret = (d['pay'] * u).sum()
        n = int((u > 0).sum())
        print(f'{name:32s}{spend:>12,.0f}{ret:>12,.0f}'
              f'{ret/spend*100:>6.0f}%{n:>9,}')

    print('\n※②で改善するのは「良いゾーンに配分を寄せた」から＝実質レース選択。')
    print('※①に差がなければ「勝っている日に厚く張る」は根拠なし(独立事象)。')


if __name__ == '__main__':
    main()
