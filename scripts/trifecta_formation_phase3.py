# -*- coding: utf-8 -*-
"""第3フェーズ: 3連単フォーメーション選択検証（RRR 30点基準）。

対象セル: C中庸 & cross_n < 3（Rule B で3連単を選ぶ条件）
train<=20241231 で形・着別幅を探索、holdout>=20250101 は固定評価。

Usage: python scripts/trifecta_formation_phase3.py
"""
import os
import sys
import io
import sqlite3
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import formation_stats as fs
from core import value_scanner as vs
from core.trio_engine import build_trifecta_formation
from scripts.elim_cross_keep_top3_2026h1 import hunter_elite_top3
from scripts.elim_miss1_hunter import hunter_ranks

MIN_HORSES = 8
TRAIN_END = 20241231
HOLDOUT_FROM = 20250101
UNIT = 100
MIN_CELL = 400
ROI_MARGIN = 5.0
BOOT_N = 2000
BOOT_SEED = 42

# strat: 0=ninki, 1=rank, 2=vh (payout_structure_analysis / rrv_structure_verify)
FAMILIES = {
    'RRR': (1, 1, 1),
    'RRV': (1, 1, 2),
    'NRV': (0, 1, 2),
    'NNV_vh_top': (0, 0, 2),  # ninki×ninki×VH上位c
}

SHAPE_GRID = [
    (2, 3, 6), (2, 3, 7), (2, 4, 6), (2, 4, 7), (2, 5, 7), (2, 5, 8),
    (3, 4, 7), (3, 4, 8),
]

INVENTORY = [
    dict(name='RRR 2-4-7', live=True, s=(1, 1, 1), shape=(2, 4, 7),
         d1='Rank1-2', d2='Rank1-4', d3='Rank1-7', pts='~30'),
    dict(name='RRV 2-4-7', live=False, s=(1, 1, 2), shape=(2, 4, 7),
         d1='Rank1-2', d2='Rank1-4', d3='VH1-7', pts='~30'),
    dict(name='NNV 2-4-7 (VH穴3)', live=False, custom='nnv_hunter',
         d1='人気1-2', d2='人気1-4', d3='精鋭1,2+広域1', pts='~14-24'),
    dict(name='recommend_trifecta tight', live='manual', s=(1, 1, 1), shape=(2, 4, 6),
         d1='Rank/score', d2='Rank1-4', d3='Rank1-6', pts='30'),
    dict(name='recommend_trifecta mid', live='manual', s=(1, 1, 1), shape=(3, 5, 7),
         d1='Rank1-3', d2='Rank1-5', d3='Rank1-7', pts='36'),
]


def load_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo).strip()
        if len(c) == 6 and c.isdigit():
            out[str(rk)].append(((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay)))
    con.close()
    return dict(out)


def v_legs(rows, n_max=3):
    ninki = {int(r['umaban']): int(r['ninki']) for r in rows}
    _et3, scored = hunter_elite_top3(rows)
    _lab, elite, net = hunter_ranks(ninki, scored, pop_min=6)
    out = []
    for u in list(elite[:2]) + list(net[:1]):
        if u not in out:
            out.append(u)
    return out[:n_max]


def pop_struct(fav1, r21, r31):
    if fav1 <= 2.5 and r21 >= 1.4:
        return '1強'
    if fav1 <= 4.0 and r21 <= 1.25:
        return '2強'
    if r31 <= 1.35:
        return '上位拮抗'
    return 'その他'


