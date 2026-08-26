# -*- coding: utf-8 -*-
"""「1頭だけ欠けた」レースの欠け馬が、穴馬ハンター画面の
精鋭1位 / 精鋭2位 / 広域網1位 かを調べる。

穴馬ハンターは 6番人気以下だけを精鋭・広域網に並べる(pages/anabaka_hunter.py)。
Usage: python scripts/elim_miss1_hunter.py
"""
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import csv_data as cd
from scripts.elim_cross_keep_top3_2026h1 import (
    DAY0, DAY1, _num, flag_counts, hunter_elite_top3, add_rklow_vh,
    edf_rank_and_surv, recommend_n, apply_flow,
)


def hunter_ranks(ninki, scored, pop_min=6):
    """ハンター画面と同じ: 6番人気以下をスコア降順で精鋭/広域網に分ける。
    戻り: um -> label
      精鋭1 / 精鋭2 / 精鋭3+ / 広域1 / 広域2+ / その他穴(6番以下・圏外) / 5番以内
    """
    elite = sorted(
        [u for u, d in scored.items()
         if d.get('tier') == '🎯精鋭' and ninki.get(u, 99) >= pop_min],
        key=lambda u: -scored[u]['score'],
    )
    net = sorted(
        [u for u, d in scored.items()
         if d.get('tier') == '🕸️広域網' and ninki.get(u, 99) >= pop_min],
        key=lambda u: -scored[u]['score'],
    )
    lab = {}
    for i, u in enumerate(elite, 1):
        lab[u] = '精鋭1' if i == 1 else ('精鋭2' if i == 2 else '精鋭3+')
    for i, u in enumerate(net, 1):
        lab[u] = '広域1' if i == 1 else '広域2+'
    for u, nk in ninki.items():
        if u in lab:
            continue
        lab[u] = 'その他穴' if nk >= pop_min else '5番以内'
    return lab, elite, net


def main():
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3', 'chakujun',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ])
    h = h[(h['day'] >= DAY0) & (h['day'] <= DAY1)]
    h['jyo'] = h['jyo'].astype(float)
    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))

    miss_lab = Counter()
    miss_nk = Counter()
    miss_chaku = Counter()
    miss_combo = Counter()
    any_of_three = Counter()  # 欠け馬が精鋭1/2/広域1のいずれか
    tot = 0
    miss1 = 0
    # 3着馬のうち「精鋭1/2/広域1」が何頭いたか（欠けに限らず）
    top3_in_hot = 0
    hot_cut = 0  # そのホット馬が欠けた

    for rk, g in h.groupby('race_key', sort=False):
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        win = set(int(x) for x in g[g['top3'] == 1]['umaban'])
        if len(win) != 3 or len(g) < 5:
            continue
        tot += 1
        rows = g.to_dict('records')
        by_um = {int(r['umaban']): r for r in rows}
        flags, ninki = flag_counts(rows)
        elite_top3, scored = hunter_elite_top3(rows)
        rk_edf, _surv = edf_rank_and_surv(rows, border=3)
        add_rklow_vh(flags, len(rows), rk_edf, scored)
        order = sorted(flags, key=lambda u: (-flags[u], -ninki.get(u, 0)))
        kigo = kigo_map.get(str(rk), '')
        is_handi = bool(handi_map.get(str(rk), int(_num(g['is_handi1'].iloc[0]) or 0)))
        tgt, _ = recommend_n(rows, kigo, is_handi)
        keep, _keep0, _add = apply_flow(order, tgt, rows, elite_top3, pool=None)
        lab, elite, net = hunter_ranks(ninki, scored)

        hot = set()
        if elite:
            hot.add(elite[0])
        if len(elite) >= 2:
            hot.add(elite[1])
        if net:
            hot.add(net[0])
        for u in win:
            if u in hot:
                top3_in_hot += 1

        miss = win - keep
        if len(miss) != 1:
            continue
        miss1 += 1
        u = next(iter(miss))
        r = by_um[u]
        lb = lab.get(u, '不明')
        miss_lab[lb] += 1
        nk = int(r['ninki'])
        miss_nk[nk] += 1
        ck = int(_num(r.get('chakujun')) or 0)
        miss_chaku[ck] += 1
        cb = int(_num(r.get('combo')) or 0)
        miss_combo[min(cb, 4)] += 1
        if u in hot:
            any_of_three[lb] += 1
            hot_cut += 1

    def pct(a, b):
        return a / b * 100 if b else 0.0

    print(f'対象 {tot:,}R / 1頭欠け {miss1:,}R ({pct(miss1, tot):.1f}%)')
    print('\n=== 欠けた1頭は、穴馬ハンター画面(6番人気以下)のどれか ===')
    order_l = ['精鋭1', '精鋭2', '精鋭3+', '広域1', '広域2+', 'その他穴', '5番以内']
    for k in order_l:
        print(f'  {k:8}  {miss_lab[k]:4}R  ({pct(miss_lab[k], miss1):5.1f}%)')
    n_ask = miss_lab['精鋭1'] + miss_lab['精鋭2'] + miss_lab['広域1']
    print(f'\n  精鋭1 + 精鋭2 + 広域1 の合計: {n_ask:,} / {miss1:,}'
          f'  ({pct(n_ask, miss1):.1f}%)')
    print(f'  → 1頭欠け全体({miss1}R)のうち、質問の3枠に入るのは {pct(n_ask, miss1):.1f}%')
    print(f'  → 全{tot}Rのうち、その3枠が欠けて1頭ミスになったのは {pct(n_ask, tot):.1f}%')

    print('\n=== 欠け馬の人気 ===')
    for k in range(1, 19):
        if miss_nk[k]:
            print(f'  {k:2}番人気  {miss_nk[k]:4}  ({pct(miss_nk[k], miss1):5.1f}%)')

    print('\n=== 欠け馬の着順 ===')
    for k in (1, 2, 3):
        print(f'  {k}着  {miss_chaku[k]:4}  ({pct(miss_chaku[k], miss1):5.1f}%)')

    print('\n=== 欠け馬の combo ===')
    for k in range(0, 5):
        labc = f'{k}' if k < 4 else '4+'
        print(f'  combo {labc}  {miss_combo[k]:4}  ({pct(miss_combo[k], miss1):5.1f}%)')

    print('\n=== 参考: 3着馬が精鋭1/2/広域1だった回数(欠けたかどうかに関係なく) ===')
    print(f'  3着馬がその3枠だった延べ頭数: {top3_in_hot}')
    print(f'  そのうち今回の操作で欠けた: {hot_cut}')


if __name__ == '__main__':
    main()
