# -*- coding: utf-8 -*-
"""N2: C ゾーン 3連単2-4-7 → 3連複化の的中増分。

Usage: python scripts/trio_conversion_backtest.py
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.trio_engine import build_formation
from scripts import hitrate_common as hc

PLAYBOOK_TRI = hc.PLAYBOOK_C_TRI
PLAYBOOK_C_TRIO = hc.PLAYBOOK_C_TRIO


def eval_cell(races, pall_tri, pall_tri_o):
    rows = {'tri': [], 'trio247': [], 'trio236': []}
    for race in races:
        if race['zone'] != 'C' or race['cross_n'] >= 3:
            continue
        rank = race['rank_ord']
        if len(rank) < 7:
            continue
        kind_tri, tix_tri = hc.live_tickets(race, PLAYBOOK_TRI)
        tix_trio = set(build_formation(rank[:2], rank[:4], rank[:7]))
        kind236, tix236 = hc.live_tickets(race, PLAYBOOK_C_TRIO)

        sc_tri = hc.score_race(tix_tri, '3連単', race['top3'], pall_tri_o.get(race['rk']))
        sc_trio = hc.score_race(tix_trio, '3連複', race['top3'], pall_tri.get(race['rk']))
        sc236 = hc.score_race(tix236, '3連複', race['top3'], pall_tri.get(race['rk']))

        if sc_tri['hit'] and not sc_trio['hit']:
            print('ASSERT FAIL: 3連単的中 ⊄ 3連複', race['rk'], race['top3'])
            sys.exit(1)

        base = dict(day=race['day'], year=race['year'], rk=race['rk'])
        rows['tri'].append({**base, **sc_tri})
        rows['trio247'].append({**base, **sc_trio})
        rows['trio236'].append({**base, **sc236})
    return rows


def print_period(label, rows):
    s_tri = hc.summarise(rows['tri'])
    s_trio = hc.summarise(rows['trio247'])
    s236 = hc.summarise(rows['trio236'])
    print(f'\n=== {label} ===')
    print('候補 | 券種 | 点 | n | 的中率 | ROI | 損失/100円 | 投資/1的中 | 最大連敗 | ROI 95%CI | 年別')
    print(hc.fmt_row('3連単2-4-7(現行)', '3連単', s_tri['avg_pts'], s_tri))
    print(hc.fmt_row('3連複2-4-7', '3連複', s_trio['avg_pts'], s_trio))
    print(hc.fmt_row('3連複2-3-6(参考)', '3連複', s236['avg_pts'], s236))
    extra = s_trio['hits'] - s_tri['hits']
    roi_ok = s_trio['roi'] >= hc.ROI_FLOOR_DEFAULT
    print(
        f"\n3連複化で的中は {s_tri['hit_rate']:.1f}%→{s_trio['hit_rate']:.1f}%"
        f"（+{s_trio['hit_rate'] - s_tri['hit_rate']:.1f}pp、増分 {extra} レース）。"
        f" ROI は {s_tri['roi']:.1f}%→{s_trio['roi']:.1f}%。"
        f" 損失/100円は {s_tri['loss_per_100']:.1f}→{s_trio['loss_per_100']:.1f}。"
        f" ROI下限{hc.ROI_FLOOR_DEFAULT}%を満たす: {'はい' if roi_ok else 'いいえ'}"
    )
    return s_tri, s_trio, s236


def main():
    races = hc.build_races(zones=('C',))
    pall_tri = hc.load_payouts('3連複')
    pall_tri_o = hc.load_payouts('3連単')
    train = [r for r in races if r['period'] == 'train']
    hold = [r for r in races if r['period'] == 'holdout']

    tr = eval_cell(train, pall_tri, pall_tri_o)
    ho = eval_cell(hold, pall_tri, pall_tri_o)
    print_period('train', tr)
    s_tri, s_trio, _ = print_period('holdout', ho)

    sections = [
        '## 対象',
        'zone C & cross_n < 3（現行 3連単 RRR 2-4-7 セル）',
        '## holdout 結論',
        (
            f"3連複化で的中 {s_tri['hit_rate']:.1f}%→{s_trio['hit_rate']:.1f}%"
            f"（+{s_trio['hit_rate'] - s_tri['hit_rate']:.1f}pp）。"
            f" ROI {s_tri['roi']:.1f}%→{s_trio['roi']:.1f}%。"
            f" 損失/100円 {s_tri['loss_per_100']:.1f}→{s_trio['loss_per_100']:.1f}。"
            f" ROI下限{hc.ROI_FLOOR_DEFAULT}%: {'はい' if s_trio['roi'] >= hc.ROI_FLOOR_DEFAULT else 'いいえ'}"
        ),
    ]
    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_trio_conversion.md')
    hc.write_memo(memo, 'verified_trio_conversion', 'N2 3連単→3連複化の的中増分', sections)
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
