# -*- coding: utf-8 -*-
"""3連複10点: 9頭から『どの馬を落とすか』で全体捕捉が上がるか。

加点ではない。C群（3着候補として弱い馬）を外して 8/7/6 頭にし、
残った箱を複勝率の積で10点にする。

評価 = 候補選定率 × 残し内10点 = 全体捕捉。
基準は「人気の薄い順に落とす」（＝人気1-Kを残す）の約41%。

A群: 人気1-2は落とさない
C群: 人気6-9だけから落とす（1-5は残す）＝本命の実験

Usage: python scripts/trio_prune_keep_backtest.py
"""
import os
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.axis_selector import fuku_rate
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd

POOL_K = 9
N_KEEP = (8, 7, 6)
N_POINTS = 10


def load_pays():
    con = sqlite3.connect(f'file:{JV_DB_PATH}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        "SELECT race_key, combo, payout FROM payouts "
        "WHERE bet_type='3連複' AND payout>0"
    ).fetchall()
    con.close()
    out = {}
    for rk, combo, p in rows:
        try:
            fs = frozenset(int(combo[i:i + 2]) for i in range(0, 6, 2))
            if len(fs) == 3:
                out[str(rk)] = (fs, float(p))
        except Exception:
            continue
    return out


def fuku_of(ninki, odds):
    v = fuku_rate(ninki, odds)
    if v is None:
        v = fuku_rate(ninki, None)
    return max(1.0, float(v or 8.0)) / 100.0


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def top10_hit(ums, fk, win):
    keep = set(ums)
    if not win <= keep:
        return False
    combos = list(combinations(ums, 3))
    if len(combos) <= N_POINTS:
        return True

    def prod(c):
        return fk[c[0]] * fk[c[1]] * fk[c[2]]

    top = {frozenset(c) for c in sorted(combos, key=prod, reverse=True)[:N_POINTS]}
    return win in top


def prune(horses, protect_max_ninki, n_keep, key_fn):
    """protect_max_ninki 以下は残す。残りから key が高い馬を残して n_keep 頭。"""
    prot = [h for h in horses if h['nk'] <= protect_max_ninki]
    rest = [h for h in horses if h['nk'] > protect_max_ninki]
    need = n_keep - len(prot)
    if need <= 0:
        return sorted(prot, key=lambda h: (h['nk'], h['u']))[:n_keep]
    rest_sorted = sorted(rest, key=key_fn, reverse=True)
    picked = rest_sorted[:max(0, need)]
    return prot + picked


def criteria():
    """高いほど残す。"""

    def pop(h):
        return (-h['nk'],)

    def fuku(h):
        return (h['fk'], -h['nk'])

    def ability(h):
        a = h['ab']
        return (-(a if a is not None else 9.0), -h['nk'])

    def vh(h):
        return (h['vh'], -h['nk'])

    def myomi(h):
        return (h['gap'], -h['nk'])

    def prev3(h):
        return (h['pt3'], -h['nk'])

    def drop_front(h):
        return (h['pos'], -h['nk'])

    def spurt(h):
        return (h['spurt'], -h['nk'])

    def drop67(h):
        return (0 if h['nk'] in (6, 7) else 1, -h['nk'])

    def mix(h):
        return (0.6 * h['vh'] + 0.4 * h['spurt'], -h['nk'])

    return [
        ('人気(薄を落)', pop),
        ('複勝率', fuku),
        ('能力', ability),
        ('穴VH', vh),
        ('妙味', myomi),
        ('前走3着', prev3),
        ('先行を落', drop_front),
        ('末脚', spurt),
        ('6-7を先落', drop67),
        ('複合VH末脚', mix),
    ]


CRITS = criteria()
CRIT_NAMES = [c[0] for c in CRITS]
FAMILIES = [
    ('A残し 1-2固定', 2),
    ('C群だけ削る 1-5固定', 5),
]


