# -*- coding: utf-8 -*-
"""Cゾーン offline 検証: 現行比・同予算・holdout 優先。

- クロス少 (cross_n<3): 予算3000円（現行30点×100円）
- クロス多 (cross_n>=3): 予算700円（現行7点×100円）

Usage: python scripts/c_zone_offline_verify.py
"""
import io
import os
import sys
from dataclasses import dataclass

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.trio_engine import build_formation, build_trifecta_formation
from scripts import hitrate_common as hc

BUDGET_LOW = 3000   # 3連単30点セル
BUDGET_HIGH = 700   # 3連複7点セル
MAX_TRI_LOW = 30    # 30点超はクロス少セルでは除外
ROI_FLOOR = hc.ROI_FLOOR_DEFAULT


def is_elim_target(elim_n, ninki):
    if elim_n is None:
        return False
    try:
        elim_n, ninki = int(elim_n), int(ninki)
    except (TypeError, ValueError):
        return False
    return (elim_n >= 3 and ninki >= 6) or (elim_n >= 5 and ninki <= 5)


def swap_rank7(race):
    rank = list(race['rank_ord'])
    if len(rank) < 7:
        return rank
    last_idx, search_from = 6, 7
    u = rank[last_idx]
    if not is_elim_target(race['elim_map'].get(u), race['ninki_map'].get(u, 99)):
        return rank
    for j in range(search_from, min(len(rank), 10)):
        u2 = rank[j]
        if not is_elim_target(race['elim_map'].get(u2), race['ninki_map'].get(u2, 99)):
            rank[last_idx], rank[j] = rank[j], rank[last_idx]
            break
    return rank


def swap_rank6(race):
    rank = list(race['rank_ord'])
    if len(rank) < 6:
        return rank
    last_idx, search_from = 5, 6
    u = rank[last_idx]
    if not is_elim_target(race['elim_map'].get(u), race['ninki_map'].get(u, 99)):
        return rank
    for j in range(search_from, min(len(rank), 10)):
        u2 = rank[j]
        if not is_elim_target(race['elim_map'].get(u2), race['ninki_map'].get(u2, 99)):
            rank[last_idx], rank[j] = rank[j], rank[last_idx]
            break
    return rank


def make_tickets(kind, col1, col2, col3, shape):
    a, b, c = shape
    if len(col1) < a or len(col2) < b or len(col3) < c:
        return set()
    if kind == '3連単':
        return set(build_trifecta_formation(col1[:a], col2[:b], col3[:c]))
    return set(build_formation(col1[:a], col2[:b], col3[:c]))


def score_budget(tickets, kind, top3, payouts, budget):
    tc = len(tickets)
    if tc == 0:
        return None
    stake = budget / tc
    cost = budget
    hit = 0
    ret = 0.0
    if kind == '3連単':
        won = top3 in tickets
        key = top3
    else:
        key = tuple(sorted(top3))
        won = key in tickets
    if won:
        hit = 1
        for combo, pay in payouts or []:
            if combo == key:
                ret = pay * (stake / 100.0)
                break
    return dict(cost=cost, ret=ret, hit=hit, tc=tc, stake=stake)


def block_roi_diff(recs_a, recs_b):
    rng = np.random.default_rng(hc.BOOT_SEED)
    ca = np.array([r['cost'] for r in recs_a], dtype=np.float64)
    ra = np.array([r['ret'] for r in recs_a], dtype=np.float64)
    cb = np.array([r['cost'] for r in recs_b], dtype=np.float64)
    rb = np.array([r['ret'] for r in recs_b], dtype=np.float64)
    days = np.array([r['day'] for r in recs_a])
    uniq, inv = np.unique(days, return_inverse=True)
    blocks = [np.where(inv == i)[0] for i in range(len(uniq))]
    diffs = []
    for _ in range(hc.BOOT_N):
        picks = rng.integers(0, len(blocks), size=len(blocks))
        idx = np.concatenate([blocks[p] for p in picks])
        sa, sb = ca[idx].sum(), cb[idx].sum()
        roi_a = ra[idx].sum() / sa * 100 if sa else 0
        roi_b = rb[idx].sum() / sb * 100 if sb else 0
        diffs.append(roi_b - roi_a)
    diffs = np.array(diffs)
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


