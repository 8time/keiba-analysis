# -*- coding: utf-8 -*-
"""レース特徴に応じた券種選択（馬連・馬単・3連複・3連単 NNV）の検証。

既存ロジック準拠（新特徴量を発明しない）:
  - 3連複 D: playbook_tickets 人気1-2 × 3-4 (2点)
  - 3連複 C: Rank 2-3-6 (vh_leg3_verify NNN 3連複形)
  - 3連単 NNV: _nnv_rrv_whatif 人気2×4 × VH穴3頭
  - 馬連/馬単: 人気1軸 × 人気2-7 (6点) — recommend_quinella の holdout 代理

train: day <= 20241231 / holdout: day >= 20250101

Usage: python scripts/bettype_selector_backtest.py
"""
import os
import sys
import io
import sqlite3
from collections import defaultdict
from itertools import combinations

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
MIN_CELL = 150
ROI_MARGIN_PP = 5.0

BET_TYPES = ('umaren', 'umatan', 'trio', 'trifecta_nnv', 'skip')


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
        if bt in ('馬連', '3連複') and len(c) == 4:
            key = tuple(sorted((int(c[:2]), int(c[2:]))))
            out[rk][(bt, 'pair', key)] = pay
        elif bt == '馬単' and len(c) == 4:
            key = (int(c[:2]), int(c[2:]))
            out[rk][(bt, 'order', key)] = pay
        elif bt in ('3連複', '3連単') and len(c) == 6:
            t = (int(c[:2]), int(c[2:4]), int(c[4:6]))
            kind = 'trio' if bt == '3連複' else 'trif'
            key = tuple(sorted(t)) if kind == 'trio' else t
            out[rk][(bt, kind, key)] = pay
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


def trio_tickets_unordered(a, b, c):
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


