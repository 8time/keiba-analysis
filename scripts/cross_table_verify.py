# -*- coding: utf-8 -*-
"""クロステーブルの必要性検証。

1. 軸間の独立性（相関行列）
2. クロス数 vs 3着内率
3. 「インチキ4クロス」検出（人気とVHの重複）
4. 役割別クロス vs 均一クロス
5. VH人気範囲の感度（3着捕捉率）

Usage: python scripts/cross_table_verify.py
"""
import os, sys, io
from collections import defaultdict
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8
ZONE_LO, ZONE_HI = 50, 70


def build_races():
    print('CSV読込...', file=sys.stderr)
    h = cd.load_horses(cols=['race_key','day','umaban','ninki','win_odds',
                             'chakujun','ability_score','vh2_score'])
    r = cd.load_races(cols=['race_key','field_size','kigo','is_handi1'])
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        odds_list = g['win_odds'].tolist()
        m = meta.get(rk)
        rv = vs.race_value_score(
            odds_list, {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                        'kigo': str(getattr(m, 'kigo', '') or '')},
            n_horses=len(g))
        if not rv or not (ZONE_LO <= rv['score'] < ZONE_HI):
            continue

        ninki_ord = g.sort_values('ninki', ascending=True)['umaban'].astype(int).tolist()
        rank_ord = g.sort_values('ability_score', ascending=True)['umaban'].astype(int).tolist()
        vh_ord = g.sort_values('vh2_score', ascending=False, na_position='last')['umaban'].astype(int).tolist()

        fin = g.sort_values('chakujun')
        top3_ub = set(fin['umaban'].astype(int).tolist()[:3])
        winner = fin['umaban'].astype(int).tolist()[0] if len(fin) else None
        if len(top3_ub) < 3:
            continue

        day_val = int(g['day'].iloc[0])
        yr = day_val // 10000
        period = 'train' if yr <= 2022 else ('val' if yr <= 2024 else
                 ('holdout' if yr == 2025 else 'recent'))

        horses = []
        for _, row in g.iterrows():
            ub = int(row['umaban'])
            nk = int(row['ninki']) if pd.notna(row['ninki']) else 99
            horses.append(dict(
                ub=ub,
                ninki_pos=ninki_ord.index(ub)+1,
                rank_pos=rank_ord.index(ub)+1,
                vh_pos=vh_ord.index(ub)+1,
                ninki=nk,
                odds=float(row['win_odds']) if pd.notna(row['win_odds']) else 99,
                in_top3=ub in top3_ub,
                is_winner=ub == winner,
                chakujun=int(row['chakujun']) if pd.notna(row['chakujun']) else 99,
            ))

        out.append(dict(horses=horses, day=day_val, year=yr, period=period,
                        n=len(g), top3=top3_ub, rk=rk))
    return out


# ─────────────────────────────────────────
# 1. 軸間の独立性
# ─────────────────────────────────────────
def section1(races):
    print(f'\n{"="*78}')
    print('■ 1. 軸間の独立性（Spearman相関）')
    print(f'{"="*78}')

    sel = [d for d in races if d['period'] in ('train', 'val')]
    ninki_all, rank_all, vh_all = [], [], []
    for d in sel:
        for h in d['horses']:
            ninki_all.append(h['ninki_pos'])
            rank_all.append(h['rank_pos'])
            vh_all.append(h['vh_pos'])

    from scipy.stats import spearmanr
    axes = {'人気': ninki_all, 'Rank': rank_all, 'VH': vh_all}
    labels = list(axes.keys())
    print(f'\n  全馬 {len(ninki_all):,}頭')
    print(f'  {"":>6}', end='')
    for l in labels:
        print(f' {l:>6}', end='')
    print()
    for i, li in enumerate(labels):
        print(f'  {li:>6}', end='')
        for j, lj in enumerate(labels):
            if i == j:
                print(f'  1.00', end='')
            else:
                rho, _ = spearmanr(axes[li], axes[lj])
                print(f'  {rho:.2f}', end='')
        print()

    print(f'\n  人気上位5頭に限定した相関:')
    n5, r5, v5 = [], [], []
    for d in sel:
        for h in d['horses']:
            if h['ninki_pos'] <= 5:
                n5.append(h['ninki_pos'])
                r5.append(h['rank_pos'])
                v5.append(h['vh_pos'])
    ax5 = {'人気': n5, 'Rank': r5, 'VH': v5}
    print(f'  {len(n5):,}頭')
    print(f'  {"":>6}', end='')
    for l in labels:
        print(f' {l:>6}', end='')
    print()
    for i, li in enumerate(labels):
        print(f'  {li:>6}', end='')
        for j, lj in enumerate(labels):
            if i == j:
                print(f'  1.00', end='')
            else:
                rho, _ = spearmanr(ax5[li], ax5[lj])
                print(f'  {rho:.2f}', end='')
        print()