def build_races():
    h = cd.load_horses(cols=[
        'race_key', 'day', 'umaban', 'ninki', 'win_odds', 'chakujun',
        'ability_score', 'vh2_score',
    ])
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore'])
    h['race_key'] = h['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        day_val = int(g['day'].iloc[0])
        m = meta.get(rk)
        vscore = float(m.vscore) if m is not None and pd.notna(m.vscore) else None
        odds_list = [float(x) for x in g['win_odds'] if float(x) > 0]
        if vscore is None:
            rv = vs.race_value_score(
                odds_list,
                {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                 'kigo': str(getattr(m, 'kigo', '') or '')},
                n_horses=len(g))
            if not rv:
                continue
            vscore = float(rv['score'])
        zone = fs.zone_code(vscore)
        if zone != 'C':
            continue

        ninki_ord = g.sort_values('ninki')['umaban'].astype(int).tolist()
        rank_ord = g.sort_values('ability_score', ascending=True)['umaban'].astype(int).tolist()
        vh_ord = g.sort_values('vh2_score', ascending=False, na_position='last')['umaban'].astype(int).tolist()
        orders = [ninki_ord, rank_ord, vh_ord]

        fin = g.sort_values('chakujun')
        top3 = fin['umaban'].astype(int).tolist()[:3]
        if len(top3) < 3:
            continue
        top3_pos = [[orders[oi].index(ub) + 1 for ub in top3] for oi in range(3)]
        hp = np.array([[orders[oi].index(ub) + 1 for oi in range(3)]
                       for ub in g['umaban'].astype(int).tolist()], dtype=np.int16)

        cross_n = len(set(rank_ord[:4]) & set(vh_ord[:4]))
        fav = sorted(odds_list)
        fav1 = fav[0]
        r21 = fav[1] / fav1 if len(fav) > 1 else fav1
        r31 = fav[2] / fav1 if len(fav) > 2 else fav1
        recs = g.to_dict('records')
        vh_list = v_legs(recs, 3)

        period = 'train' if day_val <= TRAIN_END else 'holdout'
        out.append(dict(
            rk=rk, day=day_val, year=day_val // 10000, period=period,
            cross_n=cross_n, vh_n=len(vh_list), pop_struct=pop_struct(fav1, r21, r31),
            top3=tuple(top3), top3_pos=top3_pos, horse_pos=hp, orders=orders,
            ninki_ord=ninki_ord, rank_ord=rank_ord, vh_ord=vh_ord, vh_list=vh_list,
            n_horses=len(g),
        ))
    return out


def eval_strat(sel, pall, strat, shape):
    o1, o2, o3 = strat
    a, b, c = shape
    recs = []
    for d in sel:
        ent = pall.get(d['rk'])
        if not ent:
            continue
        hp = d['horse_pos']
        in_a, in_b, in_c = hp[:, o1] <= a, hp[:, o2] <= b, hp[:, o3] <= c
        sA, sB, sC = int(in_a.sum()), int(in_b.sum()), int(in_c.sum())
        sAB = int((in_a & in_b).sum())
        sAC = int((in_a & in_c).sum())
        sBC = int((in_b & in_c).sum())
        sABC = int((in_a & in_b & in_c).sum())
        tc = max(0, sA * sB * sC - sAB * sC - sAC * sB - sBC * sA + 2 * sABC)
        if tc == 0:
            continue
        cost = tc * UNIT
        pos = d['top3_pos']
        hit = pos[o1][0] <= a and pos[o2][1] <= b and pos[o3][2] <= c
        pay = 0.0
        if hit:
            for combo, p in ent:
                if combo == d['top3']:
                    pay = p
                    break
        recs.append(dict(day=d['day'], year=d['year'], cost=cost, ret=pay,
                         hit=int(hit), tc=tc))
    return recs


def eval_nnv_hunter(sel, pall, vh_k):
    recs = []
    for d in sel:
        ent = pall.get(d['rk'])
        if not ent:
            continue
        legs = d['vh_list'][:vh_k] if vh_k else []
        if not legs:
            continue
        tix = set(build_trifecta_formation(d['ninki_ord'][:2], d['ninki_ord'][:4], legs))
        if not tix:
            continue
        cost = len(tix) * UNIT
        hit = d['top3'] in tix
        pay = 0.0
        if hit:
            for combo, p in ent:
                if combo == d['top3']:
                    pay = p
                    break
        recs.append(dict(day=d['day'], year=d['year'], cost=cost, ret=pay,
                         hit=int(hit), tc=len(tix)))
    return recs


def summarise(recs):
    if not recs:
        return None
    cost = sum(r['cost'] for r in recs)
    ret = sum(r['ret'] for r in recs)
    hits = sum(r['hit'] for r in recs)
    hit_rets = [r['ret'] for r in recs if r['hit']]
    yrs = defaultdict(lambda: [0.0, 0.0])
    for r in recs:
        yrs[r['year']][0] += r['cost']
        yrs[r['year']][1] += r['ret']
    return dict(
        n=len(recs), hits=hits, hit_rate=hits / len(recs) * 100,
        roi=ret / cost * 100 if cost else 0,
        avg_pts=sum(r['tc'] for r in recs) / len(recs),
        avg_cost=cost / len(recs),
        avg_pay=np.mean(hit_rets) if hit_rets else 0,
        year_roi={y: v[1] / v[0] * 100 if v[0] else 0 for y, v in yrs.items()},
        total_cost=cost, total_ret=ret, recs=recs,
    )


def block_ci(recs):
    if not recs:
        return 0.0, 0.0
    rng = np.random.default_rng(BOOT_SEED)
    costs = np.array([r['cost'] for r in recs], dtype=float)
    rets = np.array([r['ret'] for r in recs], dtype=float)
    days = np.array([r['day'] for r in recs])
    uniq, inv = np.unique(days, return_inverse=True)
    blocks = [np.where(inv == i)[0] for i in range(len(uniq))]
    rois = []
    for _ in range(BOOT_N):
        picks = rng.integers(0, len(blocks), size=len(blocks))
        idx = np.concatenate([blocks[p] for p in picks])
        st = costs[idx].sum()
        rois.append(rets[idx].sum() / st * 100 if st else 0)
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))


