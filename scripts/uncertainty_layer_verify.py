# -*- coding: utf-8 -*-
"""研究用: 不確実性レイヤー検証（本番ロジックは変更しない）。

現行エンジン → Rank(ability_score) → 既存買い目 の後段として、
  ① キャリブレーション（現行 / Venn-Abers / Beta）
  ② 通常EV vs 保守EV
  ③ 予測幅と実績誤差
を同一holdoutで比較する。

「確率の見た目がきれい」だけでは不採用。
馬券判断（ROI / 見送り / 大負け）が改善した場合だけ採用候補。

分割（LTRと整合）:
  較正fit = 2024年（LTRのval年）
  holdout = 2025年以降（+2026単独も併記）

Usage: python scripts/uncertainty_layer_verify.py
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.isotonic import IsotonicRegression

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import csv_data as cd

OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'uncertainty_layer')
CAL_YEAR = 2024
HOLDOUT_FROM = 2025
MIN_HORSES = 8
UNIT = 100
ECE_BINS = 10
EV_THRESHOLDS = (1.00, 1.10)
SCORE_ROUND = 4  # Venn-Abersをスコア格子でキャッシュ


def softmax_neg_ability(df):
    """ability_scoreは低いほど良い。レース内softmaxで勝率代理にする。"""
    p = np.zeros(len(df), dtype=np.float64)
    for idx in df.groupby('race_key', sort=False).indices.values():
        s = -df.iloc[idx]['ability_score'].to_numpy(dtype=np.float64)
        s = s - np.nanmax(s)
        e = np.exp(s)
        tot = e.sum()
        p[idx] = e / tot if tot > 0 else 1.0 / len(idx)
    return p


def market_prob(df):
    p = np.zeros(len(df), dtype=np.float64)
    odds = pd.to_numeric(df['win_odds'], errors='coerce').to_numpy(dtype=np.float64)
    inv = np.where(np.isfinite(odds) & (odds > 1.0), 1.0 / odds, 0.0)
    for idx in df.groupby('race_key', sort=False).indices.values():
        tot = inv[idx].sum()
        if tot > 0:
            p[idx] = inv[idx] / tot
        else:
            p[idx] = 1.0 / len(idx)
    return p


def clip_p(p):
    return np.clip(np.asarray(p, dtype=np.float64), 1e-6, 1.0 - 1e-6)


def ece_score(p, y, n_bins=ECE_BINS):
    p = clip_p(p)
    y = np.asarray(y, dtype=np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    rows = []
    n = len(y)
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        if i == n_bins - 1:
            m = (p >= lo) & (p <= hi)
        else:
            m = (p >= lo) & (p < hi)
        if not m.any():
            rows.append({'bin_lo': lo, 'bin_hi': hi, 'n': 0,
                         'mean_p': None, 'mean_y': None, 'gap': None})
            continue
        mp, my = float(p[m].mean()), float(y[m].mean())
        gap = abs(my - mp)
        ece += gap * (m.sum() / n)
        rows.append({'bin_lo': lo, 'bin_hi': hi, 'n': int(m.sum()),
                     'mean_p': mp, 'mean_y': my, 'gap': gap})
    return float(ece), pd.DataFrame(rows)


def brier_score(p, y):
    p = clip_p(p)
    y = np.asarray(y, dtype=np.float64)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y):
    p = clip_p(p)
    y = np.asarray(y, dtype=np.float64)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def beta_calibrate(s, a, b, c):
    s = clip_p(s)
    return 1.0 / (1.0 + 1.0 / (np.exp(c) * (s ** a) * ((1.0 - s) ** (-b))))


def fit_beta(s, y):
    s, y = clip_p(s), np.asarray(y, dtype=np.float64)

    def nll(params):
        a, b, c = params
        if a <= 0 or b <= 0:
            return 1e12
        p = clip_p(beta_calibrate(s, a, b, c))
        return -np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))

    best = None
    for x0 in ((1.0, 1.0, 0.0), (0.8, 1.2, 0.0), (1.2, 0.8, -0.2)):
        res = minimize(nll, x0=x0, method='Nelder-Mead',
                       options={'maxiter': 3000, 'xatol': 1e-4, 'fatol': 1e-7})
        if best is None or res.fun < best.fun:
            best = res
    return tuple(float(x) for x in best.x), float(best.fun)


class VennAbersGrid:
    """較正セットに対し、スコア格子ごとに Venn-Abers (p, p0, p1) をキャッシュ。"""

    def __init__(self, cal_scores, cal_labels, ndigits=SCORE_ROUND):
        self.cal_scores = np.asarray(cal_scores, dtype=np.float64)
        self.cal_labels = np.asarray(cal_labels, dtype=np.float64)
        self.ndigits = ndigits
        self.cache = {}

    def _one(self, score):
        key = round(float(score), self.ndigits)
        if key in self.cache:
            return self.cache[key]
        s0 = np.append(self.cal_scores, key)
        y0 = np.append(self.cal_labels, 0.0)
        y1 = np.append(self.cal_labels, 1.0)
        ir0 = IsotonicRegression(out_of_bounds='clip')
        ir1 = IsotonicRegression(out_of_bounds='clip')
        p0 = float(ir0.fit(s0, y0).predict([key])[0])
        p1 = float(ir1.fit(s0, y1).predict([key])[0])
        p0, p1 = min(p0, p1), max(p0, p1)
        den = 1.0 - p0 + p1
        p = float(p1 / den) if den > 0 else p1
        out = (clip_p([p])[0], clip_p([p0])[0], clip_p([p1])[0])
        self.cache[key] = out
        return out

    def transform(self, scores):
        pts, lo, hi = [], [], []
        for s in scores:
            p, p0, p1 = self._one(s)
            pts.append(p)
            lo.append(p0)
            hi.append(p1)
        return (np.asarray(pts), np.asarray(lo), np.asarray(hi))


def ev_backtest(df, p_col, odds_col='win_odds', y_col='win',
                thresh=1.0, p_floor_col=None):
    """p*odds >= thresh なら単勝1点(UNIT円)。p_floor_colがあればそちらで判定。"""
    p_dec = df[p_floor_col] if p_floor_col else df[p_col]
    odds = pd.to_numeric(df[odds_col], errors='coerce')
    ev = p_dec * odds
    take = (ev >= thresh) & odds.notna() & (odds > 1.0)
    stake = take.astype(int) * UNIT
    pay = np.where(take & (df[y_col] == 1), odds * UNIT, 0.0)
    pnl = pay - stake
    n_bet = int(take.sum())
    n_hit = int((take & (df[y_col] == 1)).sum())
    invest = int(stake.sum())
    ret = float(pay.sum())
    race_pnl = pd.DataFrame({
        'race_key': df['race_key'],
        'stake': stake,
        'pnl': pnl,
    }).groupby('race_key', sort=False).sum()
    n_race = int(df['race_key'].nunique())
    n_skip = int((race_pnl['stake'] == 0).sum())
    worst = float(race_pnl['pnl'].min()) if len(race_pnl) else 0.0
    p5 = float(race_pnl['pnl'].quantile(0.05)) if len(race_pnl) else 0.0
    tickets_per_race = n_bet / n_race if n_race else 0.0
    return {
        'n_race': n_race,
        'n_bet': n_bet,
        'n_hit': n_hit,
        'hit_rate': (n_hit / n_bet) if n_bet else 0.0,
        'invest': invest,
        'return': ret,
        'roi_pct': (ret / invest * 100.0) if invest else 0.0,
        'skip_rate': (n_skip / n_race) if n_race else 0.0,
        'tickets_per_race': tickets_per_race,
        'worst_race_pnl': worst,
        'p5_race_pnl': p5,
        'n_loss_races': int((race_pnl['pnl'] < 0).sum()),
        'n_big_loss_races': int((race_pnl['pnl'] <= -3 * UNIT).sum()),
    }


def load_frame():
    cols = ['race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds',
            'chakujun', 'win', 'top3', 'ability_score']
    df = cd.load_horses(cols=cols, with_period=False)
    df['jyo'] = df['jyo'].astype(str).str.zfill(2)
    df = df[df['jyo'] <= '10'].copy()
    df['ability_score'] = pd.to_numeric(df['ability_score'], errors='coerce')
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    df['win'] = pd.to_numeric(df['win'], errors='coerce').fillna(0).astype(int)
    df['day'] = pd.to_numeric(df['day'], errors='coerce')
    df = df[df['ability_score'].notna() & df['win_odds'].notna() & (df['win_odds'] > 1)]
    sizes = df.groupby('race_key')['umaban'].transform('size')
    df = df[sizes >= MIN_HORSES].copy()
    df['year'] = (df['day'] // 10000).astype(int)
    df['p_raw'] = softmax_neg_ability(df)
    df['p_market'] = market_prob(df)
    return df.reset_index(drop=True)


def metrics_row(name, period, p, y, extra=None):
    ece, _ = ece_score(p, y)
    row = {
        'method': name,
        'period': period,
        'n': int(len(y)),
        'ece': ece,
        'brier': brier_score(p, y),
        'logloss': log_loss(p, y),
        'mean_p': float(np.mean(p)),
        'base_rate': float(np.mean(y)),
    }
    if extra:
        row.update(extra)
    return row


def width_analysis(df, p_col, lo_col, hi_col, y_col='win'):
    width = (df[hi_col] - df[lo_col]).clip(lower=0)
    err = (df[p_col] - df[y_col]).abs()
    bins = [0.0, 0.05, 0.10, 1.01]
    labels = ['0-5%', '5-10%', '10%+']
    cat = pd.cut(width, bins=bins, labels=labels, right=False, include_lowest=True)
    rows = []
    for lab in labels:
        m = cat == lab
        if not m.any():
            rows.append({'width_bin': lab, 'n': 0, 'mean_width': None,
                         'mean_abs_err': None, 'brier': None, 'hit_rate': None})
            continue
        sub = df.loc[m]
        rows.append({
            'width_bin': lab,
            'n': int(m.sum()),
            'mean_width': float(width[m].mean()),
            'mean_abs_err': float(err[m].mean()),
            'brier': brier_score(sub[p_col], sub[y_col]),
            'hit_rate': float(sub[y_col].mean()),
            'mean_p': float(sub[p_col].mean()),
        })
    corr = float(pd.Series(width).corr(pd.Series(err), method='spearman'))
    return pd.DataFrame(rows), corr


def judge(cal_df, ev_df, width_df, width_corr):
    """見た目改善だけでは不採用。利益判断の上積みがあるか。"""
    ho = cal_df[cal_df['period'] == 'holdout2025+']
    raw = ho[ho['method'] == '現行(softmax Rank)'].iloc[0]
    va = ho[ho['method'] == 'Venn-Abers'].iloc[0]
    beta = ho[ho['method'] == 'Beta'].iloc[0]

    def nicer_prob(row):
        return (row['ece'] < raw['ece'] - 0.002) or (row['brier'] < raw['brier'] - 0.0002)

    ev_ho = ev_df[(ev_df['period'] == 'holdout2025+') & (ev_df['threshold'] == 1.0)]
    raw_ev = ev_ho[ev_ho['rule'] == '現行p・通常EV'].iloc[0]
    va_ev = ev_ho[ev_ho['rule'] == 'VA点・通常EV'].iloc[0]
    cons = ev_ho[ev_ho['rule'] == 'VA下限・保守EV'].iloc[0]

    def betting_better(row, base):
        roi_up = row['roi_pct'] >= base['roi_pct'] + 1.0
        skip_up = row['skip_rate'] >= base['skip_rate'] + 0.03
        bigloss_down = row['n_big_loss_races'] < base['n_big_loss_races']
        not_worse_roi = row['roi_pct'] >= base['roi_pct'] - 1.0
        return (roi_up and not_worse_roi) or (skip_up and not_worse_roi and bigloss_down)

    width_mono = False
    if len(width_df) >= 2:
        e = [r for r in width_df['mean_abs_err'].tolist() if pd.notna(r)]
        width_mono = len(e) >= 2 and all(e[i] <= e[i + 1] + 1e-9 for i in range(len(e) - 1))

    cal_ok = nicer_prob(va) or nicer_prob(beta)
    ev_ok = betting_better(va_ev, raw_ev)
    cons_ok = betting_better(cons, raw_ev)
    width_ok = bool(width_mono and pd.notna(width_corr) and width_corr >= 0.05)

    notes = []
    if cal_ok and not ev_ok:
        notes.append('較正指標は改善したが、通常EVのROI/見送りは上積み不足 → 見た目改善のみなら不採用')
    if cons_ok:
        notes.append('保守EVは無駄打ち削減またはROI維持で候補')
    if width_ok:
        notes.append('予測幅と誤差に単調関係あり → フィルター候補')
    if not notes:
        notes.append('holdoutでは利益判断の明確な上積みなし')

    return {
        'calibration_looks_better': bool(cal_ok),
        'calibration_helps_betting': bool(ev_ok),
        'conservative_helps_betting': bool(cons_ok),
        'width_tracks_error': bool(width_ok),
        'width_spearman': width_corr,
        'adopt_calibration': bool(ev_ok),
        'adopt_conservative': bool(cons_ok),
        'adopt_width_filter': bool(width_ok),
        'notes': notes,
    }


def write_report(cal_df, ev_df, width_df, width_corr, ece_bins, beta_params, judge_d):
    lines = []
    w = lines.append
    w('# 不確実性レイヤー検証（研究専用）\n')
    w('本番ロジックは未変更。Rank softmax の後段として較正・保守EV・予測幅だけを測定。\n')
    w('## 設計\n')
    w('- 現行確率: レース内 softmax(-ability_score)。低い ability_score ほど強い（CSV仕様）')
    w('- 較正fit: 2024年（LTR val年）')
    w('- holdout: 2025年以降')
    w('- 採用条件: ECE等の見た目改善だけでは不可。ROI / 見送り / 大負けが改善した場合のみ候補')
    w(f'- Betaパラメータ: a={beta_params[0]:.4f}, b={beta_params[1]:.4f}, c={beta_params[2]:.4f}')
    w('')
    w('## 1. キャリブレーション\n')
    w(cal_df.to_markdown(index=False, floatfmt='.4f'))
    w('')
    w('## 2. 通常EV vs 保守EV\n')
    w(ev_df.to_markdown(index=False, floatfmt='.3f'))
    w('')
    w('## 3. 予測幅 vs 実績誤差（Venn-Abers・holdout）\n')
    w(f'Spearman(幅, |p-y|) = {width_corr:.4f}\n')
    w(width_df.to_markdown(index=False, floatfmt='.4f'))
    w('')
    w('## 判定\n')
    w(f"- 較正の見た目改善: {judge_d['calibration_looks_better']}")
    w(f"- 較正が馬券判断を改善: {judge_d['calibration_helps_betting']} → 採用={judge_d['adopt_calibration']}")
    w(f"- 保守EVが馬券判断を改善: {judge_d['conservative_helps_betting']} → 採用={judge_d['adopt_conservative']}")
    w(f"- 幅が誤差を説明する: {judge_d['width_tracks_error']} → 採用={judge_d['adopt_width_filter']}")
    w('')
    for n in judge_d['notes']:
        w(f'- {n}')
    w('')
    w('## 次の扱い\n')
    w('- 本結果は研究レイヤー。core / JSON / 買い目ロジックへは未配線。')
    w('- 採用候補が出ても、本番投入前に買い目エンジン結合の再holdoutが必要。')
    path = os.path.join(OUT_DIR, 'report.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('report:', path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print('読込...')
    df = load_frame()
    cal = df[df['year'] == CAL_YEAR].copy()
    ho = df[df['year'] >= HOLDOUT_FROM].copy()
    ho25 = df[df['year'] == 2025].copy()
    ho26 = df[df['year'] == 2026].copy()
    print(f'  cal2024={len(cal):,}  holdout2025+={len(ho):,}  2025={len(ho25):,}  2026={len(ho26):,}')

    print('Venn-Abers fit(2024)...')
    va = VennAbersGrid(cal['p_raw'].values, cal['win'].values)
    print('Beta fit(2024)...')
    beta_params, beta_nll = fit_beta(cal['p_raw'].values, cal['win'].values)
    print(f'  Beta a,b,c={beta_params}  nll={beta_nll:.6f}')

    ir = IsotonicRegression(out_of_bounds='clip')
    ir.fit(cal['p_raw'].values, cal['win'].values)

    def apply_all(part):
        out = part.copy()
        out['p_iso'] = clip_p(ir.predict(out['p_raw'].values))
        p, lo, hi = va.transform(out['p_raw'].values)
        out['p_va'] = p
        out['p_va_lo'] = lo
        out['p_va_hi'] = hi
        out['p_beta'] = clip_p(beta_calibrate(out['p_raw'].values, *beta_params))
        out['va_width'] = (out['p_va_hi'] - out['p_va_lo']).clip(lower=0)
        return out

    print('transform...')
    cal = apply_all(cal)
    ho = apply_all(ho)
    ho25 = apply_all(ho25)
    ho26 = apply_all(ho26)
    print(f'  VA cache size={len(va.cache)}')

    cal_rows = []
    for label, part in (('cal2024(in-fit)', cal), ('holdout2025+', ho),
                        ('holdout2025', ho25), ('holdout2026', ho26)):
        if len(part) == 0:
            continue
        y = part['win'].values
        for name, col in (
            ('現行(softmax Rank)', 'p_raw'),
            ('市場暗黙確率(参考)', 'p_market'),
            ('Isotonic', 'p_iso'),
            ('Venn-Abers', 'p_va'),
            ('Beta', 'p_beta'),
        ):
            cal_rows.append(metrics_row(name, label, part[col].values, y))
    cal_df = pd.DataFrame(cal_rows)

    ev_rows = []
    for label, part in (('cal2024(in-fit)', cal), ('holdout2025+', ho),
                        ('holdout2025', ho25), ('holdout2026', ho26)):
        if len(part) == 0:
            continue
        for th in EV_THRESHOLDS:
            specs = [
                ('現行p・通常EV', 'p_raw', None),
                ('市場p・通常EV(参考)', 'p_market', None),
                ('Iso点・通常EV', 'p_iso', None),
                ('VA点・通常EV', 'p_va', None),
                ('Beta点・通常EV', 'p_beta', None),
                ('VA下限・保守EV', 'p_va', 'p_va_lo'),
            ]
            for rule, pcol, floor in specs:
                met = ev_backtest(part, pcol, thresh=th, p_floor_col=floor)
                ev_rows.append({'rule': rule, 'period': label, 'threshold': th, **met})
    ev_df = pd.DataFrame(ev_rows)

    width_df, width_corr = width_analysis(ho, 'p_va', 'p_va_lo', 'p_va_hi')
    ece_raw, ece_raw_bins = ece_score(ho['p_raw'], ho['win'])
    ece_va, ece_va_bins = ece_score(ho['p_va'], ho['win'])
    ece_beta, ece_beta_bins = ece_score(ho['p_beta'], ho['win'])
    ece_raw_bins.insert(0, 'method', '現行')
    ece_va_bins.insert(0, 'method', 'Venn-Abers')
    ece_beta_bins.insert(0, 'method', 'Beta')
    ece_bins = pd.concat([ece_raw_bins, ece_va_bins, ece_beta_bins], ignore_index=True)

    # 穴帯スライス（VH後段との相性確認。条件変更ではない）
    ho_ls = ho[ho['ninki'] >= 6]
    ls_rows = []
    if len(ho_ls):
        y = ho_ls['win'].values
        for name, col in (('現行(softmax Rank)', 'p_raw'),
                          ('Venn-Abers', 'p_va'),
                          ('Beta', 'p_beta')):
            ls_rows.append(metrics_row(name, 'holdout2025+_ninki6+', ho_ls[col].values, y))
        for th in EV_THRESHOLDS:
            for rule, pcol, floor in (
                ('現行p・通常EV', 'p_raw', None),
                ('VA点・通常EV', 'p_va', None),
                ('VA下限・保守EV', 'p_va', 'p_va_lo'),
            ):
                met = ev_backtest(ho_ls, pcol, thresh=th, p_floor_col=floor)
                ev_rows.append({'rule': rule + ' / 6人気+', 'period': 'holdout2025+_ninki6+',
                                'threshold': th, **met})
        ev_df = pd.DataFrame(ev_rows)

    judge_d = judge(cal_df, ev_df, width_df, width_corr)

    cal_df.to_csv(os.path.join(OUT_DIR, 'calibration_metrics.csv'),
                  index=False, encoding='utf-8-sig')
    ev_df.to_csv(os.path.join(OUT_DIR, 'ev_standard_vs_conservative.csv'),
                 index=False, encoding='utf-8-sig')
    width_df.to_csv(os.path.join(OUT_DIR, 'width_vs_error.csv'),
                    index=False, encoding='utf-8-sig')
    ece_bins.to_csv(os.path.join(OUT_DIR, 'ece_bins_holdout.csv'),
                    index=False, encoding='utf-8-sig')
    if ls_rows:
        pd.DataFrame(ls_rows).to_csv(
            os.path.join(OUT_DIR, 'calibration_longshot_slice.csv'),
            index=False, encoding='utf-8-sig')
    with open(os.path.join(OUT_DIR, 'judge.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'beta_params': {'a': beta_params[0], 'b': beta_params[1], 'c': beta_params[2]},
            'va_cache': len(va.cache),
            'ece_raw_holdout': ece_raw,
            'ece_va_holdout': ece_va,
            'ece_beta_holdout': ece_beta,
            'width_spearman': width_corr,
            'judge': judge_d,
        }, f, ensure_ascii=False, indent=2)

    write_report(cal_df, ev_df, width_df, width_corr, ece_bins, beta_params, judge_d)
    print('完了:', OUT_DIR)
    print(json.dumps(judge_d, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
