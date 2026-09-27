# -*- coding: utf-8 -*-
"""N1 Dゾーン: 同予算400円固定で 2点×200 vs 4点×100 を holdout 比較。

Usage: python scripts/d_4pt_budget_backtest.py
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

from scripts import hitrate_common as hc

BUDGET = 400
STAKE_BASE = 200   # 現行: 2点×200円
STAKE_NEW = 100    # 新案: 4点×100円
N_BASE = 2
N_NEW = 4


def tickets_d_2pt(race):
    """現行 D: 人気1-2 × 人気3-4（2点）。"""
    inv = {}
    for u, nk in race['ninki_map'].items():
        if nk not in inv:
            inv[nk] = u
    u1, u2, p3, p4 = inv.get(1), inv.get(2), inv.get(3), inv.get(4)
    if None in (u1, u2, p3, p4) or len({u1, u2, p3, p4}) < 4:
        return set()
    return {tuple(sorted((u1, u2, p3))), tuple(sorted((u1, u2, p4)))}


def tickets_d_4pt(race, k_ninki=5, vh_m=1):
    """新案 D: 人気1-2 × {人気3..k} ∪ VH穴 m頭（4点想定）。"""
    inv = {}
    for u, nk in race['ninki_map'].items():
        if nk not in inv:
            inv[nk] = u
    u1, u2 = inv.get(1), inv.get(2)
    if u1 is None or u2 is None:
        return set()
    thirds = set()
    for nk in range(3, k_ninki + 1):
        if inv.get(nk):
            thirds.add(inv[nk])
    vh_n = 0
    for u in race['vh_ord']:
        if race['ninki_map'].get(u, 99) >= 6 and vh_n < vh_m:
            thirds.add(u)
            vh_n += 1
    out = set()
    for u3 in thirds:
        if len({u1, u2, u3}) == 3:
            out.add(tuple(sorted((u1, u2, u3))))
    return out


def score_staked(tickets, top3, payouts, stake_per_ticket):
    """払戻は100円あたり。stake_per_ticket 円×点数=投資。"""
    tc = len(tickets)
    cost = tc * stake_per_ticket
    if not tickets:
        return dict(cost=0, ret=0.0, hit=0, tc=0)
    key = tuple(sorted(top3))
    hit = int(key in tickets)
    ret = 0.0
    if hit:
        for combo, pay in payouts or []:
            if combo == key:
                ret = pay * (stake_per_ticket / 100.0)
                break
    return dict(cost=cost, ret=ret, hit=hit, tc=tc)


def block_bootstrap_roi_diff(recs_a, recs_b, n_boot=2000, seed=42):
    rng = np.random.default_rng(seed)
    costs_a = np.array([r['cost'] for r in recs_a], dtype=np.float64)
    rets_a = np.array([r['ret'] for r in recs_a], dtype=np.float64)
    costs_b = np.array([r['cost'] for r in recs_b], dtype=np.float64)
    rets_b = np.array([r['ret'] for r in recs_b], dtype=np.float64)
    days = np.array([r['day'] for r in recs_a])
    uniq, inv = np.unique(days, return_inverse=True)
    blocks = [np.where(inv == i)[0] for i in range(len(uniq))]
    diffs = []
    for _ in range(n_boot):
        picks = rng.integers(0, len(blocks), size=len(blocks))
        idx = np.concatenate([blocks[p] for p in picks])
        sa, ra = costs_a[idx].sum(), rets_a[idx].sum()
        sb, rb = costs_b[idx].sum(), rets_b[idx].sum()
        roi_a = ra / sa * 100 if sa else 0.0
        roi_b = rb / sb * 100 if sb else 0.0
        diffs.append(roi_b - roi_a)
    diffs = np.array(diffs)
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def summarise_recs(recs):
    if not recs:
        return None
    cost = sum(r['cost'] for r in recs)
    ret = sum(r['ret'] for r in recs)
    hits = sum(r['hit'] for r in recs)
    n = len(recs)
    roi = ret / cost * 100 if cost else 0.0
    seq = [r['hit'] for r in sorted(recs, key=lambda x: (x['day'], x['rk']))]
    return dict(
        n=n, hits=hits, hit_rate=hits / n * 100,
        roi=roi, loss_per_100=100.0 - roi,
        cost_per_hit=cost / hits if hits else None,
        max_losing_streak=hc.max_losing_streak(seq),
        total_cost=cost, total_ret=ret,
    )


def run_holdout():
    races = [r for r in hc.build_races(zones=('D',)) if r['period'] == 'holdout']
    pall = hc.load_payouts('3連複')

    recs_base, recs_new = [], []
    base_only_hit = new_only_hit = 0
    skipped_base = skipped_new = 0
    skipped_mismatch = 0

    for race in races:
        t2 = tickets_d_2pt(race)
        t4 = tickets_d_4pt(race)
        pay = pall.get(race['rk'])

        if len(t2) != N_BASE:
            skipped_base += 1
            continue
        if len(t4) != N_NEW:
            skipped_new += 1
            continue

        sb = score_staked(t2, race['top3'], pay, STAKE_BASE)
        sn = score_staked(t4, race['top3'], pay, STAKE_NEW)
        if sb['cost'] != BUDGET or sn['cost'] != BUDGET:
            skipped_mismatch += 1
            continue

        base = dict(day=race['day'], year=race['year'], rk=race['rk'], **sb)
        new = dict(day=race['day'], year=race['year'], rk=race['rk'], **sn)
        recs_base.append(base)
        recs_new.append(new)
        if sb['hit'] and not sn['hit']:
            base_only_hit += 1
        elif sn['hit'] and not sb['hit']:
            new_only_hit += 1

    s_base = summarise_recs(recs_base)
    s_new = summarise_recs(recs_new)
    mcn = hc.mcnemar([r['hit'] for r in recs_base], [r['hit'] for r in recs_new])
    roi_lo, roi_hi = block_bootstrap_roi_diff(recs_base, recs_new)
    w_base = hc.wilson(s_base['hits'], s_base['n'])
    w_new = hc.wilson(s_new['hits'], s_new['n'])

    return dict(
        races_total=len(races),
        skipped_base=skipped_base,
        skipped_new=skipped_new,
        skipped_mismatch=skipped_mismatch,
        n_paired=s_base['n'],
        s_base=s_base, s_new=s_new,
        mcn=mcn, roi_diff_ci=(roi_lo, roi_hi),
        w_base=w_base, w_new=w_new,
        base_only_hit=base_only_hit, new_only_hit=new_only_hit,
        recs_base=recs_base, recs_new=recs_new,
    )


def main():
    r = run_holdout()
    sb, sn = r['s_base'], r['s_new']
    mcn = r['mcn']
    roi_lo, roi_hi = r['roi_diff_ci']

    print('=' * 72)
    print('N1 Dゾーン 同予算400円 holdout 比較（2024+）')
    print('=' * 72)
    print(f"holdout D レース総数: {r['races_total']}")
    print(f"比較対象（2点・4点とも400円で組める）: {r['n_paired']} レース")
    print(f"  現行2点が組めない: {r['skipped_base']} / 新案4点が組めない: {r['skipped_new']}")
    print()
    print(f"{'':20} {'現行 2点×200円':>18} {'新案 4点×100円':>18}")
    print('-' * 60)
    print(f"{'1レース投資':20} {BUDGET:>15}円 {BUDGET:>15}円")
    print(f"{'的中率':20} {sb['hit_rate']:>16.1f}% {sn['hit_rate']:>16.1f}%")
    print(f"{'回収率(ROI)':20} {sb['roi']:>16.1f}% {sn['roi']:>16.1f}%")
    print(f"{'損失/100円':20} {sb['loss_per_100']:>16.1f} {sn['loss_per_100']:>16.1f}")
    cph_b = f"{sb['cost_per_hit']:,.0f}円" if sb['cost_per_hit'] else '—'
    cph_n = f"{sn['cost_per_hit']:,.0f}円" if sn['cost_per_hit'] else '—'
    print(f"{'1的中あたり投資':20} {cph_b:>18} {cph_n:>18}")
    print(f"{'最長連敗':20} {sb['max_losing_streak']:>18} {sn['max_losing_streak']:>18}")
    print()
    print('--- 統計 ---')
    print(f"McNemar: 現行のみ的中 b={mcn['b']} / 新案のみ的中 c={mcn['c']} / z={mcn['z']:.3f} / p={mcn['p']:.4f}")
    print(f"  → 的中率の差が有意（p<0.05）: {'はい' if mcn['p'] < 0.05 else 'いいえ'}")
    print(f"ROI差（新案−現行）95%CI: {roi_lo:+.1f}pp 〜 {roi_hi:+.1f}pp")
    print(f"  → CIが0を跨がない（ROI差が有意）: {'はい' if roi_lo > 0 or roi_hi < 0 else 'いいえ'}")
    if r['w_base'][0] is not None:
        print(f"的中率95%区間 現行: {r['w_base'][0]:.1f}〜{r['w_base'][1]:.1f}%")
        print(f"的中率95%区間 新案: {r['w_new'][0]:.1f}〜{r['w_new'][1]:.1f}%")

    hit_delta = sn['hit_rate'] - sb['hit_rate']
    roi_delta = sn['roi'] - sb['roi']
    roi_floor = hc.ROI_FLOOR_DEFAULT

    adopt = (
        sn['roi'] >= roi_floor
        and hit_delta > 0
        and mcn['p'] < 0.05
        and mcn['c'] > mcn['b']
        and roi_lo > -2.0
    )

    print()
    print('=' * 72)
    if adopt:
        verdict = '本番採用候補'
        reason = (
            f'同予算400円で的中率+{hit_delta:.1f}pp、ROI {sn["roi"]:.1f}%（≥{roi_floor}%）、'
            f'McNemar有意（新案のみ的中が多い）。'
        )
    else:
        verdict = 'まだ採用しない'
        parts = []
        if hit_delta <= 0:
            parts.append('的中率が上がらない')
        elif mcn['p'] >= 0.05:
            parts.append(f'的中率+{hit_delta:.1f}ppだが統計的に有意でない')
        if sn['roi'] < roi_floor:
            parts.append(f'ROI {sn["roi"]:.1f}% が下限{roi_floor}%未満')
        if roi_hi < 0:
            parts.append('ROI差CIが0未満（現行より回収が悪い可能性）')
        elif roi_lo < -2 and sn['roi'] < sb['roi']:
            parts.append(f'ROI {sb["roi"]:.1f}%→{sn["roi"]:.1f}%（現行より低下）')
        if not parts:
            parts.append('採用基準（有意な的中改善＋ROI下限＋ROI差許容）を満たさない')
        reason = '。'.join(parts) + '。'

    print(f'判定: {verdict}')
    print(f'理由: {reason}')
    print('=' * 72)

    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_d_4pt_budget.md')
    hc.write_memo(
        memo,
        'verified_d_4pt_budget',
        'N1 Dゾーン 同予算400円 2×200 vs 4×100 holdout',
        [
            '## 条件',
            f'- holdout 2024+、1レース予算 **{BUDGET}円固定**',
            f'- 現行: {N_BASE}点×{STAKE_BASE}円 / 新案: {N_NEW}点×{STAKE_NEW}円（人気1-2×{{人気3-5+VH穴1}}）',
            f'- 比較レース数: {r["n_paired"]}',
            '## 結果',
            f'| | 現行2×200 | 新案4×100 |',
            f'| 的中率 | {sb["hit_rate"]:.1f}% | {sn["hit_rate"]:.1f}% |',
            f'| ROI | {sb["roi"]:.1f}% | {sn["roi"]:.1f}% |',
            f'| 損失/100円 | {sb["loss_per_100"]:.1f} | {sn["loss_per_100"]:.1f} |',
            f'| 1的中投資 | {cph_b} | {cph_n} |',
            f'| 最長連敗 | {sb["max_losing_streak"]} | {sn["max_losing_streak"]} |',
            f'| McNemar | b={mcn["b"]} c={mcn["c"]} z={mcn["z"]:.3f} p={mcn["p"]:.4f} |',
            f'| ROI差95%CI | {roi_lo:+.1f}〜{roi_hi:+.1f}pp |',
            f'## 判定',
            f'**{verdict}** — {reason}',
        ],
    )
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