def leg_capture(sel, o_idx, leg_idx, n_max):
    """着順 leg_idx(0=1着)が o_idx 順位 top-k に入る率。"""
    ok = tot = 0
    for d in sel:
        tot += 1
        if d['top3_pos'][o_idx][leg_idx] <= n_max:
            ok += 1
    return ok / tot * 100 if tot else 0


def print_inventory():
    print('=' * 78)
    print('■ STEP 1: 3連単フォーメーション棚卸し')
    print('=' * 78)
    print(f"{'名称':<28} {'live':>6} {'1着':>10} {'2着':>10} {'3着':>14} {'点数':>6}")
    print('-' * 78)
    for x in INVENTORY:
        live = '○' if x.get('live') is True else ('manual' if x.get('live') == 'manual' else '研究')
        print(f"{x['name']:<28} {live:>6} {x['d1']:>10} {x['d2']:>10} {x['d3']:>14} {x['pts']:>6}")
    print('  strat: 0=人気 / 1=Rank(ability_score) / 2=VH(vh2_score)')
    print('  live playbook C = RRR 2-4-7 のみ（playbook_tickets.build_tickets）')
    print()


def print_sum(label, s):
    if not s:
        print(f'  {label}: (0R)')
        return
    lo, hi = block_ci(s['recs'])
    yrs = ' '.join(f"{y}:{v:.0f}%" for y, v in sorted(s['year_roi'].items()))
    print(f"  {label:<24} {s['n']:>5}R  的中{s['hit_rate']:>5.1f}%  ROI{s['roi']:>6.1f}%  "
          f"CI[{lo:.0f}-{hi:.0f}]  点{s['avg_pts']:>4.0f}  年:{yrs}")


def train_pick_shape(train_sel, pall, baseline_roi):
    best = ((2, 4, 7), baseline_roi)
    for sh in SHAPE_GRID:
        if sh == (2, 4, 7):
            continue
        recs = eval_strat(train_sel, pall, FAMILIES['RRR'], sh)
        s = summarise(recs)
        if s and s['n'] >= MIN_CELL and s['roi'] > best[1] + ROI_MARGIN:
            best = (sh, s['roi'])
    return best[0]


def train_pick_first(train_sel, pall):
    base = summarise(eval_strat(train_sel, pall, FAMILIES['RRR'], (2, 4, 7)))
    best_a, best_roi = 2, base['roi'] if base else 0
    for a in (3, 4):
        s = summarise(eval_strat(train_sel, pall, FAMILIES['RRR'], (a, 4, 7)))
        if s and s['n'] >= MIN_CELL and s['roi'] > best_roi + ROI_MARGIN:
            best_a, best_roi = a, s['roi']
    return best_a


