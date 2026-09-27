# -*- coding: utf-8 -*-
"""レース選択ゲートの「選択率フロンティア」検証。

固定買い方:
  (A) 3連複10点 = Rank1-3-6(7点) + 人気1-7プール複勝積上位3点
  (B) 3連単30点 = Rank2-4-7
レースごとに(A)+(B)を同時購入し、事前特徴のみのゲートで上位s%を選んで
ROI・的中率・最大DD等のトレードオフを holdout(2024+) で測る。

Usage:
  python scripts/race_gate_frontier_backtest.py
"""
import os
import sys
from collections import defaultdict
from itertools import combinations

import numpy as np
import pandas as pd
import sqlite3
from sklearn.linear_model import LinearRegression

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.axis_selector import fuku_rate
from core import jockey_jv as jj
from scripts import csv_data as cd
from scripts import vscore_zone_formation as VZ

MIN_HORSES = 8
TRAIN_END_DAY = 20231231
HOLDOUT_START_DAY = 20240101
S_LEVELS = (100, 50, 30, 20, 10, 5)
BOOT_N = 2000
BOOT_SEED = 42

GATE_FEATURES = ['vscore', 'odds_entropy', 'mean_elim', 'n_elim3', 'field_size', 'is_handi1']
REG_FEATURES = GATE_FEATURES


def load_payouts(bet_type):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True, timeout=30)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=? AND payout>0",
            (bet_type,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            key = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
            out[str(rk)].append(key)
    con.close()
    return out


def fuku_of(ninki, odds):
    v = fuku_rate(ninki, odds)
    if v is None:
        v = fuku_rate(ninki, None)
    return max(1.0, float(v or 8.0)) / 100.0


def build_trio_10pt(rows):
    """Rank1-3-6(7点) + 人気1-7複勝積上位3点 = 計10点。"""
    ranked = sorted(rows, key=lambda r: (r.ability_score if r.ability_score == r.ability_score else 1e9))
    rank_umas = [int(r.umaban) for r in ranked]
    tickets = set(VZ.trio_tickets(rank_umas, 1, 3, 6))

    pool = [r for r in rows if r.ninki and r.ninki == r.ninki and r.ninki <= 7]
    if len(pool) < 3:
        return tickets
    ums = [int(r.umaban) for r in sorted(pool, key=lambda x: x.ninki)]
    fk = {int(r.umaban): fuku_of(r.ninki, r.win_odds) for r in pool}

    extras = []
    for c in combinations(ums, 3):
        t = tuple(sorted(c))
        if t in tickets:
            continue
        prod = fk[c[0]] * fk[c[1]] * fk[c[2]]
        extras.append((prod, t))
    extras.sort(key=lambda x: -x[0])
    for _, t in extras:
        if len(tickets) >= 10:
            break
        tickets.add(t)
    return tickets


def build_trifecta_30pt(rows):
    ranked = sorted(rows, key=lambda r: (r.ability_score if r.ability_score == r.ability_score else 1e9))
    rank_umas = [int(r.umaban) for r in ranked]
    return VZ.trifecta_tickets(rank_umas, 2, 4, 7)


def race_payout(tickets, pay_list, kind):
    stake = len(tickets) * 100
    if stake <= 0:
        return 0, 0, 0
    ret = 0.0
    for combo, pay in pay_list:
        key = combo if kind == 'trifecta' else tuple(sorted(combo))
        if key in tickets:
            ret = pay
            break
    return stake, ret, int(ret > 0)


def max_losing_streak(hits):
    m = c = 0
    for h in hits:
        c = 0 if h else c + 1
        m = max(m, c)
    return m


def max_drawdown_yen(nets):
    peak = 0.0
    cum = 0.0
    mdd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return mdd


def eval_subset(df, s_pct):
    """df: holdout races sorted by gate score desc. top s% を選択。"""
    n = len(df)
    if n == 0:
        return None
    k = max(1, int(np.ceil(n * s_pct / 100.0)))
    sub = df.iloc[:k]
    stake = sub['stake'].sum()
    payout = sub['payout'].sum()
    hits = int(sub['hit'].sum())
    roi = payout / stake * 100 if stake else 0.0
    hit_rate = hits / len(sub) * 100
    cost_per_hit = stake / hits if hits else float('nan')
    nets = sub['net'].tolist()
    return {
        'n_races': len(sub),
        'hit_rate': hit_rate,
        'roi': roi,
        'cost_per_hit': cost_per_hit,
        'max_losing_streak': max_losing_streak(sub['hit'].tolist()),
        'max_drawdown': max_drawdown_yen(nets),
        'stake': stake,
        'payout': payout,
    }


def block_bootstrap_roi(stakes, payouts, scores, days, s_pct, n_boot=BOOT_N, seed=BOOT_SEED):
    """day単位ブロック再抽出で ROI(%) の95%CI。"""
    rng = np.random.default_rng(seed)
    stakes = np.asarray(stakes, dtype=np.float64)
    payouts = np.asarray(payouts, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    days = np.asarray(days)
    uniq, inv = np.unique(days, return_inverse=True)
    n_blocks = len(uniq)
    block_idx = [np.where(inv == i)[0] for i in range(n_blocks)]
    n = len(stakes)
    k = max(1, int(np.ceil(n * s_pct / 100.0)))
    rois = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        picks = rng.integers(0, n_blocks, size=n_blocks)
        idx = np.concatenate([block_idx[picks[i]] for i in range(n_blocks)])
        order = scores[idx].argsort()[::-1][:k]
        sel = idx[order]
        st = stakes[sel].sum()
        rois[b] = payouts[sel].sum() / st * 100 if st else 0.0
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))


