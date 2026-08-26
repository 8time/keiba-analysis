# -*- coding: utf-8 -*-
"""堅帯30点を『同一3頭セット』にまとめ、着順の残し数を変える。

点の上下を切らない。30点に出た3頭組は残し、組の中の着順だけ
6 / 4 / 3 / 2 / 1 通りに制限する。
残す着順はエンジンのスコアが高いものから。

Usage: python scripts/trifecta_tight_perm_cap.py
"""
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import trio_engine as te
from core import value_scanner as vs
from scripts import csv_data as cd
from scripts.trifecta30_cover_backtest import (
    MIN_HORSES, PAY_HI, STAKE, DAY0, SHUBETSU_SKIP,
    _i, _f, load_trifecta_payouts, build_horses, ninki_axis, elim_keep,
    period_of,
)

KS = (6, 4, 3, 2, 1)  # 同一3頭あたりの着順の上限。6=実質30点のまま


def group_bets(bets):
    g = defaultdict(list)
    for b in bets:
        g[frozenset(b['combo'])].append(b)
    for fs in g:
        g[fs].sort(key=lambda x: -float(x.get('score') or 0))
    return g


def take_cap(groups, k):
    out = []
    for fs, rows in groups.items():
        out.extend(rows[:k])
    return out


def has_hit3(bets, win):
    w = frozenset(win)
    return any(frozenset(b['combo']) == w for b in bets)


def has_exact(bets, win):
    return any(tuple(b['combo']) == win for b in bets)


class Agg:
    def __init__(self):
        self.n = 0
        self.hit3 = 0
        self.exact = 0
        self.pts = 0
        self.cost = 0.0
        self.ret = 0.0

    def add(self, h3, ex, npts, pay):
        self.n += 1
        self.hit3 += int(h3)
        self.exact += int(ex)
        self.pts += npts
        self.cost += npts * STAKE
        if ex:
            self.ret += pay


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def roi(ret, cost):
    return 100.0 * ret / cost if cost else 0.0


def print_tbl(title, by_k):
    print(f'\n=== {title} ===')
    print(f"{'着順/組':>6} {'R':>5} {'点/R':>6} {'Hit3%':>8} {'厳密%':>7} "
          f"{'回収%':>7} {'損益':>10} {'30点比点':>8}")
    a6 = by_k[6]
    p30 = a6.pts / a6.n if a6.n else 30.0
    for k in KS:
        a = by_k[k]
        if a.n == 0:
            continue
        pr = a.pts / a.n
        print(f"{k:6d} {a.n:5d} {pr:6.1f} {pct(a.hit3, a.n):7.1f}% "
              f"{pct(a.exact, a.n):6.1f}% {roi(a.ret, a.cost):6.1f}% "
              f"{a.ret - a.cost:10.0f} {100.0 * pr / p30:6.1f}%")