@dataclass
class Candidate:
    cid: str
    kind: str
    cell: str
    category: str
    builder_id: str


def _race_tickets(race, spec):
    """spec: dict with kind, shape, orders (rrr/rrv/nrv), swap, max_pts."""
    kind = spec['kind']
    shape = spec['shape']
    rank = swap_rank7(race) if spec.get('swap') and spec['cell'] == 'low' else (
        swap_rank6(race) if spec.get('swap') else list(race['rank_ord']))
    ninki = race['ninki_ord']
    vh = race['vh_ord']
    ord_mode = spec.get('orders', 'rrr')
    if ord_mode == 'rrr':
        c1, c2, c3 = rank, rank, rank
    elif ord_mode == 'rrv':
        c1, c2, c3 = rank, rank, vh
    elif ord_mode == 'rvr':
        c1, c2, c3 = rank, vh, rank
    elif ord_mode == 'nrv':
        c1, c2, c3 = ninki, rank, vh
    else:
        c1, c2, c3 = rank, rank, rank
    tix = make_tickets(kind, c1, c2, c3, shape)
    max_pts = spec.get('max_pts')
    if max_pts and len(tix) > max_pts:
        return set()
    min_pts = spec.get('min_pts', 1)
    if len(tix) < min_pts:
        return set()
    return tix


def build_candidates(cell):
    out = []
    if cell == 'low':
        out.append(dict(
            cid='現行_3連単RRR2-4-7', kind='3連単', shape=(2, 4, 7),
            orders='rrr', swap=False, cell='low', max_pts=30, category='baseline'))
        # 3連単→3連複（同形状）
        out.append(dict(
            cid='3連複化_RRR2-4-7', kind='3連複', shape=(2, 4, 7),
            orders='rrr', swap=False, cell='low', category='trio_conv'))
        # N6入替
        out.append(dict(
            cid='N6入替_3連単2-4-7', kind='3連単', shape=(2, 4, 7),
            orders='rrr', swap=True, cell='low', max_pts=30, category='elim_swap'))
        out.append(dict(
            cid='N6入替_3連複2-4-7', kind='3連複', shape=(2, 4, 7),
            orders='rrr', swap=True, cell='low', category='elim_swap'))
        # Rank×VH
        out.append(dict(
            cid='RRV_3連単2-4-7', kind='3連単', shape=(2, 4, 7),
            orders='rrv', swap=False, cell='low', max_pts=30, category='rank_vh'))
        out.append(dict(
            cid='RRV_3連複2-4-7', kind='3連複', shape=(2, 4, 7),
            orders='rrv', swap=False, cell='low', category='rank_vh'))
        out.append(dict(
            cid='NRV_3連単2-4-7', kind='3連単', shape=(2, 4, 7),
            orders='nrv', swap=False, cell='low', max_pts=30, category='rank_vh'))
        # 30点以内の形探索（3連単）
        for a in range(1, 5):
            for b in range(a, 7):
                for c in range(b, 10):
                    sh = (a, b, c)
                    if sh == (2, 4, 7):
                        continue
                    out.append(dict(
                        cid=f'3連単RRR{a}-{b}-{c}', kind='3連単', shape=sh,
                        orders='rrr', swap=False, cell='low', max_pts=30,
                        category='shape_tri'))
        # 30点以内（3連複・同予算3000）
        for a in range(1, 5):
            for b in range(a, 7):
                for c in range(b, 10):
                    sh = (a, b, c)
                    if sh == (2, 4, 7):
                        continue
                    out.append(dict(
                        cid=f'3連複RRR{a}-{b}-{c}', kind='3連複', shape=sh,
                        orders='rrr', swap=False, cell='low',
                        category='shape_trio'))
    else:
        out.append(dict(
            cid='現行_3連複2-3-6', kind='3連複', shape=(2, 3, 6),
            orders='rrr', swap=False, cell='high', category='baseline'))
        out.append(dict(
            cid='N6入替_3連複2-3-6', kind='3連複', shape=(2, 3, 6),
            orders='rrr', swap=True, cell='high', category='elim_swap'))
        out.append(dict(
            cid='RRV_3連複2-3-6', kind='3連複', shape=(2, 3, 6),
            orders='rrv', swap=False, cell='high', category='rank_vh'))
        for a in range(1, 4):
            for b in range(a, 6):
                for c in range(b, 9):
                    sh = (a, b, c)
                    if sh == (2, 3, 6):
                        continue
                    out.append(dict(
                        cid=f'3連複RRR{a}-{b}-{c}', kind='3連複', shape=sh,
                        orders='rrr', swap=False, cell='high',
                        category='shape_trio'))
    return out