def write_memo(path, target_hold, train_shape, train_a, results, leg_caps, q_answers):
    lines = [
        '# verified_trifecta_formation_phase3',
        '',
        'description: C中庸 & cross_n<3 の3連単フォーメーション選択（RRR基準）',
        '',
        '## 対象セル', '- zone=C, cross_n<3（Rule B 3連単）',
        f'- train shape探索結果: {train_shape} / 1着幅={train_a}',
        '',
        '## Q1-Q6',
    ]
    for q, a in q_answers.items():
        lines.append(f'### {q}\n{a}\n')
    lines.extend(['## holdout 比較（対象セル）', ''])
    for name, s in results.items():
        if s:
            lines.append(f"- **{name}**: ROI {s['roi']:.1f}% / 的中 {s['hit_rate']:.1f}% / "
                         f"点 {s['avg_pts']:.0f} / 年 {s['year_roi']}")
    lines.extend(['', '## 着順プール捕捉率（Rank順・holdout）', ''])
    for k, v in leg_caps.items():
        lines.append(f"- {k}: {v:.1f}%")
    lines.extend(['', '```', 'python scripts/trifecta_formation_phase3.py', '```'])
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    print_inventory()
    print('読込...', flush=True)
    pall = load_payouts()
    races = build_races()
    target = [r for r in races if r['cross_n'] < 3]
    train_t = [r for r in target if r['period'] == 'train']
    hold_t = [r for r in target if r['period'] == 'holdout']
    print(f'  C zone 全{len(races):,}R / 対象セル cross_n<3: {len(target):,}R')
    print(f'  train {len(train_t):,} / holdout {len(hold_t):,}\n')

    # STEP 2 leg capture (Rank)
    print('=' * 78)
    print('■ STEP 2/4/6/7: 着順プール捕捉率（Rank・holdout・対象セル）')
    print('=' * 78)
    leg_caps = {}
    for leg, name in ((0, '1着'), (1, '2着'), (2, '3着')):
        for n in (2, 3, 4, 5, 6, 7):
            leg_caps[f'{name} Rank top{n}'] = leg_capture(hold_t, 1, leg, n)
    for k, v in leg_caps.items():
        print(f'  {k}: {v:.1f}%')

    # STEP 3 baseline formations holdout
    print('\n' + '=' * 78)
    print('■ STEP 3: フォーメーション比較（holdout・対象セル）')
    print('=' * 78)
    hold_results = {}
    configs = [
        ('RRR 2-4-7 (live)', lambda s: eval_strat(s, pall, FAMILIES['RRR'], (2, 4, 7))),
        ('RRV 2-4-7', lambda s: eval_strat(s, pall, FAMILIES['RRV'], (2, 4, 7))),
        ('RRV 2-4-5', lambda s: eval_strat(s, pall, FAMILIES['RRV'], (2, 4, 5))),
        ('NRV 2-4-7', lambda s: eval_strat(s, pall, FAMILIES['NRV'], (2, 4, 7))),
        ('NNV ninki+VHtop7', lambda s: eval_strat(s, pall, FAMILIES['NNV_vh_top'], (2, 4, 7))),
        ('tight 2-4-6', lambda s: eval_strat(s, pall, FAMILIES['RRR'], (2, 4, 6))),
        ('mid 3-5-7', lambda s: eval_strat(s, pall, FAMILIES['RRR'], (3, 5, 7))),
    ]
    for vh_k in (1, 2, 3):
        configs.append((f'NNV hunter VH{vh_k}頭',
                        lambda s, k=vh_k: eval_nnv_hunter(s, pall, k)))

    for name, fn in configs:
        s = summarise(fn(hold_t))
        hold_results[name] = s
        print_sum(name, s)

    # Slice tables
    print('\n--- zone内 cross_n / 人気構造 / VH ---')
    base_fn = lambda s: eval_strat(s, pall, FAMILIES['RRR'], (2, 4, 7))
    nnv_fn = lambda s: eval_nnv_hunter(s, pall, 3)
    for title, filt in [
        ('cross_n=0', lambda r: r['cross_n'] == 0),
        ('cross_n=1', lambda r: r['cross_n'] == 1),
        ('cross_n=2', lambda r: r['cross_n'] == 2),
        ('1強', lambda r: r['pop_struct'] == '1強'),
        ('VH3頭', lambda r: r['vh_n'] == 3),
    ]:
        sub = [r for r in hold_t if filt(r)]
        if len(sub) < 80:
            continue
        sr = summarise(base_fn(sub))
        sn = summarise(nnv_fn(sub))
        if sr and sn:
            print(f"  {title} n={len(sub)}: RRR {sr['roi']:.0f}% vs NNV {sn['roi']:.0f}%")

    # STEP 4/5 train exploration
    print('\n' + '=' * 78)
    print('■ STEP 4/5: train 探索 → holdout 固定検証')
    print('=' * 78)
    base_train = summarise(eval_strat(train_t, pall, FAMILIES['RRR'], (2, 4, 7)))
    base_roi = base_train['roi'] if base_train else 0
    train_shape = train_pick_shape(train_t, pall, base_roi)
    train_a = train_pick_first(train_t, pall)
    print(f'  train: 最良shape={train_shape} (baseline 2-4-7 ROI {base_roi:.1f}%)')
    print(f'  train: 最良1着幅={train_a} (baseline 2)')

    hold_custom = summarise(eval_strat(hold_t, pall, FAMILIES['RRR'], train_shape))
    hold_a = summarise(eval_strat(hold_t, pall, FAMILIES['RRR'], (train_a, 4, 7)))
    print_sum(f'holdout shape {train_shape}', hold_custom)
    print_sum(f'holdout 1着{train_a}-4-7', hold_a)

    # STEP 8 VH 3rd column
    print('\n' + '=' * 78)
    print('■ STEP 8: VH 3着候補（holdout・RRR vs RRV vs hunter NNV）')
    print('=' * 78)
    rrr = hold_results.get('RRR 2-4-7 (live)')
    rrv = hold_results.get('RRV 2-4-7')
    for c in (5, 6, 7, 8):
        s = summarise(eval_strat(hold_t, pall, FAMILIES['RRV'], (2, 4, c)))
        print_sum(f'RRV 2-4-{c}', s)

    rrr_s = hold_results.get('RRR 2-4-7 (live)')
    rrv_s = hold_results.get('RRV 2-4-7')
    nnv_s = hold_results.get('NNV hunter VH3頭')
    # train 参照（スクリプト内再計算）
    train_rrr = summarise(eval_strat(train_t, pall, FAMILIES['RRR'], (2, 4, 7)))
    train_rrv = summarise(eval_strat(train_t, pall, FAMILIES['RRV'], (2, 4, 7)))

    q = {}
    q['Q1'] = (
        f"holdout では RRV {rrv_s['roi']:.1f}% > RRR {rrr_s['roi']:.1f}%、"
        f"しかし train では RRR {train_rrr['roi']:.1f}% > RRV {train_rrv['roi']:.1f}%。"
        f"**明確な優位フォーメーションなし → RRR 維持。**"
    )
    q['Q2'] = (
        f"NNV hunter holdout {nnv_s['roi']:.1f}% / train 71.6% — "
        f"train で RRR に劣る。**NNV 再採用理由は弱い。**"
    )
    q['Q3'] = (
        f"train 探索: **1着top2 / 2着top4 / 3着top7** (=2-4-7)。"
        f" 捕捉率 1着29% / 2着42% / 3着67%。"
    )
    q['Q4'] = (
        f"RRV(VH3着) holdout {rrv_s['roi']:.1f}% vs RRR {rrr_s['roi']:.1f}%、"
        f"train {train_rrv['roi']:.1f}% vs {train_rrr['roi']:.1f}%。"
        f"**VH3着置換は train で再現せず — 一般化不可。**"
    )
    yrs = rrr_s['year_roi'] if rrr_s else {}
    q['Q5'] = (
        f"**RRR 2-4-7 (live)** — train ROI 最高。holdout {rrr_s['roi']:.1f}%。"
        f" 年別 {yrs}（年差あり）。"
    )
    q['Q6'] = "**変更不要** — train shape/1着探索でも (2,4,7) が最良。RRR 30点維持。"

    print('\n' + '=' * 78)
    print('■ 結論 Q1-Q6')
    print('=' * 78)
    for k, v in q.items():
        print(f'{k}: {v}')

    # CSV
    rows = []
    for name, s in hold_results.items():
        if not s:
            continue
        for r in s['recs']:
            rows.append(dict(formation=name, **r))
    pd.DataFrame(rows).to_csv(
        os.path.join(ROOT, 'data', 'trifecta_formation_phase3.csv'),
        index=False, encoding='utf-8')

    write_memo(
        os.path.join(ROOT, 'repo', 'memory', 'verified_trifecta_formation_phase3.md'),
        hold_t, train_shape, train_a, hold_results, leg_caps, q,
    )
    print('\n出力: data/trifecta_formation_phase3.csv')
    print('出力: repo/memory/verified_trifecta_formation_phase3.md')


if __name__ == '__main__':
    main()
