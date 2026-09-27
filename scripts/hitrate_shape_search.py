# -*- coding: utf-8 -*-
"""N1: 同点数・ROI下限つきで的中率最大の形を探す。

Usage:
  python scripts/hitrate_shape_search.py --zone C --cell trifecta
  python scripts/hitrate_shape_search.py --zone C --cell trio_c
  python scripts/hitrate_shape_search.py --zone D --cell d
"""
import argparse
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.trio_engine import build_formation, build_trifecta_formation
from scripts import hitrate_common as hc


def tickets_shape(race, kind, a, b, c, use_rank=True):
    ord_ = race['rank_ord'] if use_rank else race['ninki_ord']
    if len(ord_) < c:
        return set()
    if kind == '3連単':
        return set(build_trifecta_formation(ord_[:a], ord_[:b], ord_[:c]))
    return set(build_formation(ord_[:a], ord_[:b], ord_[:c]))


def tickets_d(race, k_ninki=4, vh_m=0):
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


def eval_candidate(races, builder, pall_tri, pall_tri_o):
    recs = []
    pts_sum = 0
    for race in races:
        tix, kind = builder(race)
        if not tix:
            continue
        pall = pall_tri_o if kind == '3連単' else pall_tri
        sc = hc.score_race(tix, kind, race['top3'], pall.get(race['rk']))
        pts_sum += sc['tc']
        recs.append(dict(day=race['day'], year=race['year'], rk=race['rk'], **sc))
    if not recs:
        return None
    s = hc.summarise(recs)
    s['avg_pts'] = pts_sum / len(recs)
    return s


def leg_capture(races, ord_key, leg, n_max):
    ok = tot = 0
    for race in races:
        ord_ = race[ord_key]
        top3 = race['top3']
        if leg >= len(top3):
            continue
        u = top3[leg]
        if u not in ord_:
            continue
        tot += 1
        if ord_.index(u) + 1 <= n_max:
            ok += 1
    return ok / tot * 100 if tot else 0.0


def gen_trifecta_candidates():
    for kind in ('3連単', '3連複'):
        for a in range(1, 5):
            for b in range(a, 7):
                for c in range(b, 10):
                    yield dict(
                        name=f'{kind[0]} {a}-{b}-{c}', kind=kind, a=a, b=b, c=c,
                        builder=lambda r, k=kind, aa=a, bb=b, cc=c: (
                            tickets_shape(r, k, aa, bb, cc), k),
                    )


def gen_trio_c_candidates():
    for a in range(1, 4):
        for b in range(a, 6):
            for c in range(b, 9):
                yield dict(
                    name=f'3連複 {a}-{b}-{c}', kind='3連複', a=a, b=b, c=c,
                    builder=lambda r, aa=a, bb=b, cc=c: (
                        tickets_shape(r, '3連複', aa, bb, cc), '3連複'),
                )


def gen_d_candidates():
    for k in range(3, 7):
        for m in range(0, 3):
            yield dict(
                name=f'D ninki3-{k}+vh{m}', kind='3連複', k=k, m=m,
                builder=lambda r, kk=k, mm=m: (tickets_d(r, kk, mm), '3連複'),
            )


def filter_cell(races, zone, cell):
    out = []
    for r in races:
        if r['zone'] != zone:
            continue
        if cell == 'trifecta' and r['zone'] == 'C' and r['cross_n'] < 3:
            out.append(r)
        elif cell == 'trio_c' and r['zone'] == 'C' and r['cross_n'] >= 3:
            out.append(r)
        elif cell == 'd' and r['zone'] == 'D':
            out.append(r)
    return out


def baseline_builder(cell):
    if cell == 'trifecta':
        return lambda r: (tickets_shape(r, '3連単', 2, 4, 7), '3連単')
    if cell == 'trio_c':
        return lambda r: (tickets_shape(r, '3連複', 2, 3, 6), '3連複')
    return lambda r: (tickets_d(r, 4, 0), '3連複')


