# -*- coding: utf-8 -*-
"""推奨絞り頭数: 『5着以内の8割を捕まえるには何頭に絞ればよいか』をレース性質別に実測。

背景: scripts/top5_capture_ceiling.py で全体平均では上位7頭で81.3%と分かった。
      ただし堅いレースならもっと少なく済み、荒れるレースでは7頭でも足りない。
      レースごとに必要頭数を出せれば「何頭に絞るか」の判断材料になる。

設計(過学習を避ける):
  ・新しいモデルは作らない。検証済みの荒れ予報(value_scanner.arare_prob)と頭数だけで層別し、
    各層で「上位N頭を人気順に選んだとき5着内をカバーできた率」を実測した表を作る。
  ・順位付けは人気を使う。scripts/top5_capture_ceiling.py の実測で
    LTRは人気を超えないと分かっているため、素直で再現性の高い人気順を基準にする。
  ・train窓(〜2024)で表を作り、holdout(2025+)で「その表の通りにやると本当に8割届くか」を検証する。

Usage:
  python scripts/narrow_n_backtest.py
"""
import os
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd
import sqlite3

from core import value_scanner as vs
from core import jockey_jv as jj

TARGET = 0.80          # 5着以内のカバー率の目標
NS = list(range(3, 13))
ARARE_BANDS = [('堅い(〜40%)', 0.0, 0.40), ('中間(40-55%)', 0.40, 0.55),
               ('荒れ(55-65%)', 0.55, 0.65), ('大荒れ(65%〜)', 0.65, 1.01)]
FIELD_BANDS = [('〜11頭', 5, 11), ('12-14頭', 12, 14), ('15頭〜', 15, 99)]
OUT_JSON = os.path.join(ROOT, 'data', 'narrow_n_table.json')


def load_races():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    df = pd.read_sql("""
        SELECT r.race_key, r.umaban, r.chakujun, r.ninki, r.win_odds,
               ra.year, ra.shusso_tosu, ra.kigo, ra.juryo
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE CAST(ra.year AS INTEGER) >= 2020
          AND r.chakujun > 0 AND r.ninki > 0 AND r.win_odds > 0
    """, con)
    con.close()
    return df


def race_rows(df):
    """レース単位に集約し、荒れ予報とカバー率を算出。"""
    out = []
    for rk, g in df.groupby('race_key'):
        if len(g) < 5:
            continue
        odds = g['win_odds'].tolist()
        meta = {'is_handicap': str(g['juryo'].iloc[0]) == '3',
                'kigo': str(g['kigo'].iloc[0] or '')}
        ap = vs.arare_prob(odds, meta, len(g))
        if ap is None:
            continue
        truth = set(g[g['chakujun'] <= 5]['umaban'])
        if not truth:
            continue
        gs = g.sort_values('ninki')
        cov = {}
        for n in NS:
            sel = set(gs.head(n)['umaban'])
            cov[n] = len(truth & sel) / len(truth)
        out.append({'race_key': rk, 'year': int(g['year'].iloc[0]),
                    'field': len(g), 'arare': ap, **{f'c{n}': cov[n] for n in NS}})
    return pd.DataFrame(out)


def band_of(v, bands):
    for lbl, lo, hi in bands:
        if lo <= v < hi:
            return lbl
    return bands[-1][0]


def main():
    print('読込中...', file=sys.stderr)
    rr = race_rows(load_races())
    rr['ab'] = rr['arare'].apply(lambda v: band_of(v, ARARE_BANDS))
    rr['fb'] = rr['field'].apply(lambda v: band_of(v, FIELD_BANDS))
    tr = rr[rr['year'] <= 2024]
    ho = rr[rr['year'] >= 2025]
    print(f'train {len(tr):,}R / holdout {len(ho):,}R\n')

    print(f'■ 各層で「5着内の{TARGET*100:.0f}%」に届く最小頭数（train〜2024で算出）')
    print(f'{"荒れ予報":14s}{"頭数":10s}{"R数":>7}  必要頭数   その時のカバー率')
    print('-' * 60)
    table = {}
    for al, _, _ in ARARE_BANDS:
        for fl, _, _ in FIELD_BANDS:
            sub = tr[(tr['ab'] == al) & (tr['fb'] == fl)]
            if len(sub) < 200:
                continue
            need, got = None, None
            for n in NS:
                m = sub[f'c{n}'].mean()
                if m >= TARGET:
                    need, got = n, m
                    break
            if need is None:
                need, got = NS[-1], sub[f'c{NS[-1]}'].mean()
            table[f'{al}|{fl}'] = need
            print(f'{al:14s}{fl:10s}{len(sub):>7,}  {need:>6}頭   {got*100:>6.1f}%')

    print(f'\n■ holdout(2025+)で表の通りに絞ると本当に{TARGET*100:.0f}%届くか')
    print(f'{"荒れ予報":14s}{"頭数":10s}{"R数":>7}  推奨   実カバー率  判定')
    print('-' * 62)
    ok = ng = 0
    tot_cov, tot_n, tot_sel = 0.0, 0, 0
    for key, need in table.items():
        al, fl = key.split('|')
        sub = ho[(ho['ab'] == al) & (ho['fb'] == fl)]
        if len(sub) < 30:
            continue
        m = sub[f'c{need}'].mean()
        good = m >= TARGET - 0.03      # 3pt以内の誤差は許容
        ok, ng = ok + int(good), ng + int(not good)
        tot_cov += m * len(sub); tot_n += len(sub); tot_sel += need * len(sub)
        print(f'{al:14s}{fl:10s}{len(sub):>7,}  {need:>3}頭  {m*100:>7.1f}%   '
              f'{"OK" if good else "未達"}')
    if tot_n:
        print(f'\n  holdout全体: 平均カバー率 {tot_cov/tot_n*100:.1f}% / '
              f'平均推奨頭数 {tot_sel/tot_n:.1f}頭  (層 {ok}OK/{ng}未達)')
        base = ho['c7'].mean()
        print(f'  参考: 全レース一律7頭 → カバー率 {base*100:.1f}%')

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump({'target': TARGET, 'table': table,
                   'arare_bands': [[a, b, c] for a, b, c in ARARE_BANDS],
                   'field_bands': [[a, b, c] for a, b, c in FIELD_BANDS]},
                  f, ensure_ascii=False, indent=2)
    print(f'\n表を保存: {os.path.relpath(OUT_JSON, ROOT)}')


if __name__ == '__main__':
    main()
