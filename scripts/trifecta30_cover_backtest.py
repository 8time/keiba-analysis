# -*- coding: utf-8 -*-
"""3連単おすすめエンジン 30点の『表示カバー』測定(アプリは未変更)。

目標(ユーザー): 30点を出したとき、的中3頭が順不同でも表示に出ること。
対象帯: 3連単払戻 0〜70,000円(普通の難易度)。

比較:
  現行     … recommend_trifecta そのまま(堅帯は1着2頭=軸◎〇)
  堅帯3頭  … 堅帯の1着枠だけ 2→3(3枠目はスコア順。人気3番とは限らない)
  人気1-3  … 1着候補の先頭を人気1・2・3で埋める(堅帯も n_first=3)

軸の代理: 人気1・2番=ライブの◎〇。スコア代理: -ability_score(CSVは小さいほど強い)。
オッズマップなし(未取得時のエンジンと同じ採点)。ライブLTR/軸セレクタとはずれる。

Usage: python scripts/trifecta30_cover_backtest.py
"""
import inspect
import os
import sqlite3
import sys
from collections import defaultdict
from itertools import permutations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from core import trio_engine as te
from core import value_scanner as vs
from scripts import csv_data as cd
from scripts import elim_cross_keep_top3_2026h1 as elim

MIN_HORSES = 8
PAY_HI = 70000.0
STAKE = 100.0
DAY0 = 20250101   # holdout2025 + CSV内の2026
SHUBETSU_SKIP = {'18', '19'}  # 障害


def _i(v, d=0):
    try:
        f = float(v)
        return d if f != f else int(f)
    except (TypeError, ValueError):
        return d


def _f(v):
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def load_trifecta_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit() and pay and float(pay) > 0:
            out[str(rk)] = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
    con.close()
    return out


def make_axis_head_fn(head):
    """recommend_trifecta の axis[:2] だけ head に差し替えた複製。本番関数は触らない。"""
    src = inspect.getsource(te.recommend_trifecta)
    if 'list(axis[:2])' not in src:
        raise RuntimeError('trio_engine.recommend_trifecta の axis[:2] が見つからない')
    src = src.replace('def recommend_trifecta(', f'def rec_head{head}(', 1)
    src = src.replace('list(axis[:2])', f'list(axis[:{head}])', 1)
    ns = {}
    exec(compile(src, f'<trifecta_head{head}>', 'exec'), te.__dict__, ns)
    return ns[f'rec_head{head}']


REC_HEAD3 = make_axis_head_fn(3)


def build_horses(rows):
    hs = []
    for r in rows:
        u = _i(r.get('umaban'))
        if not u:
            continue
        ab = _f(r.get('ability_score'))
        pop = _i(r.get('ninki'))
        combo = _i(r.get('combo'))
        score = (-ab if ab is not None else (-pop if pop else 0.0))
        alert = f'🧩{combo}重複' if combo >= 2 else ''
        hs.append({'umaban': u, 'name': str(u), 'score': score, 'pop': pop or None,
                   'alert': alert})
    return hs


def ninki_axis(horses, k=2):
    by_pop = sorted([h for h in horses if h.get('pop')], key=lambda h: h['pop'])
    return [h['umaban'] for h in by_pop[:k]]


def call_engine(horses, ap, mode):
    """mode: current / tight3 / ninki13"""
    saved = te._BAND_FORMATION['tight']
    ax2 = ninki_axis(horses, 2)
    ax3 = ninki_axis(horses, 3)
    try:
        if mode == 'current':
            return te.recommend_trifecta(
                horses, axis_umaban=ax2, n_points=30, arare_prob=ap)
        if mode == 'tight3':
            n1, n2, n3, ns, pah = saved
            te._BAND_FORMATION['tight'] = (3, n2, n3, ns, pah)
            return te.recommend_trifecta(
                horses, axis_umaban=ax2, n_points=30, arare_prob=ap)
        if mode == 'ninki13':
            n1, n2, n3, ns, pah = saved
            te._BAND_FORMATION['tight'] = (3, n2, n3, ns, pah)
            return REC_HEAD3(
                horses, axis_umaban=ax3, n_points=30, arare_prob=ap)
        raise ValueError(mode)
    finally:
        te._BAND_FORMATION['tight'] = saved


