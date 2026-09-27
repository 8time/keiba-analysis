# -*- coding: utf-8 -*-
"""Cゾーン クロス多 B候補の train→holdout 固定検証（的中率重視モード）。

対象: 3連複 2-4-8 / 2-5-8 / 3-5-8 vs 現行 2-3-6
予算: 700円/レース固定

Usage: python scripts/c_trio_hitmode_verify.py
"""
import io
import os
import sys

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.trio_engine import build_formation
from scripts import hitrate_common as hc

BUDGET = 700
BASELINE_SHAPE = (2, 3, 6)
CANDIDATES = [
    ('3連複2-4-8', (2, 4, 8)),
    ('3連複2-5-8', (2, 5, 8)),
    ('3連複3-5-8', (3, 5, 8)),
]


def score_budget(tickets, kind, top3, payouts, budget):
    tc = len(tickets)
    if tc == 0:
        return None
    stake = budget / tc
    cost = budget
    key = tuple(sorted(top3))
    hit = int(key in tickets)
    ret = 0.0
    if hit:
        for combo, pay in payouts or []:
            if combo == key:
                ret = pay * (stake / 100.0)
                break
    return dict(cost=cost, ret=ret, hit=hit, tc=tc, stake=stake)


def summarise_recs(recs):
    if not recs:
        return None
    cost = sum(r['cost'] for r in recs)
    ret = sum(r['ret'] for r in recs)
    hits = sum(r['hit'] for r in recs)
    n = len(recs)
    seq = [r['hit'] for r in sorted(recs, key=lambda x: (x['day'], x['rk']))]
    return dict(
        n=n, hits=hits, hit_rate=hits / n * 100,
        roi=ret / cost * 100 if cost else 0,
        loss_per_100=100 - ret / cost * 100 if cost else 100,
        cost_per_hit=cost / hits if hits else None,
        max_losing_streak=hc.max_losing_streak(seq),
        total_cost=cost, total_ret=ret,
        avg_pts=sum(r['tc'] for r in recs) / n,
    )


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


def tickets_trio(race, shape):
    rank = race['rank_ord']
    a, b, c = shape
    if len(rank) < c:
        return set()
    return set(build_formation(rank[:a], rank[:b], rank[:c]))


def eval_shape(races, shape, pall, base_map=None):
    """base_map があるとき同一 rk のペア recs を返す。"""
    recs = []
    hits_b, hits_c = [], []
    for race in races:
        tix = tickets_trio(race, shape)
        if not tix:
            continue
        if base_map is not None and race['rk'] not in base_map:
            continue
        sc = score_budget(tix, '3連複', race['top3'], pall.get(race['rk']), BUDGET)
        if sc is None:
            continue
        recs.append(dict(day=race['day'], year=race['year'], rk=race['rk'], **sc))
        hits_c.append(sc['hit'])
        if base_map is not None:
            hits_b.append(base_map[race['rk']]['hit'])
    return recs, hits_b, hits_c


def year_breakdown(recs):
    out = {}
    for y in sorted({r['year'] for r in recs}):
        sub = [r for r in recs if r['year'] == y]
        out[y] = summarise_recs(sub)
    return out


def roi_ci(recs):
    return hc.block_ci_roi(recs)


def single_year_dominance(base_recs, cand_recs, years=(2024, 2025, 2026)):
    """年別の払戻増分。1年に70%超が集中したら True。"""
    deltas = {}
    bm = {r['rk']: r for r in base_recs}
    for y in years:
        deltas[y] = 0.0
    for r in cand_recs:
        b = bm.get(r['rk'])
        if b:
            deltas[r['year']] += r['ret'] - b['ret']
    total = sum(deltas.values())
    if total <= 0:
        return False, deltas
    max_share = max(abs(v) for v in deltas.values()) / abs(total) if total else 0
    return max_share > 0.70, deltas


def year_consistent(yb, yc, years=(2024, 2025, 2026)):
    """各年: 的中↑ かつ ROI が現行比 -1pp 以上。"""
    details = []
    all_ok = True
    for y in years:
        if y not in yb or y not in yc or yb[y] is None or yc[y] is None:
            details.append((y, 'データなし', False))
            all_ok = False
            continue
        hit_d = yc[y]['hit_rate'] - yb[y]['hit_rate']
        roi_d = yc[y]['roi'] - yb[y]['roi']
        ok = hit_d > 0 and roi_d >= -1.0
        details.append((y, f'的中{hit_d:+.1f}pp ROI{roi_d:+.1f}pp n={yc[y]["n"]}', ok))
        if not ok:
            all_ok = False
    return all_ok, details


