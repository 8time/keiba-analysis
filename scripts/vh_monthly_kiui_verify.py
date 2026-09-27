# -*- coding: utf-8 -*-
"""穴馬ハンター(VH) 月別性能検証 — きうい9月穴馬との比較（研究専用）。

本番ロジック(core/value_hunter.py + data/value_hunter_light.json)を固定し、
過去CSV(data/export/horse_races.csv)へ適用して集計する。
本番コードは変更しない。

Usage: python scripts/vh_monthly_kiui_verify.py
"""
import io
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import jockey_jv as jj
from core import value_hunter as vh
from core.bayes_stats import wilson_interval

OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'vh_monthly_analysis')
HORSE_CSV = os.path.join(ROOT, 'data', 'export', 'horse_races.csv')

# きうい記事の検証期間
KIUI_FROM = 20180301
KIUI_TO = 20260630

# 本番と同一
POP_MIN = 6
HOLDOUT_FROM = 20240101
RECENT6_FROM = 20200101
RECENT3_FROM = 20230101

# きうい参照値（記事より）
KIUI_REF = {
    'sep_n': 109,
    'sep_win': 4,
    'sep_win_rate': 0.037,
    'sep_tansho_roi': 61.6,
    'other_n': 1752 - 109,
    'other_win': 129,
    'other_win_rate': 0.079,
    'other_tansho_roi': 161.4,
    'sep_finish': {
        '1着': 3.7,
        '2〜3着': 12.8,
        '4〜5着': 14.7,
        '6〜8着': 26.6,
        '9着以下': 42.2,
    },
}


def _load_params():
    p = vh.load_params()
    if not p:
        raise RuntimeError('data/value_hunter_light.json が無い')
    return p


def _recompute_combo(df):
    """consensus_view._SIG6 と同型の6シグナル重複数をCSV列から再現。"""
    g = df.groupby('race_key', sort=False)
    sp_rank = g['spurt_idx'].rank(ascending=False, method='min')
    jk_rank = g['jk_race_pct'].rank(ascending=False, method='min')
    bl_rank = g['blood_race_pct'].rank(ascending=False, method='min')
    ct_rank = g['h7_rank'].rank(ascending=True, method='min')

    sig = pd.DataFrame(index=df.index)
    sig['ct'] = (ct_rank <= 3).astype(int)
    sig['sp'] = (sp_rank <= 3).astype(int)
    sig['bl'] = (bl_rank <= 3).astype(int)
    sig['jk'] = (jk_rank <= 3).astype(int)
    sig['lap'] = pd.to_numeric(df['lap_fit_bin'], errors='coerce').fillna(0).astype(int)
    sig['roi'] = (pd.to_numeric(df['sire_winroi'], errors='coerce').fillna(0) >= 100).astype(int)
    return sig.sum(axis=1)


def _apply_vh_scores(df):
    """レース単位で本番 value_hunter と同じ7特徴→prob→tier を付与。"""
    params = _load_params()
    ops = params['ops']
    thr_elite = ops['recall0.5']
    thr_net = ops['recall0.7']

    scores = []
    tiers = []
    for _, grp in df.groupby('race_key', sort=False):
        odds_map = {}
        ctfig = {}
        spurt = {}
        blood = {}
        combo_map = {}
        elim_map = {}
        front_set = set()
        idx_map = {}

        for idx, r in grp.iterrows():
            u = int(r['umaban'])
            idx_map[u] = idx
            wo = float(r['win_odds']) if pd.notna(r['win_odds']) and r['win_odds'] > 0 else None
            if wo:
                odds_map[u] = wo
            if pd.notna(r.get('h7_fig')):
                ctfig[u] = float(r['h7_fig'])
            if pd.notna(r.get('spurt_idx')):
                spurt[u] = float(r['spurt_idx'])
            if pd.notna(r.get('blood_race_pct')):
                blood[u] = float(r['blood_race_pct'])
            combo_map[u] = int(r['combo6'])
            elim_map[u] = int(r['elim_n']) if pd.notna(r['elim_n']) else 9
            if pd.notna(r.get('avg_pos3')) and float(r['avg_pos3']) <= 3.0:
                front_set.add(u)

        sc = vh.score_race(ctfig, spurt, blood, combo_map, elim_map, odds_map, front_set)
        for u, d in sc.items():
            i = idx_map.get(u)
            if i is None:
                continue
            scores.append((i, d['score'], d['tier']))

    sc_df = pd.DataFrame(scores, columns=['idx', 'vh_score', 'vh_tier']).set_index('idx')
    df = df.copy()
    df['vh_score'] = sc_df['vh_score']
    df['vh_tier'] = sc_df['vh_tier']
    df['vh_pick'] = df['vh_tier'].isin(['🎯精鋭', '🕸️広域網'])
    df['vh_elite'] = df['vh_tier'] == '🎯精鋭'
    return df, thr_elite, thr_net


