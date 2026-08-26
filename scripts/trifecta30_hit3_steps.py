# -*- coding: utf-8 -*-
"""3連単30点 Hit3 を ①→②→③ と1段ずつ足して測る(アプリ未変更)。

最優先KPI = Hit3: 的中3頭が順不同で30点のどれかに出る率。対象=3連単払戻≤7万。
厳密的中・ROIは次点(当てる表示が先、回収の最適化は後)。

① 1軸を全点に含める(どの着順でも)。UIの「1軸＝全点に入れる」と3連単を一致。
② 1着プール = 人気1〜3 ∪ 軸(最大4頭)。点数は2着3着側の優先で30に圧縮。
③ 2着プールから人気4〜5を落とさない(人気1〜5を2着に確保)。

1軸の代理:
  auto = その場の最人気(全頭なら1番人気 / 消去残しなら残しの最人気)
  in3  = 的中3頭のうち最人気(ユーザーが3着内の馬を軸にしたときの上限)

Usage: python scripts/trifecta30_hit3_steps.py
"""
import os
import sys
from collections import defaultdict
from itertools import permutations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import trio_engine as te
from core import value_scanner as vs
from scripts import csv_data as cd
from scripts.trifecta30_cover_backtest import (
    MIN_HORSES, PAY_HI, STAKE, DAY0, SHUBETSU_SKIP,
    _i, _f, load_trifecta_payouts, build_horses, ninki_axis, elim_keep,
    period_of, eval_result,
)

N_POINTS = 30


def pay_band(pay):
    if pay <= 30000:
        return '0-3万'
    if pay <= 70000:
        return '3-7万'
    return '7万超'


def pops_upto(horses, k):
    by_pop = sorted([h for h in horses if h.get('pop')], key=lambda h: (h['pop'], h['umaban']))
    return [h['umaban'] for h in by_pop if h['pop'] <= k]


def pick_axis(horses, win, kind):
    """kind=auto: 最人気 / in3: 的中3頭のうち最人気。いなければ None。"""
    by_pop = sorted([h for h in horses if h.get('pop')], key=lambda h: (h['pop'], h['umaban']))
    if not by_pop:
        return None
    if kind == 'auto':
        return by_pop[0]['umaban']
    win_set = set(win)
    in3 = [h for h in by_pop if h['umaban'] in win_set]
    return in3[0]['umaban'] if in3 else None


def _fill(pool, source, limit):
    for h in source:
        if len(pool) >= limit:
            break
        u = h['umaban'] if isinstance(h, dict) else h
        if u not in pool:
            pool.append(u)
    return pool