def eval_on_races(races, spec, budget, pall):
    recs = []
    for race in races:
        tix = _race_tickets(race, spec)
        if not tix:
            continue
        sc = score_budget(tix, spec['kind'], race['top3'], pall.get(race['rk']), budget)
        if sc is None:
            continue
        recs.append(dict(day=race['day'], year=race['year'], rk=race['rk'], **sc))
    return recs


def paired_eval(races, spec, budget, pall, base_recs_map):
    """baseline と同一 rk のみ。予算固定。"""
    recs = []
    hits_b, hits_c = [], []
    for race in races:
        rk = race['rk']
        if rk not in base_recs_map:
            continue
        tix = _race_tickets(race, spec)
        if not tix:
            continue
        sc = score_budget(tix, spec['kind'], race['top3'], pall.get(rk), budget)
        if sc is None:
            continue
        recs.append(dict(day=race['day'], year=race['year'], rk=rk, **sc))
        hits_c.append(sc['hit'])
        hits_b.append(base_recs_map[rk]['hit'])
    return recs, hits_b, hits_c


def summarise_recs(recs):
    if not recs:
        return None
    cost = sum(r['cost'] for r in recs)
    ret = sum(r['ret'] for r in recs)
    hits = sum(r['hit'] for r in recs)
    n = len(recs)
    seq = [r['hit'] for r in sorted(recs, key=lambda x: (x['day'], x['rk']))]
    avg_pts = sum(r['tc'] for r in recs) / n
    return dict(
        n=n, hits=hits, hit_rate=hits / n * 100,
        roi=ret / cost * 100 if cost else 0,
        loss_per_100=100 - ret / cost * 100 if cost else 100,
        cost_per_hit=cost / hits if hits else None,
        max_losing_streak=hc.max_losing_streak(seq),
        total_cost=cost, total_ret=ret,
        avg_pts=avg_pts,
    )


def classify_vs_base(s, base, mcn, roi_diff_ci, n_base_total):
    if s is None:
        return 'C', '評価不可'
    if s['n'] < n_base_total * 0.995:
        return 'C', f"比較レース減（{s['n']}/{n_base_total}）"
    roi_d = s['roi'] - base['roi']
    hit_d = s['hit_rate'] - base['hit_rate']
    if s['roi'] < base['roi']:
        return 'C', f'ROI {base["roi"]:.1f}%→{s["roi"]:.1f}%（-{ -roi_d:.1f}pp）'
    if hit_d > 0 and roi_d < 0:
        return 'C', '的中↑だがROI↓'
    if s['roi'] >= base['roi'] and roi_diff_ci[0] >= 0 and hit_d >= 0:
        return 'A', f'ROI+{roi_d:.1f}pp・的中{hit_d:+.1f}pp・CI下限≥0'
    if s['roi'] >= base['roi'] and roi_diff_ci[0] >= -1.0:
        if hit_d >= 0 or roi_d >= 1.0:
            return 'A', f'ROI+{roi_d:.1f}pp（CI {roi_diff_ci[0]:+.1f}〜{roi_diff_ci[1]:+.1f}pp）'
    if s['roi'] >= base['roi'] - 1.0 and s['roi'] >= ROI_FLOOR:
        return 'B', f'ROIほぼ同等（{roi_d:+.1f}pp）要・train/追加確認'
    if hit_d > 2 and roi_d >= -2 and roi_diff_ci[1] > 0:
        return 'B', f'的中+{hit_d:.1f}pp・ROI {roi_d:+.1f}pp（CI幅広）'
    return 'C', f'現行比優位なし（ROI {roi_d:+.1f}pp 的中 {hit_d:+.1f}pp）'


