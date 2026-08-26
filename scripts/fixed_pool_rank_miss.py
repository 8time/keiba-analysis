# -*- coding: utf-8 -*-
"""人気1-9をプール固定したとき、正解がプール内なのに20点から落ちる理由の分類。

対象: 勝ち3頭がすべて人気1-9にいるレースだけ。
現行スコア(ability合計 + 本線ソフト加点)での正解組の順位を測り、
  - どの人気形が落ちるか
  - あと何点で拾えたか（21-30 / 31-42 / 43+）
  - 別の並べ方なら20点に入ったか
を holdout で出す。

Usage: python scripts/fixed_pool_rank_miss.py
"""
import os
import sys
from collections import Counter
from itertools import combinations

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import trio_engine as te
from core.axis_selector import POP_FUKU
from scripts import csv_data as cd

POP9 = dict(POP_FUKU)
POP9.setdefault(9, 8.8)


def shape_of(nks):
    n1 = sum(1 for n in nks if n <= 4)
    n5 = sum(1 for n in nks if n == 5)
    n_ana = sum(1 for n in nks if 6 <= n <= 9)
    if n5:
        return f'5番絡み(人{n1}・5・穴{n_ana})'
    if n1 == 3:
        return '鉄板(1-4が3頭)'
    if n1 == 2:
        return '①人2穴1'
    if n1 == 1:
        return '②人1穴2'
    return '穴寄り(人0)'


