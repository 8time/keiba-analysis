# -*- coding: utf-8 -*-
"""3連複 autoプールの『5番人気の空白』を測る。

現行 recommend_trio(auto, 20点未満):
  人気枠 = 1-4番人気
  穴枠   = 6-12番人気
  相手候補(4-5番) = 少頭数×堅いだけ
→ 11頭以上では 5番人気が原理的にプール外。

問うこと:
  1) 勝ち3頭に5番人気が何%入るか
  2) 現行プールで勝ち3連複を何%逃すか、そのうち5番人気落ちは何%か
  3) 常時追加 vs 救済条件付き — 捕捉と無駄打ち

Usage: python scripts/pop5_pool_gap_backtest.py
"""
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd


def in_current_pool(n):
    return (1 <= n <= 4) or (6 <= n <= 12)


def vzone(lab):
    s = str(lab or '')[:1]
    return s if s in 'SABCD' else '?'


def main():
    cols = [
        'race_key', 'day', 'umaban', 'ninki', 'win_odds', 'field_size',
        'top3', 'chakujun', 'ability_score', 'vh2_score', 'h7_rank', 'combo',
    ]
    print('CSV読込...', flush=True)
    h = cd.load_horses(cols=cols)
    r = cd.load_races(cols=['race_key', 'vlabel', 'vscore', 'field_size', 'fav1'])
    r = r.drop_duplicates('race_key')
    vmap = r.set_index('race_key')['vlabel'].to_dict()
    vsmap = r.set_index('race_key')['vscore'].to_dict()
    favmap = r.set_index('race_key')['fav1'].to_dict()

    h['ninki'] = h['ninki'].astype(int)
    h['ab_rank'] = h.groupby('race_key')['ability_score'].rank(
        ascending=False, method='min')
    h['vh_rank'] = h.groupby('race_key')['vh2_score'].rank(
        ascending=False, method='min')

    races = []
    for rk, g in h.groupby('race_key', sort=False):
        top = g[g['top3'] == 1]
        if len(top) != 3:
            continue
        nks = sorted(int(x) for x in top['ninki'].tolist())
        fs = int(g['field_size'].iloc[0] or len(g))
        if fs < 8:
            continue
        p5 = g[g['ninki'] == 5]
        if len(p5) != 1:
            continue
        row5 = p5.iloc[0]
        covered = all(in_current_pool(n) for n in nks)
        has5 = 5 in nks
        has13 = any(n >= 13 for n in nks)
        miss5_only = (not covered) and has5 and (not has13)
        miss13_only = (not covered) and has13 and (not has5)
        miss_both = (not covered) and has5 and has13
        races.append({
            'rk': rk,
            'period': g['period'].iloc[0],
            'fs': fs,
            'nks': tuple(nks),
            'covered': covered,
            'has5': has5,
            'has13': has13,
            'miss5_only': miss5_only,
            'miss13_only': miss13_only,
            'miss_both': miss_both,
            'vz': vzone(vmap.get(rk)),
            'vscore': vsmap.get(rk),
            'fav1': favmap.get(rk),
            'p5_top3': bool(row5['top3'] == 1),
            'p5_win': bool(row5['chakujun'] == 1),
            'ab_rank': row5['ab_rank'] if pd.notna(row5['ab_rank']) else np.nan,
            'vh_rank': row5['vh_rank'] if pd.notna(row5['vh_rank']) else np.nan,
            'h7_rank': row5['h7_rank'] if pd.notna(row5['h7_rank']) else np.nan,
            'combo': row5['combo'] if pd.notna(row5['combo']) else 0,
            'small': fs <= 10,
        })
    df = pd.DataFrame(races)
    print(f'対象レース(3着内揃い・5番人気あり・8頭以上): {len(df):,}')

    def report(sub, title):
        n = len(sub)
        if n == 0:
            print(f'\n=== {title}: 0R ===')
            return
        print(f'\n=== {title}: {n:,}R ===')
        print(f'  5番人気が勝ち3頭に入る     {sub.has5.mean()*100:5.1f}%  ({sub.has5.sum():,})')
        print(f'  うち5番人気が1着           {sub.p5_win.mean()*100:5.1f}%  ({sub.p5_win.sum():,})')
        print(f'  現行プールで勝ち3頭を全部含む {sub.covered.mean()*100:5.1f}%')
        miss = ~sub.covered
        nm = int(miss.sum())
        print(f'  現行プールで逃す           {nm/n*100:5.1f}%  ({nm:,})')
        if nm:
            m = sub[miss]
            print(f'    原因  5番だけ落ち        {m.miss5_only.mean()*100:5.1f}% of miss  '
                  f'({m.miss5_only.sum():,}R / 全レース{m.miss5_only.sum()/n*100:.1f}%)')
            print(f'    原因  13番人気以降だけ   {m.miss13_only.mean()*100:5.1f}% of miss  '
                  f'({m.miss13_only.sum():,})')
            print(f'    原因  5番と13番以降の両方 {m.miss_both.mean()*100:5.1f}% of miss  '
                  f'({m.miss_both.sum():,})')
        # 5番を常時足すとカバーは miss5_only が全部復活
        always = sub.covered | sub.miss5_only
        print(f'  5番を常時プールへ         カバー {always.mean()*100:5.1f}%  '
              f'(+{(always.mean()-sub.covered.mean())*100:.1f}pp / 毎レース+1頭)')

    report(df, '全体')
    for p in ('train', 'holdout', 'recent'):
        report(df[df.period == p], f'period={p}')
    report(df[df.small], '少頭数(≤10) ※相手候補が付く帯')
    report(df[~df.small], '多頭数(11〜) ※今回のキーンランドCと同じ空白')

    print('\n=== 妙味度ゾーン別（多頭数のみ）===')
    big = df[~df.small]
    print(f'{"zone":<6}{"R":>8}{"5番が3着内":>12}{"5番が1着":>10}{"現行カバー":>12}{"5番だけmiss":>12}')
    for z in 'DCBAS':
        s = big[big.vz == z]
        if s.empty:
            continue
        print(f'{z:<6}{len(s):8,}{s.has5.mean()*100:11.1f}%{s.p5_win.mean()*100:9.1f}%'
              f'{s.covered.mean()*100:11.1f}%{s.miss5_only.mean()*100:11.1f}%')

    print('\n=== 5番人気の救済条件（多頭数・holdoutで最終判定 / trainは探索）===')
    print('精度=条件ONのとき実際に5番が3着内 / 再現=5番が3着内のレースを拾える割合')
    print('カバー増=その条件で5番を足したとき、現行より勝ち3頭カバーが何pp上がるか')

    rules = [
        ('常時追加', lambda s: pd.Series(True, index=s.index)),
        ('能力Rank≤5（人気相当以上）', lambda s: s.ab_rank <= 5),
        ('能力Rank≤7', lambda s: s.ab_rank <= 7),
        ('能力が人気より上(Rank<5)', lambda s: s.ab_rank < 5),
        ('VH Rank≤5', lambda s: s.vh_rank <= 5),
        ('VH Rank≤8', lambda s: s.vh_rank <= 8),
        ('補正T Rank≤7', lambda s: s.h7_rank <= 7),
        ('妙味度S/A（荒れ寄り）', lambda s: s.vz.isin(list('SA'))),
        ('妙味度D/C（堅い）', lambda s: s.vz.isin(list('DC'))),
        ('能力Rank≤7 かつ 妙味度D/C', lambda s: (s.ab_rank <= 7) & s.vz.isin(list('DC'))),
        ('能力Rank≤7 かつ 妙味度S/A', lambda s: (s.ab_rank <= 7) & s.vz.isin(list('SA'))),
        ('能力Rank<5 または VH Rank≤5',
         lambda s: (s.ab_rank < 5) | (s.vh_rank <= 5)),
    ]

    def eval_rules(sub, tag):
        n = len(sub)
        pos = int(sub.has5.sum())
        print(f'\n-- {tag} n={n:,} / 5番が3着内 {pos:,} ({pos/n*100:.1f}%) --')
        print(f'{"条件":<28}{"発火":>8}{"精度":>8}{"再現":>8}{"カバー増":>10}{"無駄打ち":>10}')
        base_cov = sub.covered.mean()
        for name, fn in rules:
            on = fn(sub).fillna(False)
            k = int(on.sum())
            if k == 0:
                continue
            prec = sub.loc[on, 'has5'].mean()
            rec = (on & sub.has5).sum() / pos if pos else 0
            new_cov = (sub.covered | (on & sub.miss5_only)).mean()
            waste = 1.0 - prec  # 足しても3着に来ない
            print(f'{name:<28}{k/n*100:7.1f}%{prec*100:7.1f}%{rec*100:7.1f}%'
                  f'{(new_cov-base_cov)*100:9.1f}pp{waste*100:9.1f}%')

    train = big[big.period == 'train']
    hold = big[big.period == 'holdout']
    eval_rules(train, 'train 多頭数')
    eval_rules(hold, 'holdout 多頭数 ← 採用判定はここ')
    rec = big[big.period == 'recent']
    if len(rec) >= 200:
        eval_rules(rec, 'recent 多頭数')

    print('\n※精度の目安: 5番人気の無条件3着内率そのものがベース。')
    print('  救済条件の精度がベースをはっきり上回らないなら「上手く選んでいる」とは言えない。')
    print('  再現が高くても発火が広い＝点数膨張。常時追加と大差ない。')


if __name__ == '__main__':
    main()