def run_cell(cell, races, pall_tri, pall_tri_o):
    budget = BUDGET_LOW if cell == 'low' else BUDGET_HIGH
    cands = build_candidates(cell)
    baseline_spec = cands[0]
    pall = pall_tri_o if baseline_spec['kind'] == '3連単' else pall_tri

    base_recs = eval_on_races(races, baseline_spec, budget, pall)
    base_map = {r['rk']: r for r in base_recs}
    base = summarise_recs(base_recs)
    n_base_total = len(base_recs)

    results = []
    for spec in cands:
        kind = spec['kind']
        p = pall_tri_o if kind == '3連単' else pall_tri
        if spec['category'] == 'baseline':
            recs = base_recs
            hits_b = [r['hit'] for r in recs]
            hits_c = hits_b
        else:
            recs, hits_b, hits_c = paired_eval(races, spec, budget, p, base_map)
        s = summarise_recs(recs)
        if s is None:
            continue
        mcn = hc.mcnemar(hits_b, hits_c) if spec['category'] != 'baseline' else None
        if spec['category'] == 'baseline':
            roi_ci = hc.block_ci_roi(recs)
            roi_diff_ci = (0.0, 0.0)
        else:
            roi_ci = hc.block_ci_roi(recs)
            # paired subset for diff
            paired_a = [base_map[r['rk']] for r in recs]
            roi_diff_ci = block_roi_diff(paired_a, recs)
        grade, reason = classify_vs_base(
            s, base, mcn, roi_diff_ci, n_base_total)
        results.append(dict(
            spec=spec, s=s, base=base, mcn=mcn,
            roi_ci=roi_ci, roi_diff_ci=roi_diff_ci,
            grade=grade, reason=reason, recs=recs,
        ))

    # 採用向けソート: ROI差降順、的中差、現行以上のみ
    def sort_key(r):
        if r['spec']['category'] == 'baseline':
            return (999, 0, 0)
        roi_d = r['s']['roi'] - base['roi']
        hit_d = r['s']['hit_rate'] - base['hit_rate']
        return (-max(0, roi_d), -hit_d)

    ranked = sorted(
        [r for r in results if r['spec']['category'] != 'baseline'],
        key=sort_key)
    return base, results, ranked, n_base_total


def print_cell_report(cell_label, base, ranked, top_n=5):
    print(f'\n{"=" * 80}')
    print(f'【{cell_label}】 holdout 2024+  比較レース {base["n"]}  予算 '
          f'{BUDGET_LOW if "少" in cell_label else BUDGET_HIGH}円/レース')
    print('=' * 80)
    print('現行（基準）')
    print_row('現行', base, None, base, None, (0, 0), '—')

    print(f'\n--- 上位候補（ROI現行以上を優先、最大{top_n}件）---')
    shown = 0
    for r in ranked:
        if shown >= top_n:
            break
        sp = r['spec']
        print_row(sp['cid'], r['s'], base, r['s'], r['mcn'], r['roi_diff_ci'], r['grade'])
        shown += 1

    print(f'\n--- カテゴリ別代表 ---')
    cats = {}
    for r in ranked:
        cat = r['spec']['category']
        if cat not in cats:
            cats[cat] = r
    for cat, r in sorted(cats.items()):
        print(f"  [{cat}] {r['spec']['cid']}: {r['grade']} — {r['reason']}")

    a_list = [r for r in ranked if r['grade'] == 'A']
    b_list = [r for r in ranked if r['grade'] == 'B']
    print(f'\n判定サマリ: A={len(a_list)}件 / B={len(b_list)}件 / '
          f'C={len(ranked) - len(a_list) - len(b_list)}件（baseline除く）')
    if a_list:
        print('A（本番採用候補）:')
        for r in a_list[:5]:
            print(f"  - {r['spec']['cid']}: {r['reason']}")
    else:
        print('A（本番採用候補）: なし')
    if b_list:
        print('B（追加検証）:')
        for r in b_list[:5]:
            print(f"  - {r['spec']['cid']}: {r['reason']}")