def classify_hitmode(name, base_s, cand_s, mcn, roi_diff_ci, y_consistent, dominated, train_roi_d, hold_roi_d):
    hit_d = cand_s['hit_rate'] - base_s['hit_rate']
    if hold_roi_d < 0:
        return 'C', f'holdout ROI {hold_roi_d:+.1f}pp（現行未満）'
    if hit_d <= 0:
        return 'C', f'holdout 的中 {hit_d:+.1f}pp（改善なし）'
    if dominated:
        return 'C', '特定年に払戻増分が集中（再現性低）'
    if not y_consistent:
        return 'C', '年別で的中↑・ROI維持が一貫しない'
    if train_roi_d < -3 and hold_roi_d > 0:
        return 'B', f'train ROI {train_roi_d:+.1f}pp / holdout {hold_roi_d:+.1f}pp（符号不安定）'
    if mcn['p'] >= 0.05 or mcn['c'] <= mcn['b']:
        return 'B', f'McNemar 有意でない（p={mcn["p"]:.3f}）'
    if roi_diff_ci[0] < -3.0:
        return 'B', f'ROI差CI下限 {roi_diff_ci[0]:+.1f}pp（回収リスク）'
    if hit_d >= 3.0 and hold_roi_d >= 0 and y_consistent and mcn['p'] < 0.05:
        return 'A', (
            f'holdout 的中+{hit_d:.1f}pp ROI{hold_roi_d:+.1f}pp、'
            f'年別一貫、McNemar p={mcn["p"]:.4f}'
        )
    return 'B', f'holdout 改善あり（的中+{hit_d:.1f}pp ROI{hold_roi_d:+.1f}pp）だが条件一部未達'


def print_stats(label, s, base_s=None):
    if s is None:
        print(f'  {label}: データなし')
        return
    cph = f"{s['cost_per_hit']:,.0f}円" if s['cost_per_hit'] else '—'
    roi_d = hit_d = ''
    if base_s:
        roi_d = f" ({s['roi'] - base_s['roi']:+.1f}pp)"
        hit_d = f" ({s['hit_rate'] - base_s['hit_rate']:+.1f}pp)"
    print(
        f"  {label}: 的中{s['hit_rate']:.1f}%{hit_d} | ROI{s['roi']:.1f}%{roi_d} | "
        f"損失{s['loss_per_100']:.1f} | 1中{cph} | 連敗{s['max_losing_streak']} | "
        f"R{s['n']} | 投{s['total_cost']/1000:.0f}k 払{s['total_ret']/1000:.0f}k"
    )