def recommend_step(horses, ap, axis_one=None, first_ninki=0, second_ninki=0,
                   require_axis=False):
    """本番 recommend_trifecta と同じ採点。プールの種だけフラグで変える。"""
    horses = [h for h in horses if h.get('umaban')]
    by = {h['umaban']: h for h in horses}
    if len(by) < 3:
        return {'bets': [], 'meta': {}, 'warning': 'head'}
    lo, hi = te._TRIFECTA_BAND
    ranked = sorted(by.values(), key=lambda h: -(h.get('score') or 0))
    pop_th, ana_lo, ana_hi = 4, 6, 12
    pop_set = {h['umaban'] for h in horses if h.get('pop') and h['pop'] <= pop_th}
    ana_set = {h['umaban'] for h in horses if h.get('pop') and ana_lo <= h['pop'] <= ana_hi}
    oo = ninki_axis(horses, 2)  # ◎〇代理(人気1・2)
    axis_one = axis_one if axis_one in by else None

    band_name = None
    put_ana_head = False
    n_first, n_second, n_third = 3, 5, 9
    _bf = te.formation_for_arare(ap)
    if _bf is not None:
        band_name, (n_first, n_second, n_third, _sugg, put_ana_head) = _bf

    seed_first = pops_upto(horses, first_ninki) if first_ninki else list(oo[:2])
    if axis_one and (require_axis or first_ninki) and axis_one not in seed_first:
        seed_first = list(seed_first) + [axis_one]
    n_first = max(n_first, len(seed_first))
    if first_ninki:
        n_first = min(max(n_first, 3), 4)  # 1着は3頭(+軸で最大4)
        n_first = max(n_first, len(seed_first[:4]))
        seed_first = seed_first[:4]

    def _combo_lvl(u):
        m = te._COMBO_RE.search(str(by[u].get('alert', '') or ''))
        return int(m.group(1)) if m else 0

    def _has_sig(u):
        al = str(by[u].get('alert', '') or '')
        return any(s in al for s in te._VAL_SIGS)

    first = _fill(list(seed_first), ranked, n_first)
    if require_axis and axis_one and axis_one not in first:
        first.append(axis_one)
    if put_ana_head:
        for u in sorted(ana_set, key=lambda u: -_combo_lvl(u))[:1]:
            if u not in first:
                first.append(u)

    himo_ranked = sorted(by.values(),
                         key=lambda h: (-(_combo_lvl(h['umaban']) if h['umaban'] in ana_set else 0),
                                        -(1 if (h['umaban'] in ana_set and _has_sig(h['umaban'])) else 0),
                                        -(h.get('score') or 0)))
    seed_second = list(first)
    if second_ninki:
        for u in pops_upto(horses, second_ninki):
            if u not in seed_second:
                seed_second.append(u)
        n_second = max(n_second, len(seed_second), 5)
    second = _fill(list(seed_second), himo_ranked, n_second)
    if require_axis and axis_one and axis_one not in second:
        second.append(axis_one)

    n_third = max(n_third, len(second))
    third = _fill(list(second), himo_ranked, n_third)
    if require_axis and axis_one and axis_one not in third:
        third.append(axis_one)

    # 採点軸: ①なら1軸を◎扱い。それ以外は人気1・2。
    if require_axis and axis_one:
        axis = [axis_one] + [u for u in oo if u != axis_one]
    else:
        axis = list(oo)

    scored = []
    for a in first:
        for b in second:
            if b == a:
                continue
            for c in third:
                if c in (a, b):
                    continue
                base = ((by[a].get('score') or 0) * 1.0 +
                        (by[b].get('score') or 0) * 0.8 +
                        (by[c].get('score') or 0) * 0.6)
                bonus = 0.0
                if axis:
                    if a == axis[0]:
                        bonus += 8.0
                    elif a in axis:
                        bonus += 4.0
                    if b in axis and b != a:
                        bonus += 3.0
                if c in ana_set:
                    if _has_sig(c):
                        bonus += 8.0
                    lv = _combo_lvl(c)
                    if lv >= 3:
                        bonus += 14.0
                    elif lv == 2:
                        bonus += 10.0
                scored.append({'combo': (a, b, c), 'score': round(base + bonus, 1),
                               'odds': None, 'in_band': False, 'names': ('', '', ''),
                               'pop_ana': (0, 0)})
    scored.sort(key=lambda x: -x['score'])
    if require_axis and axis_one:
        scored = [x for x in scored if axis_one in x['combo']]
    bets = scored[:N_POINTS]
    return {'bets': bets,
            'meta': {'n_points': len(bets), 'first': first, 'second': second,
                     'third': third, 'axis': axis, 'band_name': band_name,
                     'require_axis_all': require_axis},
            'warning': None}


# (id, require, first_ninki, second_ninki, need_axis)
# need_axis: None=使わない / 'auto' / 'in3'
STEPS = [
    ('現行', False, 0, 0, None),
    ('+①', True, 0, 0, 'auto'),
    ('+①②', True, 3, 0, 'auto'),
    ('+①②③', True, 3, 5, 'auto'),
    ('②のみ', False, 3, 0, None),
    ('③のみ', False, 0, 5, None),
    ('②③', False, 3, 5, None),
    ('+①in3', True, 0, 0, 'in3'),
    ('+①②③in3', True, 3, 5, 'in3'),
]


