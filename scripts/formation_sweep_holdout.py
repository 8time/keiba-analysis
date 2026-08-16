# -*- coding: utf-8 -*-
"""点数スイープ＋細かい荒れ度ビン別の最適形を、train/holdoutで検証する。

問い(ユーザー/他AIの提案):
  ① 点数を減らせばROI100%を超えるのでは
  ② 荒れ度を細かく刻めばビンごとに最適形が違い、100%超が見つかるのでは
  ③ 条件を足していけば購入数は減るがROIは上がるのでは

いずれも「探せば見つかる」のは当たり前で、問題は**それが翌年も続くか**。
そこで train(2016-2023)で最良を選び、holdout(2024-2026)で追試する。
選抜バイアスの大きさ(train ROI と holdout ROI の落差)そのものを測るのが目的。

Usage:
  python scripts/formation_sweep_holdout.py
"""
import os
import sys
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import vscore_zone_formation as VZ

KIND_JP = {'trio': '3連複', 'trifecta': '3連単'}

# 極小点数から広めまで総当たり(1着列<=2着列<=3着列)
SHAPES = []
for a in range(1, 5):
    for b in range(max(a, 2), 8):
        for c in range(max(b, 3), 11):
            SHAPES.append((a, b, c))

BINS = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 201)]
MIN_TRAIN_R = 300
MIN_HOLD_R = 100


def roi_of(races, pay_map, kind, shape, lo, hi, y0, y1):
    a, b, c = shape
    spend = ret = 0.0
    n = hit = 0
    pts = 0
    for d in races:
        if not (lo <= d['vscore'] < hi):
            continue
        y = int(str(d['day'])[:4])
        if not (y0 <= y <= y1):
            continue
        pl = pay_map.get(d['_rk'])
        if not pl:
            continue
        tk = (VZ.trifecta_tickets(d['ranks'], a, b, c) if kind == 'trifecta'
              else VZ.trio_tickets(d['ranks'], a, b, c))
        if not tk:
            continue
        n += 1
        pts += len(tk)
        spend += len(tk) * 100
        for combo, pay in pl:
            key = combo if kind == 'trifecta' else tuple(sorted(combo))
            if key in tk:
                ret += pay
                hit += 1
                break
    if not n or not spend:
        return None
    return {'n': n, 'roi': ret / spend * 100, 'hit': hit / n * 100,
            'pts': pts / n}


def main():
    print('読込中...', file=sys.stderr)
    races_d = VZ.build_races()
    for rk in races_d:
        races_d[rk]['_rk'] = rk
    races = list(races_d.values())
    pays = {k: VZ.load_payouts(KIND_JP[k]) for k in ('trio', 'trifecta')}

    for kind in ('trio', 'trifecta'):
        pm = pays[kind]
        print(f'\n{"="*96}')
        print(f'■ {KIND_JP[kind]}：荒れ度ビンごとに train(2016-23)で最良形を選び holdout(2024-26)で追試')
        print(f'{"="*96}')
        print(f'{"荒れ度":10s}{"最良形(train)":>14}{"点":>6}'
              f'{"train R":>9}{"train ROI":>11}{"hold R":>8}{"hold ROI":>10}  判定')
        print('-' * 96)
        rows = []
        for lo, hi in BINS:
            best = None
            for sh in SHAPES:
                r = roi_of(races, pm, kind, sh, lo, hi, 2016, 2023)
                if not r or r['n'] < MIN_TRAIN_R:
                    continue
                if best is None or r['roi'] > best[1]['roi']:
                    best = (sh, r)
            if not best:
                print(f'{lo}-{hi-1:<8}{"標本不足":>14}')
                continue
            sh, tr = best
            ho = roi_of(races, pm, kind, sh, lo, hi, 2024, 2026)
            if not ho or ho['n'] < MIN_HOLD_R:
                print(f'{lo}-{hi-1:<8}{"-".join(map(str,sh)):>14}{tr["pts"]:>6.0f}'
                      f'{tr["n"]:>9,}{tr["roi"]:>10.0f}%{"holdout不足":>18}')
                continue
            drop = ho['roi'] - tr['roi']
            v = ('★holdoutも100%超' if ho['roi'] >= 100 else
                 f'落差{drop:+.0f}pp')
            rows.append((tr['roi'], ho['roi']))
            print(f'{lo}-{hi-1:<8}{"-".join(map(str,sh)):>14}{tr["pts"]:>6.0f}'
                  f'{tr["n"]:>9,}{tr["roi"]:>10.0f}%{ho["n"]:>8,}{ho["roi"]:>9.0f}%  {v}')
        if rows:
            t = np.array([r[0] for r in rows]); h = np.array([r[1] for r in rows])
            print(f'\n  train平均 {t.mean():.0f}% → holdout平均 {h.mean():.0f}% '
                  f'（選抜バイアス {h.mean()-t.mean():+.0f}pp）')
            print(f'  holdoutで100%を超えたビン: {(h>=100).sum()} / {len(h)}')

    # 点数とROIの関係(選抜なしの素の関係)
    print(f'\n{"="*96}')
    print('■ 参考：点数を変えるとROIはどう動くか（選抜せず全期間・C中庸50-69のみ）')
    print(f'{"="*96}')
    for kind in ('trio', 'trifecta'):
        print(f'\n[{KIND_JP[kind]}]')
        print(f'{"形":>9}{"点数":>7}{"R数":>8}{"的中":>8}{"ROI":>7}')
        print('-' * 42)
        res = []
        for sh in SHAPES:
            r = roi_of(races, pays[kind], kind, sh, 50, 70, 2016, 2026)
            if r and r['n'] >= 1000:
                res.append((sh, r))
        res.sort(key=lambda x: x[1]['pts'])
        for sh, r in res[:1] + res[len(res)//4:len(res)//4+1] + \
                res[len(res)//2:len(res)//2+1] + res[-1:]:
            print(f'{"-".join(map(str,sh)):>9}{r["pts"]:>7.0f}{r["n"]:>8,}'
                  f'{r["hit"]:>7.1f}%{r["roi"]:>6.0f}%')
        arr = np.array([(r['pts'], r['roi']) for _s, r in res])
        print(f'  点数とROIの相関: {np.corrcoef(arr[:,0], arr[:,1])[0,1]:+.3f}'
              f'  （マイナスなら「点数を絞るほどROIが高い」）')
        print(f'  全{len(res)}形のROI: 最小{arr[:,1].min():.0f}% '
              f'中央{np.median(arr[:,1]):.0f}% 最大{arr[:,1].max():.0f}%')


if __name__ == '__main__':
    main()