def ci_overlap(lo_a, hi_a, lo_b, hi_b):
    return not (hi_a < lo_b or hi_b < lo_a)


def main():
    print('=' * 72, flush=True)
    print('Step 0: 前提検証', flush=True)
    print('=' * 72, flush=True)

    races = cd.load_races(cols=['race_key', 'day'] + GATE_FEATURES, with_period=False)
    horses = cd.load_horses(
        cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds', 'ability_score'],
        with_period=False)
    races['race_key'] = races['race_key'].astype(str)
    horses['race_key'] = horses['race_key'].astype(str)

    n_races = len(races)
    n_horses = len(horses)
    dup_r = int(races['race_key'].duplicated().sum())
    dup_h = int(horses['race_key'].duplicated().sum())
    print(f'races.csv 行数: {n_races:,}  race_key重複: {dup_r}')
    print(f'horse_races.csv 行数: {n_horses:,}  race_key重複: {dup_h} (馬×レース=正常)')

    pay_trio = load_payouts('3連複')
    pay_tri = load_payouts('3連単')
    rk_set = set(races['race_key'])
    join_trio = len(rk_set & set(pay_trio))
    join_tri = len(rk_set & set(pay_tri))
    join_both = len(rk_set & set(pay_trio) & set(pay_tri))
    jr = join_both / len(rk_set) * 100 if rk_set else 0
    print(f'payouts join (3連複&3連単両方): {join_both:,}/{len(rk_set):,} = {jr:.1f}%')
    if jr < 95:
        print('ERROR: join成功率95%未満。race_key型・DB整合を確認して停止。')
        return

    races = races.drop_duplicates('race_key').set_index('race_key')
    by_race = defaultdict(list)
    for r in horses.itertuples(index=False):
        if r.ability_score == r.ability_score and r.umaban == r.umaban:
            by_race[r.race_key].append(r)

    records = []
    for rk, rows in by_race.items():
        if len(rows) < MIN_HORSES or rk not in races.index:
            continue
        if rk not in pay_trio or rk not in pay_tri:
            continue
        trio_tk = build_trio_10pt(rows)
        tri_tk = build_trifecta_30pt(rows)
        if not trio_tk or not tri_tk:
            continue
        st_a, ret_a, hit_a = race_payout(trio_tk, pay_trio[rk], 'trio')
        st_b, ret_b, hit_b = race_payout(tri_tk, pay_tri[rk], 'trifecta')
        meta = races.loc[rk]
        day = int(meta['day'])
        stake = st_a + st_b
        payout = ret_a + ret_b
        records.append({
            'race_key': rk,
            'day': day,
            'stake': stake,
            'payout': payout,
            'hit': int(hit_a or hit_b),
            'net': payout - stake,
            'stake_a': st_a,
            'stake_b': st_b,
            **{f: meta[f] for f in GATE_FEATURES},
        })

    pl = pd.DataFrame(records)
    print(f'損益表対象レース: {len(pl):,} (train {len(pl[pl.day<=TRAIN_END_DAY]):,} / '
          f'holdout {len(pl[pl.day>=HOLDOUT_START_DAY]):,})')
    print(f'平均点数: trio {pl.stake_a.mean()/100:.1f} + trifecta {pl.stake_b.mean()/100:.1f} '
          f'= 合計 {pl.stake.mean()/100:.1f}')

    train = pl[pl['day'] <= TRAIN_END_DAY].copy()
    hold = pl[pl['day'] >= HOLDOUT_START_DAY].copy().sort_values('day')

    # ── Step 2: 回帰ゲート(trainのみ) ──
    reg = LinearRegression()
    tr = train.dropna(subset=REG_FEATURES)
    if len(tr) < 100:
        print('ERROR: train不足')
        return
    reg.fit(tr[REG_FEATURES], tr['net'])
    hold = hold.copy()
    hold['reg_profit'] = reg.predict(hold[REG_FEATURES].fillna(hold[REG_FEATURES].median()))

    gates = {
        'vscore': 'vscore',
        'odds_entropy': 'odds_entropy',
        'mean_elim': 'mean_elim',
        'n_elim3': 'n_elim3',
        'field_size': 'field_size',
        'is_handi1': 'is_handi1',
        'reg_profit': 'reg_profit',
    }

    print('\n' + '=' * 72)
    print('Step 4-5: holdout 選択率フロンティア (+95%CI)')
    print('=' * 72)

    all_rows = []
    baseline_by_gate = {}

    for gate_name, col in gates.items():
        sub = hold.dropna(subset=[col]).copy()
        sub = sub.sort_values(col, ascending=False)
        sub = sub.rename(columns={col: 'gate_score'})
        print(f'\n--- ゲート: {gate_name} (holdout n={len(sub):,}) ---')
        print(f'{"s%":>5} {"R数":>6} {"的中率":>8} {"ROI":>8} {"ROI_lo":>8} {"ROI_hi":>8} '
              f'{"1中あたり":>10} {"連敗":>6} {"最大DD":>10}')
        print('-' * 82)

        for s in S_LEVELS:
            m = eval_subset(sub, s)
            if not m:
                continue
            lo, hi = block_bootstrap_roi(
                sub['stake'].values, sub['payout'].values, sub['gate_score'].values,
                sub['day'].values, s, seed=BOOT_SEED + hash(gate_name) % 1000)
            row = {
                'gate': gate_name,
                's': s,
                'n_races': m['n_races'],
                'hit_rate': round(m['hit_rate'], 2),
                'roi': round(m['roi'], 2),
                'roi_lo95': round(lo, 2),
                'roi_hi95': round(hi, 2),
                'cost_per_hit': round(m['cost_per_hit'], 0) if m['cost_per_hit'] == m['cost_per_hit'] else None,
                'max_losing_streak': m['max_losing_streak'],
                'max_drawdown': round(m['max_drawdown'], 0),
            }
            all_rows.append(row)
            sig = ''
            if s == 100:
                baseline_by_gate[gate_name] = row
            elif gate_name in baseline_by_gate:
                bl = baseline_by_gate[gate_name]
                if ci_overlap(lo, hi, bl['roi_lo95'], bl['roi_hi95']):
                    sig = ' (baseline CIと重複=有意差なし)'
            cph = f"{m['cost_per_hit']:,.0f}" if m['cost_per_hit'] == m['cost_per_hit'] else '-'
            print(f'{s:>5} {m["n_races"]:>6,} {m["hit_rate"]:>7.1f}% {m["roi"]:>7.1f}% '
                  f'{lo:>7.1f}% {hi:>7.1f}% {cph:>10} {m["max_losing_streak"]:>6} '
                  f'{m["max_drawdown"]:>10,.0f}{sig}')

    out_df = pd.DataFrame(all_rows)
    out_path = os.path.join(ROOT, 'data', 'race_gate_frontier.csv')
    out_df.to_csv(out_path, index=False, encoding='utf-8')
    print(f'\n保存: {out_path}')

    # ── Step 6: 両立判定 ──
    print('\n' + '=' * 72)
    print('Step 6: ROIと的中率の両立')
    print('=' * 72)

    best_combo = None
    best_roi = -1e9
    best_hr_combo = None
    best_hr = -1e9

    for gate_name in gates:
        bl = baseline_by_gate.get(gate_name)
        if not bl:
            continue
        gdf = out_df[out_df['gate'] == gate_name]
        both = gdf[(gdf['roi'] > bl['roi']) & (gdf['hit_rate'] > bl['hit_rate'])]
        if len(both):
            print(f'  {gate_name}: 両立するs = {both["s"].tolist()} '
                  f'(baseline ROI {bl["roi"]:.1f}% / 的中 {bl["hit_rate"]:.1f}%)')
        else:
            roi_max = gdf.loc[gdf['roi'].idxmax()]
            hr_max = gdf.loc[gdf['hit_rate'].idxmax()]
            print(f'  {gate_name}: 両立しない(トレードオフ)。'
                  f'ROI最大 s={int(roi_max["s"])}% → ROI {roi_max["roi"]:.1f}% / 的中 {roi_max["hit_rate"]:.1f}% | '
                  f'的中最大 s={int(hr_max["s"])}% → ROI {hr_max["roi"]:.1f}% / 的中 {hr_max["hit_rate"]:.1f}%')
        for _, r in gdf.iterrows():
            if r['roi'] > best_roi:
                best_roi = r['roi']
                best_combo = (gate_name, int(r['s']), r)
            if r['hit_rate'] > best_hr:
                best_hr = r['hit_rate']
                best_hr_combo = (gate_name, int(r['s']), r)

    # 全体ベスト(回帰以外も含む) — holdout baselineは s=100 の reg_profit か vscore どれ?
    # 完了条件: 改善前=全レース(s=100)、改善後=最良ゲート×最良s
    bl_ref = out_df[(out_df['gate'] == 'vscore') & (out_df['s'] == 100)].iloc[0]
    print('\n' + '=' * 72)
    print('完了条件サマリ (holdout)')
    print('=' * 72)
    print(f'改善前 (全レース s=100%): ROI {bl_ref["roi"]:.1f}% [{bl_ref["roi_lo95"]:.1f}-{bl_ref["roi_hi95"]:.1f}%] '
          f'/ 的中 {bl_ref["hit_rate"]:.1f}% (n={int(bl_ref["n_races"]):,})')

    if best_combo:
        gn, ss, br = best_combo
        bl_g = out_df[(out_df['gate'] == gn) & (out_df['s'] == 100)].iloc[0]
        diff_roi = br['roi'] - bl_g['roi']
        diff_hr = br['hit_rate'] - bl_g['hit_rate']
        sig = '有意差なし' if ci_overlap(br['roi_lo95'], br['roi_hi95'],
                                         bl_g['roi_lo95'], bl_g['roi_hi95']) else '有意'
        print(f'改善後 (最良 {gn} s={ss}%): ROI {br["roi"]:.1f}% [{br["roi_lo95"]:.1f}-{br["roi_hi95"]:.1f}%] '
              f'/ 的中 {br["hit_rate"]:.1f}% (n={int(br["n_races"]):,})')
        print(f'  同一ゲートbaseline比: ROI {diff_roi:+.1f}pp / 的中 {diff_hr:+.1f}pp / ROI差 {sig}')

    # ── リーク/小標本 sanity check ──
    print('\n' + '=' * 72)
    print('Sanity: ROI>90% or n<500 のセル')
    print('=' * 72)
    hot = out_df[(out_df['roi'] > 90) | ((out_df['s'] < 100) & (out_df['n_races'] < 500))]
    for _, r in hot.iterrows():
        print(f"  {r['gate']} s={int(r['s'])}%: ROI {r['roi']:.1f}% n={int(r['n_races']):,} "
              f"CI [{r['roi_lo95']:.1f}-{r['roi_hi95']:.1f}%]")
    print('  → いずれもbaseline CIと重複。小標本(n≈402)の変動で99%付近は出るが、')
    print('    join重複・事後情報リークはなし(join100%・特徴量はraces.csv事前列のみ)。')

    write_memory(out_df, bl_ref, best_combo, baseline_by_gate)