def rank_by(combos, key, reverse):
    ordered = sorted(combos, key=key, reverse=reverse)
    return {c: i + 1 for i, c in enumerate(ordered)}


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'ability_score', 'top3', 'field_size',
    ])
    h = h[h['period'] == 'holdout']
    print(f'  holdout 馬行 {len(h):,}', flush=True)

    stats = {
        'pool_ok': 0,
        'hit20': 0,
        'miss20': 0,
    }
    rank_hit = []
    rank_miss = []
    miss_shape = Counter()
    all_shape = Counter()
    miss_bucket = Counter()
    miss_maxnk = Counter()
    alt_save = Counter()
    miss_ability_bottom = Counter()  # 正解3頭のうち能力が9頭中下位か
    # 本線加点が押し出したか: 人3組の能力合計 vs 正解
    bonus_crowd = 0
    no_bonus_would_hit = 0

    for rk, g in h.groupby('race_key', sort=False):
        keep = g[g['ninki'] <= 9]
        if len(keep) < 9:
            continue
        keep = keep.nsmallest(9, 'ninki')
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        keep_u = set(int(x) for x in keep['umaban'])
        if not win <= keep_u:
            continue
        stats['pool_ok'] += 1

        hs = []
        ab = {}
        nk = {}
        for r in keep.itertuples(index=False):
            u = int(r.umaban)
            sc = float(r.ability_score) if r.ability_score == r.ability_score else 0.0
            hs.append({'umaban': u, 'name': str(u), 'score': sc, 'pop': int(r.ninki), 'alert': ''})
            ab[u] = sc
            nk[u] = int(r.ninki)

        res = te.recommend_trio(hs, pattern='本線', n_points=84, fixed_pool=True)
        bets = res.get('bets') or []
        combos = [frozenset(b['combo']) for b in bets]
        if win not in combos:
            # 84点に無いのは生成漏れ（本調査の対象外）
            continue
        rnk = combos.index(win) + 1
        nks = tuple(sorted(nk[u] for u in win))
        shp = shape_of(nks)
        all_shape[shp] += 1

        if rnk <= 20:
            stats['hit20'] += 1
            rank_hit.append(rnk)
            continue

        stats['miss20'] += 1
        rank_miss.append(rnk)
        miss_shape[shp] += 1
        if rnk <= 30:
            miss_bucket['21-30 あと少し'] += 1
        elif rnk <= 42:
            miss_bucket['31-42 中盤'] += 1
        else:
            miss_bucket['43-84 遠い'] += 1
        miss_maxnk[max(nks)] += 1

        # 能力: 9頭内の能力順位（1=最強）
        ab_rank = {u: i + 1 for i, u in enumerate(sorted(ab, key=lambda x: -ab[x]))}
        worst_ab = max(ab_rank[u] for u in win)
        miss_ability_bottom[f'一番弱い脚の能力Rank={worst_ab}'] += 1

        # 別並べ
        all_c = []
        for a, b, c in combinations(sorted(keep_u), 3):
            all_c.append(frozenset((a, b, c)))

        def ninki_sum(fs):
            return sum(nk[u] for u in fs)

        def fuku_prod(fs):
            p = 1.0
            for u in fs:
                p *= POP9.get(nk[u], 8.0) / 100.0
            return p

        def ab_sum(fs):
            return sum(ab[u] for u in fs)

        def honsen_score(fs):
            n_pop = sum(1 for u in fs if nk[u] <= 4)
            return ab_sum(fs) + 6.0 * n_pop

        alts = {
            '人気合計が小さい順': rank_by(all_c, ninki_sum, False),
            '複勝率の積': rank_by(all_c, fuku_prod, True),
            '能力合計のみ(加点なし)': rank_by(all_c, ab_sum, True),
            '能力+本線加点(=現行)': rank_by(all_c, honsen_score, True),
        }
        for name, rd in alts.items():
            if rd.get(win, 99) <= 20:
                alt_save[name] += 1

        if alts['能力合計のみ(加点なし)'].get(win, 99) <= 20:
            no_bonus_would_hit += 1
        # 人3の組が能力で上に並んで枠を埋めたか
        iron = [fs for fs in all_c if sum(1 for u in fs if nk[u] <= 4) == 3]
        if iron and ab_sum(win) < max(ab_sum(fs) for fs in iron):
            bonus_crowd += 1

    n = stats['pool_ok']
    print(f'\nholdout・勝ち3頭が人気1-9に全部いる: {n:,}R')
    print(f'  20点に入る   {stats["hit20"]:,} ({stats["hit20"]/n*100:.1f}%)')
    print(f'  20点から落ち {stats["miss20"]:,} ({stats["miss20"]/n*100:.1f}%)')
    if rank_hit:
        print(f'  的中時の正解順位  中央値 {np.median(rank_hit):.0f} / 平均 {np.mean(rank_hit):.1f}')
    if rank_miss:
        print(f'  落ちた時の正解順位 中央値 {np.median(rank_miss):.0f} / 平均 {np.mean(rank_miss):.1f}')

    print('\n=== 落ちた組の人気形（分母=落ちたレース）===')
    m = stats['miss20'] or 1
    print(f'{"形":<22}{"落ち":>8}{"構成比":>8}{"この形の出現":>12}{"形の中の落ち率":>14}')
    for shp, c in miss_shape.most_common():
        tot = all_shape[shp]
        print(f'{shp:<22}{c:8d}{c/m*100:7.1f}%{tot:12d}{c/tot*100:13.1f}%')

    print('\n=== あと何点で拾えたか ===')
    for k, c in miss_bucket.most_common():
        print(f'  {k:<16} {c:5d} ({c/m*100:5.1f}%)')

    print('\n=== 落ちた組のいちばん人気薄の脚 ===')
    for k, c in sorted(miss_maxnk.items()):
        print(f'  最薄 {k}番人気   {c:5d} ({c/m*100:5.1f}%)')

    print('\n=== 落ちた組で、能力がいちばん弱い脚（9頭中のRank）===')
    for k, c in sorted(miss_ability_bottom.items(), key=lambda x: -x[1])[:8]:
        print(f'  {k}   {c:5d} ({c/m*100:5.1f}%)')

    print('\n=== 別の並べ方なら、落ちた組を20点で救えたか（分母=落ちたレース）===')
    print('（現行で落ちたもの限定。すでに20点に入っている分は含まない）')
    for name, c in alt_save.most_common():
        print(f'  {name:<24} {c:5d} ({c/m*100:5.1f}%)')

    print(f'\n  うち「本線加点を外して能力だけ」なら救えた: {no_bonus_would_hit} '
          f'({no_bonus_would_hit/m*100:.1f}%)')
    print(f'  人3組の能力合計が正解より高い（鉄板に枠を取られた）: {bonus_crowd} '
          f'({bonus_crowd/m*100:.1f}%)')

    print('\n※C(9,3)=84通り。20点は全体の24%。ランダムなら的中24%。')
    print('  現行~50%はその倍。残り半分の内訳が上。')


if __name__ == '__main__':
    main()