def run_search(zone, cell, max_points, roi_floor):
    races = hc.build_races(zones=(zone,))
    train = filter_cell([r for r in races if r['period'] == 'train'], zone, cell)
    hold = filter_cell([r for r in races if r['period'] == 'holdout'], zone, cell)
    pall_tri = hc.load_payouts('3連複')
    pall_tri_o = hc.load_payouts('3連単')

    if cell == 'trifecta':
        cands = list(gen_trifecta_candidates())
        baseline_name = '現行 3連単2-4-7'
    elif cell == 'trio_c':
        cands = list(gen_trio_c_candidates())
        baseline_name = '現行 3連複2-3-6'
    else:
        cands = list(gen_d_candidates())
        baseline_name = '現行 D 2点'

    baseline = dict(name=baseline_name, builder=baseline_builder(cell))
    scored_train = []
    for cand in cands:
        s = eval_candidate(train, cand['builder'], pall_tri, pall_tri_o)
        if not s or s['avg_pts'] > max_points or s['roi'] < roi_floor:
            continue
        scored_train.append((cand, s))
    scored_train.sort(key=lambda x: -x[1]['hit_rate'])

    if not scored_train:
        print(f'ROI下限{roi_floor}%・点数上限{max_points}点: 該当なし')
        return

    top10 = scored_train[:10]
    print(f'\n=== train 上位10 ({zone}/{cell}) ===')
    print('候補 | 券種 | 点 | n | 的中率 | ROI | 損失/100円 | 投資/1的中 | 最大連敗 | ROI 95%CI | 年別')
    base_s = eval_candidate(train, baseline['builder'], pall_tri, pall_tri_o)
    if base_s:
        print(hc.fmt_row(baseline_name, cell, base_s['avg_pts'], base_s))

    holdout_cands = []
    holdout_ranked = []
    base_hold = eval_candidate(hold, baseline['builder'], pall_tri, pall_tri_o)
    base_hr = base_hold['hit_rate'] if base_hold else 0

    for i, (cand, st) in enumerate(top10):
        print(hc.fmt_row(cand['name'], cand.get('kind', '3連複'), st['avg_pts'], st))
        sh = eval_candidate(hold, cand['builder'], pall_tri, pall_tri_o)
        if sh:
            holdout_ranked.append((cand, sh, i + 1))
        if sh and sh['roi'] >= roi_floor and sh['hit_rate'] > base_hr:
            holdout_cands.append((cand, sh, i + 1))

    print(f'\n=== holdout 固定評価 ===')
    if base_hold:
        print(hc.fmt_row(baseline_name + '(基準)', cell, base_hold['avg_pts'], base_hold))
    for i, (cand, sh, tr_rank) in enumerate(holdout_ranked[:3], 1):
        print(hc.fmt_row(f'{cand["name"]}(train#{tr_rank})', cand.get('kind', '3連複'),
                         sh['avg_pts'], sh))

    train1 = top10[0][0]['name']
    top3_holdout_names = [x[0]['name'] for x in
                          sorted(holdout_ranked, key=lambda x: -x[1]['hit_rate'])[:3]]
    unstable = '順位不安定・不採用' if train1 not in top3_holdout_names else ''

    best = max(holdout_cands, key=lambda x: x[1]['hit_rate']) if holdout_cands else None
    concl = f'ROI下限{roi_floor}%・点数上限{max_points}点'
    if best:
        _, bs, _ = best
        concl += (
            f'で、holdout 的中率最大は {best[0]["name"]}'
            f'（現行比 +{bs["hit_rate"] - base_hr:.1f}pp、'
            f'損失/100円 {base_hold["loss_per_100"]:.1f}→{bs["loss_per_100"]:.1f}）'
        )
    else:
        concl += 'で holdout 候補 0 件'
    if unstable:
        concl += f'。train1位: {unstable}'
    print(f'\n{concl}')

    csv_path = os.path.join(ROOT, 'data', f'hitrate_shape_search_{cell}.csv')
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('name,train_hit,train_roi,hold_hit,hold_roi\n')
        for cand, st in top10:
            sh = eval_candidate(hold, cand['builder'], pall_tri, pall_tri_o)
            f.write(f"{cand['name']},{st['hit_rate']:.2f},{st['roi']:.2f},"
                    f"{sh['hit_rate'] if sh else 0:.2f},{sh['roi'] if sh else 0:.2f}\n")
    print(f'→ {csv_path}')

    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_hitrate_shape_search.md')
    hc.write_memo(memo, 'verified_hitrate_shape_search', f'N1 形探索 {zone}/{cell}', [concl])
    print(f'→ {memo}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zone', choices=['D', 'C'], default='C')
    ap.add_argument('--cell', choices=['trifecta', 'trio_c', 'd'], default='trifecta')
    ap.add_argument('--max-points', type=int, default=None)
    ap.add_argument('--roi-floor', type=float, default=hc.ROI_FLOOR_DEFAULT)
    args = ap.parse_args()
    defaults = {'trifecta': 30, 'trio_c': 7, 'd': 4}
    max_pts = args.max_points if args.max_points is not None else defaults[args.cell]
    run_search(args.zone, args.cell, max_pts, args.roi_floor)


if __name__ == '__main__':
    main()