def eval_result(res, win):
    bets = res.get('bets') or []
    meta = res.get('meta') or {}
    first = list(meta.get('first') or [])
    second = list(meta.get('second') or [])
    third = list(meta.get('third') or [])
    combos = [tuple(b['combo']) for b in bets]
    win_set = frozenset(win)
    exact = win in combos
    any_order = any(frozenset(c) == win_set for c in combos)
    pool_any = False
    for a, b, c in permutations(win, 3):
        if a in first and b in second and c in third:
            pool_any = True
            break
    return {
        'n': len(bets),
        'exact': exact,
        'any_order': any_order,
        'pool_any': pool_any,
        'win1_in_first': win[0] in first,
        'band': meta.get('band_name') or 'none',
        'first': first,
    }


def elim_keep(rows, kigo, is_handi):
    flags, ninki = elim.flag_counts(rows)
    elite_top3, scored = elim.hunter_elite_top3(rows)
    rk_edf, surv = elim.edf_rank_and_surv(rows, border=3)
    elim.add_rklow_vh(flags, len(rows), rk_edf, scored)
    order = sorted(flags, key=lambda u: (-flags[u], -ninki.get(u, 0)))
    tgt, _band = elim.recommend_n(rows, kigo, is_handi)
    keep, _keep0, _add = elim.apply_flow(order, tgt, rows, elite_top3, pool=surv)
    return keep


def period_of(day):
    y = day // 10000
    if y == 2025:
        return '2025'
    if y == 2026:
        return '2026'
    return None


def pay_slice(pay):
    if pay <= PAY_HI:
        return 'le70k'
    return 'gt70k'


class Agg:
    def __init__(self):
        self.n = 0
        self.exact = 0
        self.any_order = 0
        self.pool_any = 0
        self.win1_first = 0
        self.cost = 0.0
        self.ret = 0.0
        self.pts = 0
        self.elim_drop = 0

    def add(self, ev, n_pts, hit_pay):
        self.n += 1
        self.exact += int(ev['exact'])
        self.any_order += int(ev['any_order'])
        self.pool_any += int(ev['pool_any'])
        self.win1_first += int(ev['win1_in_first'])
        self.pts += n_pts
        self.cost += n_pts * STAKE
        if ev['exact']:
            self.ret += hit_pay


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def roi(ret, cost):
    return 100.0 * ret / cost if cost else 0.0


def print_block(title, cells, modes):
    print(f'\n=== {title} ===')
    hdr = f"{'セル':<22} {'方式':<8} {'R':>5} {'順不同%':>8} {'厳密%':>7} {'プール%':>8} {'1着枠%':>7} {'点/R':>6} {'回収%':>7} {'損益':>10}"
    print(hdr)
    for key in cells:
        aggs = cells[key]
        if not any(aggs[m].n for m in modes):
            continue
        for m in modes:
            a = aggs[m]
            if a.n == 0:
                continue
            tag = key
            print(f"{tag:<22} {m:<8} {a.n:5d} {pct(a.any_order, a.n):7.1f}% "
                  f"{pct(a.exact, a.n):6.1f}% {pct(a.pool_any, a.n):7.1f}% "
                  f"{pct(a.win1_first, a.n):6.1f}% {a.pts / a.n:6.1f} "
                  f"{roi(a.ret, a.cost):6.1f}% {a.ret - a.cost:10.0f}")
            tag = ''