def print_row(name, s, base, _s2, mcn, roi_diff_ci, grade):
    cph = f"{s['cost_per_hit']:,.0f}" if s['cost_per_hit'] else '—'
    roi_d = s['roi'] - base['roi'] if base else 0
    hit_d = s['hit_rate'] - base['hit_rate'] if base else 0
    mcn_s = '—'
    if mcn:
        mcn_s = f"b={mcn['b']} c={mcn['c']} p={mcn['p']:.3f}"
    print(
        f"  {name[:28]:28} | {s['avg_pts']:4.0f}点 | "
        f"的中{s['hit_rate']:5.1f}%({hit_d:+.1f}) | ROI{s['roi']:5.1f}%({roi_d:+.1f}) | "
        f"損失{s['loss_per_100']:4.1f} | 1中{cph} | 連敗{s['max_losing_streak']} | "
        f"R{s['n']} | 投{s['total_cost']/1000:.0f}k 払{s['total_ret']/1000:.0f}k | "
        f"ROI差CI[{roi_diff_ci[0]:+.1f},{roi_diff_ci[1]:+.1f}] | {mcn_s} | {grade}"
    )


def main():
    all_races = hc.build_races(zones=('C',))
    hold = [r for r in all_races if r['period'] == 'holdout']
    low = [r for r in hold if r['cross_n'] < 3]
    high = [r for r in hold if r['cross_n'] >= 3]
    pall_tri = hc.load_payouts('3連複')
    pall_tri_o = hc.load_payouts('3連単')

    print('Cゾーン offline 検証（holdout 2024+・同予算・点数増のみ禁止）')
    print(f'クロス少: {len(low)}R / クロス多: {len(high)}R')

    base_l, res_l, rank_l, _ = run_cell('low', low, pall_tri, pall_tri_o)
    base_h, res_h, rank_h, _ = run_cell('high', high, pall_tri, pall_tri_o)

    print_cell_report('クロス少（現行3連単2-4-7・予算3000円）', base_l, rank_l)
    print_cell_report('クロス多（現行3連複2-3-6・予算700円）', base_h, rank_h)

    # memo
    sections = [
        '## 条件',
        '- holdout 2024+、同予算（クロス少3000円/クロス多700円）',
        '- 点数増のみの不公平比較なし（予算/点数で均等配分）',
        '## クロス少 現行',
        f"的中{base_l['hit_rate']:.1f}% ROI{base_l['roi']:.1f}% "
        f"損失{base_l['loss_per_100']:.1f} n={base_l['n']}",
        '## クロス多 現行',
        f"的中{base_h['hit_rate']:.1f}% ROI{base_h['roi']:.1f}% "
        f"損失{base_h['loss_per_100']:.1f} n={base_h['n']}",
    ]
    for label, rank, base in (
        ('クロス少', rank_l, base_l),
        ('クロス多', rank_h, base_h),
    ):
        a = [r for r in rank if r['grade'] == 'A']
        b = [r for r in rank if r['grade'] == 'B']
        sections.append(f'## {label} 判定')
        sections.append(f"A: {len(a)}件 / B: {len(b)}件")
        if a:
            for r in a[:5]:
                sections.append(f"- A: {r['spec']['cid']} — {r['reason']}")
        else:
            sections.append('- A: なし')
        top_roi = sorted(rank, key=lambda x: x['s']['roi'] - base['roi'], reverse=True)[:3]
        for r in top_roi:
            d = r['s']['roi'] - base['roi']
            sections.append(
                f"- {r['grade']} {r['spec']['cid']}: ROI{d:+.1f}pp "
                f"的中{r['s']['hit_rate'] - base['hit_rate']:+.1f}pp — {r['reason']}"
            )

    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_c_zone_offline.md')
    hc.write_memo(memo, 'verified_c_zone_offline', 'N1 Cゾーン holdout 同予算探索', sections)
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
