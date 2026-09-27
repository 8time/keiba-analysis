# -*- coding: utf-8 -*-
"""VH 改善余地探索（研究専用）。本番ロジック・JSON・閾値は変更しない。

Usage: python scripts/vh_improvement_potential.py
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

from scripts.vh_monthly_kiui_verify import (
    KIUI_FROM, KIUI_TO, HOLDOUT_FROM, RECENT6_FROM, RECENT3_FROM,
    _recompute_combo, _apply_vh_scores, _metrics, _load_fukusho_payouts,
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

SCORE_SLICES = [
    ('全精鋭', 0.0),
    ('上位75%', 0.25),
    ('上位50%', 0.50),
    ('上位25%', 0.75),
    ('上位10%', 0.90),
    ('上位5%', 0.95),
]

FEATS = [
    ('neg_log_odds', 'neg_log_odds', True),
    ('ct_pct', 'ct_pct', True),
    ('spurt_pct', 'spurt_pct', True),
    ('blood_pct', 'blood_pct', True),
    ('combo', 'combo6', True),
    ('low_elim', 'low_elim', True),
    ('pos_front', 'pos_front', True),
]


def _simple_auc(y, s):
    df = pd.DataFrame({'y': y, 's': s}).dropna()
    if len(df) < 10 or df['y'].nunique() < 2:
        return None
    df = df.sort_values('s', ascending=False)
    p = float(df['y'].sum())
    n = len(df) - p
    if p == 0 or n == 0:
        return None
    tp = fp = 0.0
    prev_fpr = prev_tpr = 0.0
    auc = 0.0
    for _, r in df.iterrows():
        if r['y']:
            tp += 1
        else:
            fp += 1
        tpr = tp / p
        fpr = fp / n
        auc += (fpr - prev_fpr) * (tpr + prev_tpr) / 2
        prev_fpr, prev_tpr = fpr, tpr
    return auc


def _load_elite_with_feats():
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
    df, thr_elite, _ = _apply_vh_scores(df)
    elite = df[(df['ninki'] >= 6) & (df['vh_tier'] == '🎯精鋭') & df['vh_score'].notna()].copy()
    wo = elite['win_odds'].clip(lower=1e-9)
    elite['neg_log_odds'] = -np.log(wo)
    elite['ct_pct'] = pd.to_numeric(elite['h7_pct'], errors='coerce')
    elite['spurt_pct'] = pd.to_numeric(elite['spurt_race_pct'], errors='coerce')
    elite['blood_pct'] = pd.to_numeric(elite['blood_race_pct'], errors='coerce')
    elite['combo6'] = pd.to_numeric(elite['combo6'], errors='coerce').fillna(0)
    elite['low_elim'] = (pd.to_numeric(elite['elim_n'], errors='coerce').fillna(9) <= 1).astype(float)
    elite['pos_front'] = (pd.to_numeric(elite['avg_pos3'], errors='coerce') <= 3.0).astype(float)
    return elite, thr_elite


def _met_dict(sub, fuku):
    m = _metrics(sub, fuku)
    return {
        'n': m['n'],
        'win_rate_pct': round(m['win_rate'] * 100, 2),
        'place_rate_pct': round(m['place_rate'] * 100, 2),
        'tansho_roi_pct': round(m['tansho_roi'], 2),
        'fukusho_roi_pct': round(m['fukusho_roi'], 2),
        'avg_odds': round(m['avg_odds'], 2),
        'med_odds': round(m['med_odds'], 2),
    }


def score_slice_analysis(elite, fuku):
    rows = []
    for pname, d0, d1 in PERIODS:
        sub = elite[(elite['day'] >= d0) & (elite['day'] <= d1)]
        if len(sub) == 0:
            continue
        scores = sub['vh_score']
        for label, q in SCORE_SLICES:
            thr = scores.quantile(q) if q > 0 else scores.min() - 1
            grp = sub[sub['vh_score'] >= thr]
            m = _met_dict(grp, fuku)
            rows.append({'period': pname, 'slice': label, 'score_threshold': round(float(thr), 4),
                         'score_quantile': q, **m})
    return pd.DataFrame(rows)


def check_monotonicity(slice_df, period='全期間'):
    sub = slice_df[slice_df['period'] == period].copy()
    order = [s[0] for s in SCORE_SLICES]
    sub['slice'] = pd.Categorical(sub['slice'], categories=order, ordered=True)
    sub = sub.sort_values('slice')
    wr = sub['win_rate_pct'].tolist()
    pr = sub['place_rate_pct'].tolist()
    tr = sub['tansho_roi_pct'].tolist()

    def _mono_increasing(vals):
        """全精鋭→上位5% に向かって非減少か。"""
        breaks = []
        for i in range(len(vals) - 1):
            if vals[i + 1] < vals[i]:
                breaks.append((order[i], order[i + 1], vals[i], vals[i + 1]))
        return len(breaks) == 0, breaks

    wr_ok, wr_breaks = _mono_increasing(wr)
    pr_ok, pr_breaks = _mono_increasing(pr)
    tr_ok, tr_breaks = _mono_increasing(tr)
    return {
        'period': period,
        'win_rate_monotonic': wr_ok,
        'place_rate_monotonic': pr_ok,
        'tansho_roi_monotonic': tr_ok,
        'win_rate_breaks': wr_breaks,
        'place_rate_breaks': pr_breaks,
        'tansho_roi_breaks': tr_breaks,
        'values': sub[['slice', 'n', 'win_rate_pct', 'place_rate_pct', 'tansho_roi_pct']].to_dict('records'),
    }


def feature_univariate(elite, fuku, period_name='全期間', d0=KIUI_FROM, d1=KIUI_TO):
    sub = elite[(elite['day'] >= d0) & (elite['day'] <= d1)].copy()
    rows = []
    for fname, col, higher_better in FEATS:
        s = pd.to_numeric(sub[col], errors='coerce')
        valid = sub[s.notna()].copy()
        valid['_v'] = s[s.notna()]
        if len(valid) < 30:
            continue
        try:
            valid['_bin'] = pd.qcut(valid['_v'], 3, labels=['低位', '中位', '高位'], duplicates='drop')
        except ValueError:
            # 二値(low_elim/pos_front)は 0/1 の2群
            valid['_bin'] = valid['_v'].map({0.0: '低位', 1.0: '高位'})
            valid = valid[valid['_bin'].notna()]
        for b in ['低位', '中位', '高位']:
            g = valid[valid['_bin'] == b]
            if len(g) == 0:
                continue
            m = _met_dict(g, fuku)
            rows.append({'period': period_name, 'feature': fname, 'bin': b, **m})
        # correlation / AUC on full valid set
        y_win = valid['win'].astype(int)
        y_top3 = valid['top3'].astype(int)
        corr_win = valid['_v'].corr(y_win, method='spearman')
        corr_top3 = valid['_v'].corr(y_top3, method='spearman')
        auc_win = _simple_auc(y_win, valid['_v'] if higher_better else -valid['_v'])
        auc_top3 = _simple_auc(y_top3, valid['_v'] if higher_better else -valid['_v'])
        rows.append({
            'period': period_name, 'feature': fname, 'bin': '_summary',
            'n': len(valid),
            'spearman_win': round(corr_win, 4) if pd.notna(corr_win) else None,
            'spearman_top3': round(corr_top3, 4) if pd.notna(corr_top3) else None,
            'auc_win': round(auc_win, 4) if auc_win is not None else None,
            'auc_top3': round(auc_top3, 4) if auc_top3 is not None else None,
        })
    return rows


def improvement_delta(slice_df, period='全期間'):
    """全精鋭 vs 上位25% / 上位10% の差分。"""
    sub = slice_df[slice_df['period'] == period].set_index('slice')
    base = sub.loc['全精鋭']
    out = {}
    for label in ('上位25%', '上位10%', '上位5%'):
        if label not in sub.index:
            continue
        row = sub.loc[label]
        out[label] = {
            'n_ratio': round(row['n'] / base['n'], 3),
            'win_rate_diff_pt': round(row['win_rate_pct'] - base['win_rate_pct'], 2),
            'place_rate_diff_pt': round(row['place_rate_pct'] - base['place_rate_pct'], 2),
            'tansho_roi_diff_pt': round(row['tansho_roi_pct'] - base['tansho_roi_pct'], 2),
            'fukusho_roi_diff_pt': round(row['fukusho_roi_pct'] - base['fukusho_roi_pct'], 2),
        }
    return out


def _judge(slice_df, mono, feat_rows, deltas):
    """A/B/C/D と 2%改善可能性。"""
    d25 = deltas.get('上位25%', {})
    d10 = deltas.get('上位10%', {})
    d05 = deltas.get('上位5%', {})

    score_helps = (
        mono.get('win_rate_monotonic')
        and d25.get('win_rate_diff_pt', 0) >= 0.5
        and d10.get('place_rate_diff_pt', 0) >= 2.0
    )
    roi_ok = d10.get('tansho_roi_diff_pt', 0) >= 1.0

    summaries = [r for r in feat_rows if r.get('bin') == '_summary' and r.get('period') == '全期間']
    strong_feats = [r['feature'] for r in summaries
                    if (r.get('auc_top3') or 0) >= 0.52 or abs(r.get('spearman_top3') or 0) >= 0.03]
    weak_feats = [r['feature'] for r in summaries
                  if (r.get('auc_top3') or 0.5) <= 0.505 and abs(r.get('spearman_top3') or 0) < 0.01]

    if score_helps and roi_ok:
        abcd = 'A'
    elif len(strong_feats) >= 2 or (strong_feats and d25.get('win_rate_diff_pt', 0) >= 0.3):
        abcd = 'B' if not score_helps else 'A'
    elif d25.get('win_rate_diff_pt', 0) < 0.3 and d10.get('tansho_roi_diff_pt', 0) < 1:
        abcd = 'C'
    elif len(strong_feats) == 0 and d25.get('win_rate_diff_pt', 0) < 0.2:
        abcd = 'D'
    else:
        abcd = 'B' if strong_feats else 'C'

    best_wr_gain = max(d25.get('win_rate_diff_pt', 0), d10.get('win_rate_diff_pt', 0),
                       d05.get('win_rate_diff_pt', 0))
    best_roi_gain = max(d25.get('tansho_roi_diff_pt', 0), d10.get('tansho_roi_diff_pt', 0),
                        d05.get('tansho_roi_diff_pt', 0))
    best_place_gain = max(d25.get('place_rate_diff_pt', 0), d10.get('place_rate_diff_pt', 0),
                          d05.get('place_rate_diff_pt', 0))

    holdout_mono = mono  # caller passes holdout separately in report
    holdout_roi_drop = d10.get('tansho_roi_diff_pt', 0)  # placeholder

    if best_wr_gain >= 1.5 and best_roi_gain >= 2 and mono.get('win_rate_monotonic'):
        pct_label = '可能性高い'
    elif best_wr_gain >= 0.5 and (best_roi_gain >= 1.5 or best_place_gain >= 3):
        pct_label = '可能性あり'
    elif best_wr_gain >= 0.3 or best_roi_gain >= 1:
        pct_label = '判断困難'
    else:
        pct_label = '可能性低い'

    return {
        'abcd': abcd,
        'pct_label': pct_label,
        'strong_feats': strong_feats,
        'weak_feats': weak_feats,
        'best_wr_gain': best_wr_gain,
        'best_roi_gain': best_roi_gain,
        'best_place_gain': best_place_gain,
    }


def _write_report(slice_df, mono_all, mono_holdout, feat_df, feat_summaries,
                  deltas, judge, thr_elite):
    lines = []
    w = lines.append

    w('# VH 改善余地探索レポート\n')
    w('本番ロジック・JSON・閾値は変更なし。分析のみ。\n')

    w('## 1. スコア分位点別成績（🎯精鋭）\n')
    w(f'精鋭閾値: score ≥ {thr_elite:.4f}\n')
    for pname in slice_df['period'].unique():
        w(f'### {pname}\n')
        sub = slice_df[slice_df['period'] == pname]
        w(sub[['slice', 'n', 'win_rate_pct', 'place_rate_pct', 'tansho_roi_pct',
               'fukusho_roi_pct', 'avg_odds', 'med_odds']].to_markdown(index=False))
        w('')

    w('## 2. 直近holdout\n')
    for pname in ('2024年以降', '2025年'):
        if pname in slice_df['period'].values:
            w(f'### {pname}\n')
            w(slice_df[slice_df['period'] == pname].to_markdown(index=False))
            w('')

    w('## 3. 7特徴の分位点別成績（全期間・精鋭）\n')
    bins = feat_df[(feat_df['bin'].isin(['低位', '中位', '高位'])) & (feat_df['period'] == '全期間')]
    for fname in bins['feature'].unique():
        w(f'### {fname}\n')
        w(bins[bins['feature'] == fname][['bin', 'n', 'win_rate_pct', 'place_rate_pct',
                                          'tansho_roi_pct']].to_markdown(index=False))
        w('')

    w('## 4. スコア順位の単調性\n')
    for m in (mono_all, mono_holdout):
        w(f"### {m['period']}\n")
        w(f"- 1着率: {'単調（上位ほど高い）' if m['win_rate_monotonic'] else '単調でない'}")
        if m['win_rate_breaks']:
            for b in m['win_rate_breaks']:
                w(f"  - 逆転: {b[0]}→{b[1]} ({b[2]}%→{b[3]}%)")
        w(f"- 複勝率: {'単調' if m['place_rate_monotonic'] else '単調でない'}")
        if m['place_rate_breaks']:
            for b in m['place_rate_breaks']:
                w(f"  - 逆転: {b[0]}→{b[1]} ({b[2]}%→{b[3]}%)")
        w(f"- 単勝回収率: {'単調' if m['tansho_roi_monotonic'] else '単調でない'}")
        if m['tansho_roi_breaks']:
            for b in m['tansho_roi_breaks']:
                w(f"  - 逆転: {b[0]}→{b[1]} ({b[2]}%→{b[3]}%)")
        w('')

    w('## 5. ROIへの影響（全精鋭 vs 濃縮）\n')
    w('| 濃縮 | 頭数比 | 1着率差 | 複勝率差 | 単勝回収率差 | 複勝回収率差 |')
    w('|---|---:|---:|---:|---:|---:|')
    for label, d in deltas.items():
        w(f"| {label} | {d['n_ratio']:.1%} | {d['win_rate_diff_pt']:+.2f}pt | "
          f"{d['place_rate_diff_pt']:+.2f}pt | {d['tansho_roi_diff_pt']:+.2f}pt | "
          f"{d['fukusho_roi_diff_pt']:+.2f}pt |")
    w('')
    w('※ 1着率だけ上がって回収率が下がる濃縮は「改善」とは見なさない。')
    w('')

    w('## 6. 特徴量サマリ（Spearman / AUC）\n')
    fs = feat_summaries[feat_summaries['period'] == '全期間'] if 'period' in feat_summaries.columns else feat_summaries
    w(fs.to_markdown(index=False))
    w('')
    w('相関が弱い特徴の削除は推奨しない（分析のみ）。')
    w('')

    w('## 7. 改善余地の判定\n')
    w(f"### ABCD分類: **{judge['abcd']}**\n")
    abcd_txt = {
        'A': 'スコア上位に行くほど性能が明確に上昇 → 濃縮による改善余地あり',
        'B': '一部の特徴量に明確な性能差 → 特徴量設計の改善余地あり',
        'C': 'スコア上位化しても性能が大きく変わらない → 順位付け能力に限界',
        'D': '全体的にランダムに近い → 閾値いじりは危険',
    }
    w(abcd_txt.get(judge['abcd'], ''))
    w('')
    if judge['strong_feats']:
        w(f"- 予測力が相対的に高い特徴: {', '.join(judge['strong_feats'])}")
    if judge['weak_feats']:
        w(f"- 予測力が弱い特徴（削除はしない）: {', '.join(judge['weak_feats'])}")
    w('')

    w('## 8. 次に検証すべき候補\n')
    w('- holdout固定で「上位25%濃縮」の再現性（今回は閾値決定はしない）')
    w('- レース内1位のみ vs 精鋭全頭の比較（既存検証: VH1位が+4pp）')
    w('- neg_log_odds（市場）除外時の残差（project_value_horse_hunter参照）')
    w('- 広域網を足すと薄まる点の再確認（前回 tier 検証済）')
    w('')

    w('## 9. 「約2%改善できそうか」\n')
    w(f"**判定: {judge['pct_label']}**\n")
    w(f"- 濃縮で得られる1着率改善（最大）: {judge['best_wr_gain']:+.2f}pt")
    w(f"- 濃縮で得られる複勝率改善（最大）: {judge['best_place_gain']:+.2f}pt")
    w(f"- 濃縮で得られる単勝回収率改善（最大）: {judge['best_roi_gain']:+.2f}pt")
    w('')
    w('9月は補助確認のみ: 精鋭9月 vs その他の差は前回検証どおり限定的。')
    w('')

    path = os.path.join(OUT_DIR, 'vh_improvement_potential.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('report:', path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print('読込...')
    elite, thr_elite = _load_elite_with_feats()
    print('複勝払戻...')
    fuku = _load_fukusho_payouts()

    print('スコア分位分析...')
    slice_df = score_slice_analysis(elite, fuku)
    slice_df.to_csv(os.path.join(OUT_DIR, 'score_slice_analysis.csv'),
                    index=False, encoding='utf-8-sig')

    mono_all = check_monotonicity(slice_df, '全期間')
    mono_holdout = check_monotonicity(slice_df, '2024年以降')

    print('7特徴単変量...')
    feat_rows = []
    for pname, d0, d1 in PERIODS:
        feat_rows.extend(feature_univariate(elite, fuku, pname, d0, d1))
    feat_df = pd.DataFrame([r for r in feat_rows if r.get('bin') != '_summary'])
    feat_summaries = pd.DataFrame([r for r in feat_rows if r.get('bin') == '_summary'])
    feat_df.to_csv(os.path.join(OUT_DIR, 'feature_univariate_bins.csv'),
                   index=False, encoding='utf-8-sig')
    feat_summaries.to_csv(os.path.join(OUT_DIR, 'feature_univariate_summary.csv'),
                          index=False, encoding='utf-8-sig')

    deltas = {}
    for pname in ('全期間', '2024年以降', '2025年'):
        deltas[pname] = improvement_delta(slice_df, pname)

    judge = _judge(slice_df, mono_all, feat_rows, deltas['全期間'])

    with open(os.path.join(OUT_DIR, 'improvement_monotonicity.json'), 'w', encoding='utf-8') as f:
        json.dump({'全期間': mono_all, '2024年以降': mono_holdout}, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(OUT_DIR, 'improvement_deltas.json'), 'w', encoding='utf-8') as f:
        json.dump(deltas, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, 'improvement_judge.json'), 'w', encoding='utf-8') as f:
        json.dump(judge, f, ensure_ascii=False, indent=2)

    _write_report(slice_df, mono_all, mono_holdout, feat_df, feat_summaries,
                  deltas['全期間'], judge, thr_elite)
    print('完了')


if __name__ == '__main__':
    main()
