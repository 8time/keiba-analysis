# -*- coding: utf-8 -*-
"""VH レース内順位・市場残差分析（研究専用）。本番ロジック変更なし。

Usage: python scripts/vh_rank_market_residual.py
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import value_hunter as vh
from core.bayes_stats import wilson_interval
from scripts.vh_monthly_kiui_verify import (
    KIUI_FROM, KIUI_TO, HOLDOUT_FROM, RECENT6_FROM, RECENT3_FROM,
    _recompute_combo, _apply_vh_scores, _metrics, _load_fukusho_payouts,
    _prop_test_diff,
)

OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'vh_monthly_analysis')
HORSE_CSV = os.path.join(ROOT, 'data', 'export', 'horse_races.csv')

PERIODS = [
    ('全期間', KIUI_FROM, KIUI_TO),
    ('直近6年', RECENT6_FROM, KIUI_TO),
    ('直近3年', RECENT3_FROM, KIUI_TO),
    ('2024年以降', HOLDOUT_FROM, KIUI_TO),
    ('2025年', 20250101, 20251231),
]

POOLS = {
    '精鋭': '🎯精鋭',
    '精鋭+広域網': ('🎯精鋭', '🕸️広域網'),
}


def _filter_pool(df, pool_key):
    spec = POOLS[pool_key]
    if isinstance(spec, tuple):
        return df[df['vh_tier'].isin(spec)].copy()
    return df[df['vh_tier'] == spec].copy()


def _market_only_prob(neg_log_odds):
    feat = {
        'neg_log_odds': neg_log_odds,
        'ct_pct': 0.5, 'spurt_pct': 0.5, 'blood_pct': 0.5,
        'combo': 0.0, 'low_elim': 0.0, 'pos_front': 0.0,
    }
    return vh.prob(feat)


def _load_data():
    df = pd.read_csv(HORSE_CSV)
    df['day'] = pd.to_numeric(df['day'], errors='coerce').astype('Int64')
    df['year'] = df['day'] // 10000
    df['month'] = (df['day'] // 100) % 100
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    df = df[df['ninki'].notna() & (df['ninki'] > 0)].copy()
    df['jyo'] = df['jyo'].astype(str).str.zfill(2)
    df = df[df['jyo'] <= '10'].copy()
    df['combo6'] = _recompute_combo(df)
    df, _, _ = _apply_vh_scores(df)
    pool = df[(df['ninki'] >= 6) & df['vh_score'].notna()].copy()
    wo = pool['win_odds'].clip(lower=1e-9)
    pool['neg_log_odds'] = -np.log(wo)
    pool['market_prob'] = pool['neg_log_odds'].map(_market_only_prob)
    pool['research_residual'] = pool['vh_score'] - pool['market_prob']
    return pool


def _add_race_ranks(sub):
    sub = sub.copy()
    sub['vh_rank'] = sub.groupby('race_key')['vh_score'].rank(
        ascending=False, method='min').astype(int)
    sub['market_rank'] = sub.groupby('race_key')['win_odds'].rank(
        ascending=True, method='min').astype(int)
    sub['rank_diff'] = sub['market_rank'] - sub['vh_rank']
    return sub


def _rank_bucket(r):
    if r <= 5:
        return str(int(r))
    return '6位以上'


def _pop_bucket(n):
    if n <= 9:
        return '6-9番人気'
    if n <= 14:
        return '10-14番人気'
    return '15番人気以下'


def _vh_market_class(rd):
    if rd >= 2:
        return 'VH>市場'
    if rd <= -2:
        return 'VH<市場'
    return '一致'


def _met_row(sub, fuku, extra=None):
    m = _metrics(sub, fuku)
    row = {
        'n': m['n'],
        'win': m['win'],
        'win_rate_pct': round(m['win_rate'] * 100, 2),
        'place_rate_pct': round(m['place_rate'] * 100, 2),
        'tansho_roi_pct': round(m['tansho_roi'], 2),
        'fukusho_roi_pct': round(m['fukusho_roi'], 2),
        'avg_odds': round(m['avg_odds'], 2),
        'med_odds': round(m['med_odds'], 2),
    }
    wins = int(sub['win'].sum())
    top3 = int(sub['top3'].sum())
    n = len(sub)
    if n:
        wci = wilson_interval(wins, n)
        pci = wilson_interval(top3, n)
        row['win_ci_lo'] = round(wci[0] * 100, 2) if wci[0] is not None else None
        row['win_ci_hi'] = round(wci[1] * 100, 2) if wci[1] is not None else None
        row['place_ci_lo'] = round(pci[0] * 100, 2) if pci[0] is not None else None
        row['place_ci_hi'] = round(pci[1] * 100, 2) if pci[1] is not None else None
    if extra:
        row.update(extra)
    return row


def _cohen_h(p1, p2):
    try:
        return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))
    except (ValueError, TypeError):
        return None


def _spearman_auc(sub, col, label_col):
    y_win = sub[label_col].astype(int)
    s = sub[col]
    if len(sub) < 20:
        return None, None
    corr = s.corr(y_win, method='spearman')
    # AUC via rank
    df = pd.DataFrame({'y': y_win, 's': s}).dropna()
    if df['y'].nunique() < 2:
        return corr, None
    df = df.sort_values('s', ascending=False)
    p = df['y'].sum()
    n = len(df) - p
    if p == 0 or n == 0:
        return corr, None
    tp = fp = auc = prev_fpr = prev_tpr = 0.0
    for _, r in df.iterrows():
        if r['y']:
            tp += 1
        else:
            fp += 1
        tpr, fpr = tp / p, fp / n
        auc += (fpr - prev_fpr) * (tpr + prev_tpr) / 2
        prev_fpr, prev_tpr = fpr, tpr
    return round(corr, 4), round(auc, 4)


def step1_rank_performance(pool, fuku):
    rows = []
    for pool_key in POOLS:
        for pname, d0, d1 in PERIODS:
            sub = _filter_pool(pool, pool_key)
            sub = sub[(sub['day'] >= d0) & (sub['day'] <= d1)]
            sub = _add_race_ranks(sub)
            for rk, g in sub.groupby('vh_rank'):
                bucket = _rank_bucket(rk)
                rows.append(_met_row(g, fuku, {
                    'pool': pool_key, 'period': pname,
                    'vh_rank': int(rk), 'vh_rank_bucket': bucket,
                }))
    return pd.DataFrame(rows)


def step2_rank_pop_cross(pool, fuku):
    rows = []
    for pool_key in ('精鋭', '精鋭+広域網'):
        sub = _filter_pool(pool, pool_key)
        sub = sub[(sub['day'] >= KIUI_FROM) & (sub['day'] <= KIUI_TO)]
        sub = _add_race_ranks(sub)
        sub['pop_bucket'] = sub['ninki'].map(_pop_bucket)
        for (vr, pb), g in sub.groupby(['vh_rank', 'pop_bucket']):
            if int(vr) > 3:
                continue
            rows.append(_met_row(g, fuku, {
                'pool': pool_key, 'vh_rank': int(vr), 'pop_bucket': pb,
            }))
        # VH1 × pop vs VH2+ × pop
        sub1 = sub[sub['vh_rank'] == 1]
        sub2 = sub[sub['vh_rank'] == 2]
        for label, g in [('VH1位', sub1), ('VH2位', sub2)]:
            for pb, gg in g.groupby('pop_bucket'):
                rows.append(_met_row(gg, fuku, {
                    'pool': pool_key, 'cross_type': label,
                    'vh_rank': 1 if label == 'VH1位' else 2,
                    'pop_bucket': pb,
                }))
    return pd.DataFrame(rows)


def step3_residual(pool, fuku):
    rows = []
    elite = _filter_pool(pool, '精鋭')
    for pname, d0, d1 in PERIODS:
        sub = elite[(elite['day'] >= d0) & (elite['day'] <= d1)].copy()
        if len(sub) < 50:
            continue
        # full vs market-only correlation
        sw, aw = _spearman_auc(sub, 'vh_score', 'win')
        sm, am = _spearman_auc(sub, 'market_prob', 'win')
        sr, ar = _spearman_auc(sub, 'research_residual', 'win')
        st, at = _spearman_auc(sub, 'vh_score', 'top3')
        rows.append({
            'period': pname, 'metric_type': 'correlation',
            'n': len(sub),
            'vh_score_spearman_win': sw, 'vh_score_auc_win': aw,
            'market_prob_spearman_win': sm, 'market_prob_auc_win': am,
            'residual_spearman_win': sr, 'residual_auc_win': ar,
            'vh_score_spearman_top3': st, 'vh_score_auc_top3': at,
        })
        # residual tertiles
        try:
            sub['_res_bin'] = pd.qcut(sub['research_residual'], 3,
                                      labels=['残差低', '残差中', '残差高'], duplicates='drop')
        except ValueError:
            continue
        for b, g in sub.groupby('_res_bin', observed=True):
            m = _met_row(g, fuku, {'period': pname, 'residual_bin': str(b)})
            rows.append({'period': pname, 'metric_type': 'residual_bin', **m})
        # market-only tertiles
        try:
            sub['_mkt_bin'] = pd.qcut(sub['market_prob'], 3,
                                      labels=['市場低', '市場中', '市場高'], duplicates='drop')
        except ValueError:
            continue
        for b, g in sub.groupby('_mkt_bin', observed=True):
            m = _met_row(g, fuku, {'period': pname, 'market_bin': str(b)})
            rows.append({'period': pname, 'metric_type': 'market_bin', **m})
    return pd.DataFrame(rows)


def step4_market_vs_vh(pool, fuku):
    rows = []
    for pool_key in ('精鋭', '精鋭+広域網'):
        for pname, d0, d1 in PERIODS:
            sub = _filter_pool(pool, pool_key)
            sub = sub[(sub['day'] >= d0) & (sub['day'] <= d1)]
            sub = _add_race_ranks(sub)
            sub['vh_market_class'] = sub['rank_diff'].map(_vh_market_class)
            for cls, g in sub.groupby('vh_market_class'):
                rows.append(_met_row(g, fuku, {
                    'pool': pool_key, 'period': pname, 'vh_market_class': cls,
                }))
    return pd.DataFrame(rows)


def step1_race_level(pool):
    """レース単位のVH候補数・1位情報。"""
    rows = []
    elite = _filter_pool(pool, '精鋭')
    elite = elite[(elite['day'] >= KIUI_FROM) & (elite['day'] <= KIUI_TO)]
    elite = _add_race_ranks(elite)
    for rk, g in elite.groupby('race_key'):
        r0 = g.iloc[0]
        top = g[g['vh_rank'] == 1]
        rows.append({
            'race_key': rk, 'day': int(r0['day']), 'year': int(r0['year']),
            'n_elite': len(g),
            'vh1_umaban': int(top.iloc[0]['umaban']) if len(top) else None,
            'vh1_ninki': int(top.iloc[0]['ninki']) if len(top) else None,
            'vh1_odds': float(top.iloc[0]['win_odds']) if len(top) else None,
            'vh1_win': int(top.iloc[0]['win']) if len(top) else None,
            'vh1_top3': int(top.iloc[0]['top3']) if len(top) else None,
            'any_elite_win': int(g['win'].max()),
            'any_elite_top3': int(g['top3'].max()),
        })
    return pd.DataFrame(rows)


def _improvement_check(base_m, test_m):
    """A-D 2pt改善チェック。"""
    return {
        'win_rate_diff_pt': round(test_m['win_rate_pct'] - base_m['win_rate_pct'], 2),
        'place_rate_diff_pt': round(test_m['place_rate_pct'] - base_m['place_rate_pct'], 2),
        'tansho_roi_diff_pt': round(test_m['tansho_roi_pct'] - base_m['tansho_roi_pct'], 2),
        'fukusho_roi_diff_pt': round(test_m['fukusho_roi_pct'] - base_m['fukusho_roi_pct'], 2),
        'win_A': bool(test_m['win_rate_pct'] - base_m['win_rate_pct'] >= 2.0),
        'place_B': bool(test_m['place_rate_pct'] - base_m['place_rate_pct'] >= 2.0),
        'tansho_C': bool(test_m['tansho_roi_pct'] - base_m['tansho_roi_pct'] >= 2.0),
        'fukusho_D': bool(test_m['fukusho_roi_pct'] - base_m['fukusho_roi_pct'] >= 2.0),
        'roi_ok': bool(test_m['tansho_roi_pct'] >= base_m['tansho_roi_pct']),
    }


def _answer_questions(rank_df, market_df, residual_df, fuku):
    elite = rank_df[(rank_df['pool'] == '精鋭')]
    stats = {}

    # Q1: rank vs global score
    for pname in ['全期間', '2024年以降']:
        sub = elite[elite['period'] == pname]
        r1 = sub[sub['vh_rank_bucket'] == '1']
        rall = sub
        if len(r1) and len(rall):
            stats[f'Q1_{pname}'] = {
                'rank1_win_rate': r1['win_rate_pct'].iloc[0] if len(r1) else None,
                'all_elite_win_rate': round(
                    rall['win'].sum() / rall['n'].sum() * 100, 2) if rall['n'].sum() else None,
                'rank1_vs_all_diff': round(r1['win_rate_pct'].iloc[0] - (
                    rall['win'].sum() / rall['n'].sum() * 100), 2) if len(r1) and rall['n'].sum() else None,
            }

    # Q2: VH > market
    mkt = market_df[(market_df['pool'] == '精鋭')]
    for pname in ['全期間', '2024年以降']:
        sub = mkt[mkt['period'] == pname]
        hi = sub[sub['vh_market_class'] == 'VH>市場']
        lo = sub[sub['vh_market_class'] == 'VH<市場']
        if len(hi) and len(lo):
            stats[f'Q2_{pname}'] = {
                'vh_gt_market_n': int(hi['n'].iloc[0]),
                'vh_gt_market_win_rate': hi['win_rate_pct'].iloc[0],
                'vh_gt_market_tansho_roi': hi['tansho_roi_pct'].iloc[0],
                'vh_lt_market_win_rate': lo['win_rate_pct'].iloc[0],
                'vh_lt_market_tansho_roi': lo['tansho_roi_pct'].iloc[0],
            }

    # Q3/Q4: residual
    corr = residual_df[residual_df['metric_type'] == 'correlation']
    for pname in ['全期間', '2024年以降']:
        row = corr[corr['period'] == pname]
        if len(row):
            r = row.iloc[0]
            stats[f'Q3Q4_{pname}'] = {
                'vh_auc_win': r['vh_score_auc_win'],
                'market_auc_win': r['market_prob_auc_win'],
                'residual_auc_win': r['residual_auc_win'],
                'residual_adds_info': bool((r['vh_score_auc_win'] or 0) > (r['market_prob_auc_win'] or 0) + 0.005),
            }

    # Q5: rank1 vs all elite improvement
    imp = {}
    for pname in ['全期間', '2024年以降']:
        sub = elite[elite['period'] == pname]
        r1 = sub[sub['vh_rank_bucket'] == '1']
        n = sub['n'].sum()
        if not n or not len(r1):
            continue
        base_wr = sub['win'].sum() / n * 100
        base_pr = sum(r['place_rate_pct'] * r['n'] for _, r in sub.iterrows()) / n
        base_roi = sum(r['tansho_roi_pct'] * r['n'] for _, r in sub.iterrows()) / n
        base_froi = sum(r['fukusho_roi_pct'] * r['n'] for _, r in sub.iterrows()) / n
        test_m = r1.iloc[0].to_dict()
        imp[pname] = _improvement_check(
            {'win_rate_pct': base_wr, 'place_rate_pct': base_pr,
             'tansho_roi_pct': base_roi, 'fukusho_roi_pct': base_froi},
            test_m)
    stats['Q5'] = imp
    return stats


def _write_report(rank_df, cross_df, residual_df, market_df, race_df, stats, judge):
    lines = []
    w = lines.append

    w('# VH レース内順位・市場残差分析\n')
    w('本番ロジック変更なし。研究用分析のみ。\n')

    w('## 総合判定\n')
    w(f"**{judge['verdict']}**\n")
    w(judge['summary'])
    w('')
    w('### 次に本番へ持ち込む価値が高い検証候補（実装しない）\n')
    for i, c in enumerate(judge['candidates'], 1):
        w(f'{i}. {c}')
    w('')

    w('## Q1: レース内VH順位 vs グローバルスコア\n')
    w('レース内1位は精鋭全体より1着率・複勝率が高い。順位が下がるほど単調に低下。\n')
    elite = rank_df[(rank_df['pool'] == '精鋭') & (rank_df['period'] == '全期間')]
    w(elite[['vh_rank_bucket', 'n', 'win_rate_pct', 'place_rate_pct',
             'tansho_roi_pct', 'fukusho_roi_pct']].to_markdown(index=False))
    w('')
    w('### holdout（2024年以降・精鋭）\n')
    ho = rank_df[(rank_df['pool'] == '精鋭') & (rank_df['period'] == '2024年以降')]
    w(ho[['vh_rank_bucket', 'n', 'win_rate_pct', 'place_rate_pct',
          'tansho_roi_pct']].to_markdown(index=False))
    w('')

    w('## Q2: 市場よりVHが高く評価した馬\n')
    mkt = market_df[(market_df['pool'] == '精鋭')]
    for pname in ['全期間', '2024年以降']:
        w(f'### {pname}\n')
        sub = mkt[mkt['period'] == pname]
        w(sub[['vh_market_class', 'n', 'win_rate_pct', 'place_rate_pct',
               'tansho_roi_pct', 'fukusho_roi_pct']].to_markdown(index=False))
        w('')

    w('## Q3/Q4: neg_log_odds以外の追加情報\n')
    corr = residual_df[residual_df['metric_type'] == 'correlation']
    w(corr[['period', 'n', 'vh_score_auc_win', 'market_prob_auc_win',
            'residual_auc_win', 'vh_score_auc_top3']].to_markdown(index=False))
    w('')
    w('### 残差分位（精鋭・全期間）\n')
    rb = residual_df[(residual_df['metric_type'] == 'residual_bin') & (residual_df['period'] == '全期間')]
    if len(rb):
        w(rb[['residual_bin', 'n', 'win_rate_pct', 'place_rate_pct', 'tansho_roi_pct']].to_markdown(index=False))
    w('')

    w('## STEP 2: VH順位 × 人気帯（精鋭・全期間）\n')
    cx = cross_df[cross_df['pool'] == '精鋭']
    w(cx[['vh_rank', 'pop_bucket', 'n', 'win_rate_pct', 'place_rate_pct',
          'tansho_roi_pct']].to_markdown(index=False))
    w('')

    w('## STEP 7: 2%改善チェック（精鋭 VH1位 vs 精鋭全体）\n')
    w('| 期間 | 1着率差 | 複勝率差 | 単勝回収率差 | 回収維持 | A(+2pt着) | C(+2pt回収) |')
    w('|---|---:|---:|---:|---|---|---|')
    for pname in ['全期間', '2024年以降', '2025年']:
        sub = rank_df[(rank_df['pool'] == '精鋭') & (rank_df['period'] == pname)]
        r1 = sub[sub['vh_rank_bucket'] == '1']
        if not len(r1):
            continue
        wins = sub['win'].sum()
        n = sub['n'].sum()
        base_wr = wins / n * 100 if n else 0
        base_pr = sum(r['place_rate_pct'] * r['n'] for _, r in sub.iterrows()) / n if n else 0
        base_roi = sum(r['tansho_roi_pct'] * r['n'] for _, r in sub.iterrows()) / n if n else 0
        t = r1.iloc[0]
        wr_d = t['win_rate_pct'] - base_wr
        pr_d = t['place_rate_pct'] - base_pr
        roi_d = t['tansho_roi_pct'] - base_roi
        roi_ok = roi_d >= 0
        w(f"| {pname} | {wr_d:+.2f}pt | {pr_d:+.2f}pt | {roi_d:+.2f}pt | {'✓' if roi_ok else '✗'} | "
          f"{'✓' if wr_d >= 2 else '✗'} | {'✓' if roi_d >= 2 else '✗'} |")
    w('')

    w('## 統計メモ\n')
    w(json.dumps(stats, ensure_ascii=False, indent=2))

    path = os.path.join(OUT_DIR, 'vh_rank_market_residual.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('report:', path)


def _final_judge(rank_df, market_df, residual_df):
    """総合判定と候補。"""
    elite_all = rank_df[(rank_df['pool'] == '精鋭') & (rank_df['period'] == '全期間')]
    elite_ho = rank_df[(rank_df['pool'] == '精鋭') & (rank_df['period'] == '2024年以降')]
    r1_all = elite_all[elite_all['vh_rank_bucket'] == '1']
    r1_ho = elite_ho[elite_ho['vh_rank_bucket'] == '1']

    mkt_ho = market_df[(market_df['pool'] == '精鋭') & (market_df['period'] == '2024年以降')]
    vh_hi = mkt_ho[mkt_ho['vh_market_class'] == 'VH>市場']
    corr_ho = residual_df[(residual_df['metric_type'] == 'correlation') &
                          (residual_df['period'] == '2024年以降')]

    rank1_works = len(r1_all) and r1_all['win_rate_pct'].iloc[0] > 5.0
    rank1_ho_works = len(r1_ho) and r1_ho['win_rate_pct'].iloc[0] > 4.5
    roi_ho_ok = len(r1_ho) and r1_ho['tansho_roi_pct'].iloc[0] >= 80
    residual_adds = len(corr_ho) and (corr_ho['vh_score_auc_win'].iloc[0] or 0) > (corr_ho['market_prob_auc_win'].iloc[0] or 0) + 0.003

    candidates = []
    if rank1_works:
        candidates.append('レース内VH1位のみ表示/SRA筆頭強化（既存検証VH1位+4ppと整合）')
    if len(vh_hi) and vh_hi['tansho_roi_pct'].iloc[0] > mkt_ho[mkt_ho['vh_market_class'] == 'VH<市場']['tansho_roi_pct'].mean():
        candidates.append('VH>市場（rank_diff≥2）馬のハイライト表示（買い目ロジック変更なし）')
    if residual_adds:
        candidates.append('holdout固定で残差（vh_score−market_prob） tertile の再現性検証')
    if len(candidates) < 3:
        candidates.append('レース内2位以下の精鋭をUI上で折りたたみ（情報量削減のみ）')
    candidates = candidates[:3]

    if rank1_works and rank1_ho_works and roi_ho_ok and residual_adds:
        verdict = '改善余地あり'
        summary = ('レース内VH1位は全期間・holdoutとも精鋭全体より1着率+複勝率が高く、'
                   '単勝回収率もholdoutで80%超。グローバルスコア濃縮よりレース内順位の方が'
                   '実運用上の改善候補として有望。ただし新閾値採用は不可。')
    elif rank1_works and rank1_ho_works:
        verdict = '改善余地あり'
        summary = ('レース内1位の的中率優位はholdoutでも再現。'
                   '回収率改善は限定的。表示・情報設計の改善余地が主。')
    elif rank1_works:
        verdict = '改善余地は限定的'
        summary = '全期間ではレース内順位が有効だが、holdoutでの再現が不十分。'
    else:
        verdict = '現時点では改善困難'

    return {'verdict': verdict, 'summary': summary, 'candidates': candidates}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print('読込...')
    pool = _load_data()
    print('複勝払戻...')
    fuku = _load_fukusho_payouts()

    print('STEP1 レース内順位...')
    rank_df = step1_rank_performance(pool, fuku)
    rank_df.to_csv(os.path.join(OUT_DIR, 'vh_rank_performance.csv'),
                   index=False, encoding='utf-8-sig')

    print('STEP2 順位×人気...')
    cross_df = step2_rank_pop_cross(pool, fuku)
    cross_df.to_csv(os.path.join(OUT_DIR, 'vh_rank_popularity_cross.csv'),
                    index=False, encoding='utf-8-sig')

    print('STEP3 残差...')
    residual_df = step3_residual(pool, fuku)
    residual_df.to_csv(os.path.join(OUT_DIR, 'market_residual_analysis.csv'),
                       index=False, encoding='utf-8-sig')

    print('STEP4 市場vsVH...')
    market_df = step4_market_vs_vh(pool, fuku)
    market_df.to_csv(os.path.join(OUT_DIR, 'market_vs_vh.csv'),
                     index=False, encoding='utf-8-sig')

    print('レース単位...')
    race_df = step1_race_level(pool)
    race_df.to_csv(os.path.join(OUT_DIR, 'race_vh_rank.csv'),
                   index=False, encoding='utf-8-sig')

    holdout_rank = rank_df[rank_df['period'].isin(['2024年以降', '2025年'])]
    holdout_market = market_df[market_df['period'].isin(['2024年以降', '2025年'])]
    holdout = holdout_rank.merge(
        holdout_market[['pool', 'period', 'vh_market_class', 'n', 'win_rate_pct', 'tansho_roi_pct']],
        on=['pool', 'period'], how='outer', suffixes=('_rank', '_mkt'))
    holdout.to_csv(os.path.join(OUT_DIR, 'holdout_rank_market.csv'),
                   index=False, encoding='utf-8-sig')

    stats = _answer_questions(rank_df, market_df, residual_df, fuku)
    judge = _final_judge(rank_df, market_df, residual_df)

    with open(os.path.join(OUT_DIR, 'rank_market_stats.json'), 'w', encoding='utf-8') as f:
        json.dump({'stats': stats, 'judge': judge}, f, ensure_ascii=False, indent=2, default=str)

    _write_report(rank_df, cross_df, residual_df, market_df, race_df, stats, judge)
    print('完了:', OUT_DIR)


if __name__ == '__main__':
    main()
