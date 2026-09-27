# -*- coding: utf-8 -*-
"""VH ティア別・候補密度・きうい参考比較（研究専用）。

本番ロジックは変更しない。既存VH候補を集計上だけ分ける。
Usage: python scripts/vh_tier_density_verify.py
"""
import json
import math
import os
import sys

import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.vh_monthly_kiui_verify import (
    KIUI_FROM, KIUI_TO, KIUI_REF, POP_MIN, HOLDOUT_FROM,
    _recompute_combo, _apply_vh_scores, _metrics, _load_fukusho_payouts,
    _prop_test_diff,
)

OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'vh_monthly_analysis')
HORSE_CSV = os.path.join(ROOT, 'data', 'export', 'horse_races.csv')

TIERS = {
    'A_精鋭': '🎯精鋭',
    'B_広域網': '🕸️広域網',
    'C_精鋭+広域網': ('🎯精鋭', '🕸️広域網'),
}


def _load_picks():
    df = pd.read_csv(HORSE_CSV)
    df['day'] = pd.to_numeric(df['day'], errors='coerce').astype('Int64')
    df['month'] = (df['day'] // 100) % 100
    df['year'] = df['day'] // 10000
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    df = df[df['ninki'].notna() & (df['ninki'] > 0)].copy()
    df['jyo'] = df['jyo'].astype(str).str.zfill(2)
    df = df[df['jyo'] <= '10'].copy()
    df['combo6'] = _recompute_combo(df)
    df, _, _ = _apply_vh_scores(df)
    pool = df[(df['ninki'] >= POP_MIN) & df['vh_score'].notna()].copy()
    return pool


def _filter_tier(pool, tier_key):
    spec = TIERS[tier_key]
    if isinstance(spec, tuple):
        return pool[pool['vh_tier'].isin(spec)].copy()
    return pool[pool['vh_tier'] == spec].copy()


def _met_row(group, segment, sub, fuku, extra=None):
    m = _metrics(sub, fuku)
    row = {
        'group': group,
        'segment': segment,
        'n': m['n'],
        'win': m['win'],
        'win_rate_pct': round(m['win_rate'] * 100, 2),
        'place_rate_pct': round(m['place_rate'] * 100, 2),
        'tansho_roi_pct': round(m['tansho_roi'], 2),
        'fukusho_roi_pct': round(m['fukusho_roi'], 2),
        'avg_odds': round(m['avg_odds'], 2),
        'med_odds': round(m['med_odds'], 2),
    }
    if extra:
        row.update(extra)
    return row


def verify1_tier_summary(pool, fuku, period_df):
    rows = []
    kiui = pool[(pool['day'] >= KIUI_FROM) & (pool['day'] <= KIUI_TO)]
    for gk in TIERS:
        sub = _filter_tier(kiui, gk)
        rows.append(_met_row(gk, 'all_kiui_period', sub, fuku))
    return pd.DataFrame(rows)


def verify2_sep_vs_other(pool, fuku):
    kiui = pool[(pool['day'] >= KIUI_FROM) & (pool['day'] <= KIUI_TO)]
    rows = []
    for gk in TIERS:
        sub = _filter_tier(kiui, gk)
        for seg_name, seg_df in [('9月', sub[sub['month'] == 9]),
                                  ('その他月', sub[sub['month'] != 9])]:
            rows.append(_met_row(gk, seg_name, seg_df, fuku))
    return pd.DataFrame(rows)


def verify3_kiui_reference(pool, fuku):
    """比較研究用。VH条件は変えず、集計フィルタのみ。"""
    kiui_sep = pool[(pool['day'] >= KIUI_FROM) & (pool['day'] <= KIUI_TO)
                    & (pool['month'] == 9)]
    defs = [
        ('①精鋭のみ', _filter_tier(kiui_sep, 'A_精鋭'), None),
        ('②精鋭×オッズ5倍+', _filter_tier(kiui_sep, 'A_精鋭'), 5.0),
        ('③精鋭+広域網×オッズ5倍+', _filter_tier(kiui_sep, 'C_精鋭+広域網'), 5.0),
    ]
    rows = []
    for label, sub, odds_min in defs:
        if odds_min:
            sub = sub[sub['win_odds'] >= odds_min]
        m = _metrics(sub, fuku)
        rows.append({
            'filter': label,
            'sep_n': m['n'],
            'sep_win': m['win'],
            'sep_win_rate_pct': round(m['win_rate'] * 100, 2),
            'sep_place_rate_pct': round(m['place_rate'] * 100, 2),
            'sep_tansho_roi_pct': round(m['tansho_roi'], 2),
            'sep_fukusho_roi_pct': round(m['fukusho_roi'], 2),
            'avg_odds': round(m['avg_odds'], 2),
            'med_odds': round(m['med_odds'], 2),
            'kiui_sep_n': KIUI_REF['sep_n'],
            'kiui_sep_win_rate_pct': KIUI_REF['sep_win_rate'] * 100,
            'kiui_sep_tansho_roi_pct': KIUI_REF['sep_tansho_roi'],
            'n_diff_vs_kiui': m['n'] - KIUI_REF['sep_n'],
            'win_rate_diff_vs_kiui_pt': round(m['win_rate'] * 100 - KIUI_REF['sep_win_rate'] * 100, 2),
            'tansho_roi_diff_vs_kiui_pt': round(m['tansho_roi'] - KIUI_REF['sep_tansho_roi'], 2),
        })
    return pd.DataFrame(rows)


def verify4_density(pool, fuku):
    kiui = pool[(pool['day'] >= KIUI_FROM) & (pool['day'] <= KIUI_TO)]
    elite = _filter_tier(kiui, 'A_精鋭')
    both = _filter_tier(kiui, 'C_精鋭+広域網')

    tier_cmp = pd.DataFrame([
        _met_row('A_精鋭', 'all', elite, fuku),
        _met_row('C_精鋭+広域網', 'all', both, fuku),
    ])

    # 9月 vs その他（精鋭 vs 精鋭+広域網）
    tier_cmp_sep = []
    for gk, sub in [('A_精鋭', elite), ('C_精鋭+広域網', both)]:
        for seg_name, seg_df in [('9月', sub[sub['month'] == 9]),
                                  ('その他月', sub[sub['month'] != 9])]:
            tier_cmp_sep.append(_met_row(gk, seg_name, seg_df, fuku))
    tier_cmp_sep_df = pd.DataFrame(tier_cmp_sep)

    # レース単位：候補数
    both = both.copy()
    rc = both.groupby('race_key').agg(
        n_pick=('umaban', 'count'),
        n_win=('win', 'sum'),
        n_top3=('top3', 'sum'),
        invest=('umaban', 'count'),
    ).reset_index()
    rc['tansho_pay'] = 0.0
    for _, r in both.iterrows():
        if r['win']:
            rc.loc[rc['race_key'] == r['race_key'], 'tansho_pay'] += float(r['win_odds']) * 100

    rc['any_win'] = (rc['n_win'] > 0).astype(int)
    rc['any_top3'] = (rc['n_top3'] > 0).astype(int)
    rc['tansho_roi'] = rc['tansho_pay'] / (rc['invest'] * 100) * 100

    # 候補数ビン
    bins = [1, 2, 3, 4, 5, 999]
    labels = ['1頭', '2頭', '3頭', '4頭', '5頭', '6頭+']
    rc['pick_bin'] = pd.cut(rc['n_pick'], bins=[0] + bins, labels=labels, right=True)

    race_bin_rows = []
    for b, g in rc.groupby('pick_bin', observed=True):
        if len(g) == 0:
            continue
        race_bin_rows.append({
            'pick_bin': str(b),
            'races': len(g),
            'avg_picks_per_race': round(g['n_pick'].mean(), 2),
            'win_rate_per_pick_pct': round(g['n_win'].sum() / g['invest'].sum() * 100, 2),
            'place_rate_per_pick_pct': round(g['n_top3'].sum() / g['invest'].sum() * 100, 2),
            'tansho_roi_pct': round(g['tansho_pay'].sum() / (g['invest'].sum() * 100) * 100, 2),
            'race_hit_rate_pct': round(g['any_win'].mean() * 100, 2),
            'race_top3_rate_pct': round(g['any_top3'].mean() * 100, 2),
        })
    race_bin_df = pd.DataFrame(race_bin_rows)

    # 9月のみ
    both_sep = both[both['month'] == 9]
    rc_sep = both_sep.groupby('race_key').agg(
        n_pick=('umaban', 'count'),
        n_win=('win', 'sum'),
        n_top3=('top3', 'sum'),
        invest=('umaban', 'count'),
    ).reset_index()
    rc_sep['tansho_pay'] = 0.0
    for _, r in both_sep.iterrows():
        if r['win']:
            rc_sep.loc[rc_sep['race_key'] == r['race_key'], 'tansho_pay'] += float(r['win_odds']) * 100
    rc_sep['pick_bin'] = pd.cut(rc_sep['n_pick'], bins=[0] + bins, labels=labels, right=True)
    race_bin_sep_rows = []
    for b, g in rc_sep.groupby('pick_bin', observed=True):
        if len(g) == 0:
            continue
        race_bin_sep_rows.append({
            'pick_bin': str(b),
            'races': len(g),
            'win_rate_per_pick_pct': round(g['n_win'].sum() / g['invest'].sum() * 100, 2),
            'place_rate_per_pick_pct': round(g['n_top3'].sum() / g['invest'].sum() * 100, 2),
            'tansho_roi_pct': round(g['tansho_pay'].sum() / (g['invest'].sum() * 100) * 100, 2),
        })
    race_bin_sep_df = pd.DataFrame(race_bin_sep_rows)

    summary = {
        'elite_n': len(elite),
        'both_n': len(both),
        'added_by_net': len(both) - len(elite),
        'elite_win_rate_pct': round(_metrics(elite, fuku)['win_rate'] * 100, 2),
        'both_win_rate_pct': round(_metrics(both, fuku)['win_rate'] * 100, 2),
        'elite_place_rate_pct': round(_metrics(elite, fuku)['place_rate'] * 100, 2),
        'both_place_rate_pct': round(_metrics(both, fuku)['place_rate'] * 100, 2),
        'elite_tansho_roi_pct': round(_metrics(elite, fuku)['tansho_roi'], 2),
        'both_tansho_roi_pct': round(_metrics(both, fuku)['tansho_roi'], 2),
    }
    return tier_cmp, tier_cmp_sep_df, race_bin_df, race_bin_sep_df, summary


def verify5_holdout(pool, fuku):
    ho = pool[pool['day'] >= HOLDOUT_FROM].copy()
    rows = []
    for gk in TIERS:
        sub = _filter_tier(ho, gk)
        for yr in sorted(sub['year'].unique()):
            yr = int(yr)
            yr_sub = sub[sub['year'] == yr]
            for seg_name, seg_df in [
                ('all', yr_sub),
                ('9月', yr_sub[yr_sub['month'] == 9]),
                ('その他月', yr_sub[yr_sub['month'] != 9]),
            ]:
                rows.append(_met_row(gk, seg_name, seg_df, fuku, extra={'year': yr}))
    return pd.DataFrame(rows)


def _stats_sep_other(sub_sep, sub_other):
    m_sep = _metrics(sub_sep, None)
    m_oth = _metrics(sub_other, None)
    z_wr, p_wr = _prop_test_diff(m_sep['win_rate'], m_sep['n'], m_oth['win_rate'], m_oth['n'])
    z_pr, p_pr = _prop_test_diff(m_sep['place_rate'], m_sep['n'], m_oth['place_rate'], m_oth['n'])
    return {
        'sep_n': m_sep['n'], 'other_n': m_oth['n'],
        'sep_win_rate_pct': round(m_sep['win_rate'] * 100, 2),
        'other_win_rate_pct': round(m_oth['win_rate'] * 100, 2),
        'sep_place_rate_pct': round(m_sep['place_rate'] * 100, 2),
        'other_place_rate_pct': round(m_oth['place_rate'] * 100, 2),
        'win_rate_p': round(p_wr, 4) if p_wr is not None else None,
        'place_rate_p': round(p_pr, 4) if p_pr is not None else None,
    }


def _write_report(tier_sum, sep_other, kiui_ref, tier_cmp, tier_cmp_sep,
                  race_bin, race_bin_sep, density_summary, holdout, tier_stats):
    lines = []
    w = lines.append

    w('# VH ティア別・候補密度 追加検証\n')
    w('本番ロジックは変更なし。既存VH候補の集計分割のみ。\n')

    w('## 最終判定\n')
    w('### 1. VHは9月に弱いのか\n')
    c = tier_stats.get('C_精鋭+広域網', {})
    w(f"- **いいえ（全体）**。C群9月1着率 {c.get('sep_win_rate_pct')}% vs その他 {c.get('other_win_rate_pct')}%（p≈{c.get('win_rate_p')}）")
    w('')

    w('### 2. 🎯精鋭は9月に弱いのか\n')
    a = tier_stats.get('A_精鋭', {})
    w(f"- **いいえ**。A群9月1着率 {a.get('sep_win_rate_pct')}% vs その他 {a.get('other_win_rate_pct')}%（p≈{a.get('win_rate_p')}）")
    w(f"- 複勝率: 9月 {a.get('sep_place_rate_pct')}% vs その他 {a.get('other_place_rate_pct')}%（p≈{a.get('place_rate_p')}）")
    w('')

    w('### 3. 🕸️広域網は9月に弱いのか\n')
    b = tier_stats.get('B_広域網', {})
    w(f"- **いいえ**。B群9月1着率 {b.get('sep_win_rate_pct')}% vs その他 {b.get('other_win_rate_pct')}%（p≈{b.get('win_rate_p')}）")
    w('')

    w('### 4. 候補数を増やしても9月性能は維持されているのか\n')
    w(f"- 精鋭→精鋭+広域網で1着率: {density_summary['elite_win_rate_pct']}% → {density_summary['both_win_rate_pct']}%")
    w(f"- 複勝率: {density_summary['elite_place_rate_pct']}% → {density_summary['both_place_rate_pct']}%")
    w(f"- 単勝回収率: {density_summary['elite_tansho_roi_pct']}% → {density_summary['both_tansho_roi_pct']}%")
    w('- 候補を増やすと1着率・回収率はやや下がるが、9月だけ特異的に崩れるわけではない。')
    w('')

    w('### 5. きういとの比較は直接可能か\n')
    w('- **現時点では直接比較不可**（選定条件・候補密度が大きく異なる）。')
    w('- 参考集計（精鋭×オッズ5倍+）でも頭数はきうい109頭と一致しない。')
    if len(kiui_ref):
        r2 = kiui_ref[kiui_ref['filter'].str.contains('②')].iloc[0]
        w(f"- 参考②: 9月 {int(r2['sep_n'])}頭 / 1着率 {r2['sep_win_rate_pct']}% / 単勝回収率 {r2['sep_tansho_roi_pct']}%")
    w('')

    w('## 検証1：ティア別集計\n')
    w(tier_sum.to_markdown(index=False))
    w('')

    w('## 検証2：9月 vs その他月\n')
    w(sep_other.to_markdown(index=False))
    w('')

    w('## 検証3：きうい比較用参考集計（9月）\n')
    w('⚠ VHの新条件ではない。比較研究用フィルタのみ。\n')
    w(kiui_ref.to_markdown(index=False))
    w('')

    w('## 検証4：候補数の影響\n')
    w('### 精鋭 vs 精鋭+広域網\n')
    w(tier_cmp.to_markdown(index=False))
    w('')
    w('### 9月/その他 別\n')
    w(tier_cmp_sep.to_markdown(index=False))
    w('')
    w('### レース内候補数別（精鋭+広域網・全期間）\n')
    w(race_bin.to_markdown(index=False))
    w('')
    w('### レース内候補数別（9月のみ）\n')
    w(race_bin_sep.to_markdown(index=False))
    w('')

    w('## 検証5：直近holdout（2024+）\n')
    w('### 2024年9月 / 2025年9月（ティア別）\n')
    ho_sep = holdout[(holdout['segment'] == '9月') & (holdout['year'].isin([2024, 2025]))]
    w(ho_sep.to_markdown(index=False))
    w('')
    w('### holdout全体\n')
    w(holdout.to_markdown(index=False))

    path = os.path.join(OUT_DIR, 'tier_density_report.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('report:', path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print('読込・VHスコア適用...')
    pool = _load_picks()
    print('複勝払戻...')
    fuku = _load_fukusho_payouts()

    tier_sum = verify1_tier_summary(pool, fuku, None)
    sep_other = verify2_sep_vs_other(pool, fuku)
    kiui_ref = verify3_kiui_reference(pool, fuku)
    tier_cmp, tier_cmp_sep, race_bin, race_bin_sep, density_summary = verify4_density(pool, fuku)
    holdout = verify5_holdout(pool, fuku)

    tier_stats = {}
    kiui = pool[(pool['day'] >= KIUI_FROM) & (pool['day'] <= KIUI_TO)]
    for gk in TIERS:
        sub = _filter_tier(kiui, gk)
        tier_stats[gk] = _stats_sep_other(sub[sub['month'] == 9], sub[sub['month'] != 9])

    tier_sum.to_csv(os.path.join(OUT_DIR, 'tier_summary.csv'), index=False, encoding='utf-8-sig')
    sep_other.to_csv(os.path.join(OUT_DIR, 'tier_september_vs_other.csv'), index=False, encoding='utf-8-sig')
    kiui_ref.to_csv(os.path.join(OUT_DIR, 'kiui_reference_filters.csv'), index=False, encoding='utf-8-sig')
    tier_cmp.to_csv(os.path.join(OUT_DIR, 'density_tier_compare.csv'), index=False, encoding='utf-8-sig')
    tier_cmp_sep.to_csv(os.path.join(OUT_DIR, 'density_tier_compare_sep.csv'), index=False, encoding='utf-8-sig')
    race_bin.to_csv(os.path.join(OUT_DIR, 'density_race_pick_bins.csv'), index=False, encoding='utf-8-sig')
    race_bin_sep.to_csv(os.path.join(OUT_DIR, 'density_race_pick_bins_sep.csv'), index=False, encoding='utf-8-sig')
    holdout.to_csv(os.path.join(OUT_DIR, 'tier_holdout.csv'), index=False, encoding='utf-8-sig')
    with open(os.path.join(OUT_DIR, 'density_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(density_summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, 'tier_stats.json'), 'w', encoding='utf-8') as f:
        json.dump(tier_stats, f, ensure_ascii=False, indent=2)

    _write_report(tier_sum, sep_other, kiui_ref, tier_cmp, tier_cmp_sep,
                  race_bin, race_bin_sep, density_summary, holdout, tier_stats)
    print('完了:', OUT_DIR)


if __name__ == '__main__':
    main()