def add_race_feats(h):
    g = h.groupby('race_key', sort=False)
    h = h.copy()
    h['ab_rank'] = g['ability_score'].rank(method='min', ascending=True)
    h['vh_pct'] = g['vh2_score'].rank(method='min', ascending=True, pct=True)
    h['spurt_rk'] = g['spurt_idx'].rank(method='min', ascending=False)
    h['gap'] = ((h['ninki'] - h['ab_rank']).clip(lower=0.0) / 6.0).clip(upper=1.0)
    h['spurt_flag'] = ((h['spurt_rk'] <= 3) & (h['ninki'] >= 6)).astype(float)
    h['vh_pct'] = h['vh_pct'].fillna(0.0)
    h['gap'] = h['gap'].fillna(0.0)
    h['pt3'] = h['prior_top3_rate'].fillna(0.0)
    h['pos'] = h['pos_ratio3'].fillna(0.5)
    h['spurt_flag'] = h['spurt_flag'].fillna(0.0)
    return h


def horse_row(r):
    return {
        'u': int(r.umaban),
        'nk': int(r.ninki),
        'fk': fuku_of(r.ninki, r.win_odds),
        'ab': _num(r.ability_score),
        'vh': float(r.vh_pct) if r.vh_pct == r.vh_pct else 0.0,
        'gap': float(r.gap) if r.gap == r.gap else 0.0,
        'pt3': float(r.pt3) if r.pt3 == r.pt3 else 0.0,
        'pos': float(r.pos) if r.pos == r.pos else 0.5,
        'spurt': float(r.spurt_flag) if r.spurt_flag == r.spurt_flag else 0.0,
        'top3': int(r.top3) == 1,
    }


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'ability_score', 'top3',
        'vh2_score', 'spurt_idx', 'prior_top3_rate', 'pos_ratio3',
    ])
    h = add_race_feats(h)
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    # cell[(period, fam, crit, n_keep)] = [n_all, n_sel, n_hit, cost, ret]
    cell = defaultdict(lambda: [0, 0, 0, 0, 0])
    # 9頭そのまま
    base9 = defaultdict(lambda: [0, 0, 0, 0, 0])
    # ninki in winning trio
    in_win = defaultdict(lambda: [0, 0])  # n, in_top3
    third_nk = defaultdict(int)
    n_third = 0
    # ninki × 旗 → 3着内
    flag_cell = defaultdict(lambda: [0, 0])

    def bump_flag(nk, name, is_top3):
        a = flag_cell[(nk, name)]
        a[0] += 1
        a[1] += int(is_top3)

    for rk, g in h.groupby('race_key', sort=False):
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if not pay:
            try:
                pay = pays.get(int(rk))
            except (TypeError, ValueError):
                pay = None
        if not pay or pay[0] != win:
            continue
        payout = pay[1]
        period = str(g['period'].iloc[0])
        pool_g = g[g['ninki'] <= POOL_K]
        if len(pool_g) < 6:
            continue
        horses = [horse_row(r) for r in pool_g.itertuples(index=False)]
        fk = {x['u']: x['fk'] for x in horses}
        ums9 = [x['u'] for x in horses]
        nk_of = {x['u']: x['nk'] for x in horses}

        win_in_pool = win <= set(ums9)
        if period == 'holdout' and win_in_pool:
            third = max(win, key=lambda u: nk_of.get(u, 99))
            n_third += 1
            third_nk[nk_of[third]] += 1

        if period == 'holdout':
            for x in horses:
                nk = x['nk']
                if nk < 5:
                    continue
                in_win[nk][0] += 1
                in_win[nk][1] += int(x['top3'])
                bump_flag(nk, '全体', x['top3'])
                bump_flag(nk, 'VH高' if x['vh'] >= 0.5 else 'VH低', x['top3'])
                bump_flag(nk, '末脚あり' if x['spurt'] >= 1 else '末脚なし', x['top3'])
                bump_flag(nk, '妙味高' if x['gap'] >= 0.5 else '妙味低', x['top3'])

        hit9 = top10_hit(ums9, fk, win) if win_in_pool else False
        for per in (period, 'ALL'):
            b = base9[per]
            b[0] += 1
            b[1] += int(win_in_pool)
            b[2] += int(hit9)
            b[3] += N_POINTS * 100
            b[4] += payout if hit9 else 0.0

        for fam_name, protect in FAMILIES:
            for crit_name, key_fn in CRITS:
                for n_keep in N_KEEP:
                    picked = prune(horses, protect, n_keep, key_fn)
                    ums = [x['u'] for x in picked]
                    sel = win <= set(ums)
                    hit = top10_hit(ums, fk, win) if sel else False
                    for per in (period, 'ALL'):
                        c = cell[(per, fam_name, crit_name, n_keep)]
                        c[0] += 1
                        c[1] += int(sel)
                        c[2] += int(hit)
                        c[3] += N_POINTS * 100
                        c[4] += payout if hit else 0.0

    def pct(a, b):
        return a / b * 100 if b else 0.0

    def show_row(label, n_all, n_sel, n_hit, cost, ret):
        sel = pct(n_sel, n_all)
        cond = pct(n_hit, n_sel)
        overall = pct(n_hit, n_all)
        roi = (ret / cost * 100) if cost else 0.0
        mark = ''
        if '人気' in label:
            mark = ' ←基準'
        print(f'{label:<14}{sel:8.1f}%{cond:8.1f}%{overall:8.1f}%{roi:8.1f}%{mark}')

    def pr_period(period, title):
        print(f'\n=== {title} ===')
        b = base9[period]
        print(f'\n9頭のまま10点  {b[0]:,}R')
        print(f'{"削り方":<14}{"選定率":>9}{"残し内10点":>9}{"全体捕捉":>9}{"10点ROI":>9}')
        show_row('落とさない', *b)
        for fam_name, _protect in FAMILIES:
            print(f'\n-- {fam_name} → 8 / 7 / 6 頭 --')
            for n_keep in N_KEEP:
                print(f'\n  残 {n_keep} 頭')
                print(f'{"削り方":<14}{"選定率":>9}{"残し内10点":>9}{"全体捕捉":>9}{"10点ROI":>9}')
                for crit_name in CRIT_NAMES:
                    c = cell[(period, fam_name, crit_name, n_keep)]
                    show_row(crit_name, *c)

    pr_period('holdout', 'holdout ← 採用判定')
    pr_period('train', 'train 参考')

    print('\n=== holdout・9頭プール内 人気別の3着内率 ===')
    print(f'{"人気":>6}{"頭数":>8}{"3着内":>8}')
    for nk in range(5, 10):
        n, k = in_win[nk]
        print(f'{nk:6d}{n:8,d}{pct(k, n):7.1f}%')

    print('\n=== holdout・正解3着（組内で一番薄い馬）の人気 ===')
    tot = sum(third_nk.values()) or 1
    for nk in sorted(third_nk):
        print(f'  {nk}番人気: {third_nk[nk]:,}  ({third_nk[nk] / tot * 100:.1f}%)')

    print('\n=== holdout・人気6-9を旗で分けた3着内率（落とせるかの材料） ===')
    print(f'{"人気":>4}{"旗":<10}{"頭数":>8}{"3着内":>8}')
    for nk in (6, 7, 8, 9):
        for name in ('全体', 'VH高', 'VH低', '末脚あり', '末脚なし', '妙味高', '妙味低'):
            n, k = flag_cell[(nk, name)]
            if n == 0:
                continue
            print(f'{nk:4d}  {name:<8}{n:8,d}{pct(k, n):7.1f}%')

    print('\n主指標は全体捕捉。人気で8-9を落とす（＝1-7残し）を超えなければ不採用。')
    print('アプリは変更していない。')


if __name__ == '__main__':
    main()
