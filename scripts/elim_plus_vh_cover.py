# -*- coding: utf-8 -*-
"""残った馬(A) ＋ 穴馬ハンター(B) で3着3頭を何%カバーできるか。

A = 消去クロスで推奨まで切った残し ＋ 敗者復活
B は穴馬ハンター画面(6番人気以下)の足し方を段階的に変える。

Usage: python scripts/elim_plus_vh_cover.py
"""
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import formation_stats as fs
from core import value_hunter as vh
from scripts import csv_data as cd
from scripts.elim_cross_keep_top3_2026h1 import (
    DAY0, DAY1, _num, flag_counts, hunter_elite_top3, add_rklow_vh,
    edf_rank_and_surv, recommend_n, apply_flow,
)
from scripts.elim_miss1_hunter import hunter_ranks

POP_MIN = 6
OPS = (vh.load_params() or {}).get('ops') or {}
TH_ELITE = float(OPS.get('recall0.5') or 0.124)
TH_NET = float(OPS.get('recall0.7') or 0.083)


def pct(a, b):
    return a / b * 100 if b else 0.0


def hunter_sets(ninki, scored, elite, net):
    """画面と同じ6番人気以下の集合。"""
    long = {u for u, nk in ninki.items() if nk >= POP_MIN}
    other = {u for u in long
             if scored.get(u) and scored[u].get('tier') not in ('🎯精鋭', '🕸️広域網')}
    no_score = {u for u in long if u not in scored}
    return {
        'e1': set(elite[:1]),
        'e12': set(elite[:2]),
        'e12n1': set(elite[:2]) | set(net[:1]),
        'elite_all': set(elite),
        'nets': set(elite) | set(net),
        'page': set(elite) | set(net) | other,  # 画面に出る全候補(スコアあり)
        'long_all': long,  # 6番以下すべて(スコア無し含む)
        'other': other,
        'no_score': no_score,
    }


def main():
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ])
    h = h[(h['day'] >= DAY0) & (h['day'] <= DAY1)]
    h['jyo'] = h['jyo'].astype(float)
    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))
    vs_map = dict(zip(races['race_key'].astype(str), races['vscore']))

    steps = [
        ('Aだけ', None),
        ('A＋精鋭1', 'e1'),
        ('A＋精鋭1・2', 'e12'),
        ('A＋精鋭1・2＋広域1', 'e12n1'),
        ('A＋精鋭全員', 'elite_all'),
        ('A＋精鋭＋広域(網)', 'nets'),
        ('A＋VH画面の全候補', 'page'),
        ('A＋6番人気以下すべて', 'long_all'),
    ]

    # zone -> step -> {tot, hit, extra_sum, size_sum}
    st = defaultdict(lambda: {k: {'tot': 0, 'hit': 0, 'extra': 0.0, 'size': 0.0}
                              for _, k in steps})
    # 圏外198相当: 1頭欠けの欠け馬がスコアを持つか
    miss1_other = {'n': 0, 'has_score': 0, 'below_net': 0, 'no_score': 0,
                   'score_sum': 0.0}

    zones_order = ('D 鉄板', 'C 中庸', 'B/A 荒れ', '全体')

    for rk, g in h.groupby('race_key', sort=False):
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        win = set(int(x) for x in g[g['top3'] == 1]['umaban'])
        if len(win) != 3 or len(g) < 5:
            continue
        z = fs.ZONE_SHORT.get(fs.zone_of(vs_map.get(str(rk))), '不明')
        rows = g.to_dict('records')
        flags, ninki = flag_counts(rows)
        elite_top3, scored = hunter_elite_top3(rows)
        rk_edf, _surv = edf_rank_and_surv(rows, border=3)
        add_rklow_vh(flags, len(rows), rk_edf, scored)
        order = sorted(flags, key=lambda u: (-flags[u], -ninki.get(u, 0)))
        kigo = kigo_map.get(str(rk), '')
        is_handi = bool(handi_map.get(str(rk), int(_num(g['is_handi1'].iloc[0]) or 0)))
        tgt, _ = recommend_n(rows, kigo, is_handi)
        keep, _, _ = apply_flow(order, tgt, rows, elite_top3, pool=None)
        _lab, elite, net = hunter_ranks(ninki, scored)
        hs = hunter_sets(ninki, scored, elite, net)

        miss = win - keep
        if len(miss) == 1:
            u = next(iter(miss))
            if ninki.get(u, 0) >= POP_MIN and _lab.get(u) == 'その他穴':
                miss1_other['n'] += 1
                d = scored.get(u)
                if not d:
                    miss1_other['no_score'] += 1
                else:
                    miss1_other['has_score'] += 1
                    miss1_other['score_sum'] += float(d['score'])
                    if d['score'] < TH_NET:
                        miss1_other['below_net'] += 1

        for zone_key in (z, '全体'):
            for name, key in steps:
                extra = set() if key is None else hs[key]
                uni = keep | extra
                cell = st[zone_key][key]
                cell['tot'] += 1
                if win <= uni:
                    cell['hit'] += 1
                added = extra - keep
                cell['extra'] += len(added)
                cell['size'] += len(uni)

    print('対象: 2026/1-6 JRA。A=クロス残し＋敗者復活。'
          f'VHは{POP_MIN}番人気以下（画面と同じ）。')
    print(f'精鋭しきい値 {TH_ELITE:.3f} / 広域 {TH_NET:.3f}')
    print()
    for z in zones_order:
        print(f'=== {z} ===')
        print(f'  {"足し方":<22}  3頭カバー    平均頭数  追加')
        base_hit = None
        for name, key in steps:
            c = st[z][key]
            t = c['tot']
            if not t:
                continue
            hit_p = pct(c['hit'], t)
            if key is None:
                base_hit = hit_p
            gain = '' if base_hit is None or key is None else f'  (+{hit_p - base_hit:.1f}pt)'
            print(f'  {name:<22} {c["hit"]:4}/{t} {hit_p:5.1f}%'
                  f'   {c["size"]/t:5.1f}頭  +{c["extra"]/t:4.1f}{gain}')
        print()

    n = miss1_other['n']
    print('=== 1頭欠けのうち「ハンター圏外の6番以下」(前回198) のスコア ===')
    print(f'  {n}頭')
    print(f'  スコアあり: {miss1_other["has_score"]}  '
          f'（平均 {miss1_other["score_sum"]/miss1_other["has_score"]:.3f}）'
          if miss1_other['has_score'] else '  スコアあり: 0')
    print(f'  広域しきい値({TH_NET:.3f})未満: {miss1_other["below_net"]}')
    print(f'  スコアなし: {miss1_other["no_score"]}')
    print('  → 圏外は「画面の網から落ちた」だけで、スコア自体は大抵ある。')


if __name__ == '__main__':
    main()
