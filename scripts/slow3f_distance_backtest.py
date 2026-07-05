# -*- coding: utf-8 -*-
"""末脚下位フラグ(消去クロス slow3f)が短距離で来にくさ予測力を持つか検証。

ユーザー観測: 北九州記念(芝1200m)で1番人気すら末脚下位フラグに該当=スプリントは末脚でなく
前半スピードで決まるので、末脚下位フラグがほぼ全馬に出て非識別では?

検証: 距離帯別に「末脚下位フラグ(spurt_index<=0.30)の発火率」と「フラグ該当馬 vs 非該当馬の
複勝率差(=識別力)」を出す。発火率が高すぎ(≒全馬)＋複勝率差が小さい距離帯では、そのフラグは
その距離帯で無意味=距離ゲートすべき。JRA平地2016-2025・リーク無し(spurt_indexは各レース時点
より前の走のみ)。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import elim_cross as ec

DB = jj.JV_DB_PATH
TH = ec.SLOW3F_TH  # 0.30


def dist_band(k):
    if k <= 1300:
        return '短距離(〜1300)'
    if k <= 1899:
        return 'マイル(1400-1899)'
    if k <= 2100:
        return '中距離(1900-2100)'
    return '長距離(2200〜)'


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, ra.kyori, ra.surface, ra.year "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(ra.year AS INT)>=2016 "
        "ORDER BY r.race_key").fetchall()
    con.close()

    # 馬の上がり順位比率履歴(spurt_indexプロキシ)を時系列で: kt -> [(rk, agari_rank_ratio)]
    by_race = defaultdict(list)
    for r in rows:
        by_race[r[0]].append(r)
    hist = defaultdict(list)
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    ar = con.execute("SELECT race_key, ketto_num, ato3f FROM results WHERE jyo<='10' AND chakujun>0").fetchall()
    con.close()
    a_by_race = defaultdict(list)
    for rk, kt, a3 in ar:
        if a3 and a3 > 0:
            a_by_race[rk].append((a3, kt))
    for rk, lst in a_by_race.items():
        lst.sort(key=lambda t: t[0])
        n = len(lst)
        for i, (_, kt) in enumerate(lst):
            hist[kt].append((rk, (i + 1) / n))
    for k in hist:
        hist[k].sort(key=lambda z: z[0])

    def spurt_before(kt, rk, n=5, minr=2):
        h = hist.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk][-n:]
        if len(past) < minr:
            return None
        return 1.0 - (sum(past) / len(past))   # 高いほど好末脚(spurt_index同型)

    # 距離帯別: フラグ発火/非発火の複勝(chakujun<=3)集計
    agg = defaultdict(lambda: {'n': 0, 'flag_n': 0, 'flag_t3': 0, 'noflag_n': 0, 'noflag_t3': 0})
    for r in rows:
        rk, kt, ch, nk, kyori, surf, yr = r
        if not kyori:
            continue
        si = spurt_before(kt, rk)
        if si is None:
            continue
        band = dist_band(kyori)
        d = agg[band]
        d['n'] += 1
        t3 = 1 if ch <= 3 else 0
        if si <= TH:
            d['flag_n'] += 1; d['flag_t3'] += t3
        else:
            d['noflag_n'] += 1; d['noflag_t3'] += t3

    print(f"末脚下位フラグ(spurt_index<={TH})の距離帯別・識別力(JRA平地2016-25)\n" + "=" * 68)
    print(f"{'距離帯':20s} {'発火率':>7s} {'該当複勝':>8s} {'非該当複勝':>10s} {'差(pp)':>8s}")
    for band in ['短距離(〜1300)', 'マイル(1400-1899)', '中距離(1900-2100)', '長距離(2200〜)']:
        d = agg.get(band)
        if not d or d['n'] < 100:
            continue
        fire = d['flag_n'] / d['n']
        fr = d['flag_t3'] / d['flag_n'] if d['flag_n'] else 0
        nr = d['noflag_t3'] / d['noflag_n'] if d['noflag_n'] else 0
        print(f"{band:20s} {fire:>6.1%} {fr:>8.1%} {nr:>9.1%} {(fr-nr)*100:>+7.1f}")
    print("\n[判定] 発火率が高い(≒全馬に出る)＋該当/非該当の複勝差が小さい(≈0)距離帯では、"
          "末脚下位フラグは非識別=その距離帯では消去に数えない(距離ゲート)のが妥当。"
          "差が明確にマイナス(該当馬が来にくい)なら、その距離帯ではフラグ有効。")


if __name__ == '__main__':
    main()