# ─────────────────────────────────────────
# 2. クロス数 vs 3着内率
# ─────────────────────────────────────────
def section2(races):
    print(f'\n{"="*78}')
    print('■ 2. クロス数 vs 3着内率')
    print(f'{"="*78}')

    sel = [d for d in races if d['period'] in ('train', 'val')]
    K = 5

    print(f'\n  上位{K}頭を「◎」とした4軸クロス:')
    print(f'  人気≤{K} / Rank≤{K} / VH≤{K} / 妙味(Rank-人気≥3)')

    cross_data = defaultdict(lambda: [0, 0, 0])
    for d in sel:
        for h in d['horses']:
            cx = 0
            if h['ninki_pos'] <= K: cx += 1
            if h['rank_pos'] <= K: cx += 1
            if h['vh_pos'] <= K: cx += 1
            if h['ninki_pos'] - h['rank_pos'] >= 3: cx += 1
            cross_data[cx][0] += 1
            if h['in_top3']:
                cross_data[cx][1] += 1
            if h['is_winner']:
                cross_data[cx][2] += 1

    print(f'\n  {"クロス数":>8} {"頭数":>8} {"3着内率":>8} {"勝率":>6}')
    print(f'  {"-"*34}')
    for cx in sorted(cross_data):
        total, top3, wins = cross_data[cx]
        print(f'  {cx:>8} {total:>8,} {top3/total*100:>7.1f}% {wins/total*100:>5.1f}%')

    print(f'\n  ── 「人気を除いた」3軸クロス (Rank/VH/妙味) ──')
    cross3 = defaultdict(lambda: [0, 0, 0])
    for d in sel:
        for h in d['horses']:
            cx = 0
            if h['rank_pos'] <= K: cx += 1
            if h['vh_pos'] <= K: cx += 1
            if h['ninki_pos'] - h['rank_pos'] >= 3: cx += 1
            cross3[cx][0] += 1
            if h['in_top3']:
                cross3[cx][1] += 1
            if h['is_winner']:
                cross3[cx][2] += 1

    print(f'  {"クロス数":>8} {"頭数":>8} {"3着内率":>8} {"勝率":>6}')
    print(f'  {"-"*34}')
    for cx in sorted(cross3):
        total, top3, wins = cross3[cx]
        print(f'  {cx:>8} {total:>8,} {top3/total*100:>7.1f}% {wins/total*100:>5.1f}%')


