# -*- coding: utf-8 -*-
"""券種選択第2フェーズ: live score版馬連・馬単 + 簡略ルール holdout 検証。

- Rank(live score 代理) = ability_score 昇順（小=強）。recommend_quinella と同じく
  スコア最高=Rank1 を軸、2-7位を相手6頭。
- cross_n = Rank上位4 ∩ VH上位4（consensus_view.py と同一）
- train <= 20241231 で Rule B の cross_n 閾値のみ決定、holdout は固定

Usage: python scripts/bettype_selector_phase2.py
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
TRAIN_END_DAY = 20241231
HOLDOUT_FROM_DAY = 20250101
UNIT = 100
BOOT_N = 2000
BOOT_SEED = 42
MIN_C_BRANCH = 400


def load_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(dict)
    for rk, bt, combo, pay in con.execute(
            "SELECT race_key, bet_type, combo, payout FROM payouts "
            "WHERE bet_type IN ('馬連','馬単','3連複','3連単')"):
        c = str(combo).strip()
        if not c.isdigit():
            continue
        rk, pay = str(rk), float(pay)
        if bt in ('馬連',) and len(c) == 4:
            key = tuple(sorted((int(c[:2]), int(c[2:]))))
            out[rk][('馬連', 'pair', key)] = pay
        elif bt == '馬単' and len(c) == 4:
            out[rk][('馬単', 'order', (int(c[:2]), int(c[2:])))] = pay
        elif bt == '3連複' and len(c) == 6:
            t = (int(c[:2]), int(c[2:4]), int(c[4:6]))
            out[rk][('3連複', 'trio', tuple(sorted(t)))] = pay
        elif bt == '3連単' and len(c) == 6:
            out[rk][('3連単', 'trif', (int(c[:2]), int(c[2:4]), int(c[4:6])))] = pay
    con.close()
    return out


def v_legs(rows):
    ninki = {int(r['umaban']): int(r['ninki']) for r in rows}
    _et3, scored = hunter_elite_top3(rows)
    _lab, elite, net = hunter_ranks(ninki, scored, pop_min=6)
    out = []
    for u in list(elite[:2]) + list(net[:1]):
        if u not in out:
            out.append(u)
    return out


def trio_unordered(a, b, c):
    out = set()
    for x in a:
        for y in b:
            if y == x:
                continue
            for z in c:
                if z in (x, y):
                    continue
                out.add(tuple(sorted((x, y, z))))
    return out


def pop_structure(fav1, r21, r31):
    if fav1 <= 2.5 and r21 >= 1.4:
        return '1強'
    if fav1 <= 4.0 and r21 <= 1.25:
        return '2強'
    if r31 <= 1.35:
        return '上位拮抗'
    return 'その他'


def pair_bet(axis, opps, top2, win12, pm, kind):
    if kind == 'umaren':
        tix = {tuple(sorted((axis, o))) for o in opps}
        cost = len(tix) * UNIT
        ret = pm.get(('馬連', 'pair', top2), 0.0) if top2 in tix else 0.0
    else:
        tix = {(axis, o) for o in opps}
        cost = len(tix) * UNIT
        ret = pm.get(('馬単', 'order', win12), 0.0) if win12 in tix else 0.0
    return dict(cost=cost, ret=ret, hit=int(ret > 0), n_points=len(tix))


def build_races(pall):
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'chakujun',
        'ability_score', 'vh2_score',
    ])
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore', 'field_size'])
    h['race_key'] = h['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    rows_out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        try:
            jyo = int(float(g['jyo'].iloc[0]))
        except (TypeError, ValueError):
            continue
        if not (1 <= jyo <= 10):
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
        if zone == 'BA':
            continue

        ninki_ord = [int(x) for x in g.sort_values('ninki')['umaban']]
        rank_ord = [int(x) for x in g.sort_values('ability_score', ascending=True)['umaban']]
        vh_ord = [int(x) for x in g.sort_values('vh2_score', ascending=False, na_position='last')['umaban']]
        if len(ninki_ord) < 7 or len(rank_ord) < 7:
            continue

        fin = g.sort_values('chakujun')
        top3 = [int(x) for x in fin['umaban'][:3]]
        if len(top3) < 3:
            continue
        win_trif = tuple(top3)
        win_trio = tuple(sorted(top3))
        top2 = tuple(sorted(top3[:2]))
        win12 = (top3[0], top3[1])

        recs = g.to_dict('records')
        ninki_map = {int(r['umaban']): int(r['ninki']) for r in recs}
        cross_n = len(set(rank_ord[:4]) & set(vh_ord[:4]))
        vh_legs_list = v_legs(recs)

        fav_odds = sorted(odds_list)
        fav1 = fav_odds[0]
        fav2 = fav_odds[1] if len(fav_odds) > 1 else fav1
        fav3 = fav_odds[2] if len(fav_odds) > 2 else fav2
        r21 = fav2 / fav1 if fav1 else 99.0
        r31 = fav3 / fav1 if fav1 else 99.0
        rank1_ninki = ninki_map.get(rank_ord[0], 99)

        pm = pall.get(rk)
        if not pm:
            continue

        bets = {}
        bets['umaren_ninki'] = pair_bet(ninki_ord[0], ninki_ord[1:7], top2, win12, pm, 'umaren')
        bets['umatan_ninki'] = pair_bet(ninki_ord[0], ninki_ord[1:7], top2, win12, pm, 'umatan')
        bets['umaren_rank'] = pair_bet(rank_ord[0], rank_ord[1:7], top2, win12, pm, 'umaren')
        bets['umatan_rank'] = pair_bet(rank_ord[0], rank_ord[1:7], top2, win12, pm, 'umatan')

        if zone == 'D':
            a, b, p3, p4 = ninki_ord[0], ninki_ord[1], ninki_ord[2], ninki_ord[3]
            trio_tix = {tuple(sorted((a, b, p3))), tuple(sorted((a, b, p4)))}
        else:
            trio_tix = trio_unordered(rank_ord[:2], rank_ord[:3], rank_ord[:6])
        cost = len(trio_tix) * UNIT
        ret = pm.get(('3連複', 'trio', win_trio), 0.0) if win_trio in trio_tix else 0.0
        bets['trio'] = dict(cost=cost, ret=ret, hit=int(ret > 0), n_points=len(trio_tix))

        if vh_legs_list:
            nnv_tix = set(build_trifecta_formation(ninki_ord[:2], ninki_ord[:4], vh_legs_list))
            c2 = len(nnv_tix) * UNIT
            r2 = pm.get(('3連単', 'trif', win_trif), 0.0) if win_trif in nnv_tix else 0.0
            bets['trifecta_nnv'] = dict(cost=c2, ret=r2, hit=int(r2 > 0), n_points=len(nnv_tix))
        rrr_tix = set(build_trifecta_formation(rank_ord[:2], rank_ord[:4], rank_ord[:7]))
        c3 = len(rrr_tix) * UNIT
        r3 = pm.get(('3連単', 'trif', win_trif), 0.0) if win_trif in rrr_tix else 0.0
        bets['trifecta_rrr'] = dict(cost=c3, ret=r3, hit=int(r3 > 0), n_points=len(rrr_tix))

        period = 'train' if day_val <= TRAIN_END_DAY else 'holdout'
        rows_out.append(dict(
            race_key=rk, day=day_val, year=day_val // 10000,
            period=period, zone=zone, vscore=vscore,
            n_horses=len(g), fav1=fav1, r21=r21, r31=r31,
            cross_n=cross_n, vh_n_legs=len(vh_legs_list),
            rank1_ninki=rank1_ninki, pop_struct=pop_structure(fav1, r21, r31),
            field_size=int(getattr(m, 'field_size', len(g)) or len(g)),
            bets=bets,
        ))
    return rows_out


def max_losing_streak(hits):
    m = c = 0
    for h in hits:
        c = 0 if h else c + 1
        m = max(m, c)
    return m


def block_bootstrap_roi(costs, rets, days, n_boot=BOOT_N, seed=BOOT_SEED):
    rng = np.random.default_rng(seed)
    costs = np.asarray(costs, dtype=np.float64)
    rets = np.asarray(rets, dtype=np.float64)
    days = np.asarray(days)
    uniq, inv = np.unique(days, return_inverse=True)
    n_blocks = len(uniq)
    block_idx = [np.where(inv == i)[0] for i in range(n_blocks)]
    rois = np.empty(n_boot, dtype=np.float64)
    for _ in range(n_boot):
        picks = rng.integers(0, n_blocks, size=n_blocks)
        idx = np.concatenate([block_idx[picks[i]] for i in range(n_blocks)])
        st = costs[idx].sum()
        rois[_] = rets[idx].sum() / st * 100 if st else 0.0
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))


def eval_rule(rows, pick_fn):
    recs = []
    for r in rows:
        bt = pick_fn(r)
        if bt is None or bt not in r['bets']:
            continue
        b = r['bets'][bt]
        recs.append(dict(
            day=r['day'], year=r['year'], zone=r['zone'],
            pick=bt, cost=b['cost'], ret=b['ret'], hit=b['hit'],
        ))
    if not recs:
        return None
    costs = [x['cost'] for x in recs]
    rets = [x['ret'] for x in recs]
    hits = [x['hit'] for x in recs]
    days = [x['day'] for x in recs]
    stake = sum(costs)
    payout = sum(rets)
    roi_lo, roi_hi = block_bootstrap_roi(costs, rets, days)
    by_year = defaultdict(lambda: [0.0, 0.0])
    for x in recs:
        by_year[x['year']][0] += x['cost']
        by_year[x['year']][1] += x['ret']
    yr_roi = {y: v[1] / v[0] * 100 if v[0] else 0 for y, v in by_year.items()}
    by_zone = defaultdict(list)
    for x in recs:
        by_zone[x['zone']].append(x)
    zone_roi = {}
    for z, sub in by_zone.items():
        sc = sum(s['cost'] for s in sub)
        sr = sum(s['ret'] for s in sub)
        zone_roi[z] = sr / sc * 100 if sc else 0
    return dict(
        n=len(recs), hits=sum(hits), hit_rate=sum(hits) / len(recs) * 100,
        roi=payout / stake * 100 if stake else 0,
        roi_lo95=roi_lo, roi_hi95=roi_hi,
        max_losing_streak=max_losing_streak(hits),
        total_cost=stake, total_payout=payout,
        year_roi=yr_roi, zone_roi=zone_roi, picks=recs,
    )


def agg_single(rows, bet_key):
    sub = [r for r in rows if bet_key in r['bets']]
    costs, rets, hits, days = [], [], [], []
    for r in sub:
        b = r['bets'][bet_key]
        costs.append(b['cost'])
        rets.append(b['ret'])
        hits.append(b['hit'])
        days.append(r['day'])
    if not costs:
        return None
    stake, payout = sum(costs), sum(rets)
    lo, hi = block_bootstrap_roi(costs, rets, days)
    return dict(
        n=len(sub), hit_rate=sum(hits) / len(sub) * 100,
        roi=payout / stake * 100, roi_lo95=lo, roi_hi95=hi,
        avg_points=sum(r['bets'][bet_key]['n_points'] for r in sub) / len(sub),
        avg_cost=stake / len(sub),
        avg_pay=np.mean([r['bets'][bet_key]['ret'] for r in sub if r['bets'][bet_key]['hit']]) if sum(hits) else 0,
    )


def pick_zone_default(r):
    return 'trio' if r['zone'] == 'D' else 'trifecta_nnv'


def pick_rule_b(r, cross_thresh):
    if r['zone'] == 'D':
        return 'trio'
    if r['zone'] == 'C':
        if cross_thresh is not None and r['cross_n'] >= cross_thresh:
            return 'trio'
        return 'trifecta_nnv'
    return 'trio'


def pick_rule_c(r, cross_thresh):
    if r['zone'] == 'D':
        if r['fav1'] <= 2.0 and r['rank1_ninki'] == 1:
            return 'umatan_rank'
        return 'trio'
    return pick_rule_b(r, cross_thresh)


def train_cross_threshold(train_rows):
    """C zone のみ: cross_n >= T なら3連複、else NNV。T∈{3,4}を train ROI で選択。"""
    best_t, best_roi = None, -1.0
    c_rows = [r for r in train_rows if r['zone'] == 'C']
    base = eval_rule(c_rows, lambda r: 'trifecta_nnv')
    base_roi = base['roi'] if base else 0
    for t in (3, 4):
        sub_c = [r for r in c_rows if r['cross_n'] >= t]
        sub_n = [r for r in c_rows if r['cross_n'] < t]
        if len(sub_c) < MIN_C_BRANCH or len(sub_n) < MIN_C_BRANCH:
            continue
        e = eval_rule(c_rows, lambda r, tt=t: pick_rule_b(r, tt))
        if e and e['roi'] > best_roi:
            best_roi = e['roi']
            best_t = t
    if best_t is None or best_roi <= base_roi:
        return None, 'C常にNNV（trainで例外なし）'
    return best_t, f'C: cross_n>={best_t}→3連複、else NNV'


def print_defs():
    print('=' * 78)
    print('■ STEP 1: 定義棚卸し')
    print('=' * 78)
    print('live score (holdout代理): ability_score 昇順=Rank1が最強')
    print('  ※ライブ LTR は高いほど強い（符号反転）。CSV は playbook と同じ Rank 代理。')
    print('cross_n: len(Rank上位4 ∩ VH上位4) — consensus_view.py L433-435')
    print('zone: formation_stats — D 0-49 / C 50-69 / BA 70+')
    print('VH穴: hunter_elite_top3 + hunter_ranks → 精鋭1,2 + 広域1 (pop>=6)')
    print('馬連/馬単 ninki版: 人気1軸×2-7 (6点) | rank版: Rank1軸×2-7 (recommend_quinella 構造)')
    print('3連複: D=playbook 2点 / C=Rank2-3-6')
    print('3連単 NNV: 人気2×4×VH穴3 (_nnv_rrv_whatif) — playbook未配線')
    print('3連単 RRR: Rank2-4-7 30点 (playbook C ライブ既定)')
    print()


def compare_pair(rows, title, ninki_key, rank_key):
    print(f'\n--- {title} ---')
    a, b = agg_single(rows, ninki_key), agg_single(rows, rank_key)
    if not a or not b:
        return
    print(f"  {'':8} {'R':>6} {'的中%':>7} {'ROI%':>7} {'CI95':>15} {'平均点':>6}")
    print(f"  {'人気軸':>8} {a['n']:>6} {a['hit_rate']:>6.1f} {a['roi']:>6.1f} "
          f"{a['roi_lo95']:.1f}-{a['roi_hi95']:.1f} {a['avg_points']:>6.1f}")
    print(f"  {'Rank軸':>8} {b['n']:>6} {b['hit_rate']:>6.1f} {b['roi']:>6.1f} "
          f"{b['roi_lo95']:.1f}-{b['roi_hi95']:.1f} {b['avg_points']:>6.1f}")
    print(f"  差(Rank-人気): 的中{b['hit_rate']-a['hit_rate']:+.1f}pp  ROI{b['roi']-a['roi']:+.1f}pp")


def print_rule_result(name, res):
    if not res:
        print(f'  {name}: (0R)')
        return
    yrs = ' / '.join(f"{y}:{v:.0f}%" for y, v in sorted(res['year_roi'].items()))
    zns = ' / '.join(f"{z}:{v:.0f}%" for z, v in sorted(res['zone_roi'].items()))
    print(f"  {name:<22} {res['n']:>5}R  的中{res['hit_rate']:>5.1f}%  "
          f"ROI{res['roi']:>6.1f}%  CI[{res['roi_lo95']:.0f}-{res['roi_hi95']:.0f}]  "
          f"連敗{res['max_losing_streak']:>3}  年:{yrs}  zone:{zns}")


def relative_winner(rows, zone):
    sub = [r for r in rows if r['zone'] == zone]
    keys = ('trio', 'trifecta_nnv', 'umaren_rank', 'umatan_rank')
    rois = {}
    for k in keys:
        a = agg_single(sub, k)
        rois[k] = a['roi'] if a else 0
    return rois


def write_memo(path, train_thresh, thresh_desc, hold, train, rule_results, nnv_rrr):
    labels = dict(
        always_trio='常に3連複', always_nnv='常にNNV',
        zone_default='ゾーン既定', rule_a='RuleA', rule_b='RuleB',
        rule_c='RuleC', rule_c_umaren='RuleC+馬連',
    )
    lines = [
        '# verified_bettype_selector_phase2',
        '',
        'description: live score版馬連・馬単 + zone+cross_n 簡略ルール holdout 検証',
        '',
        '## STEP 1 定義',
        '- **Rank/live score**: `ability_score` 昇順（小=強）。ライブ LTR は符号反転。',
        '- **cross_n**: Rank上位4 ∩ VH上位4（`consensus_view.py`）',
        '- **zone**: D 0-49 / C 50-69',
        '',
        f'## Rule B train 決定: {thresh_desc}',
        '',
        '## Q1: 馬連・馬単は live score で価値があるか？',
        '',
    ]
    for title, nk, rk in [('馬連', 'umaren_ninki', 'umaren_rank'),
                          ('馬単', 'umatan_ninki', 'umatan_rank')]:
        a, b = agg_single(hold, nk), agg_single(hold, rk)
        if a and b:
            lines.append(f"- **{title}** holdout: 人気 ROI {a['roi']:.1f}% → Rank ROI {b['roi']:.1f}% "
                         f"(的中 {a['hit_rate']:.1f}% → {b['hit_rate']:.1f}%)")
    lines.append('- **結論**: Rank軸でも ROI<100%。券種選択の主役にはならない（第1フェーズと同様）。')
    lines.extend(['', '## Q2: zone+cross_n 簡略ルールは holdout で優位か？', ''])
    for k, res in rule_results.items():
        if res:
            lines.append(f"- **{labels.get(k, k)}**: ROI {res['roi']:.1f}% "
                         f"(CI {res['roi_lo95']:.0f}-{res['roi_hi95']:.0f}%)")
    lines.extend(['', '## Q3: D=3連複 / C=NNV の再現性', ''])
    zd = rule_results.get('zone_default')
    if zd:
        lines.append(f"- holdout ROI {zd['roi']:.1f}% / 年別 {zd['year_roi']}")
    lines.extend(['', '## Q4: NNV live 配線価値（C zone vs RRR30点）', ''])
    if nnv_rrr:
        lines.append(f"- C holdout NNV: ROI {nnv_rrr['nnv']:.1f}% / 的中 {nnv_rrr['nnv_hr']:.1f}% / "
                     f"平均{nnv_rrr['nnv_pts']:.0f}点")
        lines.append(f"- C holdout RRR: ROI {nnv_rrr['rrr']:.1f}% / 的中 {nnv_rrr['rrr_hr']:.1f}% / "
                     f"平均{nnv_rrr['rrr_pts']:.0f}点")
    lines.extend([
        '', '## Q5: 第1段階ルールの単純化限界',
        '',
        '```',
        'zone → (D:3連複 / C:NNV)',
        '  + optional: C & cross_n>=T → 3連複  (Tはtrainのみで決定)',
        '  + optional: D & fav1<=2 & Rank1=1番人気 → 馬単Rank',
        '```',
        '',
        '## 再現', '```', 'python scripts/bettype_selector_phase2.py', '```',
    ])
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def main():
    print_defs()
    print('読込...', flush=True)
    pall = load_payouts()
    all_rows = build_races(pall)
    train = [r for r in all_rows if r['period'] == 'train']
    hold = [r for r in all_rows if r['period'] == 'holdout']
    print(f'  全{len(all_rows):,}R  train{len(train):,}  holdout{len(hold):,}\n')

    print('=' * 78)
    print('■ STEP 2: 馬連・馬単 ninki vs Rank（live score代理）')
    print('=' * 78)
    compare_pair(hold, 'holdout 全体', 'umaren_ninki', 'umaren_rank')
    compare_pair(hold, 'holdout 全体', 'umatan_ninki', 'umatan_rank')
    for z, zl in [('D', 'D鉄板'), ('C', 'C中庸')]:
        compare_pair([r for r in hold if r['zone'] == z], f'holdout {zl}', 'umaren_ninki', 'umaren_rank')
    for ps in ('1強', '2強', '上位拮抗', 'その他'):
        compare_pair([r for r in hold if r['pop_struct'] == ps], f'holdout {ps}', 'umatan_ninki', 'umatan_rank')

    cross_t, thresh_desc = train_cross_threshold(train)
    print('\n' + '=' * 78)
    print(f'■ STEP 3-4: ルール比較（Rule B train決定: {thresh_desc}）')
    print('=' * 78)

    rules = {
        'always_trio': lambda r: 'trio',
        'always_nnv': lambda r: 'trifecta_nnv',
        'zone_default': pick_zone_default,
        'rule_a': pick_zone_default,
        'rule_b': lambda r: pick_rule_b(r, cross_t),
        'rule_c': lambda r: pick_rule_c(r, cross_t),
        'rule_c_umaren': lambda r: (
            'umaren_rank' if r['zone'] == 'D' and r['fav1'] <= 2.5 and r['rank1_ninki'] <= 2
            else pick_rule_c(r, cross_t)),
    }
    rule_results = {}
    print(f"\n{'ルール':<22} {'holdout':>7}  詳細")
    print('-' * 78)
    for name, fn in rules.items():
        res = eval_rule(hold, fn)
        rule_results[name] = res
        print_rule_result(name, res)

    print('\n' + '=' * 78)
    print('■ STEP 5-6: 相対優劣（holdout・zone別）')
    print('=' * 78)
    for z in ('D', 'C'):
        rois = relative_winner(hold, z)
        best = max(rois, key=rois.get)
        print(f"  {z} zone: " + ' / '.join(f"{k}={v:.0f}%" for k, v in rois.items()))
        print(f"    → 相対最良: {best}")

    print('\n' + '=' * 78)
    print('■ STEP 7: NNV vs RRR（C zone holdout・live配線判断）')
    print('=' * 78)
    c_hold = [r for r in hold if r['zone'] == 'C']
    a_nnv = agg_single(c_hold, 'trifecta_nnv')
    a_rrr = agg_single(c_hold, 'trifecta_rrr')
    nnv_rrr = {}
    if a_nnv and a_rrr:
        nnv_rrr = dict(nnv=a_nnv['roi'], rrr=a_rrr['roi'],
                       nnv_hr=a_nnv['hit_rate'], rrr_hr=a_rrr['hit_rate'],
                       nnv_pts=a_nnv['avg_points'], rrr_pts=a_rrr['avg_points'])
        print(f"  NNV 2-4-7(VH穴): {a_nnv['n']}R  的中{a_nnv['hit_rate']:.1f}%  "
              f"ROI{a_nnv['roi']:.1f}%  {a_nnv['avg_points']:.0f}点  "
              f"CI[{a_nnv['roi_lo95']:.0f}-{a_nnv['roi_hi95']:.0f}]")
        print(f"  RRR 2-4-7(live): {a_rrr['n']}R  的中{a_rrr['hit_rate']:.1f}%  "
              f"ROI{a_rrr['roi']:.1f}%  {a_rrr['avg_points']:.0f}点  "
              f"CI[{a_rrr['roi_lo95']:.0f}-{a_rrr['roi_hi95']:.0f}]")
        # 年別
        for label, key in [('NNV', 'trifecta_nnv'), ('RRR', 'trifecta_rrr')]:
            by_y = defaultdict(lambda: [0.0, 0.0])
            for r in c_hold:
                b = r['bets'].get(key)
                if not b:
                    continue
                by_y[r['year']][0] += b['cost']
                by_y[r['year']][1] += b['ret']
            ys = ' '.join(f"{y}:{v[1]/v[0]*100:.0f}%" for y, v in sorted(by_y.items()) if v[0])
            print(f"    {label} 年別: {ys}")

    # CSV
    csv_path = os.path.join(ROOT, 'data', 'bettype_selector_phase2.csv')
    flat = []
    for r in all_rows:
        row = {k: v for k, v in r.items() if k != 'bets'}
        for bk, b in r['bets'].items():
            for kk, vv in b.items():
                row[f'{bk}_{kk}'] = vv
        flat.append(row)
    pd.DataFrame(flat).to_csv(csv_path, index=False, encoding='utf-8')

    md_path = os.path.join(ROOT, 'repo', 'memory', 'verified_bettype_selector_phase2.md')
    write_memo(md_path, cross_t, thresh_desc, hold, train, rule_results, nnv_rrr)
    print(f'\n出力: {csv_path}')
    print(f'出力: {md_path}')


if __name__ == '__main__':
    main()