def main():
    all_c = [r for r in hc.build_races(zones=('C',)) if r['cross_n'] >= 3]
    train = [r for r in all_c if r['period'] == 'train']
    hold = [r for r in all_c if r['period'] == 'holdout']
    pall = hc.load_payouts('3連複')

    print('=' * 76)
    print('Cゾーン クロス多 B候補 — train固定→holdout評価（予算700円/レース）')
    print('=' * 76)
    print(f'train: {len(train)}R / holdout: {len(hold)}R')

    # baseline
    base_train, _, _ = eval_shape(train, BASELINE_SHAPE, pall)
    base_hold, _, _ = eval_shape(hold, BASELINE_SHAPE, pall)
    bs_tr = summarise_recs(base_train)
    bs_ho = summarise_recs(base_hold)
    bm_ho = {r['rk']: r for r in base_hold}

    print('\n【現行 3連複 2-3-6】')
    print('--- train ---')
    print_stats('全体', bs_tr)
    for y, s in year_breakdown(base_train).items():
        print_stats(f'{y}年', s)
    print('--- holdout（最終評価の基準）---')
    print_stats('全体', bs_ho)
    yb_ho = year_breakdown(base_hold)
    for y, s in yb_ho.items():
        print_stats(f'{y}年', s)
    roi_lo, roi_hi = roi_ci(base_hold)
    print(f'  ROI 95%CI: [{roi_lo:.1f}, {roi_hi:.1f}]%')

    results = []
    print('\n' + '=' * 76)
    print('【候補 — train で形状固定 → holdout 最終評価】')
    print('=' * 76)

    for name, shape in CANDIDATES:
        print(f'\n### {name} ###')
        tr_recs, _, _ = eval_shape(train, shape, pall)
        ho_recs, hb, hc2 = eval_shape(hold, shape, pall, bm_ho)
        s_tr = summarise_recs(tr_recs)
        s_ho = summarise_recs(ho_recs)
        mcn = hc.mcnemar(hb, hc2)
        paired_base = [bm_ho[r['rk']] for r in ho_recs]
        roi_diff_ci = block_roi_diff(paired_base, ho_recs)
        rci_lo, rci_hi = roi_ci(ho_recs)

        print('--- train（参考）---')
        print_stats('全体', s_tr, bs_tr)
        yt = year_breakdown(tr_recs)
        for y in sorted(yt):
            print_stats(f'{y}年', yt[y], year_breakdown(base_train).get(y))

        print('--- holdout（最終）---')
        print_stats('全体', s_ho, bs_ho)
        yc = year_breakdown(ho_recs)
        for y in sorted(yc):
            print_stats(f'{y}年', yc[y], yb_ho.get(y))
        print(
            f"  ROI 95%CI: [{rci_lo:.1f}, {rci_hi:.1f}]% | "
            f"ROI差CI: [{roi_diff_ci[0]:+.1f}, {roi_diff_ci[1]:+.1f}]pp | "
            f"McNemar b={mcn['b']} c={mcn['c']} z={mcn['z']:.2f} p={mcn['p']:.4f}"
        )

        y_ok, y_det = year_consistent(yb_ho, yc)
        dom, y_delta = single_year_dominance(base_hold, ho_recs)
        print('  年別一貫性（各年: 的中↑ かつ ROI≥現行−1pp）:')
        for y, msg, ok in y_det:
            mark = 'OK' if ok else 'NG'
            print(f'    {y}年 [{mark}] {msg}')
        if dom:
            print(f'  ⚠ 払戻増分の年別内訳: {y_delta} → 1年集中')

        train_roi_d = s_tr['roi'] - bs_tr['roi']
        hold_roi_d = s_ho['roi'] - bs_ho['roi']
        grade, reason = classify_hitmode(
            name, bs_ho, s_ho, mcn, roi_diff_ci, y_ok, dom, train_roi_d, hold_roi_d)
        print(f'  → 判定: **{grade}** — {reason}')
        results.append(dict(name=name, shape=shape, grade=grade, reason=reason,
                          s_tr=s_tr, s_ho=s_ho, mcn=mcn, roi_diff_ci=roi_diff_ci,
                          y_ok=y_ok, dom=dom, yt=yt, yc=yc))

    print('\n' + '=' * 76)
    print('【最終サマリ】')
    print('=' * 76)
    for r in results:
        d = r['s_ho']
        print(
            f"{r['name']:14} | {r['grade']} | holdout 的中{d['hit_rate']:.1f}% "
            f"ROI{d['roi']:.1f}% | {r['reason']}"
        )
    a = [r for r in results if r['grade'] == 'A']
    print(f"\nA（的中率重視モード採用候補）: {len(a)}件")
    if not a:
        print('  → なし')

    # memo
    lines = [
        '## 条件',
        f'- クロス多（cross_n≥3）、予算{BUDGET}円/レース',
        '- 候補形は train 前固定 → holdout 最終評価',
        '## 現行 holdout',
        f"的中{bs_ho['hit_rate']:.1f}% ROI{bs_ho['roi']:.1f}% n={bs_ho['n']}",
    ]
    for r in results:
        d = r['s_ho']
        lines.append(f"## {r['name']} → **{r['grade']}**")
        lines.append(
            f"holdout: 的中{d['hit_rate']:.1f}% ROI{d['roi']:.1f}% "
            f"({d['hit_rate']-bs_ho['hit_rate']:+.1f}pp / {d['roi']-bs_ho['roi']:+.1f}pp)"
        )
        lines.append(r['reason'])
        for y in sorted(r['yc']):
            s = r['yc'][y]
            b = yb_ho.get(y)
            if b:
                lines.append(
                    f"- {y}: 的中{s['hit_rate']:.1f}%({s['hit_rate']-b['hit_rate']:+.1f}) "
                    f"ROI{s['roi']:.1f}%({s['roi']-b['roi']:+.1f})"
                )
    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_c_trio_hitmode.md')
    hc.write_memo(memo, 'verified_c_trio_hitmode', 'Cクロス多 B候補 train→holdout', lines)
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
