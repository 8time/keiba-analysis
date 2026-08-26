# -*- coding: utf-8 -*-
"""確定オッズ＋結果から、10点に入らなかった3着組の中身を見る。
時系列変動は使わない（データ不足の確認だけ別途）。
"""
import os
import sqlite3
import sys
from collections import Counter
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import formation_stats as fs
from scripts import csv_data as cd
from scripts.elim_cross_keep_top3_2026h1 import (
    DAY0, DAY1, _num, flag_counts, hunter_elite_top3, add_rklow_vh,
    edf_rank_and_surv, recommend_n, apply_flow,
)
from scripts.elim_miss1_hunter import hunter_ranks
from scripts.trio_rank10_backtest import load_pays, fuku_of


def combo_rank(pool, win, fk):
    ums = list(pool)
    if len(ums) < 3 or not (win <= pool):
        return None, None
    combos = [frozenset(c) for c in combinations(ums, 3)]

    def sc(fs):
        p = 1.0
        for u in fs:
            p *= fk.get(u, 0.01)
        return p

    combos.sort(key=sc, reverse=True)
    try:
        r = combos.index(win) + 1
    except ValueError:
        return None, len(combos)
    return r, len(combos)


def main():
    db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'data', 'odds_history.db')
    print('=== 時系列オッズ蓄積 ===')
    if os.path.exists(db):
        con = sqlite3.connect(db)
        n_r = con.execute('select count(distinct race_id) from odds_logs').fetchone()[0]
        n_m = con.execute(
            "select count(*) from (select race_id from odds_logs where odds_type='win' "
            "group by race_id having count(distinct timestamp)>=2)"
        ).fetchone()[0]
        ts = con.execute('select min(timestamp), max(timestamp) from odds_logs').fetchone()
        h1 = con.execute(
            "select count(distinct race_id) from odds_logs "
            "where timestamp>='2026-01-01' and timestamp<'2026-07-01'"
        ).fetchone()[0]
        print(f'  odds_history.db  {n_r}R / 2時点以上 {n_m}R / 2026H1 {h1}R')
        print(f'  期間 {ts[0]} 〜 {ts[1]}')
        con.close()
    else:
        print('  odds_history.db なし')

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
    pays = load_pays()

    # カバーだが10点外 / 10点内
    gap_third_nk = Counter()  # 3着組で一番人気が薄い脚の人気
    hit_third_nk = Counter()
    gap_rank = []
    hit_odds_third = []
    gap_odds_third = []
    gap_in_net = 0
    gap_n = 0
    hit_n = 0
    cover_n = 0
    not_cover = 0
    third_in_a = 0
    third_only_vh = 0

    for rk, g in h.groupby('race_key', sort=False):
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3 or len(g) < 5:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if not pay or pay[0] != win:
            continue
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
        pool = set(keep) | set(elite) | set(net)
        fk = {int(r['umaban']): fuku_of(int(r['ninki']), _num(r.get('win_odds')))
              for r in rows}
        odds = {int(r['umaban']): _num(r.get('win_odds')) for r in rows}

        if not (win <= pool):
            not_cover += 1
            continue
        cover_n += 1
        rnk, ncmb = combo_rank(pool, win, fk)
        third = max(win, key=lambda u: ninki.get(u, 0))
        nk3 = ninki[third]
        od3 = odds.get(third) or 0
        only_vh = third not in keep
        if only_vh:
            third_only_vh += 1
        else:
            third_in_a += 1
        if rnk is not None and rnk <= 10:
            hit_n += 1
            hit_third_nk[nk3] += 1
            hit_odds_third.append(od3)
        else:
            gap_n += 1
            gap_third_nk[nk3] += 1
            gap_odds_third.append(od3)
            if rnk:
                gap_rank.append(rnk)
            if third in set(elite) | set(net):
                gap_in_net += 1

    def med(xs):
        if not xs:
            return 0
        s = sorted(xs)
        return s[len(s) // 2]

    print('\n=== A＋VH網に3頭いるレースでの、確定オッズ・複勝積 ===')
    print(f'  カバー {cover_n} / 非カバー {not_cover}')
    print(f'  10点に入った {hit_n} ({hit_n/cover_n*100:.1f}%)')
    print(f'  カバーだが10点外 {gap_n} ({gap_n/cover_n*100:.1f}%)')
    print(f'  一番薄い脚が残し内 {third_in_a} / VH網だけの追加 {third_only_vh}')
    print(f'  10点外のうち、薄い脚がVH網所属 {gap_in_net}/{gap_n}')
    print(f'  10点外の正解組の複勝積順位 中央 {med(gap_rank):.0f} / 平均 {sum(gap_rank)/len(gap_rank):.1f}'
          if gap_rank else '')
    print(f'  一番薄い脚の確定単勝  的中側 中央 {med(hit_odds_third):.1f}倍'
          f' / 10点外側 中央 {med(gap_odds_third):.1f}倍')
    print('\n  一番薄い脚の人気（10点に入った）')
    for k in range(1, 19):
        if hit_third_nk[k]:
            print(f'    {k:2}番  {hit_third_nk[k]:4}')
    print('  一番薄い脚の人気（カバーだが10点外）')
    for k in range(1, 19):
        if gap_third_nk[k]:
            print(f'    {k:2}番  {gap_third_nk[k]:4}')


if __name__ == '__main__':
    main()