# ─────────────────────────────────────────
# 3. 人気×VH重複の検出
# ─────────────────────────────────────────
def section3(races):
    print(f'\n{"="*78}')
    print('■ 3. 人気×VH重複検出（4クロスの内訳）')
    print(f'{"="*78}')

    sel = [d for d in races if d['period'] in ('train', 'val')]
    K = 5

    combo = defaultdict(lambda: [0, 0])
    for d in sel:
        for h in d['horses']:
            n_in = h['ninki_pos'] <= K
            r_in = h['rank_pos'] <= K
            v_in = h['vh_pos'] <= K
            m_in = h['ninki_pos'] - h['rank_pos'] >= 3
            key = (n_in, r_in, v_in, m_in)
            combo[key][0] += 1
            if h['in_top3']:
                combo[key][1] += 1

    print(f'\n  人気  Rank   VH  妙味   頭数       3着内率  クロス数')
    print(f'  {"-"*58}')
    for key in sorted(combo, key=lambda k: -combo[k][1]/max(combo[k][0],1)):
        n, r, v, m = key
        total, top3 = combo[key]
        if total < 500:
            continue
        cx = sum(key)
        marks = ['◎' if x else '△' for x in key]
        rate = top3/total*100
        print(f'   {marks[0]:>2}    {marks[1]:>2}    {marks[2]:>2}   {marks[3]:>2}'
              f'  {total:>8,}  {rate:>6.1f}%    {cx}')

    print(f'\n  ── 人気◎かつVH◎ vs 片方だけ ──')
    both, n_only, v_only, neither = [0,0], [0,0], [0,0], [0,0]
    for d in sel:
        for h in d['horses']:
            n_in = h['ninki_pos'] <= K
            v_in = h['vh_pos'] <= K
            if n_in and v_in:
                both[0] += 1; both[1] += int(h['in_top3'])
            elif n_in:
                n_only[0] += 1; n_only[1] += int(h['in_top3'])
            elif v_in:
                v_only[0] += 1; v_only[1] += int(h['in_top3'])
            else:
                neither[0] += 1; neither[1] += int(h['in_top3'])

    for lbl, dat in [('人気◎+VH◎', both), ('人気◎のみ', n_only),
                     ('VH◎のみ', v_only), ('両方△', neither)]:
        rate = dat[1]/dat[0]*100 if dat[0] else 0
        print(f'    {lbl:>12}: {dat[0]:>8,}頭  3着内{rate:.1f}%')


# ─────────────────────────────────────────
# 4. 役割別クロス vs 均一クロス
# ─────────────────────────────────────────
def section4(races):
    print(f'\n{"="*78}')
    print('■ 4. 着順ごとの最適軸（役割別クロスの根拠）')
    print(f'{"="*78}')

    sel = [d for d in races if d['period'] in ('train', 'val')]

    for pos_label, pos_idx in [('1着', 1), ('2着', 2), ('3着', 3)]:
        print(f'\n  ── {pos_label}馬の捕捉率（上位N頭） ──')
        for N in [3, 5, 7]:
            caps = {'人気': 0, 'Rank': 0, 'VH': 0}
            total = 0
            for d in sel:
                for h in d['horses']:
                    if h['chakujun'] != pos_idx:
                        continue
                    total += 1
                    if h['ninki_pos'] <= N: caps['人気'] += 1
                    if h['rank_pos'] <= N: caps['Rank'] += 1
                    if h['vh_pos'] <= N: caps['VH'] += 1
            if total == 0: continue
            parts = [f'{k}={caps[k]/total*100:.1f}%' for k in ['人気','Rank','VH']]
            print(f'    上位{N}頭: {" / ".join(parts)}  (N={total:,})')

    print(f'\n  ── Rank×VH交差（3着馬のみ） ──')
    cross_3rd = defaultdict(lambda: [0,0])
    for d in sel:
        for h in d['horses']:
            if h['chakujun'] != 3:
                continue
            r_in = h['rank_pos'] <= 5
            v_in = h['vh_pos'] <= 5
            key = (r_in, v_in)
            cross_3rd[key][0] += 1

    total_3rd = sum(v[0] for v in cross_3rd.values())
    for (r, v), (cnt, _) in sorted(cross_3rd.items(), key=lambda x: -x[1][0]):
        rl = 'Rank◎' if r else 'Rank△'
        vl = 'VH◎' if v else 'VH△'
        print(f'    {rl}+{vl}: {cnt:,} ({cnt/total_3rd*100:.1f}%)')