def main():
    print('堅帯30点: 同一3頭の着順を畳む (本番未変更)', flush=True)
    payout = load_trifecta_payouts()
    cols = [
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ]
    h = cd.load_horses(cols=cols)
    h = h[h['day'] >= DAY0]
    h['jyo'] = h['jyo'].astype(float)
    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'shubetsu'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))
    shu_map = dict(zip(races['race_key'].astype(str),
                       races['shubetsu'].fillna('').astype(str)))

    cells = defaultdict(lambda: defaultdict(lambda: {k: Agg() for k in KS}))
    n_sets = []          # unique 3-sets per race
    perms_per_set = []   # size of each group
    exact_rank_in_set = []  # 1-indexed rank of winning order inside its group
    n_tight = 0
    n_h3_but_exact_not_in_30 = 0

    for rk, g in h.groupby('race_key', sort=False):
        rk = str(rk)
        if rk not in payout or len(g) < MIN_HORSES:
            continue
        if not (1 <= int(g['jyo'].iloc[0]) <= 10):
            continue
        if str(shu_map.get(rk, '') or '') in SHUBETSU_SKIP:
            continue
        per = period_of(int(g['day'].iloc[0]))
        if per is None:
            continue
        rows = g.to_dict('records')
        win, pay = payout[rk]
        umas = {_i(r['umaban']) for r in rows}
        if any(u not in umas for u in win):
            continue
        odds_list = [o for o in (_f(r.get('win_odds')) for r in rows) if o and o > 0]
        if len(odds_list) < 3:
            continue
        kigo = kigo_map.get(rk, '')
        is_handi = bool(handi_map.get(rk, _i(g['is_handi1'].iloc[0])))
        ap = vs.arare_prob(odds_list, {'is_handicap': is_handi, 'kigo': kigo or ''},
                           len(rows))
        bf = te.formation_for_arare(ap)
        if bf is None or bf[0] != 'tight':
            continue
        horses = build_horses(rows)
        if len(horses) < 3:
            continue
        res = te.recommend_trifecta(
            horses, axis_umaban=ninki_axis(horses, 2), n_points=30, arare_prob=ap)
        bets = list(res.get('bets') or [])
        if not bets:
            continue
        n_tight += 1
        groups = group_bets(bets)
        n_sets.append(len(groups))
        for rows_g in groups.values():
            perms_per_set.append(len(rows_g))

        win_fs = frozenset(win)
        if win_fs in groups:
            g_rows = groups[win_fs]
            found = None
            for i, b in enumerate(g_rows, 1):
                if tuple(b['combo']) == win:
                    found = i
                    break
            if found:
                exact_rank_in_set.append(found)
            else:
                n_h3_but_exact_not_in_30 += 1
                exact_rank_in_set.append(None)  # Hit3だが着順はその30に無い

        sls = ['ALL', per]
        if pay <= PAY_HI:
            sls += ['le70k', f'{per}|le70k']
        else:
            sls.append('gt70k')

        keep = elim_keep(rows, kigo, is_handi)
        horses_elim = [x for x in horses if x['umaban'] in keep]
        elim_ok = len(horses_elim) >= 3 and all(u in keep for u in win)
        elim_groups = None
        if elim_ok:
            r2 = te.recommend_trifecta(
                horses_elim, axis_umaban=ninki_axis(horses_elim, 2),
                n_points=30, arare_prob=ap)
            elim_groups = group_bets(list(r2.get('bets') or []))

        for k in KS:
            kept = take_cap(groups, k)
            h3 = has_hit3(kept, win)
            ex = has_exact(kept, win)
            for sl in sls:
                cells['full'][sl][k].add(h3, ex, len(kept), pay)
            if elim_groups is not None:
                kept_e = take_cap(elim_groups, k)
                h3e = has_hit3(kept_e, win)
                exe = has_exact(kept_e, win)
                for sl in sls:
                    cells['elim'][sl][k].add(h3e, exe, len(kept_e), pay)

        if n_tight % 400 == 0:
            print(f'  ... 堅帯 {n_tight}R', flush=True)

    print(f'\n堅帯 {n_tight}R')
    if n_sets:
        print(f'  30点の中のユニーク3頭組: 平均 {sum(n_sets)/len(n_sets):.1f} '
              f'/ 中央 {sorted(n_sets)[len(n_sets)//2]} '
              f'/ min {min(n_sets)} max {max(n_sets)}')
    if perms_per_set:
        from collections import Counter
        c = Counter(perms_per_set)
        print('  1組あたりの着順数(30点内): ' +
              ' '.join(f'{n}通り×{c[n]}組' for n in sorted(c)))
        print(f'  平均 {sum(perms_per_set)/len(perms_per_set):.2f} 通り/組')

    print_tbl('堅帯・全頭・2025+2026', cells['full']['ALL'])
    print_tbl('堅帯・2025 holdout', cells['full']['2025'])
    print_tbl('堅帯・≤7万', cells['full']['le70k'])
    print_tbl('堅帯・7万超', cells['full']['gt70k'])
    print_tbl('堅帯・消去3頭残・全頭', cells['elim']['ALL'])
    print_tbl('堅帯・消去3頭残・≤7万', cells['elim']['le70k'])

    print('\n=== 的中3頭が30点に出たとき、正解の着順は組の何位か ===')
    in_set = [x for x in exact_rank_in_set if x is not None]
    h3_n = len(exact_rank_in_set)
    print(f'  Hit3レース {h3_n} / うち着順も30点内 {len(in_set)} '
          f'/ 組はあるが着順なし {n_h3_but_exact_not_in_30}')
    if in_set:
        for k in KS:
            ok = sum(1 for r in in_set if r <= k)
            # Hit3母数で厳密率(着順が組の上位kに入る)
            print(f'  組内スコア上位{k}通りに正解着順: {ok}/{h3_n} '
                  f'= Hit3レースの {pct(ok, h3_n):.1f}% '
                  f'(着順ありの {pct(ok, len(in_set)):.1f}%)')

    a6 = cells['full']['ALL'][6]
    print('\n【判定】堅帯・全頭 着順6通り(≈30点) vs 畳み')
    for k in KS:
        a = cells['full']['ALL'][k]
        print(f'  {k}通り/組  点 {a.pts/a.n:.1f}  Hit3 {pct(a.hit3, a.n):.1f}%  '
              f'厳密 {pct(a.exact, a.n):.1f}%  回収 {roi(a.ret, a.cost):.1f}%')
    print('  まだ買い目は変えていません。')


if __name__ == '__main__':
    main()