def main():
    print('3連単30点 表示カバー測定 (エンジン未変更)', flush=True)
    print(f'  主指標=順不同で30点に的中3頭が出るか / 対象払戻≤{PAY_HI:.0f}円 / 1点={STAKE:.0f}円',
          flush=True)
    payout = load_trifecta_payouts()
    print(f'  3連単払戻 {len(payout):,}R', flush=True)

    cols = [
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ]
    h = cd.load_horses(cols=cols)
    h = h[h['day'] >= DAY0]
    h['jyo'] = h['jyo'].astype(float)
    print(f'  馬行 {len(h):,} / レース {h["race_key"].nunique():,}', flush=True)

    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'shubetsu', 'field_size'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))
    shu_map = dict(zip(races['race_key'].astype(str),
                       races['shubetsu'].fillna('').astype(str)))

    modes = ('current', 'tight3', 'ninki13')
    # cells: universe|period|slice|band
    cells = defaultdict(lambda: {m: Agg() for m in modes})
    win1_ninki_le70 = defaultdict(int)
    miss_why = defaultdict(int)
    n_skip = defaultdict(int)

    n_done = 0
    for rk, g in h.groupby('race_key', sort=False):
        rk = str(rk)
        if rk not in payout:
            n_skip['no_pay'] += 1
            continue
        jyo = int(g['jyo'].iloc[0])
        if not (1 <= jyo <= 10):
            n_skip['nar'] += 1
            continue
        shu = str(shu_map.get(rk, '') or '')
        if shu in SHUBETSU_SKIP:
            n_skip['jump'] += 1
            continue
        if len(g) < MIN_HORSES:
            n_skip['field'] += 1
            continue
        day = int(g['day'].iloc[0])
        per = period_of(day)
        if per is None:
            n_skip['year'] += 1
            continue
        rows = g.to_dict('records')
        win, pay = payout[rk]
        umas = {_i(r['umaban']) for r in rows}
        if any(u not in umas for u in win):
            n_skip['win_miss'] += 1
            continue
        odds_list = [_f(r.get('win_odds')) for r in rows]
        odds_list = [o for o in odds_list if o and o > 0]
        if len(odds_list) < 3:
            n_skip['odds'] += 1
            continue
        kigo = kigo_map.get(rk, '')
        is_handi = bool(handi_map.get(rk, _i(g['is_handi1'].iloc[0])))
        ap = vs.arare_prob(odds_list, {'is_handicap': is_handi, 'kigo': kigo or ''},
                           len(rows))
        horses_all = build_horses(rows)
        if len(horses_all) < 3:
            n_skip['h3'] += 1
            continue

        keep = elim_keep(rows, kigo, is_handi)
        horses_elim = [x for x in horses_all if x['umaban'] in keep]
        elim_ok = len(horses_elim) >= 3 and all(u in keep for u in win)

        sl = pay_slice(pay)
        ninki_of = {_i(r['umaban']): _i(r['ninki']) for r in rows}
        if sl == 'le70k':
            win1_ninki_le70[ninki_of.get(win[0], 0)] += 1

        universes = [('full', horses_all, True)]
        universes.append(('elim', horses_elim, elim_ok))

        for uni, hs, ok3 in universes:
            if not ok3:
                for mode in modes:
                    for key in (f'{uni}|{per}|{sl}|drop', f'{uni}|ALL|{sl}|drop'):
                        cells[key][mode].n += 1
                        cells[key][mode].elim_drop += 1
                continue
            if len(hs) < 3:
                n_skip['hs<3'] += 1
                continue
            for mode in modes:
                res = call_engine(hs, ap, mode)
                ev = eval_result(res, win)
                band = ev['band']
                n_pts = ev['n'] or 30
                for key in (
                    f'{uni}|{per}|{sl}|ALL',
                    f'{uni}|{per}|{sl}|{band}',
                    f'{uni}|ALL|{sl}|ALL',
                    f'{uni}|ALL|{sl}|{band}',
                    f'{uni}|ALL|ALL|ALL',
                ):
                    cells[key][mode].add(ev, n_pts, pay)
                if uni == 'full' and sl == 'le70k' and mode == 'current' and not ev['any_order']:
                    if not ev['win1_in_first']:
                        miss_why['1着が1着枠外'] += 1
                    elif not ev['pool_any']:
                        miss_why['3頭は揃うがフォーメーション外'] += 1
                    else:
                        miss_why['プールにはあるが30点外'] += 1
                    wn = ninki_of.get(win[0], 0)
                    miss_why[f'1着人気={wn}'] += 1

        n_done += 1
        if n_done % 500 == 0:
            print(f'  ... {n_done}R', flush=True)

    print(f'\n走査 {n_done}R  skip={dict(n_skip)}')

    print('\n--- 読み方 ---')
    print('順不同% = 30点のどれかに的中3頭が順不同で出る(表示目標)。3連単の払戻にはならない。')
    print('厳密%   = 着順どおりの1点が30点に入る(実際に3連単が当たる)。')
    print('プール% = 1着×2着×3着の枠を全部回せば順不同で作れる(点数cap前)。')
    print('1着枠%  = 勝った馬が1着候補に入っている。')
    print('回収%   = 厳密的中の払戻÷投資(1点100円)。順不同では払わない。')
    print('full=出走全頭 / elim=アプリ寄りの消去残し(📊→クロス→推奨頭数+復活)。')
    print('スコアはCSV ability_scoreの符号反転。ライブのLTR・◎〇セレクタとは別物。')

    print('\n【主表】払戻≤7万 / 全頭 / 2025+2026')
    print_block('full × ≤7万', {
        'full|ALL|le70k|ALL': cells['full|ALL|le70k|ALL'],
        'full|2025|le70k|ALL': cells['full|2025|le70k|ALL'],
        'full|2026|le70k|ALL': cells['full|2026|le70k|ALL'],
    }, modes)
    print_block('full × ≤7万 × 帯', {
        'full|ALL|le70k|tight': cells['full|ALL|le70k|tight'],
        'full|ALL|le70k|mid': cells['full|ALL|le70k|mid'],
        'full|ALL|le70k|arare': cells['full|ALL|le70k|arare'],
        'full|ALL|le70k|none': cells['full|ALL|le70k|none'],
    }, modes)

    print('\n【対照】払戻>7万 / 全頭')
    print_block('full × >7万', {
        'full|ALL|gt70k|ALL': cells['full|ALL|gt70k|ALL'],
    }, modes)

    print('\n【消去残し】払戻≤7万 (的中3頭が残ったレースだけ方式比較)')
    print_block('elim × ≤7万 (3頭残)', {
        'elim|ALL|le70k|ALL': cells['elim|ALL|le70k|ALL'],
        'elim|2025|le70k|ALL': cells['elim|2025|le70k|ALL'],
        'elim|2026|le70k|ALL': cells['elim|2026|le70k|ALL'],
    }, modes)
    ndrop = cells['elim|ALL|le70k|drop']['current'].n
    nkeep = cells['elim|ALL|le70k|ALL']['current'].n
    print(f'  消去で的中3頭が欠けた ≤7万: {ndrop}R '
          f'(残った {nkeep}R と合わせると欠落率 {pct(ndrop, ndrop + nkeep):.1f}%)')

    print('\n【全払戻】参考')
    print_block('full × 全払戻', {
        'full|ALL|ALL|ALL': cells['full|ALL|ALL|ALL'],
    }, modes)

    print('\n【≤7万】勝った馬の人気(全頭ユニバースの母数)')
    tot = sum(win1_ninki_le70.values())
    for k in sorted(win1_ninki_le70):
        print(f'  1着={k}番人気  {win1_ninki_le70[k]:5d}  {pct(win1_ninki_le70[k], tot):5.1f}%')
    n13 = sum(win1_ninki_le70[k] for k in (1, 2, 3))
    print(f'  1着が人気1-3合計  {n13}  {pct(n13, tot):.1f}%')

    print('\n【現行が見逃した ≤7万(全頭)】内訳')
    for k, v in sorted(miss_why.items(), key=lambda x: -x[1]):
        print(f'  {k}: {v}')

    cur = cells['full|ALL|le70k|ALL']['current']
    v13 = cells['full|ALL|le70k|ALL']['ninki13']
    print('\n【判定材料】≤7万・全頭・2025+2026')
    print(f'  順不同  現行 {pct(cur.any_order, cur.n):.1f}% → 人気1-3 {pct(v13.any_order, v13.n):.1f}% '
          f'({v13.any_order - cur.any_order:+d}R / {cur.n}R)')
    print(f'  厳密     現行 {pct(cur.exact, cur.n):.1f}% → 人気1-3 {pct(v13.exact, v13.n):.1f}%')
    print(f'  回収     現行 {roi(cur.ret, cur.cost):.1f}% → 人気1-3 {roi(v13.ret, v13.cost):.1f}%')
    print('  採用しない: 順不同が上がっても厳密/回収が明らかに壊れるとき。')
    print('  まだアプリには入れていません。')


if __name__ == '__main__':
    main()
