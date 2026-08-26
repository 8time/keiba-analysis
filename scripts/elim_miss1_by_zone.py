# -*- coding: utf-8 -*-
"""1頭欠けを妙味度ゾーン(D鉄板/C中庸/B/A荒れ)で分解する。"""
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import formation_stats as fs
from scripts import csv_data as cd
from scripts.elim_cross_keep_top3_2026h1 import (
    DAY0, DAY1, _num, flag_counts, hunter_elite_top3, add_rklow_vh,
    edf_rank_and_surv, recommend_n, apply_flow,
)
from scripts.elim_miss1_hunter import hunter_ranks


def pct(a, b):
    return a / b * 100 if b else 0.0


def main():
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3', 'chakujun',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ])
    h = h[(h['day'] >= DAY0) & (h['day'] <= DAY1)]
    h['jyo'] = h['jyo'].astype(float)
    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore', 'vlabel'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))
    vs_map = dict(zip(races['race_key'].astype(str), races['vscore']))

    st = defaultdict(lambda: dict(
        tot=0, all3=0, miss1=0, miss2=0, m1_lab=Counter(),
        hot_in_top3=0, hot_miss=0, outsider_miss=0,
    ))

    for rk, g in h.groupby('race_key', sort=False):
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        win = set(int(x) for x in g[g['top3'] == 1]['umaban'])
        if len(win) != 3 or len(g) < 5:
            continue
        z = fs.ZONE_SHORT.get(fs.zone_of(vs_map.get(str(rk))), '不明')
        s = st[z]
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
        lab, elite, net = hunter_ranks(ninki, scored)
        hot = set()
        if elite:
            hot.add(elite[0])
        if len(elite) >= 2:
            hot.add(elite[1])
        if net:
            hot.add(net[0])
        s['tot'] += 1
        miss = win - keep
        nmiss = len(miss)
        if nmiss == 0:
            s['all3'] += 1
        elif nmiss == 1:
            s['miss1'] += 1
        else:
            s['miss2'] += 1
        for u in win:
            if u in hot:
                s['hot_in_top3'] += 1
        if nmiss == 1:
            u = next(iter(miss))
            lb = lab.get(u, '不明')
            s['m1_lab'][lb] += 1
            if lb == 'その他穴':
                s['outsider_miss'] += 1
            if u in hot:
                s['hot_miss'] += 1

    print('ゾーンはアプリの妙味度: D鉄板 0-49 / C中庸 50-69 / B/A荒れ 70+')
    print()
    for z in ('D 鉄板', 'C 中庸', 'B/A 荒れ'):
        s = st[z]
        t = s['tot']
        print(f'=== {z}  {t}R ===')
        print(f'  3頭全部残る {s["all3"]:4} ({pct(s["all3"], t):5.1f}%)')
        print(f'  1頭欠け     {s["miss1"]:4} ({pct(s["miss1"], t):5.1f}%)')
        print(f'  2頭以上欠け {s["miss2"]:4} ({pct(s["miss2"], t):5.1f}%)')
        print(f'  1頭欠けのうち網外の穴馬 {s["outsider_miss"]:4} / {s["miss1"]}'
              f' ({pct(s["outsider_miss"], s["miss1"]):5.1f}%)')
        print(f'  全レース比で網外欠け     {s["outsider_miss"]:4} / {t}'
              f' ({pct(s["outsider_miss"], t):5.1f}%)')
        print(f'  1頭欠けのうち精鋭1+2+広域1 {s["hot_miss"]:4} / {s["miss1"]}'
              f' ({pct(s["hot_miss"], s["miss1"]):5.1f}%)')
        per = s['hot_in_top3'] / t if t else 0
        print(f'  3着馬が精鋭1/2/広域1だった延べ {s["hot_in_top3"]} (1Rあたり {per:.2f}頭)')
        if s['miss1']:
            print('  欠け馬ラベル:', dict(s['m1_lab']))
        print()

    dc = {k: 0 for k in ('tot', 'all3', 'miss1', 'outsider_miss')}
    for z in ('D 鉄板', 'C 中庸'):
        for k in dc:
            dc[k] += st[z][k]
    print('=== 鉄板+中庸 まとめ ===')
    print(f'  {dc["tot"]}R  全部残る {pct(dc["all3"], dc["tot"]):.1f}%'
          f'  1頭欠け {pct(dc["miss1"], dc["tot"]):.1f}%'
          f'  網外欠け {pct(dc["outsider_miss"], dc["tot"]):.1f}%')


if __name__ == '__main__':
    main()