# ─────────────────────────────────────────
# 5. VH人気範囲の感度
# ─────────────────────────────────────────
def section5(races):
    print(f'\n{"="*78}')
    print('■ 5. VH人気範囲の感度（3着捕捉率）')
    print(f'{"="*78}')

    sel = [d for d in races if d['period'] in ('train', 'val')]

    print(f'\n  VH上位N頭の3着捕捉率を、VH対象人気範囲別に比較')
    print(f'  「VH対象=人気1-K」＝ VH順位をK番人気以内の馬に限定して再計算')

    for pop_limit_label, pop_limit in [('1-6人気', 6), ('1-8人気', 8),
                                        ('1-10人気', 10), ('全頭', 99)]:
        print(f'\n  ── VH対象: {pop_limit_label} ──')
        for N in [5, 7, 9]:
            cap = 0; total = 0
            for d in sel:
                restricted = [h for h in d['horses'] if h['ninki_pos'] <= pop_limit]
                restricted.sort(key=lambda h: h['vh_pos'])
                vh_top_n = set(h['ub'] for h in restricted[:N])
                for h in d['horses']:
                    if h['chakujun'] == 3:
                        total += 1
                        if h['ub'] in vh_top_n:
                            cap += 1
            if total:
                print(f'    VH上位{N}頭: 3着捕捉 {cap/total*100:.1f}%  ({cap:,}/{total:,})')

    print(f'\n  ── VH上位7頭の構成（全頭VH使用時） ──')
    pop_dist = defaultdict(int)
    total_horses = 0
    for d in sel:
        ordered = sorted(d['horses'], key=lambda h: h['vh_pos'])
        for h in ordered[:7]:
            total_horses += 1
            if h['ninki_pos'] <= 3:
                pop_dist['人気1-3'] += 1
            elif h['ninki_pos'] <= 6:
                pop_dist['人気4-6'] += 1
            elif h['ninki_pos'] <= 9:
                pop_dist['人気7-9'] += 1
            else:
                pop_dist['人気10+'] += 1

    print(f'  VH上位7頭の人気帯構成 ({total_horses:,}頭):')
    for lbl in ['人気1-3', '人気4-6', '人気7-9', '人気10+']:
        cnt = pop_dist.get(lbl, 0)
        print(f'    {lbl}: {cnt/total_horses*100:.1f}%')


# ─────────────────────────────────────────
# 6. 判定
# ─────────────────────────────────────────
def section6():
    print(f'\n{"="*78}')
    print('■ 6. クロステーブルの必要性判定')
    print(f'{"="*78}')
    print(f"""
  検証結果に基づく判定:

  (1) 4軸均一クロスの問題:
      人気とVHの相関が高い → 2軸が重複 → 「インチキ4クロス」のリスクあり
      → 4軸均一カウントはやめるべき

  (2) 有効なクロス構造:
      着順別に最適な軸が異なる:
      - 1着: Rank (能力上位)
      - 2着: Rank×人気 (実力+市場合意)
      - 3着: VH (品質再順位付け)
      → 役割別クロスは意味がある

  (3) 実装案:
      × 4軸均一クロス数を表示
      ○ 着順ロール別の「成立/不成立」を表示
      ○ Rank×VH一致度を表示（3着候補の品質指標として）

  (4) VH人気範囲:
      上の結果参照 → データに基づいて判断
""")


def main():
    races = build_races()
    n_t = sum(1 for d in races if d['period'] == 'train')
    n_v = sum(1 for d in races if d['period'] == 'val')
    n_h = sum(1 for d in races if d['period'] == 'holdout')
    print(f'C中庸 {len(races):,}R (train: {n_t:,} / val: {n_v:,} / hold: {n_h:,})\n')

    section1(races)
    section2(races)
    section3(races)
    section4(races)
    section5(races)
    section6()


if __name__ == '__main__':
    main()