def build_races(pall):
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'chakujun',
        'ability_score', 'vh2_score', 'combo', 'elim_n', 'h7_fig', 'spurt_idx',
    ])
    r = cd.load_races(cols=[
        'race_key', 'kigo', 'is_handi1', 'vscore', 'field_size',
        'odds_entropy', 'mean_elim', 'n_elim3',
    ])
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
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
        vscore = None
        if m is not None and pd.notna(getattr(m, 'vscore', None)):
            vscore = float(m.vscore)
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

        g2 = g.sort_values('ninki')
        ninki_ord = [int(x) for x in g2['umaban']]
        if len(ninki_ord) < 7:
            continue
        g3 = g.sort_values('ability_score', ascending=True, na_position='last')
        rank_ord = [int(x) for x in g3['umaban']]
        g4 = g.sort_values('vh2_score', ascending=False, na_position='last')
        vh_ord = [int(x) for x in g4['umaban']]

        fin = g.sort_values('chakujun')
        top3 = [int(x) for x in fin['umaban'][:3]]
        if len(top3) < 3:
            continue
        win_trif = tuple(top3)
        win_trio = tuple(sorted(top3))
        top2 = tuple(sorted(top3[:2]))

        recs = g.to_dict('records')
        ninki_map = {int(r['umaban']): int(r['ninki']) for r in recs}
        ab1 = rank_ord[0]
        rank1_ninki = ninki_map.get(ab1, 99)
        ab_scores = g3['ability_score'].dropna()
        rank_gap = float(ab_scores.iloc[1] - ab_scores.iloc[0]) if len(ab_scores) >= 2 else 0.0

        vh_legs_list = v_legs(recs)
        vh_top4 = set(vh_ord[:4])
        rank_top4 = set(rank_ord[:4])
        cross_n = len(vh_top4 & rank_top4)

        fav_odds = sorted(odds_list)
        fav1 = fav_odds[0]
        fav2 = fav_odds[1] if len(fav_odds) > 1 else fav1
        fav3 = fav_odds[2] if len(fav_odds) > 2 else fav2
        r21 = fav2 / fav1 if fav1 else 99.0
        r31 = fav3 / fav1 if fav1 else 99.0
        ap = vs.arare_prob(odds_list, {'is_handicap': bool(getattr(m, 'is_handi1', 0))}, len(g))

        pm = pall.get(rk)
        if not pm:
            continue

        # --- 券種別チケット ---
        axis = ninki_ord[0]
        opps = ninki_ord[1:7]
        umaren_tix = {tuple(sorted((axis, o))) for o in opps}
        umatan_tix = {(axis, o) for o in opps}

        if zone == 'D':
            p3, p4 = ninki_ord[2], ninki_ord[3]
            a, b = ninki_ord[0], ninki_ord[1]
            trio_tix = {tuple(sorted((a, b, p3))), tuple(sorted((a, b, p4)))}
        else:
            trio_tix = trio_tickets_unordered(rank_ord[:2], rank_ord[:3], rank_ord[:6])

        if vh_legs_list:
            trif_tix = set(build_trifecta_formation(
                ninki_ord[:2], ninki_ord[:4], vh_legs_list))
        else:
            trif_tix = set()

        def pay_umaren():
            cost = len(umaren_tix) * UNIT
            ret = sum(pm.get(('馬連', 'pair', t), 0.0) for t in umaren_tix if t == top2)
            return cost, ret, int(ret > 0)

        def pay_umatan():
            cost = len(umatan_tix) * UNIT
            ret = 0.0
            if (win_trif[0], win_trif[1]) in umatan_tix:
                ret = pm.get(('馬単', 'order', (win_trif[0], win_trif[1])), 0.0)
            return cost, ret, int(ret > 0)

        def pay_trio():
            cost = len(trio_tix) * UNIT
            ret = pm.get(('3連複', 'trio', win_trio), 0.0) if win_trio in trio_tix else 0.0
            return cost, ret, int(ret > 0)

        def pay_trif():
            if not trif_tix:
                return 0, 0, 0
            cost = len(trif_tix) * UNIT
            ret = pm.get(('3連単', 'trif', win_trif), 0.0) if win_trif in trif_tix else 0.0
            return cost, ret, int(ret > 0)

        bets = {}
        for name, fn in (('umaren', pay_umaren), ('umatan', pay_umatan),
                         ('trio', pay_trio), ('trifecta_nnv', pay_trif)):
            c, r, h = fn()
            if c <= 0:
                continue
            bets[name] = dict(cost=c, ret=r, hit=h, n_points=c // UNIT)

        if not bets:
            continue

        period = 'train' if day_val <= TRAIN_END_DAY else 'holdout'

        rows_out.append(dict(
            race_key=rk, day=day_val, period=period, zone=zone, vscore=vscore,
            n_horses=len(g), fav1=fav1, r21=r21, r31=r31,
            arare_prob=float(ap) if ap is not None else np.nan,
            rank1_ninki=rank1_ninki, rank_gap=rank_gap, cross_n=cross_n,
            vh_n_legs=len(vh_legs_list),
            pop_struct=pop_structure(fav1, r21, r31),
            field_size=int(getattr(m, 'field_size', len(g)) or len(g)),
            odds_entropy=float(getattr(m, 'odds_entropy', np.nan) or np.nan),
            mean_elim=float(getattr(m, 'mean_elim', np.nan) or np.nan),
            bets=bets,
        ))
    return rows_out


def agg_bets(rows, bet_name):
    sub = [r for r in rows if bet_name in r['bets']]
    if not sub:
        return None
    cost = sum(r['bets'][bet_name]['cost'] for r in sub)
    ret = sum(r['bets'][bet_name]['ret'] for r in sub)
    hits = sum(r['bets'][bet_name]['hit'] for r in sub)
    pts = sum(r['bets'][bet_name]['n_points'] for r in sub)
    hit_rets = [r['bets'][bet_name]['ret'] for r in sub if r['bets'][bet_name]['hit']]
    nets = [r['bets'][bet_name]['ret'] - r['bets'][bet_name]['cost'] for r in sub]
    hit_profits = [r['bets'][bet_name]['ret'] - r['bets'][bet_name]['cost']
                   for r in sub if r['bets'][bet_name]['hit']]
    return dict(
        n=len(sub), hits=hits, hit_rate=hits / len(sub) * 100,
        roi=ret / cost * 100 if cost else 0,
        avg_points=pts / len(sub),
        avg_cost=cost / len(sub),
        avg_pay=np.mean(hit_rets) if hit_rets else 0.0,
        med_pay=np.median(hit_rets) if hit_rets else 0.0,
        avg_hit_profit=np.mean(hit_profits) if hit_profits else 0.0,
        miss_rate=(len(sub) - hits) / len(sub) * 100,
        total_cost=cost, total_ret=ret,
    )


def print_agg_table(rows, title):
    print(f'\n{"=" * 78}\n■ {title}\n{"=" * 78}')
    labels = dict(umaren='馬連', umatan='馬単', trio='3連複', trifecta_nnv='3連単NNV')
    print(f"{'券種':>10} {'R数':>6} {'的中率':>7} {'ROI%':>7} {'平均点':>6} {'投資/R':>8} "
          f"{'的中払戻':>8} {'外れ率':>7}")
    print('-' * 78)
    for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv'):
        a = agg_bets(rows, bt)
        if not a:
            continue
        print(f"{labels[bt]:>10} {a['n']:>6} {a['hit_rate']:>6.1f}% {a['roi']:>6.1f}% "
              f"{a['avg_points']:>6.1f} {a['avg_cost']:>7.0f} {a['avg_pay']:>8,.0f} "
              f"{a['miss_rate']:>6.1f}%")


def feature_slice(rows, key_fn, title):
    print(f'\n--- {title} ---')
    buckets = defaultdict(list)
    for r in rows:
        buckets[key_fn(r)].append(r)
    print(f"{'区分':>12} {'R':>5}  {'馬連ROI':>8} {'馬単ROI':>8} {'3連複ROI':>8} {'NNV ROI':>8} {'最良':>8}")
    print('-' * 72)
    for k in sorted(buckets, key=str):
        sub = buckets[k]
        if len(sub) < 80:
            continue
        rois = {}
        for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv'):
            a = agg_bets(sub, bt)
            rois[bt] = a['roi'] if a else 0
        best = max(rois, key=rois.get)
        labels = dict(umaren='馬連', umatan='馬単', trio='3連複', trifecta_nnv='NNV')
        print(f"{str(k):>12} {len(sub):>5}  {rois.get('umaren', 0):>7.1f}% "
              f"{rois.get('umatan', 0):>7.1f}% {rois.get('trio', 0):>7.1f}% "
              f"{rois.get('trifecta_nnv', 0):>7.1f}% {labels[best]:>8}")


def train_selection_rules(train_rows):
    """zone × pop_struct × fav1_bin で train ROI 最大券種を決定。"""
    rules = {}
    for zone in ('D', 'C'):
        zrows = [r for r in train_rows if r['zone'] == zone]
        for ps in ('1強', '2強', '上位拮抗', 'その他'):
            for fav_hi in (2.0, 3.0, 5.0, 99.0):
                fav_lo = {2.0: 0, 3.0: 2.0, 5.0: 3.0, 99.0: 5.0}[fav_hi]
                cell = [r for r in zrows if r['pop_struct'] == ps
                        and fav_lo < r['fav1'] <= fav_hi]
                if len(cell) < MIN_CELL:
                    continue
                rois = {}
                for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv'):
                    a = agg_bets(cell, bt)
                    rois[bt] = a['roi'] if a else -1
                ranked = sorted(rois.items(), key=lambda x: -x[1])
                best, best_roi = ranked[0]
                second_roi = ranked[1][1]
                if best_roi - second_roi < ROI_MARGIN_PP:
                    pick = 'trio' if zone == 'D' else 'trifecta_nnv'
                else:
                    pick = best
                rules[(zone, ps, fav_lo, fav_hi)] = dict(
                    pick=pick, n=len(cell), rois=rois, best_roi=best_roi,
                )
    return rules


def apply_rules(rows, rules):
    """ルール適用 + oracle 比較。"""
    picks = []
    for r in rows:
        fav = r['fav1']
        fav_bin = None
        for hi in (2.0, 3.0, 5.0, 99.0):
            lo = {2.0: 0, 3.0: 2.0, 5.0: 3.0, 99.0: 5.0}[hi]
            if lo < fav <= hi:
                fav_bin = (lo, hi)
                break
        key = (r['zone'], r['pop_struct'], fav_bin[0], fav_bin[1])
        rule = rules.get(key)
        if rule:
            pick = rule['pick']
        else:
            pick = 'trio' if r['zone'] == 'D' else 'trifecta_nnv'

        best_bt, best_net = None, -1e18
        for bt, b in r['bets'].items():
            net = b['ret'] - b['cost']
            if net > best_net:
                best_net = net
                best_bt = bt

        sel = r['bets'].get(pick)
        picks.append(dict(
            race_key=r['race_key'], day=r['day'], zone=r['zone'],
            pick=pick, oracle=best_bt,
            sel_cost=sel['cost'] if sel else 0,
            sel_ret=sel['ret'] if sel else 0,
            sel_hit=sel['hit'] if sel else 0,
            oracle_ret=r['bets'][best_bt]['ret'] if best_bt else 0,
            oracle_cost=r['bets'][best_bt]['cost'] if best_bt else 0,
        ))
    return picks


def eval_picks(picks, label):
    n = len(picks)
    cost = sum(p['sel_cost'] for p in picks)
    ret = sum(p['sel_ret'] for p in picks)
    hits = sum(p['sel_hit'] for p in picks)
    oc = sum(p['oracle_cost'] for p in picks)
    or_ = sum(p['oracle_ret'] for p in picks)
    agree = sum(1 for p in picks if p['pick'] == p['oracle'])
    print(f'\n--- {label} ---')
    print(f"  ルール選択: {n}R 的中{hits} ({hits/n*100:.1f}%)  ROI {ret/cost*100:.1f}%")
    print(f"  Oracle(事後最良): ROI {or_/oc*100:.1f}%  一致率 {agree/n*100:.1f}%")


def write_outputs(all_rows, train_rows, hold_rows, rules, picks_hold, path_csv, path_md):
    # CSV: race-level
    flat = []
    for r in all_rows:
        row = {k: v for k, v in r.items() if k != 'bets'}
        for bt, b in r['bets'].items():
            row[f'{bt}_cost'] = b['cost']
            row[f'{bt}_ret'] = b['ret']
            row[f'{bt}_hit'] = b['hit']
            row[f'{bt}_pts'] = b['n_points']
        flat.append(row)
    pd.DataFrame(flat).to_csv(path_csv, index=False, encoding='utf-8')

    # MD report
    lines = [
        '# verified_bettype_selector',
        '',
        'description: レース特徴に応じた券種選択（馬連・馬単・3連複・3連単NNV）の holdout 検証',
        '',
        '## 0. 既存ロジック棚卸し（変更なし）',
        '',
        '| 券種 | ライブ実装 | holdout代理 | VH 3着 |',
        '|------|-----------|------------|--------|',
        '| 3連複 | D: playbook 人気1-2×3-4 (2点) | 同左 / C: Rank2-3-6 | Dのみ研究NNV |',
        '| 3連単 | C: playbook Rank2-4-7 (30点) | **NNV** 人気2×4×VH穴3 (_nnv_rrv_whatif) | ○ |',
        '| 馬連 | manual recommend_quinella_exacta | 人気1軸×2-7 (6点) | 間接 |',
        '| 馬単 | 同上 exacta | 人気1→2-7 (6点) | 間接 |',
        '',
        '**注意**: UIラベル「D=NNV」は型の目安。ライブ券面は D=3連複2点 / C=Rank3連単30点。',
        'NNV 2-4-7 3連単は `_nnv_rrv_whatif.py` で検証済みだが playbook には未配線。',
        '',
        '## A. 券種別基本成績（holdout）',
        '',
    ]
    labels = dict(umaren='馬連', umatan='馬単', trio='3連複', trifecta_nnv='3連単NNV')
    lines.append('| 券種 | R数 | 的中率 | ROI | 平均点 | 投資/R |')
    lines.append('|------|-----|--------|-----|--------|--------|')
    for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv'):
        a = agg_bets(hold_rows, bt)
        if a:
            lines.append(f"| {labels[bt]} | {a['n']} | {a['hit_rate']:.1f}% | {a['roi']:.1f}% | "
                         f"{a['avg_points']:.1f} | {a['avg_cost']:.0f}円 |")

    lines.extend(['', '## B. レース特徴別の最適券種（holdout・ROI最大）', ''])
    for title, key_fn in [
        ('妙味度ゾーン', lambda r: f"{r['zone']} ({'鉄板' if r['zone']=='D' else '中庸'})"),
        ('人気構造', lambda r: r['pop_struct']),
        ('1番人気オッズ帯', lambda r: '≤2.0' if r['fav1'] <= 2 else ('2-3' if r['fav1'] <= 3 else ('3-5' if r['fav1'] <= 5 else '5+'))),
        ('VH穴3頭', lambda r: f"{r['vh_n_legs']}頭"),
        ('R×Vクロス数', lambda r: f"{r['cross_n']}頭"),
    ]:
        buckets = defaultdict(list)
        for r in hold_rows:
            buckets[key_fn(r)].append(r)
        lines.append(f'### {title}')
        lines.append('| 区分 | R数 | 馬連 | 馬単 | 3連複 | NNV | 最良 |')
        lines.append('|------|-----|------|------|-------|-----|------|')
        for k in sorted(buckets, key=str):
            sub = buckets[k]
            if len(sub) < 80:
                continue
            rois = {}
            for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv'):
                a = agg_bets(sub, bt)
                rois[bt] = a['roi'] if a else 0
            best = max(rois, key=rois.get)
            lines.append(
                f"| {k} | {len(sub)} | {rois['umaren']:.0f}% | {rois['umatan']:.0f}% | "
                f"{rois['trio']:.0f}% | {rois['trifecta_nnv']:.0f}% | {labels[best]} |"
            )
        lines.append('')

    lines.extend(['## C. 3連単 NNV 2-4-7 が強い条件（holdout）', ''])
    nnv_rows = hold_rows
    nnv_best = []
    for title, key_fn in [
        ('zone', lambda r: r['zone']),
        ('pop_struct', lambda r: r['pop_struct']),
        ('fav1', lambda r: '≤2.5' if r['fav1'] <= 2.5 else '2.5+'),
        ('vh_n', lambda r: r['vh_n_legs']),
    ]:
        buckets = defaultdict(list)
        for r in nnv_rows:
            buckets[key_fn(r)].append(r)
        for k, sub in sorted(buckets.items(), key=lambda x: str(x[0])):
            if len(sub) < 80:
                continue
            a = agg_bets(sub, 'trifecta_nnv')
            t = agg_bets(sub, 'trio')
            if a and t and a['roi'] > t['roi'] + 5:
                nnv_best.append(f"- {title}={k}: NNV ROI {a['roi']:.0f}% > 3連複 {t['roi']:.0f}% (n={len(sub)})")
    lines.extend(nnv_best or ['- holdout で NNV が 3連複を大きく上回る安定セルは限定的'])
    lines.extend(['', '## D. NNV より他券種が良い条件（holdout）', ''])
    escape = []
    for r in hold_rows:
        pass
    buckets = defaultdict(list)
    for r in hold_rows:
        buckets[r['pop_struct']].append(r)
    for k, sub in buckets.items():
        if len(sub) < 80:
            continue
        rois = {bt: (agg_bets(sub, bt) or {}).get('roi', 0)
                for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv')}
        best = max(rois, key=rois.get)
        if best != 'trifecta_nnv' and rois[best] > rois['trifecta_nnv'] + 8:
            escape.append(f"- {k}: {labels[best]} ROI {rois[best]:.0f}% vs NNV {rois['trifecta_nnv']:.0f}%")
    lines.extend(escape or ['- 人気構造別でも NNV 独壇はなく、3連複/馬連が競合'])

    # E holdout rule performance
    cost = sum(p['sel_cost'] for p in picks_hold)
    ret = sum(p['sel_ret'] for p in picks_hold)
    hits = sum(p['sel_hit'] for p in picks_hold)
    n = len(picks_hold)
    lines.extend([
        '', '## E. 券種選択ルール holdout 成績', '',
        'train で zone×人気構造×fav1帯ごとに ROI 最大券種を決定（差<5ppはゾーン既定にフォールバック）。',
        '',
        f"- ルール選択: {n}R / 的中率 {hits/n*100:.1f}% / ROI {ret/cost*100:.1f}%",
    ])
    for bt in ('umaren', 'umatan', 'trio', 'trifecta_nnv'):
        a = agg_bets(hold_rows, bt)
        if a:
            lines.append(f"- 常に{labels[bt]}: ROI {a['roi']:.1f}%")

    lines.extend([
        '', '## F. アプリ実装の価値', '',
        '- **現時点では「推奨券種」UIの実装価値は低〜中**。holdout でも全券種 ROI<100% が基本。',
        '- **ただし券種選択の考え方自体は有効**: D鉄板=3連複、2強+VH穴=NNV 3連単、上位拮抗=3連複/馬連、など方向性はデータと一致。',
        '- **第1段階（券種）と第2段階（フォーメーション）を分離**して設計すべき。NNV 2-4-7 は第2段階。',
        '- 実装するなら: zone + pop_struct + fav1 + cross_n から券種ヒントを出し、買い目は既存 playbook/NNV に委譲。',
        '',
        '## 再現', '```', 'python scripts/bettype_selector_backtest.py', '```',
    ])
    with open(path_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def print_inventory():
    print('=' * 78)
    print('■ 0. 既存券種ロジック棚卸し（ライブ = 変更しない）')
    print('=' * 78)
    print('3連複  D鉄板: playbook_tickets.build_tickets → 人気1-2 × 3-4 (2点)')
    print('3連単  C中庸: playbook_tickets → LTR Rank 2-4-7 (30点) = RRR')
    print('3連単  NNV:  _nnv_rrv_whatif → 人気2×4 × VH穴3 — 研究のみ・playbook未配線')
    print('馬連/馬単: trio_engine.recommend_quinella_exacta — 手動エンジン（app.py L11105+）')
    print('UI型ラベル: app.py L9484 — D=NNV / C=RRV|RRR（券面とは別・目安のみ）')
    print()


def main():
    print_inventory()
    print('データ読込...', flush=True)
    pall = load_payouts()
    all_rows = build_races(pall)
    train_rows = [r for r in all_rows if r['period'] == 'train']
    hold_rows = [r for r in all_rows if r['period'] == 'holdout']
    print(f'  全 {len(all_rows):,}R  train {len(train_rows):,}  holdout {len(hold_rows):,}\n')

    print_agg_table(hold_rows, 'A. holdout 券種別基本成績')
    print_agg_table(train_rows, 'A. train 券種別基本成績（参考）')

    print('\n' + '=' * 78)
    print('■ B/C/D. レース特徴別 ROI（holdout）')
    print('=' * 78)
    feature_slice(hold_rows, lambda r: r['zone'], '妙味度ゾーン')
    feature_slice(hold_rows, lambda r: r['pop_struct'], '人気構造')
    feature_slice(hold_rows, lambda r: '≤2.0' if r['fav1'] <= 2 else (
        '2-3' if r['fav1'] <= 3 else ('3-5' if r['fav1'] <= 5 else '5+')),
                  '1番人気オッズ帯')
    feature_slice(hold_rows, lambda r: r['vh_n_legs'], 'VH穴頭数')
    feature_slice(hold_rows, lambda r: r['cross_n'], 'R×Vクロス数')

    print('\n' + '=' * 78)
    print('■ C. 3連単 NNV 2-4-7 独立成績（holdout）')
    print('=' * 78)
    a = agg_bets(hold_rows, 'trifecta_nnv')
    if a:
        print(f"  全 holdout: {a['n']}R  的中{a['hit_rate']:.1f}%  ROI{a['roi']:.1f}%  "
              f"平均{a['avg_points']:.0f}点  的中払戻{a['avg_pay']:,.0f}円")

    print('\n' + '=' * 78)
    print('■ E. train 決定ルール → holdout 検証')
    print('=' * 78)
    rules = train_selection_rules(train_rows)
    print(f'  train から {len(rules)} セルルール生成')
    for key, val in sorted(rules.items()):
        z, ps, lo, hi = key
        print(f"    {z}/{ps}/fav({lo},{hi}] → {val['pick']} "
              f"(n={val['n']}, ROI={val['best_roi']:.1f}%)")

    picks_hold = apply_rules(hold_rows, rules)
    eval_picks(picks_hold, 'holdout ルール選択 vs Oracle')

    csv_path = os.path.join(ROOT, 'data', 'bettype_selector_backtest.csv')
    md_path = os.path.join(ROOT, 'repo', 'memory', 'verified_bettype_selector.md')
    write_outputs(all_rows, train_rows, hold_rows, rules, picks_hold, csv_path, md_path)
    print(f'\n出力: {csv_path}')
    print(f'出力: {md_path}')


if __name__ == '__main__':
    main()