def _load_fukusho_payouts():
    """race_key -> {umaban: payout_yen}"""
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(dict)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=? AND payout>0",
            ('複勝',)):
        try:
            um = int(str(combo).strip())
            out[str(rk)][um] = float(pay)
        except (TypeError, ValueError):
            continue
    con.close()
    return dict(out)


def _metrics(sub, fuku_map=None, unit=100):
    n = len(sub)
    if n == 0:
        return {
            'n': 0, 'win': 0, 'place2': 0, 'place3': 0,
            'win_rate': 0.0, 'place_rate': 0.0,
            'tansho_roi': 0.0, 'fukusho_roi': 0.0,
            'avg_odds': 0.0, 'med_odds': 0.0,
            'invest': 0, 'tansho_pay': 0, 'fukusho_pay': 0, 'profit_tansho': 0,
        }
    wins = int(sub['win'].sum())
    p2 = int((sub['chakujun'] == 2).sum())
    p3 = int((sub['chakujun'] == 3).sum())
    top3 = int(sub['top3'].sum())
    odds = pd.to_numeric(sub['win_odds'], errors='coerce').fillna(0)
    invest = n * unit
    tansho_pay = float((sub['win'] * odds * unit).sum())
    fukusho_pay = 0.0
    if fuku_map is not None:
        for _, r in sub.iterrows():
            pay = fuku_map.get(str(r['race_key']), {}).get(int(r['umaban']))
            if pay:
                fukusho_pay += pay
    return {
        'n': n,
        'win': wins,
        'place2': p2,
        'place3': p3,
        'win_rate': wins / n,
        'place_rate': top3 / n,
        'tansho_roi': tansho_pay / invest * 100 if invest else 0.0,
        'fukusho_roi': fukusho_pay / invest * 100 if invest else 0.0,
        'avg_odds': float(odds.mean()),
        'med_odds': float(odds.median()),
        'invest': invest,
        'tansho_pay': tansho_pay,
        'fukusho_pay': fukusho_pay,
        'profit_tansho': tansho_pay - invest,
    }


def _finish_bucket(ch):
    if ch == 1:
        return '1着'
    if 2 <= ch <= 3:
        return '2〜3着'
    if 4 <= ch <= 5:
        return '4〜5着'
    if 6 <= ch <= 8:
        return '6〜8着'
    return '9着以下'


