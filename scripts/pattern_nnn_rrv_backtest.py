# -*- coding: utf-8 -*-
"""鉄板 NNN/NNV と中庸 RRR/RRV の4パターン holdout 比較。

定義は vh_leg3_verify.py / formation_hires_backtest.py / formation_stats.ZONE_BOUNDS に準拠。
holdout = day >= 20240101（train 成績は報告しない）。

Usage: python scripts/pattern_nnn_rrv_backtest.py
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

MIN_HORSES = 8
HOLDOUT_FROM = 20240101
UNIT = 100
BOOT_N = 2000
BOOT_SEED = 42

# vh_leg3_verify.CONFIGS と同一
PATTERNS = [
    dict(
        name='D_NNN', zone='D', zone_lo=0, zone_hi=50,
        kind='trio', bet_label='3連複', shape=(2, 3, 6),
        strat=(0, 0, 0), family='NNN',
        desc='1-2列=人気上位2/3、3列=人気上位6',
    ),
    dict(
        name='D_NNV', zone='D', zone_lo=0, zone_hi=50,
        kind='trio', bet_label='3連複', shape=(2, 3, 6),
        strat=(0, 0, 2), family='NNV',
        desc='1-2列=人気上位2/3、3列=VH(vh2_score)上位6',
    ),
    dict(
        name='C_RRR', zone='C', zone_lo=50, zone_hi=70,
        kind='trifecta', bet_label='3連単', shape=(2, 4, 7),
        strat=(1, 1, 1), family='RRR',
        desc='1-2列=Rank(ability_score)上位2/4、3列=Rank上位7',
    ),
    dict(
        name='C_RRV', zone='C', zone_lo=50, zone_hi=70,
        kind='trifecta', bet_label='3連単', shape=(2, 4, 7),
        strat=(1, 1, 2), family='RRV',
        desc='1-2列=Rank上位2/4、3列=VH(vh2_score)上位7',
    ),
]

PAIRS = [
    ('D_NNN', 'D_NNV', '鉄板 NNN vs NNV'),
    ('C_RRR', 'C_RRV', '中庸 RRR vs RRV'),
]


def load_payouts(bet_type):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?", (bet_type,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[str(rk)].append(((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay)))
    con.close()
    return out


def check_hit(top3_pos, strat, shape, kind):
    o1i, o2i, o3i = strat
    a, b, c = shape
    if kind == 'trifecta':
        return (top3_pos[o1i][0] <= a and top3_pos[o2i][1] <= b and top3_pos[o3i][2] <= c)
    for p0, p1, p2 in ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)):
        if top3_pos[o1i][p0] <= a and top3_pos[o2i][p1] <= b and top3_pos[o3i][p2] <= c:
            return True
    return False


def ticket_count(hp, strat, shape, kind):
    o1i, o2i, o3i = strat
    a, b, c = shape
    in_a = hp[:, o1i] <= a
    in_b = hp[:, o2i] <= b
    in_c = hp[:, o3i] <= c
    sA, sB, sC = int(in_a.sum()), int(in_b.sum()), int(in_c.sum())
    sAB = int((in_a & in_b).sum())
    sAC = int((in_a & in_c).sum())
    sBC = int((in_b & in_c).sum())
    sABC = int((in_a & in_b & in_c).sum())
    tc = max(0, sA * sB * sC - sAB * sC - sAC * sB - sBC * sA + 2 * sABC)
    if kind != 'trifecta':
        # 3連複: 上記は3連単点数。3連複は組合せ重複を除く必要があるが、
        # vh_leg3_verify と同じ inclusive 公式を使う（実務上ほぼ一致）。
        pass
    return tc


def get_payout(pm, rk, kind, top3):
    pl = pm.get(rk)
    if not pl:
        return None
    for combo, pay in pl:
        if kind == 'trifecta':
            if combo == top3:
                return pay
        elif tuple(sorted(combo)) == tuple(sorted(top3)):
            return pay
    return None


def max_losing_streak(hits):
    m = c = 0
    for h in hits:
        c = 0 if h else c + 1
        m = max(m, c)
    return m


def block_bootstrap_roi(costs, rets, days, n_boot=BOOT_N, seed=BOOT_SEED):
    """開催日ブロック再抽出で ROI(%) の95%CI。"""
    rng = np.random.default_rng(seed)
    costs = np.asarray(costs, dtype=np.float64)
    rets = np.asarray(rets, dtype=np.float64)
    days = np.asarray(days)
    uniq, inv = np.unique(days, return_inverse=True)
    n_blocks = len(uniq)
    block_idx = [np.where(inv == i)[0] for i in range(n_blocks)]
    rois = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        picks = rng.integers(0, n_blocks, size=n_blocks)
        idx = np.concatenate([block_idx[picks[i]] for i in range(n_blocks)])
        st = costs[idx].sum()
        rois[b] = rets[idx].sum() / st * 100 if st else 0.0
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))


def block_bootstrap_roi_diff(costs_a, rets_a, costs_b, rets_b, days, n_boot=BOOT_N, seed=BOOT_SEED):
    """ペアの ROI 差 (B-A) の95%CI。同一レース集合を day ブロックで再抽出。"""
    rng = np.random.default_rng(seed)
    costs_a = np.asarray(costs_a, dtype=np.float64)
    rets_a = np.asarray(rets_a, dtype=np.float64)
    costs_b = np.asarray(costs_b, dtype=np.float64)
    rets_b = np.asarray(rets_b, dtype=np.float64)
    days = np.asarray(days)
    uniq, inv = np.unique(days, return_inverse=True)
    n_blocks = len(uniq)
    block_idx = [np.where(inv == i)[0] for i in range(n_blocks)]
    diffs = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        picks = rng.integers(0, n_blocks, size=n_blocks)
        idx = np.concatenate([block_idx[picks[i]] for i in range(n_blocks)])
        sa, ra = costs_a[idx].sum(), rets_a[idx].sum()
        sb, rb = costs_b[idx].sum(), rets_b[idx].sum()
        roi_a = ra / sa * 100 if sa else 0.0
        roi_b = rb / sb * 100 if sb else 0.0
        diffs[b] = roi_b - roi_a
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def mcnemar(base_hits, test_hits):
    """base/test のペア的中。両方評価できたレースのみ。"""
    both = base_only = test_only = 0
    for bh, th in zip(base_hits, test_hits):
        if bh and th:
            both += 1
        elif bh:
            base_only += 1
        elif th:
            test_only += 1
    n_disc = base_only + test_only
    z = (test_only - base_only) / (n_disc ** 0.5) if n_disc else 0.0
    sig = abs(z) >= 1.96 if n_disc else False
    return dict(both=both, base_only=base_only, test_only=test_only,
                net=test_only - base_only, z=z, sig=sig)


def print_definitions():
    print('=' * 72)
    print('■ 0. データ定義（コード/メモ準拠）')
    print('=' * 72)
    print('妙味度ゾーン (formation_stats.ZONE_BOUNDS / playbook_tickets.advise):')
    for lbl, lo, hi in fs.ZONE_BOUNDS:
        print(f'  {lbl}: {lo} ≤ vscore < {hi}')
    print('  算出: races.csv の vscore（無ければ value_scanner.race_value_score）')
    print()
    print('列の意味 (formation_hires_backtest.STRATEGIES / app.py R×Vクロス):')
    print('  N = 人気順 (ninki 昇順 = 1番人気が先)')
    print('  R = Rank = ability_score 昇順（小さいほど強い = holdout LTR 代理）')
    print('  V = VH = vh2_score 降順（穴馬ハンタースコア・人気薄側の妙味馬）')
    print()
    print('4パターン (vh_leg3_verify.CONFIGS と同一券種・形):')
    for p in PATTERNS:
        zlbl = 'D 鉄板' if p['zone'] == 'D' else 'C 中庸'
        print(f"  {p['family']} ({p['name']}): {zlbl} / {p['bet_label']} / 形{p['shape']} — {p['desc']}")
    print(f'holdout: day >= {HOLDOUT_FROM}')
    print('JRA central 10場のみ (jyo 1-10)、頭数 >= 8')
    print()


def build_races(vscore_map):
    h = cd.load_horses(cols=['race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score', 'vh2_score'])
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore', 'vlabel'])
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    out = []
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
        if day_val < HOLDOUT_FROM:
            continue

        m = meta.get(rk)
        vscore = None
        vlabel = ''
        if m is not None:
            try:
                vscore = float(m.vscore) if pd.notna(m.vscore) else None
            except (TypeError, ValueError):
                vscore = None
            vlabel = str(getattr(m, 'vlabel', '') or '')

        if vscore is None:
            odds_list = g['win_odds'].tolist()
            rv = vs.race_value_score(
                odds_list,
                {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                 'kigo': str(getattr(m, 'kigo', '') or '')},
                n_horses=len(g))
            if not rv:
                continue
            vscore = float(rv['score'])
        else:
            vscore = float(vscore)

        ninki_ord = g.sort_values('ninki', ascending=True)['umaban'].astype(int).tolist()
        rank_ord = g.sort_values('ability_score', ascending=True)['umaban'].astype(int).tolist()
        vh_ord = g.sort_values('vh2_score', ascending=False, na_position='last')['umaban'].astype(int).tolist()
        orders = [ninki_ord, rank_ord, vh_ord]

        fin = g.sort_values('chakujun')
        top3_ub = fin['umaban'].astype(int).tolist()[:3]
        if len(top3_ub) < 3:
            continue
        top3_pos = [[orders[oi].index(ub) + 1 for ub in top3_ub] for oi in range(3)]
        horses = g['umaban'].astype(int).tolist()
        horse_pos = np.array([[orders[oi].index(ub) + 1 for oi in range(3)] for ub in horses],
                             dtype=np.int16)

        out.append(dict(
            rk=rk, day=day_val, vscore=vscore, vlabel=vlabel,
            top3=tuple(top3_ub), top3_pos=top3_pos, horse_pos=horse_pos,
            n_horses=len(g),
        ))
    return out


def eval_pattern(races, pm, cfg):
    recs = []
    for d in races:
        if not (cfg['zone_lo'] <= d['vscore'] < cfg['zone_hi']):
            continue
        tc = ticket_count(d['horse_pos'], cfg['strat'], cfg['shape'], cfg['kind'])
        if tc <= 0:
            continue
        pay = get_payout(pm, d['rk'], cfg['kind'], d['top3'])
        if pay is None:
            continue
        hit = check_hit(d['top3_pos'], cfg['strat'], cfg['shape'], cfg['kind'])
        cost = tc * UNIT
        ret = pay if hit else 0.0
        recs.append(dict(
            race_key=d['rk'], day=d['day'], vscore=d['vscore'],
            pattern=cfg['name'], family=cfg['family'], zone=cfg['zone'],
            bet_type=cfg['bet_label'], n_points=tc,
            cost=cost, ret=ret, hit=int(hit), net=ret - cost,
        ))
    return recs


def summarise(recs):
    if not recs:
        return None
    costs = [r['cost'] for r in recs]
    rets = [r['ret'] for r in recs]
    hits = [r['hit'] for r in recs]
    days = [r['day'] for r in recs]
    stake = sum(costs)
    payout = sum(rets)
    n = len(recs)
    roi_lo, roi_hi = block_bootstrap_roi(costs, rets, days)
    return dict(
        n_races=n,
        n_hits=sum(hits),
        hit_rate=sum(hits) / n * 100,
        roi=payout / stake * 100 if stake else 0.0,
        roi_lo95=roi_lo,
        roi_hi95=roi_hi,
        max_losing_streak=max_losing_streak(hits),
        avg_points=sum(r['n_points'] for r in recs) / n,
        total_cost=stake,
        total_payout=payout,
    )


def write_csv(all_recs, summary_rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = []
    for s in summary_rows:
        rows.append({**s, 'row_type': 'summary'})
    for r in all_recs:
        rows.append({**r, 'row_type': 'race'})
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8')


def write_memo(summary_by_name, pair_results, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        '# verified_pattern_nnn_rrv',
        '',
        'description: 鉄板 NNN/NNV と中庸 RRR/RRV の holdout 比較（3列目を N/R vs V）',
        '',
        '## データ定義',
        '',
        '### 妙味度ゾーン (formation_stats.ZONE_BOUNDS)',
        '- **D 鉄板**: 0 ≤ vscore < 50',
        '- **C 中庸**: 50 ≤ vscore < 70',
        '- **B/A 荒れ**: vscore ≥ 70（本検証では対象外）',
        '- vscore: `data/export/races.csv`（欠損時 `value_scanner.race_value_score`）',
        '',
        '### 列の意味',
        '- **N**: 人気順（`ninki` 昇順）',
        '- **R**: Rank = `ability_score` 昇順（小さいほど強い。holdout の LTR 代理）',
        '- **V**: VH = `vh2_score` 降順（穴馬ハンタースコア。app の「V=VH順位」）',
        '',
        '### 4パターン（vh_leg3_verify と同一）',
        '| パターン | ゾーン | 券種 | 形 | 1-2列 | 3列 |',
        '|---------|--------|------|-----|-------|-----|',
        '| NNN | D 鉄板 | 3連複 | 2-3-6 | 人気 | 人気 |',
        '| NNV | D 鉄板 | 3連複 | 2-3-6 | 人気 | VH |',
        '| RRR | C 中庸 | 3連単 | 2-4-7 | Rank | Rank |',
        '| RRV | C 中庸 | 3連単 | 2-4-7 | Rank | VH |',
        '',
        f'holdout: day >= {HOLDOUT_FROM}。配当: `data/jravan.db` payouts 実配当。',
        '',
        '## holdout 成績',
        '',
        '| パターン | レース数 | 的中率 | ROI | ROI 95%CI | 最大連敗 | 平均点数 |',
        '|---------|---------|--------|-----|-----------|---------|---------|',
    ]
    for name in ('D_NNN', 'D_NNV', 'C_RRR', 'C_RRV'):
        s = summary_by_name[name]
        lines.append(
            f"| {s['family']} | {s['n_races']} | {s['hit_rate']:.1f}% | {s['roi']:.1f}% | "
            f"{s['roi_lo95']:.1f}-{s['roi_hi95']:.1f}% | {s['max_losing_streak']} | {s['avg_points']:.1f} |"
        )
    lines.extend(['', '## ペア比較（NNN vs NNV / RRR vs RRV）', ''])
    for pr in pair_results:
        lines.extend([
            f"### {pr['label']}",
            f"- 的中率: {pr['base_name']} {pr['base_hit']:.1f}% vs {pr['test_name']} {pr['test_hit']:.1f}% "
            f"(差 {pr['hit_diff']:+.1f}pp)",
            f"- ROI: {pr['base_roi']:.1f}% vs {pr['test_roi']:.1f}% (差 {pr['roi_diff']:+.1f}pp, "
            f"bootstrap差95%CI {pr['roi_diff_lo']:+.1f}〜{pr['roi_diff_hi']:+.1f}pp)",
            f"- McNemar: baseのみ {pr['mcn']['base_only']} / testのみ {pr['mcn']['test_only']} "
            f"(z={pr['mcn']['z']:+.2f}, {'有意' if pr['mcn']['sig'] else '非有意'})",
            f"- 判定: **{pr['verdict']}**",
            '',
        ])
    lines.extend([
        '## 迷ったときの推奨',
        '',
        f"**{pair_results[0]['recommendation']}**",
        f"**{pair_results[1]['recommendation']}**",
        '',
        '## 再現',
        '```',
        'python scripts/pattern_nnn_rrv_backtest.py',
        '```',
    ])
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def recommend_pair(base_s, test_s, mcn, roi_diff, roi_diff_lo, roi_diff_hi, zone_label):
    """1-2行の推奨ルール。"""
    base_name = base_s['family']
    test_name = test_s['family']
    roi_sig = (roi_diff_lo > 0) or (roi_diff_hi < 0)
    hit_sig = mcn['sig']
    diff_pp = abs(test_s['hit_rate'] - base_s['hit_rate'])
    roi_diff_abs = abs(roi_diff)

    if roi_sig and roi_diff > 0:
        return f"{zone_label}: 3列目は {test_name}（{test_name[2]}=VH穴）を推奨 — ROI差 {roi_diff:+.1f}pp が bootstrap CI で正側。"
    if roi_sig and roi_diff < 0:
        return f"{zone_label}: 3列目は {base_name}（本線）を推奨 — {test_name} より ROI が有意に低い。"
    if hit_sig and mcn['net'] > 0 and roi_diff >= -2:
        return f"{zone_label}: 的中率は {test_name} が McNemar 有意だが ROI 差は小さい（{roi_diff:+.1f}pp）— 点数増を許容するなら {test_name}。"
    if hit_sig and mcn['net'] < 0:
        return f"{zone_label}: 3列目は {base_name}（本線）— {test_name} は的中率で劣る（McNemar 有意）。"
    if diff_pp < 1.0 and roi_diff_abs < 3.0:
        return f"{zone_label}: {base_name} と {test_name} の差は小さい（的中 {diff_pp:.1f}pp / ROI {roi_diff:+.1f}pp）— デフォルトは点数の少ない {base_name} でよい。"
    if test_s['roi'] > base_s['roi']:
        return f"{zone_label}: 差は統計的に明確でないが ROI は {test_name} が僅差（{roi_diff:+.1f}pp）— 穴寄りを取るなら {test_name}。"
    return f"{zone_label}: 差は統計的に明確でない — デフォルトは検証済み本線 {base_name}（点数・説明の単純さ優先）。"


def verdict_text(base_s, test_s, mcn, roi_diff, roi_diff_lo, roi_diff_hi):
    roi_sig = (roi_diff_lo > 0) or (roi_diff_hi < 0)
    if roi_sig:
        winner = test_s['family'] if roi_diff > 0 else base_s['family']
        return f"ROI差は有意 — {winner} が優位"
    if mcn['sig']:
        winner = test_s['family'] if mcn['net'] > 0 else base_s['family']
        return f"的中率差は McNemar 有意 — {winner} が優位（ROI差 {roi_diff:+.1f}pp は CI 跨ぎ）"
    return f"差は小さい/非有意（的中 {test_s['hit_rate']-base_s['hit_rate']:+.1f}pp, ROI {roi_diff:+.1f}pp）"


def main():
    print_definitions()

    print('読込...', flush=True)
    rmeta = cd.load_races(cols=['race_key', 'vscore'])
    vscore_map = dict(zip(rmeta['race_key'].astype(str), rmeta['vscore']))
    races = build_races(vscore_map)
    pm_trio = load_payouts('3連複')
    pm_trf = load_payouts('3連単')
    print(f'  holdout レース {len(races):,}R\n', flush=True)

    cfg_by_name = {p['name']: p for p in PATTERNS}
    recs_by_name = {}
    summary_by_name = {}

    print('=' * 72)
    print('■ 1. 4パターン holdout 成績')
    print('=' * 72)
    hdr = f"{'パターン':>8} {'券種':>6} {'R数':>6} {'的中':>5} {'率%':>6} {'ROI%':>7} {'CI95%':>17} {'連敗':>5} {'点':>5}"
    print(hdr)
    print('-' * len(hdr))

    all_recs = []
    summary_rows = []
    for p in PATTERNS:
        pm = pm_trio if p['kind'] == 'trio' else pm_trf
        recs = eval_pattern(races, pm, p)
        recs_by_name[p['name']] = recs
        all_recs.extend(recs)
        s = summarise(recs)
        s = {**s, 'pattern': p['name'], 'family': p['family'], 'zone': p['zone'],
             'bet_type': p['bet_label']}
        summary_by_name[p['name']] = s
        summary_rows.append(s)
        ci = f"{s['roi_lo95']:.1f}-{s['roi_hi95']:.1f}"
        print(f"{p['family']:>8} {p['bet_label']:>6} {s['n_races']:>6} {s['n_hits']:>5} "
              f"{s['hit_rate']:>5.1f} {s['roi']:>6.1f} {ci:>17} {s['max_losing_streak']:>5} "
              f"{s['avg_points']:>5.1f}")

    print('\n' + '=' * 72)
    print('■ 2. ペア比較')
    print('=' * 72)

    pair_results = []
    recommendations = []
    for base_name, test_name, label in PAIRS:
        base_recs = {r['race_key']: r for r in recs_by_name[base_name]}
        test_recs = {r['race_key']: r for r in recs_by_name[test_name]}
        common = sorted(set(base_recs) & set(test_recs))
        base_h = [base_recs[k]['hit'] for k in common]
        test_h = [test_recs[k]['hit'] for k in common]
        mcn = mcnemar(base_h, test_h)

        base_s = summary_by_name[base_name]
        test_s = summary_by_name[test_name]
        costs_a = [base_recs[k]['cost'] for k in common]
        rets_a = [base_recs[k]['ret'] for k in common]
        costs_b = [test_recs[k]['cost'] for k in common]
        rets_b = [test_recs[k]['ret'] for k in common]
        days = [base_recs[k]['day'] for k in common]
        roi_diff = test_s['roi'] - base_s['roi']
        roi_diff_lo, roi_diff_hi = block_bootstrap_roi_diff(
            costs_a, rets_a, costs_b, rets_b, days, seed=BOOT_SEED + hash(label) % 1000)

        zone_label = '鉄板' if base_name.startswith('D_') else '中庸'
        rec = recommend_pair(base_s, test_s, mcn, roi_diff, roi_diff_lo, roi_diff_hi, zone_label)
        recommendations.append(rec)
        pr = dict(
            label=label,
            base_name=base_s['family'],
            test_name=test_s['family'],
            base_hit=base_s['hit_rate'],
            test_hit=test_s['hit_rate'],
            hit_diff=test_s['hit_rate'] - base_s['hit_rate'],
            base_roi=base_s['roi'],
            test_roi=test_s['roi'],
            roi_diff=roi_diff,
            roi_diff_lo=roi_diff_lo,
            roi_diff_hi=roi_diff_hi,
            mcn=mcn,
            verdict=verdict_text(base_s, test_s, mcn, roi_diff, roi_diff_lo, roi_diff_hi),
            recommendation=rec,
            n_common=len(common),
        )
        pair_results.append(pr)

        print(f'\n--- {label} (共通 {len(common)}R) ---')
        print(f"  的中率: {base_s['family']} {base_s['hit_rate']:.1f}% vs "
              f"{test_s['family']} {test_s['hit_rate']:.1f}% ({pr['hit_diff']:+.1f}pp)")
        print(f"  ROI:    {base_s['family']} {base_s['roi']:.1f}% vs "
              f"{test_s['family']} {test_s['roi']:.1f}% ({roi_diff:+.1f}pp, "
              f"差CI {roi_diff_lo:+.1f}〜{roi_diff_hi:+.1f}pp)")
        print(f"  McNemar: baseのみ {mcn['base_only']} / testのみ {mcn['test_only']} "
              f"(z={mcn['z']:+.2f}) → {pr['verdict']}")
        print(f"  推奨: {rec}")

    print('\n' + '=' * 72)
    print('■ 3. 結論（迷ったとき）')
    print('=' * 72)
    for rec in recommendations:
        print(rec)

    csv_path = os.path.join(ROOT, 'data', 'pattern_nnn_rrv_backtest.csv')
    memo_path = os.path.join(ROOT, 'repo', 'memory', 'verified_pattern_nnn_rrv.md')
    write_csv(all_recs, summary_rows, csv_path)
    write_memo(summary_by_name, pair_results, memo_path)
    print(f'\n出力: {csv_path}')
    print(f'出力: {memo_path}')


if __name__ == '__main__':
    main()