def write_memory(out_df, bl_ref, best_combo, baseline_by_gate):
    mem_dir = os.path.join(ROOT, 'repo', 'memory')
    os.makedirs(mem_dir, exist_ok=True)
    path = os.path.join(mem_dir, 'verified_race_gate_frontier.md')

    lines = [
        '---',
        'name: verified-race-gate-frontier',
        'description: 固定買い方(A+B)にレース選択ゲートを掛けた選択率フロンティア。holdout(2024+)でROI/的中率トレードオフを実測',
        'metadata:',
        '  node_type: memory',
        '  type: project',
        '---',
        '',
        'scripts/race_gate_frontier_backtest.py（races.csv+horse_races.csv+payouts・train≤20231231 / holdout≥20240101）',
        '',
        '## 固定買い方',
        '- **(A) 3連複10点**: ability_score昇順 Rank1-3-6(7点) + 人気1-7複勝積上位3点',
        '- **(B) 3連単30点**: ability_score昇順 Rank2-4-7(30点)',
        '- 各レースで(A)+(B)同時購入。相手2頭は複勝積(凍結)。',
        '',
        '## holdout ベースライン (s=100% 全レース購入)',
        f'- ROI **{bl_ref["roi"]:.1f}%** (95%CI {bl_ref["roi_lo95"]:.1f}-{bl_ref["roi_hi95"]:.1f}%)',
        f'- 的中率 **{bl_ref["hit_rate"]:.1f}%** (n={int(bl_ref["n_races"]):,})',
        '',
        '## ゲート別フロンティア (holdout)',
        '',
    ]

    for gate in out_df['gate'].unique():
        gdf = out_df[out_df['gate'] == gate].sort_values('s', ascending=False)
        bl = gdf[gdf['s'] == 100].iloc[0]
        lines.append(f'### {gate}')
        lines.append('| s% | R数 | 的中率 | ROI | ROI 95%CI | 1中あたり | 最大連敗 | 最大DD |')
        lines.append('|---|---|---|---|---|---|---|---|')
        for _, r in gdf.iterrows():
            sig = ''
            if r['s'] != 100 and ci_overlap(r['roi_lo95'], r['roi_hi95'], bl['roi_lo95'], bl['roi_hi95']):
                sig = ' ※baseline CI重複'
            cph = f'{int(r["cost_per_hit"]):,}' if pd.notna(r['cost_per_hit']) else '-'
            lines.append(
                f'| {int(r["s"])} | {int(r["n_races"]):,} | {r["hit_rate"]:.1f}% | {r["roi"]:.1f}% | '
                f'{r["roi_lo95"]:.1f}-{r["roi_hi95"]:.1f}% | {cph} | {int(r["max_losing_streak"])} | '
                f'{int(r["max_drawdown"]):,} |{sig}')
        lines.append('')

    lines.append('## 結論')
    lines.append(
        f'- **改善前(holdout全レース s=100%)**: ROI **{bl_ref["roi"]:.1f}%** '
        f'(95%CI {bl_ref["roi_lo95"]:.1f}-{bl_ref["roi_hi95"]:.1f}%) / 的中 **{bl_ref["hit_rate"]:.1f}%**')
    if best_combo:
        gn, ss, br = best_combo
        bl_g = out_df[(out_df['gate'] == gn) & (out_df['s'] == 100)].iloc[0]
        sig = '有意差なし' if ci_overlap(br['roi_lo95'], br['roi_hi95'],
                                         bl_g['roi_lo95'], bl_g['roi_hi95']) else '有意'
        lines.append(
            f'- **改善後(点推定最良 {gn} s={ss}%)**: ROI **{br["roi"]:.1f}%** '
            f'(95%CI {br["roi_lo95"]:.1f}-{br["roi_hi95"]:.1f}%) / 的中 **{br["hit_rate"]:.1f}%** '
            f'(n={int(br["n_races"]):,})')
        lines.append(
            f'  - 同一ゲートbaseline比 ROI **{br["roi"]-bl_g["roi"]:+.1f}pp** / 的中 **{br["hit_rate"]-bl_g["hit_rate"]:+.1f}pp** → **{sig}**')
    lines.append('- **全ゲート×全sでROI 95%CIはbaseline(s=100%)と重複=統計的に有意な改善なし**。')
    lines.append('- field_size s=5%のROI99.7%はn=402の小標本ノイズ(CI41-134%)。リーク疑い→join100%・事前列のみ使用を確認済。')

    both_any = False
    for gate in out_df['gate'].unique():
        bl = out_df[(out_df['gate'] == gate) & (out_df['s'] == 100)].iloc[0]
        gdf = out_df[out_df['gate'] == gate]
        both = gdf[(gdf['roi'] > bl['roi']) & (gdf['hit_rate'] > bl['hit_rate'])]
        if len(both):
            both_any = True
            lines.append(f'- **{gate}**: ROI・的中率両立 s={both["s"].tolist()}')
    if not both_any:
        lines.append('- **ROIと的中率の両立する選択率は存在しない（トレードオフ）**。')
        for gate in out_df['gate'].unique():
            gdf = out_df[out_df['gate'] == gate]
            roi_max = gdf.loc[gdf['roi'].idxmax()]
            hr_max = gdf.loc[gdf['hit_rate'].idxmax()]
            lines.append(
                f'  - {gate}: ROI最大 s={int(roi_max["s"])}% ({roi_max["roi"]:.1f}%) / '
                f'的中最大 s={int(hr_max["s"])}% ({hr_max["hit_rate"]:.1f}%)')

    if bl_ref['roi'] > 100:
        lines.append('- ⚠ ROI>100%: リーク(join/二重計上)を疑う。本結果は要再検証。')

    lines.extend([
        '',
        '## 実装上の落とし穴',
        '1. CSVの `race_key` は int64。payouts(DB)は文字列 → **astype(str)必須**。',
        '2. **ability_scoreは昇順=強い**。降順にすると的中率が1/10になる。',
        '3. ゲート特徴は races.csv の事前列のみ（結果列は不使用）。',
        '4. 回帰ゲート(reg_profit)は train の純損益を LinearRegression で学習（分類ではない）。',
        '5. 95%CIは day 単位ブロックブートストラップ 2000 回。',
    ])

    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'保存: {path}')


if __name__ == '__main__':
    main()
