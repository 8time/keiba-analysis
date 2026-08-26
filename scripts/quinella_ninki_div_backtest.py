# -*- coding: utf-8 -*-
"""馬連支持順位 vs 単勝人気のズレ — holdout 残差。

単勝人気より馬連で売れている馬（お宝候補）/嫌われている馬（消し候補）が、
同じオッズ帯の他馬より3着内に来やすいか。ガラス人気と同じ「券種の意見のズレ」。

判定: 見る(〜2024) と 確認(2025) の両方で複勝残差 z>=+2 かつ残差>0 なら印を出せる。
未達なら UI に出さない。

Usage: python scripts/quinella_ninki_div_backtest.py
"""
import os
import sqlite3
import sys
from collections import defaultdict

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from core import quinella_div as qd
from scripts import csv_data as cd

MIN_N = 200
Z_GATE = 2.0
DELTAS = (2, 3, 4)
CHUNK = 400


def _band_exp(odds, exp, key, default):
    bands = odds.map(jj._odds_band)
    return bands.map(lambda b: (exp.get(b) or {}).get(key, default)).astype(float)


def stats(sub, e3):
    n = len(sub)
    if n == 0:
        return None
    t3 = sub['top3'].to_numpy()
    resid = t3 - e3.loc[sub.index].to_numpy()
    se = (0.22 * 0.78 / n) ** 0.5
    z = (resid.mean() / se) if se > 0 else 0.0
    return {
        'n': n,
        'hit': float(t3.mean()),
        'z': float(z),
        'resid': float(resid.mean()),
        'hits': int(t3.sum()),
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 捕捉{s['hits']:5d} "
            f"複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def both_pos(train, hold):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return (train['z'] >= Z_GATE and hold['z'] >= Z_GATE
            and train['resid'] > 0 and hold['resid'] > 0)


def both_neg(train, hold):
    if train is None or hold is None:
        return False
    if train['n'] < MIN_N or hold['n'] < MIN_N:
        return False
    return (train['z'] <= -Z_GATE and hold['z'] <= -Z_GATE
            and train['resid'] < 0 and hold['resid'] < 0)


def load_qrank(race_keys):
    """jravan 馬連オッズからレースごとの支持順位 {race_key: {umaban: qrank}}。"""
    keys = [str(x) for x in race_keys]
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True, timeout=60)
    qmap = defaultdict(list)
    n_pair = 0
    for i in range(0, len(keys), CHUNK):
        chunk = keys[i:i + CHUNK]
        ph = ','.join('?' * len(chunk))
        rows = con.execute(
            f"SELECT race_key, combo, odds FROM odds "
            f"WHERE bet_type='quinella' AND race_key IN ({ph}) "
            f"AND odds IS NOT NULL AND odds > 0",
            chunk).fetchall()
        for rk, combo, odds in rows:
            qmap[str(rk)].append({'combo': combo, 'odds': odds})
            n_pair += 1
    con.close()
    ranks = {rk: qd.support_rank(qd.support_mass(rows)) for rk, rows in qmap.items()}
    return ranks, n_pair


def main():
    print('較正（見る期間 2021-24）...', flush=True)
    exp = jj.calibrate_odds_expectation(years=('2021', '2022', '2023', '2024'))
    print('CSV...', flush=True)
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds', 'top3'])
    for c in ('umaban', 'ninki', 'win_odds', 'top3', 'day'):
        h[c] = pd.to_numeric(h[c], errors='coerce')
    h = h[(h['win_odds'] > 0) & (h['umaban'] > 0) & (h['ninki'] > 0)].copy()
    h['race_key'] = h['race_key'].astype(str)
    h = h.reset_index(drop=True)
    print(f'  horses {len(h):,}  races {h["race_key"].nunique():,}')

    print('馬連オッズ...', flush=True)
    ranks, n_pair = load_qrank(h['race_key'].unique())
    print(f'  quinella pairs {n_pair:,}  races with qrank {len(ranks):,}')

    h['qrank'] = [
        (ranks.get(str(rk)) or {}).get(int(u))
        for rk, u in zip(h['race_key'], h['umaban'])
    ]
    h = h[h['qrank'].notna()].copy()
    h['delta'] = h['ninki'].astype(int) - h['qrank'].astype(int)
    h = h.reset_index(drop=True)
    print(f'  joined horses {len(h):,}')

    e3 = _band_exp(h['win_odds'], exp, 'top3', 0.22)

    corr = h[['ninki', 'qrank']].corr(method='spearman').iloc[0, 1]
    print(f'\n■ 単勝人気 vs 馬連支持順位  Spearman={corr:.3f}')
    print(f"  delta=単勝人気−馬連順位  平均 {h['delta'].mean():+.2f}  "
          f"中央 {h['delta'].median():+.1f}  "
          f"|delta|>=2 {(h['delta'].abs() >= 2).mean():.1%}")

    periods = {
        '見る(〜2024)': h['period'] == 'train',
        '確認(2025)': h['period'] == 'holdout',
        '直近3ヶ月': h['period'] == 'recent',
    }
    verdicts = []

    def block(title, mask):
        print(f'\n--- {title} ---')
        row = {}
        for pname, pm in periods.items():
            st = stats(h[mask & pm], e3)
            row[pname] = st
            print(f'  {pname:12s} {fmt(st)}')
        ok = both_pos(row.get('見る(〜2024)'), row.get('確認(2025)'))
        ng = both_neg(row.get('見る(〜2024)'), row.get('確認(2025)'))
        if ok:
            msg = '★来ている（両窓 z>=+2）→ 印を出してよい'
        elif ng:
            msg = '★来にくい（両窓 z<=-2）→ 消し印を出してよい'
        else:
            msg = 'ゲート未達 → UIに出さない'
        print('  → ' + msg)
        verdicts.append((title, ok, ng))
        return row

    for d in DELTAS:
        block(f'馬連の方が支持（delta>=+{d}）', h['delta'] >= d)
        block(f'単勝の方が支持（delta<=-{d}）', h['delta'] <= -d)

    print('\n--- 馬連の方が支持 delta>=+3 × 単勝人気帯 ---')
    for lo, hi, lab in ((1, 5, '1-5番人気'), (6, 10, '6-10番人気'), (11, 18, '11番人気以下')):
        block(f'delta>=+3 かつ {lab}',
              (h['delta'] >= 3) & (h['ninki'] >= lo) & (h['ninki'] <= hi))

    print('\n[判定] 見る+確認の両方で z>=+2 かつ残差>0 ならお宝印。'
          'z<=-2 かつ残差<0 なら消し印。それ以外は UI に出さない。')
    ship = [t for t, ok, ng in verdicts if ok or ng]
    print('採用候補: ' + (' / '.join(ship) if ship else 'なし'))

    fade = h['delta'] <= -2
    print('\n--- 消し候補(delta<=-2)の単勝人気 ---')
    print(h.loc[fade, 'ninki'].describe().to_string())
    vc = h.loc[fade, 'ninki'].astype(int).clip(upper=12).value_counts().sort_index()
    print(vc.to_string())
    print(f"  1-5番人気の割合 {(h.loc[fade, 'ninki'] <= 5).mean():.1%}")
    print(f"  6番人気以下の割合 {(h.loc[fade, 'ninki'] >= 6).mean():.1%}")


if __name__ == '__main__':
    main()