def _prop_test_diff(p1, n1, p2, n2):
    """2比例のz検定（近似）。"""
    if n1 == 0 or n2 == 0:
        return None, None
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return None, None
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    # 両側p値（正規近似）
    pval = math.erfc(abs(z) / math.sqrt(2))
    return z, pval


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print('読込:', HORSE_CSV)
    df = pd.read_csv(HORSE_CSV)
    df['day'] = pd.to_numeric(df['day'], errors='coerce').astype('Int64')
    df['month'] = (df['day'] // 100) % 100
    df['year'] = df['day'] // 10000
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df = df[df['ninki'].notna() & (df['ninki'] > 0)].copy()

    # JRA中央のみ（本番 build_edge_sets と同条件: jyo<=10）
    df['jyo'] = df['jyo'].astype(str).str.zfill(2)
    df = df[df['jyo'] <= '10'].copy()

    print('combo6再計算...')
    df['combo6'] = _recompute_combo(df)

    print('VHスコア適用(本番 value_hunter)...')
    df, thr_elite, thr_net = _apply_vh_scores(df)

    # 穴馬母集団 → VHピック（精鋭+広域網）
    pool = df[(df['ninki'] >= POP_MIN) & df['vh_score'].notna()].copy()
    picks = pool[pool['vh_pick']].copy()

    # きうい比較期間
    kiui = picks[(picks['day'] >= KIUI_FROM) & (picks['day'] <= KIUI_TO)].copy()
    data_to = int(pool['day'].max())
    data_from = int(pool['day'].min())

    print(f'データ期間: {data_from}〜{data_to}')
    print(f'VHピック(6人気+×精鋭/広域網): {len(picks):,} / 母集団 {len(pool):,}')

    print('複勝払戻読込...')
    fuku = _load_fukusho_payouts()

    # --- STEP 4: 全期間 ---
    all_m = _metrics(kiui, fuku)
    all_m['period'] = f'kiui_aligned_{KIUI_FROM}_{min(KIUI_TO, data_to)}'

    # --- STEP 5: 月別 ---
    monthly_rows = []
    for m in range(1, 13):
        sub = kiui[kiui['month'] == m]
        met = _metrics(sub, fuku)
        met['month'] = m
        monthly_rows.append(met)
    monthly_df = pd.DataFrame(monthly_rows)

    # --- STEP 6: 9月 vs その他 ---
    sep = kiui[kiui['month'] == 9]
    other = kiui[kiui['month'] != 9]
    m_sep = _metrics(sep, fuku)
    m_other = _metrics(other, fuku)

    def _ratio(a, b):
        return (a / b) if b else None

    sep_vs_other = {
        'segment': ['9月', 'その他月', '9月/その他月'],
        'n': [m_sep['n'], m_other['n'], None],
        'win': [m_sep['win'], m_other['win'], None],
        'win_rate_pct': [m_sep['win_rate'] * 100, m_other['win_rate'] * 100,
                         _ratio(m_sep['win_rate'], m_other['win_rate'])],
        'place_rate_pct': [m_sep['place_rate'] * 100, m_other['place_rate'] * 100,
                           _ratio(m_sep['place_rate'], m_other['place_rate'])],
        'tansho_roi_pct': [m_sep['tansho_roi'], m_other['tansho_roi'],
                           _ratio(m_sep['tansho_roi'], m_other['tansho_roi'])],
        'fukusho_roi_pct': [m_sep['fukusho_roi'], m_other['fukusho_roi'],
                            _ratio(m_sep['fukusho_roi'], m_other['fukusho_roi'])],
    }
    sep_vs_other_df = pd.DataFrame(sep_vs_other)

    # --- STEP 7: きうい直接比較 ---
    kiui_sep_m = _metrics(sep, fuku)
    kiui_cmp = pd.DataFrame([
        {
            'metric': '9月対象頭数',
            'kiui': KIUI_REF['sep_n'],
            'vh': kiui_sep_m['n'],
            'diff': kiui_sep_m['n'] - KIUI_REF['sep_n'],
        },
        {
            'metric': '1着数',
            'kiui': KIUI_REF['sep_win'],
            'vh': kiui_sep_m['win'],
            'diff': kiui_sep_m['win'] - KIUI_REF['sep_win'],
        },
        {
            'metric': '1着率(%)',
            'kiui': KIUI_REF['sep_win_rate'] * 100,
            'vh': kiui_sep_m['win_rate'] * 100,
            'diff': kiui_sep_m['win_rate'] * 100 - KIUI_REF['sep_win_rate'] * 100,
        },
        {
            'metric': '単勝回収率(%)',
            'kiui': KIUI_REF['sep_tansho_roi'],
            'vh': kiui_sep_m['tansho_roi'],
            'diff': kiui_sep_m['tansho_roi'] - KIUI_REF['sep_tansho_roi'],
        },
        {
            'metric': '複勝率(%)',
            'kiui': None,
            'vh': kiui_sep_m['place_rate'] * 100,
            'diff': None,
        },
        {
            'metric': '複勝回収率(%)',
            'kiui': None,
            'vh': kiui_sep_m['fukusho_roi'],
            'diff': None,
        },
    ])

    # --- STEP 8: 9月着順分布 ---
    buckets = ['1着', '2〜3着', '4〜5着', '6〜8着', '9着以下']
    sep_dist = []
    n_sep = len(sep)
    for b in buckets:
        if b == '1着':
            cnt = int((sep['chakujun'] == 1).sum())
        elif b == '2〜3着':
            cnt = int(sep['chakujun'].isin([2, 3]).sum())
        elif b == '4〜5着':
            cnt = int(sep['chakujun'].isin([4, 5]).sum())
        elif b == '6〜8着':
            cnt = int(sep['chakujun'].isin([6, 7, 8]).sum())
        else:
            cnt = int((sep['chakujun'] >= 9).sum())
        sep_dist.append({
            'bucket': b,
            'kiui_pct': KIUI_REF['sep_finish'].get(b),
            'vh_pct': cnt / n_sep * 100 if n_sep else 0,
            'vh_n': cnt,
        })
    sep_dist_df = pd.DataFrame(sep_dist)

    # --- STEP 9: 年×月 ---
    ym_win = picks[(picks['day'] >= KIUI_FROM) & (picks['day'] <= KIUI_TO)].pivot_table(
        index='year', columns='month', values='win', aggfunc='sum', fill_value=0)
    ym_n = picks[(picks['day'] >= KIUI_FROM) & (picks['day'] <= KIUI_TO)].pivot_table(
        index='year', columns='month', values='umaban', aggfunc='count', fill_value=0)

    # --- STEP 10: 期間分割 ---
    period_defs = [
        ('kiui_aligned', KIUI_FROM, min(KIUI_TO, data_to)),
        ('recent6y', RECENT6_FROM, data_to),
        ('recent3y', RECENT3_FROM, data_to),
        ('holdout2024+', HOLDOUT_FROM, data_to),
    ]
    period_rows = []
    for label, d0, d1 in period_defs:
        sub_all = picks[(picks['day'] >= d0) & (picks['day'] <= d1)]
        for seg, seg_df in [('all', sub_all),
                            ('sep', sub_all[sub_all['month'] == 9]),
                            ('other', sub_all[sub_all['month'] != 9])]:
            met = _metrics(seg_df, fuku)
            met.update({'period': label, 'segment': seg, 'from': d0, 'to': d1})
            period_rows.append(met)
    period_df = pd.DataFrame(period_rows)

    # --- STEP 11: holdout ---
    holdout_rows = []
    for yr in sorted(kiui['year'].unique()):
        if yr < 2024:
            continue
        sub = kiui[kiui['year'] == yr]
        for seg, seg_df in [('all', sub),
                            ('sep', sub[sub['month'] == 9]),
                            ('other', sub[sub['month'] != 9])]:
            met = _metrics(seg_df, fuku)
            met.update({'year': int(yr), 'segment': seg})
            holdout_rows.append(met)
    holdout_df = pd.DataFrame(holdout_rows)

    # --- STEP 12: 統計 ---
    z_wr, p_wr = _prop_test_diff(m_sep['win_rate'], m_sep['n'], m_other['win_rate'], m_other['n'])
    z_pr, p_pr = _prop_test_diff(m_sep['place_rate'], m_sep['n'], m_other['place_rate'], m_other['n'])
    wil_sep_wr = wilson_interval(m_sep['win'], m_sep['n']) if m_sep['n'] else (0, 0)
    wil_other_wr = wilson_interval(m_other['win'], m_other['n']) if m_other['n'] else (0, 0)
    wil_sep_pr = wilson_interval(int(sep['top3'].sum()), m_sep['n']) if m_sep['n'] else (0, 0)
    wil_other_pr = wilson_interval(int(other['top3'].sum()), m_other['n']) if m_other['n'] else (0, 0)

    stats = {
        'sep_n': m_sep['n'],
        'other_n': m_other['n'],
        'win_rate_sep': m_sep['win_rate'],
        'win_rate_other': m_other['win_rate'],
        'win_rate_z': z_wr,
        'win_rate_p': p_wr,
        'place_rate_sep': m_sep['place_rate'],
        'place_rate_other': m_other['place_rate'],
        'place_rate_z': z_pr,
        'place_rate_p': p_pr,
        'wilson_win_sep': wil_sep_wr,
        'wilson_win_other': wil_other_wr,
        'wilson_place_sep': wil_sep_pr,
        'wilson_place_other': wil_other_pr,
    }

    # --- 保存 ---
    monthly_df.to_csv(os.path.join(OUT_DIR, 'monthly_summary.csv'), index=False, encoding='utf-8-sig')
    sep_vs_other_df.to_csv(os.path.join(OUT_DIR, 'september_vs_other.csv'), index=False, encoding='utf-8-sig')
    ym_win.to_csv(os.path.join(OUT_DIR, 'year_month_first_place.csv'), encoding='utf-8-sig')
    ym_n.to_csv(os.path.join(OUT_DIR, 'year_month_pick_count.csv'), encoding='utf-8-sig')
    sep_dist_df.to_csv(os.path.join(OUT_DIR, 'september_finish_distribution.csv'), index=False, encoding='utf-8-sig')
    kiui_cmp.to_csv(os.path.join(OUT_DIR, 'kiui_vs_vh.csv'), index=False, encoding='utf-8-sig')
    holdout_df.to_csv(os.path.join(OUT_DIR, 'holdout_september.csv'), index=False, encoding='utf-8-sig')
    period_df.to_csv(os.path.join(OUT_DIR, 'period_comparison.csv'), index=False, encoding='utf-8-sig')

    with open(os.path.join(OUT_DIR, 'stats.json'), 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)

    spec = {
        'production_module': 'core/value_hunter.py',
        'params': 'data/value_hunter_light.json',
        'pop_min': POP_MIN,
        'tier_elite_threshold': thr_elite,
        'tier_net_threshold': thr_net,
        'pick_definition': '6番人気以下 × (🎯精鋭 or 🕸️広域網)',
        'data_from': data_from,
        'data_to': data_to,
        'kiui_from': KIUI_FROM,
        'kiui_to': KIUI_TO,
        'kiui_period_note': '完全比較' if data_to >= KIUI_TO else f'データ上限{data_to}のため2026年6月後半は未包含',
        'odds_note': 'CSV win_odds=JV事前確定オッズ。きうい=前日夜オッズ5倍+。条件差あり。',
        'pop_note': 'VH=6番人気以下。きうい=オッズ5倍+（人気条件なし）。',
    }
    with open(os.path.join(OUT_DIR, 'vh_spec.json'), 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    # --- レポート ---
    _write_report(
        OUT_DIR, spec, all_m, monthly_df, sep_vs_other_df, kiui_cmp,
        sep_dist_df, period_df, holdout_df, stats, m_sep, m_other,
    )
    print('完了:', OUT_DIR)


def _write_report(out_dir, spec, all_m, monthly_df, sep_vs_other_df, kiui_cmp,
                  sep_dist_df, period_df, holdout_df, stats, m_sep, m_other):
    lines = []
    w = lines.append

    w('# 穴馬ハンター（VH）9月性能検証\n')
    w('きうい｜検証AI競馬予想との比較\n')

    w('## 1. 結論\n')
    vh_wr = kiui_cmp.loc[kiui_cmp['metric'] == '1着率(%)', 'vh'].iloc[0]
    kiui_wr = kiui_cmp.loc[kiui_cmp['metric'] == '1着率(%)', 'kiui'].iloc[0]
    vh_roi = kiui_cmp.loc[kiui_cmp['metric'] == '単勝回収率(%)', 'vh'].iloc[0]
    kiui_roi = kiui_cmp.loc[kiui_cmp['metric'] == '単勝回収率(%)', 'kiui'].iloc[0]
    vh_pr = kiui_cmp.loc[kiui_cmp['metric'] == '複勝率(%)', 'vh'].iloc[0]

    verdict_parts = []
    if vh_wr > kiui_wr and vh_roi > kiui_roi:
        grade = 'A（明確に上回る）'
        verdict_parts.append('9月の1着率・単勝回収率の両方でVHが上')
    elif (vh_wr > kiui_wr) != (vh_roi > kiui_roi):
        grade = 'B（一部上回る）'
        verdict_parts.append('1着率と単勝回収率で優劣が分かれる')
    elif abs(vh_wr - kiui_wr) < 1.0 and abs(vh_roi - kiui_roi) < 15:
        grade = 'C（ほぼ同等）'
    else:
        grade = 'D（下回る）'
        verdict_parts.append('重要指標でVHが劣る')

    w(f'**総合判定: {grade}**\n')
    w(f'- 9月1着率: VH {vh_wr:.1f}% vs きうい {kiui_wr:.1f}% （差 {vh_wr - kiui_wr:+.1f}pt）')
    w(f'- 9月単勝回収率: VH {vh_roi:.1f}% vs きうい {kiui_roi:.1f}% （差 {vh_roi - kiui_roi:+.1f}pt）')
    w(f'- 9月複勝率: VH {vh_pr:.1f}%（きうい記事に複勝率なし）')
    w('')
    w('⚠ **完全同条件比較ではない**: VH=6番人気以下×精鋭/広域網、きうい=AI条件×前日夜オッズ5倍+。')
    w('')

    w('## 2. 9月の比較（きうい vs VH）\n')
    w(kiui_cmp.to_markdown(index=False, floatfmt='.1f'))
    w('')

    w('## 3. 月別成績\n')
    md = monthly_df.copy()
    md['win_rate'] = md['win_rate'] * 100
    md['place_rate'] = md['place_rate'] * 100
    w(md[['month', 'n', 'win', 'place2', 'place3', 'win_rate', 'place_rate',
          'tansho_roi', 'fukusho_roi']].to_markdown(index=False, floatfmt='.1f'))
    w('')

    w('## 4. 9月 vs その他月\n')
    w(sep_vs_other_df.to_markdown(index=False, floatfmt='.2f'))
    w('')

    w('## 5. 着順分布（9月）\n')
    w(sep_dist_df.to_markdown(index=False, floatfmt='.1f'))
    w('')

    w('## 6. 年×月分析\n')
    w('`year_month_first_place.csv` / `year_month_pick_count.csv` を参照。\n')

    w('## 7. 直近holdout\n')
    if len(holdout_df):
        h = holdout_df.copy()
        h['win_rate'] = h['win_rate'] * 100
        h['place_rate'] = h['place_rate'] * 100
        w(h[['year', 'segment', 'n', 'win', 'win_rate', 'place_rate', 'tansho_roi']].to_markdown(
            index=False, floatfmt='.1f'))
    w('')

    w('## 8. 統計的信頼性\n')
    p_wr = stats.get('win_rate_p')
    p_pr = stats.get('place_rate_p')
    if p_wr is not None and p_wr < 0.05:
        w(f'- 1着率: 9月 vs その他月で有意差あり（p≈{p_wr:.3f}）')
    else:
        w('- 1着率: 9月は低く見えるが、統計的に明確な差とは言えない（p≈{:.3f}）'.format(p_wr or 1))
    if p_pr is not None and p_pr < 0.05:
        w(f'- 複勝率: 9月 vs その他月で有意差あり（p≈{p_pr:.3f}）')
    else:
        w('- 複勝率: 9月 vs その他月で統計的に明確な差とは言えない（p≈{:.3f}）'.format(p_pr or 1))
    w(f"- Wilson 1着率CI: 9月 {stats['wilson_win_sep']} / その他 {stats['wilson_win_other']}")
    w('')

    w('## 9. VHの9月における特徴\n')
    sep_wr = m_sep['win_rate'] * 100
    other_wr = m_other['win_rate'] * 100
    sep_pr = m_sep['place_rate'] * 100
    other_pr = m_other['place_rate'] * 100
    if sep_wr < other_wr - 1 and abs(sep_pr - other_pr) < 2:
        w('- **1着だけ弱い**傾向: 9月は1着率が通常月より低いが、複勝率は近い。')
    elif sep_wr < other_wr - 1 and sep_pr < other_pr - 2:
        w('- **複勝圏全体が弱い**傾向: 1着率・複勝率とも9月が通常月より低い。')
    else:
        w('- 9月と通常月の差は限定的。')
    w('')

    w('## 10. 本番VH仕様（調査結果）\n')
    w('| 項目 | 内容 |')
    w('|---|---|')
    w('| 本番モジュール | `core/value_hunter.py`（軽量7特徴ロジスティック） |')
    w('| パラメータ | `data/value_hunter_light.json` |')
    w('| UI | `pages/anabaka_hunter.py` / SRA(app.py) |')
    w('| 人気条件 | **6番人気以下**（`core/longshot_threshold.LONGSHOT_MIN=6`） |')
    w('| オッズ条件 | なし（人気帯で定義） |')
    w('| スコア | neg_log_odds + 補正T/末脚/血統 percentile + combo + low_elim + pos_front |')
    w(f"| 精鋭閾値 | recall0.5 ≥ {spec['tier_elite_threshold']:.4f} |")
    w(f"| 広域網閾値 | recall0.7 ≥ {spec['tier_net_threshold']:.4f} |")
    w('| 複数頭 | レース内で該当する全頭を表示（精鋭/広域網/その他） |')
    w('| オッズ取得 | 出走表スクレイプ時点（当日） |')
    w('| 対象 | JRA中央（jyo≤10） |')
    w(f"| 検証データ | horse_races.csv {spec['data_from']}〜{spec['data_to']} |")
    w('')

    w('## 11. 今後の検討（実装しない）\n')
    w('- 9月除外・月別閾値変更は今回の結果だけでは実施しない。')
    w('- きういと同条件（前日夜オッズ5倍+）での再検証は別途可能。')
    w('')

    path = os.path.join(out_dir, 'report.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('report:', path)


if __name__ == '__main__':
    main()