class Agg:
    def __init__(self):
        self.n = 0
        self.hit3 = 0
        self.exact = 0
        self.pool = 0
        self.cost = 0.0
        self.ret = 0.0
        self.pts = 0
        self.ax_in = 0
        self.ax_miss_hit3 = 0  # 1軸が3着内にいないのにHit3(①では0のはず)

    def add(self, ev, pay, axis_in_win):
        self.n += 1
        self.hit3 += int(ev['any_order'])
        self.exact += int(ev['exact'])
        self.pool += int(ev['pool_any'])
        n_pts = ev['n'] or N_POINTS
        self.pts += n_pts
        self.cost += n_pts * STAKE
        if ev['exact']:
            self.ret += pay
        if axis_in_win:
            self.ax_in += 1
        if not axis_in_win and ev['any_order']:
            self.ax_miss_hit3 += 1


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def roi(ret, cost):
    return 100.0 * ret / cost if cost else 0.0


def print_table(title, rows):
    print(f'\n=== {title} ===')
    print(f"{'方式':<12} {'R':>5} {'Hit3%':>8} {'厳密%':>7} {'プール%':>8} "
          f"{'点/R':>6} {'回収%':>7} {'1軸が3着内':>10}")
    for name, a in rows:
        if a.n == 0:
            continue
        ax = f"{pct(a.ax_in, a.n):.0f}%" if a.n else '-'
        print(f"{name:<12} {a.n:5d} {pct(a.hit3, a.n):7.1f}% {pct(a.exact, a.n):6.1f}% "
              f"{pct(a.pool, a.n):7.1f}% {a.pts / a.n:6.1f} {roi(a.ret, a.cost):6.1f}% {ax:>10}")


