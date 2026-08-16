# -*- coding: utf-8 -*-
"""複勝の実配当が、事前に示されたレンジ(下限〜上限)のどこに着地するかを測る。

r40複勝EVの最後の懸念:
  「払戻が常に下限だったと仮定するとROIは105.7%→84.7%に転落する」。
  エッジ全部が『払戻が下限より上に着地すること』から来ているので、
  そこに体系的な偏り(特に選抜群だけ下限に張り付く等)がないかを潰す。

着地位置 = (実配当/100 - 下限) / (上限 - 下限)
  0.0 = 下限ちょうど / 1.0 = 上限ちょうど

見るもの:
  ① 全体の着地位置の分布
  ② r40選抜群だけ偏っていないか（ここが偏っていたら選抜が壊れている）
  ③ 着地位置を保守的に仮定し直した時のROI（感度分析）

Usage:
  python scripts/place_range_landing.py
"""
import os
import sys
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

import scripts.r40_place_model as R


def build():
    h = R.load()
    h = h[(h['win_odds'] > 0) & (h['pl_min'] > 0) & (h['chakujun'] > 0)]
    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < 8:
            continue
        raw = R.TAKEOUT / g['win_odds'].to_numpy()
        pi = raw / raw.sum()
        th = R.theta_r40(pi)
        if not np.isfinite(th).all():
            continue
        out.append(pd.DataFrame({
            'day': g['day'].to_numpy(), 'ninki': g['ninki'].to_numpy(),
            'pi': pi, 'theta': th,
            'pl_min': g['pl_min'].to_numpy(), 'pl_max': g['pl_max'].to_numpy(),
            'pl_payout': g['pl_payout'].to_numpy(),
            'top3': (g['chakujun'].to_numpy() <= 3).astype(int),
        }))
    d = pd.concat(out, ignore_index=True)
    d['year'] = d['day'].astype(str).str[:4].astype(int)
    d['pl_mid'] = np.where(d['pl_max'].notna(),
                           (d['pl_min'] + d['pl_max']) / 2, d['pl_min'])
    d['ev_mid'] = d['theta'] * d['pl_mid']
    return d


def main():
    print('読込中...', file=sys.stderr)
    d = build()
    print(f'対象 {len(d):,}頭')
    print(f'上限オッズが入っている割合: {d["pl_max"].notna().mean()*100:.1f}%')

    w = d[(d['top3'] == 1) & d['pl_max'].notna() & (d['pl_max'] > d['pl_min'])].copy()
    w['odds_real'] = w['pl_payout'] / 100.0
    w['pos'] = (w['odds_real'] - w['pl_min']) / (w['pl_max'] - w['pl_min'])
    w['pos'] = w['pos'].clip(-0.2, 1.2)
    print(f'レンジ幅がある的中馬: {len(w):,}頭\n')

    def dist(name, s):
        if len(s) < 200:
            print(f'{name:30s}{"標本不足":>10}')
            return
        p = s['pos']
        print(f'{name:30s}{len(s):>9,}{p.mean():>9.3f}{p.median():>9.3f}'
              f'{(p <= 0.05).mean()*100:>10.1f}%{(p >= 0.95).mean()*100:>9.1f}%')

    print('■ ① 着地位置（0=下限ちょうど / 1=上限ちょうど）')
    print(f'{"群":30s}{"n":>9}{"平均":>9}{"中央値":>9}{"下限付近":>10}{"上限付近":>9}')
    print('-' * 78)
    dist('全的中馬', w)
    dist('1-5番人気', w[w['ninki'] <= 5])
    fav = w[w['pi'] >= 0.20]
    dist('単勝支持率20%以上', fav)
    dist('★r40選抜 (EV>1.10)', fav[fav['ev_mid'] > 1.10])
    dist('  比較: 同帯のEV<=1.10', fav[fav['ev_mid'] <= 1.10])

    print('\n■ ② 着地位置のヒストグラム（r40選抜 EV>1.10）')
    s = fav[fav['ev_mid'] > 1.10]['pos']
    for lo in np.arange(0, 1.0, 0.1):
        c = ((s >= lo) & (s < lo + 0.1)).sum()
        print(f'  {lo:.1f}-{lo+0.1:.1f}: {c:>5,} {"█" * int(c / max(len(s),1) * 120)}')

    print('\n■ ③ 感度分析: 着地位置を強制的に固定したらROIはどうなるか')
    print('   (的中馬の払戻を「下限+位置×レンジ幅」で置き換えて再計算)')
    sel = d[(d['pi'] >= 0.20) & (d['ev_mid'] > 1.10)].copy()
    sel['rng'] = np.where(sel['pl_max'].notna(),
                          sel['pl_max'] - sel['pl_min'], 0.0)
    print(f'{"仮定":34s}{"回収率":>9}')
    print('-' * 46)
    for lbl, pos in (('最悪: 常に下限 (pos=0.00)', 0.0),
                     ('悲観: pos=0.15', 0.15),
                     ('やや悲観: pos=0.25', 0.25),
                     ('中間: pos=0.50', 0.50),
                     ('実測の平均位置', None)):
        if pos is None:
            roi = sel['pl_payout'].mean()
            lbl = f'{lbl} (= 実際の配当)'
        else:
            sim = sel['top3'] * (sel['pl_min'] + pos * sel['rng']) * 100
            roi = sim.mean()
        print(f'{lbl:34s}{roi:>8.1f}%')

    print('\n■ ④ 損益分岐となる着地位置を逆算')
    lo_, hi_ = 0.0, 1.0
    for _ in range(40):
        mid = (lo_ + hi_) / 2
        r = (sel['top3'] * (sel['pl_min'] + mid * sel['rng']) * 100).mean()
        if r < 100:
            lo_ = mid
        else:
            hi_ = mid
    act = fav[fav['ev_mid'] > 1.10]['pos'].mean()
    print(f'  回収率100%に必要な平均着地位置: **{(lo_+hi_)/2:.3f}**')
    print(f'  実測の平均着地位置           : **{act:.3f}**')
    print(f'  → 実測が必要値を{"上回る(余裕あり)" if act > (lo_+hi_)/2 else "下回る(危険)"}')


if __name__ == '__main__':
    main()
