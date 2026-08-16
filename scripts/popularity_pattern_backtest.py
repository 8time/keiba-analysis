# -*- coding: utf-8 -*-
"""3連単の「人気パターン」に高期待値の定数があるかを検証。

資料の主張:
  (A) 「1番人気-3番人気-13番人気」の3連単は期待値121円
  (B) 「1着が3番人気」となる順列は発生確率3.56%・**期待値163円**
      → これら24通りを買い続けるのが「中長期で儲かる買い方の核心」

⚠この種の主張は多重検定の温床。18頭立てなら人気パターンは18×17×16=4,896通りあり、
  全部試せば期待値150円超が偶然でいくつも出る。
  そこで **train(2016-2021)で選び holdout(2022-2026)で追試** し、
  選抜バイアスの大きさそのものを測る。
  [[verified_formation_sweep_holdout]]で同じ設計をやったときは -23〜-32pp 落ちた。

Usage:
  python scripts/popularity_pattern_backtest.py
"""
import os
import sys
import io
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

FIT_END = 2021


def load():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    pay = {}
    for rk, combo, p in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            pay[str(rk)] = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(p))
    con.close()
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'chakujun'])
    h['race_key'] = h['race_key'].astype(str)
    rows = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < 10 or rk not in pay:
            continue
        combo, p = pay[rk]
        u2n = dict(zip(g['umaban'].astype(int), g['ninki'].astype(int)))
        pat = tuple(u2n.get(u, 99) for u in combo)
        if 99 in pat:
            continue
        rows.append({'rk': rk, 'year': int(str(g['day'].iloc[0])[:4]),
                     'n': len(g), 'pat': pat, 'pay': p})
    return pd.DataFrame(rows)


def roi_of(df, match):
    """match(pat)->bool を満たすパターン群を全部買った時のROI。
    点数 = そのレースで match を満たす順列の総数。"""
    tot_spend = tot_ret = 0.0
    hits = 0
    for r in df.itertuples(index=False):
        n = r.n
        cnt = sum(1 for a in range(1, n + 1) for b in range(1, n + 1)
                  for c in range(1, n + 1)
                  if len({a, b, c}) == 3 and match((a, b, c)))
        if not cnt:
            continue
        tot_spend += cnt * 100
        if match(r.pat):
            tot_ret += r.pay
            hits += 1
    if not tot_spend:
        return None
    return {'roi': tot_ret / tot_spend * 100, 'hit': hits / len(df) * 100,
            'spend': tot_spend, 'n': len(df)}


def main():
    print('読込中...', file=sys.stderr)
    d = load()
    print(f'対象 {len(d):,}レース（{d["year"].min()}〜{d["year"].max()}）\n')

    print('■ 資料が名指しした2つの主張を直接検証（全期間）')
    print(f'{"主張":40s}{"点/R":>7}{"的中率":>8}{"回収率":>8}')
    print('-' * 66)
    # (A) 1番人気-3番人気-13番人気 の1点
    s = d[d['n'] >= 13]
    hit = (s['pat'] == (1, 3, 13)).sum()
    roi = s.loc[s['pat'] == (1, 3, 13), 'pay'].sum() / (len(s) * 100) * 100
    print(f'{"(A) 人気1-3-13 の1点買い":40s}{1:>7}{hit/len(s)*100:>7.2f}%{roi:>7.0f}%'
          f'   [主張121円]')
    # (B) 1着が3番人気（2-3着は総流し）
    r = roi_of(d, lambda p: p[0] == 3)
    print(f'{"(B) 1着=3番人気 の総流し":40s}'
          f'{r["spend"]/len(d)/100:>7.0f}{r["hit"]:>7.2f}%{r["roi"]:>7.0f}%'
          f'   [主張163円]')
    for k in (1, 2, 4, 5):
        r = roi_of(d, lambda p, k=k: p[0] == k)
        print(f'{f"　 比較: 1着={k}番人気 の総流し":40s}'
              f'{r["spend"]/len(d)/100:>7.0f}{r["hit"]:>7.2f}%{r["roi"]:>7.0f}%')

    # ── 多重検定の実演: trainで最良パターンを選び holdout で追試 ──
    print('\n■ 「人気パターンを総当たりして良いものを選ぶ」と何が起きるか')
    tr = d[d['year'] <= FIT_END]
    ho = d[d['year'] > FIT_END]
    print(f'  train {len(tr):,}R (〜{FIT_END}) / holdout {len(ho):,}R ({FIT_END+1}〜)')

    def pattern_roi(df, min_hits=8):
        """各人気パターン(1点買い)のROIを全部出す。"""
        agg = defaultdict(lambda: [0, 0.0])
        for r in df.itertuples(index=False):
            a = agg[r.pat]
            a[0] += 1
            a[1] += r.pay
        n = len(df)
        out = []
        for pat, (c, s) in agg.items():
            if c >= min_hits:
                out.append({'pat': pat, 'hits': c, 'roi': s / (n * 100) * 100})
        return pd.DataFrame(out)

    ptr = pattern_roi(tr).sort_values('roi', ascending=False)
    pho = pattern_roi(ho, min_hits=1).set_index('pat')['roi'].to_dict()
    hho = pattern_roi(ho, min_hits=1).set_index('pat')['hits'].to_dict()
    print(f'\n{"trainで良かったパターン":26s}{"train的中":>10}{"train ROI":>11}'
          f'{"hold ROI":>11}')
    print('-' * 60)
    keep = []
    for _, x in ptr.head(12).iterrows():
        hr = pho.get(x['pat'])
        keep.append((x['roi'], hr if hr is not None else 0.0))
        print(f'{str(x["pat"]):26s}{x["hits"]:>10}{x["roi"]:>10.0f}%'
              f'{(f"{hr:.0f}%" if hr is not None else "0%"):>11}')
    if keep:
        t = np.array([k[0] for k in keep])
        h = np.array([k[1] for k in keep])
        print(f'\n  train平均 {t.mean():.0f}% → holdout平均 {h.mean():.0f}% '
              f'（選抜バイアス {h.mean()-t.mean():+.0f}pp）')
        print(f'  holdoutでも100%を超えたのは {int((h>=100).sum())}/{len(h)} パターン')

    print('\n※3連単の払戻率は75%。全パターンの平均は必ず75%付近になる。')
    print('※特定パターンだけ150%超が『定数として』存在するなら、')
    print('  それを買い続ける人が現れてオッズが下がり消える(市場の自己修正)。')


if __name__ == '__main__':
    main()