def main():
    print('Hit3 ①→②→③ 一段ずつ (エンジン未変更)', flush=True)
    print(f'  最優先=Hit3(順不同で30点に的中3頭) / ≤{PAY_HI:.0f}円 / 1点={STAKE:.0f}円',
          flush=True)
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

    # cells[uni][band][step] 
    cells = defaultdict(lambda: defaultdict(lambda: {s[0]: Agg() for s in STEPS}))
    n_done = 0
    n_skip = defaultdict(int)

    for rk, g in h.groupby('race_key', sort=False):
        rk = str(rk)
        if rk not in payout:
            n_skip['no_pay'] += 1
            continue
        jyo = int(g['jyo'].iloc[0])
        if not (1 <= jyo <= 10):
            n_skip['nar'] += 1
            continue
        if str(shu_map.get(rk, '') or '') in SHUBETSU_SKIP:
            n_skip['jump'] += 1
            continue
        if len(g) < MIN_HORSES:
            n_skip['field'] += 1
            continue
        if period_of(int(g['day'].iloc[0])) is None:
            n_skip['year'] += 1
            continue
        rows = g.to_dict('records')
        win, pay = payout[rk]
        umas = {_i(r['umaban']) for r in rows}
        if any(u not in umas for u in win):
            n_skip['win_miss'] += 1
            continue
        odds_list = [o for o in (_f(r.get('win_odds')) for r in rows) if o and o > 0]
        if len(odds_list) < 3:
            n_skip['odds'] += 1
            continue
        kigo = kigo_map.get(rk, '')
        is_handi = bool(handi_map.get(rk, _i(g['is_handi1'].iloc[0])))
        ap = vs.arare_prob(odds_list, {'is_handicap': is_handi, 'kigo': kigo or ''},
                           len(rows))
        horses_all = build_horses(rows)
        if len(horses_all) < 3:
            continue
        keep = elim_keep(rows, kigo, is_handi)
        horses_elim = [x for x in horses_all if x['umaban'] in keep]
        elim_ok = len(horses_elim) >= 3 and all(u in keep for u in win)
        pb = pay_band(pay)
        bands = [pb, 'ALL']
        if pay <= PAY_HI:
            bands.append('le70k')

        universes = [('full', horses_all, True)]
        if elim_ok:
            universes.append(('elim', horses_elim, True))
        else:
            universes.append(('elim_drop', horses_elim, False))

        for uni, hs, ok3 in universes:
            if not ok3 or len(hs) < 3:
                continue
            ax_auto = pick_axis(hs, win, 'auto')
            ax_in3 = pick_axis(hs, win, 'in3')
            for name, req, fn, sn, akind in STEPS:
                if name == '現行':
                    res = te.recommend_trifecta(
                        hs, axis_umaban=ninki_axis(hs, 2), n_points=N_POINTS,
                        arare_prob=ap)
                    ax_used = ax_auto
                else:
                    ax_used = None
                    if akind == 'auto':
                        ax_used = ax_auto
                    elif akind == 'in3':
                        ax_used = ax_in3
                        if ax_used is None:
                            continue
                    res = recommend_step(
                        hs, ap, axis_one=ax_used, first_ninki=fn,
                        second_ninki=sn, require_axis=req)
                ev = eval_result(res, win)
                ax_in = bool(ax_used and ax_used in win)
                for b in bands:
                    cells[uni][b][name].add(ev, pay, ax_in)

        n_done += 1
        if n_done % 500 == 0:
            print(f'  ... {n_done}R', flush=True)

    print(f'\n走査 {n_done}R  skip={dict(n_skip)}')
    print('\n--- 読み方 ---')
    print('Hit3% = 30点のどれかに的中3頭が順不同で出る(今回の最上位指標)。')
    print('厳密% = 着順どおり1点が入る。回収% = その払戻÷投資。Hit3では払わない。')
    print('①auto = 1軸をその場の最人気にする(ユーザーが本命を軸にした想定)。')
    print('①in3  = 1軸を的中3頭のうち最人気にする(軸が3着内にいたときの上限)。')
    print('② = 1着候補を人気1〜3(+軸)。③ = 2着から人気4〜5を落とさない。')
    print('full=出走全頭 / elim=消去で的中3頭が残ったレースだけ。')

    order = [s[0] for s in STEPS]

    def dump(uni, band, title):
        rows = [(nm, cells[uni][band][nm]) for nm in order]
        print_table(title, rows)

    dump('full', 'le70k', '【主表】Hit3  ≤7万・全頭')
    dump('elim', 'le70k', '【主表】Hit3  ≤7万・消去で3頭残')
    dump('full', '0-3万', '≤7万の内訳  0〜3万・全頭')
    dump('full', '3-7万', '≤7万の内訳  3〜7万・全頭')
    dump('elim', '0-3万', '0〜3万・消去3頭残')
    dump('elim', '3-7万', '3〜7万・消去3頭残')
    dump('full', '7万超', '【対照】7万超・全頭 ※ここを壊さないかが次点')
    dump('elim', '7万超', '7万超・消去3頭残')

    print('\n【一段の寄与】≤7万・全頭  Hit3差(現行比)')
    base = cells['full']['le70k']['現行']
    for nm in order:
        a = cells['full']['le70k'][nm]
        if a.n == 0 or nm == '現行':
            continue
        print(f'  {nm:<12} Hit3 {pct(base.hit3, base.n):.1f}% → {pct(a.hit3, a.n):.1f}% '
              f"({a.hit3 - base.hit3:+d}R)  厳密 {pct(base.exact, base.n):.1f}% → {pct(a.exact, a.n):.1f}%  "
              f"回収 {roi(base.ret, base.cost):.1f}% → {roi(a.ret, a.cost):.1f}%")

    print('\n【一段の寄与】≤7万・消去3頭残')
    base = cells['elim']['le70k']['現行']
    for nm in order:
        a = cells['elim']['le70k'][nm]
        if a.n == 0 or nm == '現行':
            continue
        print(f'  {nm:<12} Hit3 {pct(base.hit3, base.n):.1f}% → {pct(a.hit3, a.n):.1f}% '
              f"({a.hit3 - base.hit3:+d}R)  厳密 {pct(base.exact, base.n):.1f}% → {pct(a.exact, a.n):.1f}%  "
              f"回収 {roi(base.ret, base.cost):.1f}% → {roi(a.ret, a.cost):.1f}%")

    print('\nまだアプリには入れていません。Hit3が目的なら②③が本丸、①は「軸が3着内のとき」専用。')


if __name__ == '__main__':
    main()
