# -*- coding: utf-8 -*-
"""俗説有効度の成立可否 — 実装しない。生データだけで判定する。

repo/brief_folklore_effectiveness.md の指示書どおり。

見るのは3点:
  1. 予測した効果量の五分位が、実現残差で単調か
  2. 人気ならし残差が、生の複勝率差と食い違うか（織込み）
  3. 同日前レースのバイアス(D)が、条件だけ(C)を holdout で上回るか

0〜100 の有効度は作らない。train で類似度1案を freeze。D は同日2R未満なら欠損。

叩き2走目（固定）: 前走の days_since>=90 かつ 今回 days_since<63。

Usage: python scripts/folklore_effectiveness_backtest.py
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import csv_data as cd

MIN_N = 200
MIN_R = 80
MIN_PRIOR = 2
LAYOFF_DAYS = 90
SECOND_GAP_MAX = 63  # 叩き2走目: 休み明けの直後=中8週未満
Z_SE_P = 0.22
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, 'data', 'folklore_effectiveness_summary.json')

FOLK = [
    ('draw_inner', '内枠有利'),
    ('draw_outer', '外枠有利'),
    ('style_nige', '逃げ有利'),
    ('style_senko', '先行有利'),
    ('style_sashi', '差し有利'),
    ('rot_layoff', '休み明け好走'),
    ('rot_second', '叩き2走目'),
    ('wt_up', '馬体重増'),
    ('wt_down', '馬体重減'),
    ('wt_big', '大幅増減'),
]


def dist_band(kyori):
    k = int(kyori)
    if k <= 1400:
        return 0
    if k <= 1800:
        return 1
    if k <= 2200:
        return 2
    return 3


def baba_grp(code):
    try:
        c = int(code)
    except (TypeError, ValueError):
        return 1
    if c <= 1:
        return 1  # 良
    if c == 2:
        return 2  # 稍重
    return 3  # 重不良


def surf_label(c):
    return 'ダ' if int(c) == 1 else '芝'


def ninki_band(n):
    n = int(n)
    if n <= 3:
        return '1-3'
    if n <= 5:
        return '4-5'
    return '6+'


def field_band(n):
    n = int(n)
    if n <= 11:
        return '~11'
    if n <= 14:
        return '12-14'
    return '15+'


def stats_from_resid(resid, top3, win, odds):
    n = len(resid)
    if n == 0:
        return None
    r = np.asarray(resid, dtype=float)
    t3 = np.asarray(top3, dtype=float)
    w = np.asarray(win, dtype=float)
    o = np.asarray(odds, dtype=float)
    se = (Z_SE_P * (1 - Z_SE_P) / n) ** 0.5
    pay = np.where(w == 1, np.nan_to_num(o, nan=0.0), 0.0).sum()
    return {
        'n': int(n),
        'hit': float(t3.mean()),
        'win': float(w.mean()),
        'roi': float(pay / n),
        'resid': float(r.mean()),
        'z': float(r.mean() / se) if se > 0 else 0.0,
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 勝{s['win']:5.1%} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def spearman(a, b):
    s = pd.Series(a).rank().corr(pd.Series(b).rank())
    return float(s) if s == s else 0.0


def monotone_up(vals):
    """隣接差がすべて >= -0.1pp なら単調増とみなす（ノイズ1pt未満は許容しない。0.1pp=0.001）。"""
    if len(vals) < 3:
        return False
    return all(vals[i + 1] + 1e-6 >= vals[i] for i in range(len(vals) - 1))


def add_flags(h):
    waku = pd.to_numeric(h['waku_n'], errors='coerce')
    zogen = pd.to_numeric(h['zogen'], errors='coerce')
    days = pd.to_numeric(h['days_since'], errors='coerce')
    pos = pd.to_numeric(h['avg_pos3'], errors='coerce')
    ratio = pd.to_numeric(h['pos_ratio3'], errors='coerce')
    h = h.copy()
    h['draw_inner'] = (waku >= 1) & (waku <= 3)
    h['draw_outer'] = (waku >= 6) & (waku <= 8)
    h['style_nige'] = pos <= 2
    h['style_senko'] = ratio <= 0.28
    h['style_sashi'] = ratio >= 0.50
    h['rot_layoff'] = days >= LAYOFF_DAYS
    ordered = h.sort_values(['ketto_num', 'day', 'race_key'])
    prev_days = ordered.groupby('ketto_num', sort=False)['days_since'].shift(1)
    second = (prev_days >= LAYOFF_DAYS) & (ordered['days_since'] < SECOND_GAP_MAX)
    second = second.fillna(False)
    h['rot_second'] = False
    h.loc[ordered.index, 'rot_second'] = second.to_numpy()
    h['wt_up'] = zogen >= 10
    h['wt_down'] = zogen <= -10
    h['wt_big'] = zogen.abs() >= 16
    for fid, _ in FOLK:
        h[fid] = h[fid].fillna(False).astype(bool)
    return h


def build_race_real(h, folk_ids):
    """レース×俗説の実現残差（該当馬の平均）。該当0頭のレースは行なし。"""
    grp = h.groupby('race_key', sort=False)
    meta = grp.agg(
        day=('day', 'first'), jyo=('jyo', 'first'), surf=('surface_code', 'first'),
        kyori=('kyori_int', 'first'), baba=('baba', 'first'),
        race_num=('race_num', 'first'), field_size=('field_size', 'first'),
        period=('period', 'first'), year=('year', 'first'),
        field_hit=('top3', 'mean'),
    ).reset_index()
    pay = np.where(h['win'].to_numpy() == 1, np.nan_to_num(h['win_odds'].to_numpy(), nan=0.0), 0.0)
    tmp = h.assign(_pay=pay)
    rows = []
    for fid, _ in FOLK:
        sub = tmp.loc[tmp[fid], ['race_key', 'resid', 'top3', 'win', '_pay']]
        if sub.empty:
            continue
        g = sub.groupby('race_key', sort=False).agg(
            n=('resid', 'size'),
            resid=('resid', 'mean'),
            hit=('top3', 'mean'),
            win=('win', 'mean'),
            roi=('_pay', 'mean'),
        ).reset_index()
        g['fid'] = fid
        rows.append(g)
    real = pd.concat(rows, ignore_index=True)
    real = real.merge(meta, on='race_key', how='left')
    real['raw_diff'] = real['hit'] - real['field_hit']
    real['dband'] = real['kyori'].map(dist_band)
    real['bgrp'] = real['baba'].map(baba_grp)
    real['dist100'] = (pd.to_numeric(real['kyori'], errors='coerce') // 100).astype(int)
    return real


def expanding_preds(real):
    """時系列順に S1/S2/S3 の予測残差と、同日バイアスを付ける。"""
    real = real.sort_values(['day', 'race_num', 'race_key', 'fid']).reset_index(drop=True)
    # セル累積: fid -> key -> [sum, n]
    acc1 = defaultdict(lambda: [0.0, 0])
    acc2 = defaultdict(lambda: [0.0, 0])
    acc3 = defaultdict(lambda: [0.0, 0])
    # fid -> (jyo, surf, dist100, bgrp) -> [sum, n]  （S3は俗説ごとに回す）
    acc_s3 = defaultdict(dict)
    # 同日: (day,jyo,surf,fid) の当該 race_num より前
    day_acc = defaultdict(lambda: [0.0, 0])

    p1 = np.full(len(real), np.nan)
    n1 = np.zeros(len(real), dtype=int)
    p2 = np.full(len(real), np.nan)
    n2 = np.zeros(len(real), dtype=int)
    p3 = np.full(len(real), np.nan)
    n3 = np.zeros(len(real), dtype=int)
    day_r = np.full(len(real), np.nan)
    day_n = np.zeros(len(real), dtype=int)

    # 同じレースの10俗説をまとめて「予測してから累積に足す」
    i = 0
    n = len(real)
    n_races = 0
    while i < n:
        rk = real.at[i, 'race_key']
        j = i
        while j < n and real.at[j, 'race_key'] == rk:
            j += 1
        block = list(range(i, j))
        day = int(real.at[i, 'day'])
        jyo = int(real.at[i, 'jyo'])
        surf = int(real.at[i, 'surf'])
        dband = int(real.at[i, 'dband'])
        bgrp = int(real.at[i, 'bgrp'])
        dist100 = int(real.at[i, 'dist100']) if pd.notna(real.at[i, 'dist100']) else -1

        for k in block:
            fid = real.at[k, 'fid']
            k1 = (fid, jyo, surf, dband, bgrp)
            k2 = (fid, jyo, surf, dband)
            k3 = (fid, surf, dband)
            s1, c1 = acc1[k1]
            s2, c2 = acc2[k2]
            s3, c3 = acc3[k3]
            n1[k] = c1
            n2[k] = c2
            if c1 >= MIN_R:
                p1[k] = s1 / c1
            # S2: A=exact, B=same jyo+surf+dist other baba, C=same surf+dist other jyo
            sumA, nA = s1, c1
            sumB, nB = s2 - s1, c2 - c1
            sumC, nC = s3 - s2, c3 - c2
            wsum = 1.0 * nA + 0.5 * max(nB, 0) + 0.25 * max(nC, 0)
            vsum = 1.0 * sumA + 0.5 * sumB + 0.25 * sumC
            n2_eff = nA + nB + nC
            n2[k] = int(n2_eff)
            if wsum >= MIN_R and wsum > 0:
                p2[k] = vsum / wsum
            # S3（同じ俗説のセルだけ）
            v3 = 0.0
            w3 = 0.0
            n3c = 0
            cells = acc_s3.get(fid)
            if cells and dist100 >= 0:
                for (jy2, sf2, d100, bg2), (ss, cc) in cells.items():
                    if sf2 != surf or cc <= 0:
                        continue
                    wj = 1.0 if jy2 == jyo else 0.3
                    wb = 1.0 if bg2 == bgrp else 0.5
                    wd = float(np.exp(-abs(d100 - dist100) * 100.0 / 200.0))
                    w = wd * wj * wb
                    v3 += w * ss
                    w3 += w * cc
                    n3c += cc
            n3[k] = n3c
            if w3 >= MIN_R and w3 > 0:
                p3[k] = v3 / w3
            dk = (day, jyo, surf, fid)
            ds, dc = day_acc[dk]
            day_n[k] = dc
            if dc >= MIN_PRIOR:
                day_r[k] = ds / dc

        for k in block:
            fid = real.at[k, 'fid']
            resid = float(real.at[k, 'resid'])
            acc1[(fid, jyo, surf, dband, bgrp)][0] += resid
            acc1[(fid, jyo, surf, dband, bgrp)][1] += 1
            acc2[(fid, jyo, surf, dband)][0] += resid
            acc2[(fid, jyo, surf, dband)][1] += 1
            acc3[(fid, surf, dband)][0] += resid
            acc3[(fid, surf, dband)][1] += 1
            if dist100 >= 0:
                cell = acc_s3[fid].setdefault((jyo, surf, dist100, bgrp), [0.0, 0])
                cell[0] += resid
                cell[1] += 1
            day_acc[(day, jyo, surf, fid)][0] += resid
            day_acc[(day, jyo, surf, fid)][1] += 1
        n_races += 1
        if n_races % 4000 == 0:
            print(f'  ... {n_races}R 処理済み', flush=True)
        i = j

    real = real.copy()
    real['pred_s1'] = p1
    real['n_s1'] = n1
    real['pred_s2'] = p2
    real['n_s2'] = n2
    real['pred_s3'] = p3
    real['n_s3'] = n3
    real['day_resid'] = day_r
    real['day_n'] = day_n
    return real


def pick_scheme(train):
    scores = {}
    for sch, col in (('S1', 'pred_s1'), ('S2', 'pred_s2'), ('S3', 'pred_s3')):
        sub = train.dropna(subset=[col, 'resid'])
        if len(sub) < 500:
            scores[sch] = -1.0
            continue
        scores[sch] = spearman(sub[col], sub['resid'])
    best = max(scores, key=scores.get)
    return best, scores


def freeze_bins(train_df, pred_col):
    """train の五分位境。holdout に同じ境を当てる（holdout で切り直さない）。"""
    s = train_df[pred_col].dropna().to_numpy(dtype=float)
    if len(s) < 500:
        return None
    qs = np.quantile(s, [0.2, 0.4, 0.6, 0.8])
    bins = [-np.inf]
    for q in qs:
        if q > bins[-1]:
            bins.append(float(q))
    bins.append(np.inf)
    if len(bins) < 4:
        return None
    return bins


def quintile_table(df, pred_col, bins=None):
    sub = df.dropna(subset=[pred_col, 'resid']).copy()
    if len(sub) < 500:
        return None
    if bins is not None:
        sub['q'] = pd.cut(sub[pred_col], bins=bins, labels=False, include_lowest=True)
        sub = sub.dropna(subset=['q'])
        if sub.empty:
            return None
        sub['q'] = sub['q'].astype(int)
    else:
        try:
            sub['q'] = pd.qcut(sub[pred_col], 5, labels=False, duplicates='drop')
        except ValueError:
            sub['q'] = pd.qcut(sub[pred_col].rank(method='first'), 5, labels=False)
    rows = []
    for q, g in sub.groupby('q'):
        st = stats_from_resid(g['resid'], g['hit'], g['win'], g['roi'])
        # g['hit'] is race-level mean not horse-level; use resid/roi already race-mean.
        # Recompute horse-equivalent from race rows: weight by n
        w = g['n'].to_numpy(dtype=float)
        resid = float(np.average(g['resid'], weights=w))
        hit = float(np.average(g['hit'], weights=w))
        win = float(np.average(g['win'], weights=w))
        roi = float(np.average(g['roi'].fillna(0), weights=w))
        n = int(w.sum())
        se = (Z_SE_P * (1 - Z_SE_P) / n) ** 0.5
        rows.append({
            'q': int(q) + 1,
            'n': n,
            'nrace': int(len(g)),
            'hit': hit,
            'win': win,
            'roi': roi,
            'resid': resid,
            'z': resid / se if se > 0 else 0.0,
            'pred_mean': float(np.average(g[pred_col], weights=w)),
        })
    rows.sort(key=lambda x: x['q'])
    return rows


def print_q(title, rows):
    print(f'\n{title}')
    if not rows:
        print('  (分位不能)')
        return False
    print(f"  {'帯':>4} {'n頭':>8} {'R':>6} {'複':>7} {'単ROI':>8} {'残差':>9} {'z':>7} {'予測':>9}")
    vals = []
    for r in rows:
        print(f"  Q{r['q']:<3} {r['n']:8d} {r['nrace']:6d} {r['hit']:6.1%} "
              f"{r['roi']:7.1%} {r['resid']*100:+7.2f}pp {r['z']:+6.2f} {r['pred_mean']*100:+7.2f}pp")
        vals.append(r['resid'])
    mono = monotone_up(vals)
    sp = spearman([r['q'] for r in rows], vals)
    print(f"  単調増: {'YES' if mono else 'NO'}  分位Spearman={sp:+.3f}")
    return mono


def slice_resid(h, mask, label):
    sub = h.loc[mask]
    return label, stats_from_resid(
        sub['resid'].to_numpy(), sub['top3'].to_numpy(),
        sub['win'].to_numpy(), sub['win_odds'].to_numpy())


def main():
    print('CSV読み込み...', flush=True)
    cols = [
        'race_key', 'day', 'jyo', 'surface_code', 'kyori_int', 'race_num', 'field_size',
        'ketto_num', 'umaban', 'waku_n', 'ninki', 'win_odds', 'zogen', 'days_since',
        'avg_pos3', 'pos_ratio3', 'chakujun', 'top3', 'win',
    ]
    h = cd.load_horses(cols=cols, with_period=True)
    races = cd.load_races(cols=['race_key', 'baba_code'], with_period=False)
    h = h.merge(races.rename(columns={'baba_code': 'baba'}), on='race_key', how='left')
    h['year'] = (pd.to_numeric(h['day'], errors='coerce') // 10000).astype(int)
    h['win_odds'] = pd.to_numeric(h['win_odds'], errors='coerce')
    h['top3'] = pd.to_numeric(h['top3'], errors='coerce').fillna(0)
    h['win'] = pd.to_numeric(h['win'], errors='coerce').fillna(0)

    train_h = h[h['period'] == 'train']
    base = cd.base_top3_by_ninki(train_h)
    h['exp'] = h['ninki'].astype(int).map(base).astype(float)
    h['resid'] = h['top3'] - h['exp']
    print(f'馬行 {len(h):,}  train期待複勝を人気別に固定（リーク防止）', flush=True)

    print('俗説フラグ...', flush=True)
    h = add_flags(h)

    print('\n========== ① 全体（モデルBの素材） ==========')
    overall = {}
    for fid, title in FOLK:
        print(f'\n--- {title} ({fid}) ---')
        overall[fid] = {}
        for per in ('train', 'holdout', 'recent'):
            sub = h[(h['period'] == per) & h[fid]]
            st = stats_from_resid(sub['resid'], sub['top3'], sub['win'], sub['win_odds'])
            allp = h[h['period'] == per]
            raw = None
            if len(sub) and len(allp):
                raw = float(sub['top3'].mean() - allp['top3'].mean())
            overall[fid][per] = {'stats': st, 'raw_diff': raw}
            raw_s = f" 生差{raw*100:+.2f}pt" if raw is not None else ''
            print(f'  {per:8s} {fmt(st)}{raw_s}')
        # 年別
        years = []
        for y, g in h[h[fid] & (h['period'] == 'train')].groupby('year'):
            st = stats_from_resid(g['resid'], g['top3'], g['win'], g['win_odds'])
            if st and st['n'] >= MIN_N:
                years.append((int(y), st['resid'] > 0, st['resid']))
        if years:
            pos = sum(1 for _, p, _ in years if p)
            print(f'  train年プラス {pos}/{len(years)}'
                  + '  ' + ' '.join(f"{y}:{r*100:+.1f}" for y, _, r in years))
            overall[fid]['year_pos'] = pos / len(years)
        else:
            overall[fid]['year_pos'] = None

    print('\n切る軸（holdout・n>=200のみ判定）', flush=True)
    h['dband'] = h['kyori_int'].map(dist_band)
    h['bgrp'] = h['baba'].map(baba_grp)
    hold_h = h[h['period'] == 'holdout']
    axes = {
        '芝ダ': hold_h['surface_code'].map(surf_label),
        '距離帯': hold_h['dband'].map({0: '~1400', 1: '1401-1800', 2: '1801-2200', 3: '2201+'}),
        '馬場': hold_h['bgrp'].map({1: '良', 2: '稍重', 3: '重不良'}),
        '頭数': hold_h['field_size'].map(field_band),
        '人気': hold_h['ninki'].map(ninki_band),
        '場': hold_h['jyo'].astype(str),
    }
    cond_hits = []
    for fid, title in FOLK:
        print(f'\n  [{title}]')
        for ax_name, series in axes.items():
            for cell, idx in series.groupby(series).groups.items():
                sub = hold_h.loc[idx]
                m = sub[fid]
                st = stats_from_resid(sub.loc[m, 'resid'], sub.loc[m, 'top3'],
                                      sub.loc[m, 'win'], sub.loc[m, 'win_odds'])
                if st is None or st['n'] < MIN_N:
                    continue
                mark = ''
                glob = overall[fid]['holdout']['stats']
                if glob and glob['n'] >= MIN_N:
                    if glob['resid'] <= 0 < st['resid'] and st['z'] >= 2:
                        mark = '  ★全体否決→このセルはプラス'
                        cond_hits.append((title, ax_name, str(cell), st))
                    elif glob['resid'] > 0 >= st['resid'] and st['z'] <= -2:
                        mark = '  ★全体プラス→このセルはマイナス'
                if mark or st['z'] >= 2 or st['z'] <= -2:
                    print(f"    {ax_name}={cell}: {fmt(st)}{mark}")

    print('\nレース単位の実現残差...', flush=True)
    real = build_race_real(h, [f for f, _ in FOLK])
    print(f'レース×俗説 {len(real):,} 行', flush=True)
    print('類似度の予測（時系列・自分より前だけ）... 数十秒かかることがあります', flush=True)
    real = expanding_preds(real)
    real['pred_d'] = real['pred_s2']  # placeholder, 上書きする

    train = real[real['period'] == 'train']
    hold = real[real['period'] == 'holdout']
    recent = real[real['period'] == 'recent']

    best, sch_scores = pick_scheme(train)
    print('\n========== 類似度案の train Spearman（予測 vs 実現残差） ==========')
    for k, v in sch_scores.items():
        mark = ' ← freeze' if k == best else ''
        print(f'  {k}: {v:+.4f}{mark}')
    pred_col = {'S1': 'pred_s1', 'S2': 'pred_s2', 'S3': 'pred_s3'}[best]
    real['pred_c'] = real[pred_col]
    train = real[real['period'] == 'train']
    hold = real[real['period'] == 'holdout']
    recent = real[real['period'] == 'recent']

    # D: C + 同日残差。欠損は使わない
    real['pred_d'] = real['pred_c'] + real['day_resid']
    d_cov = float(real['day_resid'].notna().mean())
    print(f'\n同日バイアス(D)が使える割合: {d_cov:.1%}  （2R未満は欠損・ゼロ埋めしない）')

    print('\n========== ② 五分位（一本の軸に並べられるか） ==========')
    print('分位境は train で freeze。残差=人気ならし。')
    bins_c = freeze_bins(train, 'pred_c')
    q_train_c = quintile_table(train, 'pred_c', bins_c)
    q_hold_c = quintile_table(hold, 'pred_c', bins_c)
    q_rec_c = quintile_table(recent, 'pred_c', bins_c)
    print_q(f'train C ({best})', q_train_c)
    mono_ho = print_q(f'holdout C ({best}) ※本番', q_hold_c)
    print_q(f'recent C ({best})', q_rec_c)

    hold_d = hold.dropna(subset=['pred_d', 'resid'])
    train_d = train.dropna(subset=['pred_d', 'resid'])
    bins_d = freeze_bins(train_d, 'pred_d')
    q_train_d = quintile_table(train_d, 'pred_d', bins_d)
    q_hold_d = quintile_table(hold_d, 'pred_d', bins_d)
    print('\n--- D = C + 同日残差（Dが計算できるレースだけ） ---')
    print_q('train D', q_train_d)
    mono_d = print_q('holdout D ※本番', q_hold_d)

    print('\n========== ③ モデル比較 B / C / D ==========')
    # B: 定数予測 = train全体のその俗説残差。レース実現との Spearman は定数なので 0。
    #    代わりに「C/Dの上分位の実現残差」が B の全体残差を超えるかを見る。
    print('B = 全レース共通（俗説をいつも同じだけ信じる）')
    print('C = 類似条件だけ')
    print('D = C + 同日前レース（使えるときだけ）')

    def period_spear(df, col):
        s = df.dropna(subset=[col, 'resid'])
        if len(s) < 200:
            return None, len(s)
        return spearman(s[col], s['resid']), len(s)

    for name, dfp in (('train', train), ('holdout', hold), ('recent', recent)):
        sc, n = period_spear(dfp, 'pred_c')
        sd, nd = period_spear(dfp.dropna(subset=['day_resid']), 'pred_d')
        print(f'  {name:8s} C Spearman={sc:+.4f} (n={n})'
              + (f'  D Spearman={sd:+.4f} (n={nd})' if sd is not None else '  D なし'))

    d_minus_c = None
    q_spread_c = None
    q_spread_d = None
    d_sp_same = None
    c_sp_same = None
    both = hold.dropna(subset=['pred_c', 'pred_d', 'resid'])
    if len(both) >= 500:
        c_sp_same = spearman(both['pred_c'], both['resid'])
        d_sp_same = spearman(both['pred_d'], both['resid'])
        d_minus_c = d_sp_same - c_sp_same
        print(f'\n  holdout 同一母集団で D−C Spearman差: {d_minus_c:+.4f}'
              f'  (C {c_sp_same:+.4f} / D {d_sp_same:+.4f} / n={len(both)})')
        both = both.copy()
        both['qc'] = pd.qcut(both['pred_c'].rank(method='first'), 5, labels=False)
        both['qd'] = pd.qcut(both['pred_d'].rank(method='first'), 5, labels=False)

        def q_spread(df, qcol):
            lo = df[df[qcol] == 0]
            hi = df[df[qcol] == 4]
            return float(np.average(hi['resid'], weights=hi['n']) -
                         np.average(lo['resid'], weights=lo['n']))
        q_spread_c = q_spread(both, 'qc')
        q_spread_d = q_spread(both, 'qd')
        print(f'  holdout Q5−Q1 残差 C={q_spread_c*100:+.2f}pp'
              f'  D={q_spread_d*100:+.2f}pp')

    print('\n俗説別 holdout Spearman（C）')
    for fid, title in FOLK:
        sub = hold[hold['fid'] == fid].dropna(subset=['pred_c', 'resid'])
        if len(sub) < 100:
            print(f'  {title}: 標本不足')
            continue
        print(f'  {title}: {spearman(sub["pred_c"], sub["resid"]):+.3f}  nR={len(sub)}')

    print('\n同意/逆行（Cの符号 vs 同日バイアス） holdout')
    h2 = hold.dropna(subset=['pred_c', 'day_resid', 'resid'])
    if len(h2):
        agree = np.sign(h2['pred_c']) == np.sign(h2['day_resid'])
        for name, m in (('一致', agree), ('逆行', ~agree)):
            g = h2[m]
            if g.empty:
                continue
            r = float(np.average(g['resid'], weights=g['n']))
            print(f'  {name}: nR={len(g)} 実現残差 {r*100:+.2f}pp')

    # 判定
    print('\n========== 判定 ==========')
    c_sp_hold, _ = period_spear(hold, 'pred_c')
    d_improve = False
    if d_minus_c is not None:
        d_improve = d_minus_c > 0.02
    verdict = 'C'
    if mono_ho and c_sp_hold is not None and c_sp_hold >= 0.15:
        verdict = 'A' if d_improve or c_sp_hold >= 0.25 else 'B'
    elif q_hold_c and (c_sp_hold or 0) >= 0.08:
        verdict = 'B'
    print(f'類似度 freeze: {best}')
    print(f'holdout C 五分位単調: {mono_ho}  Spearman={c_sp_hold}')
    print(f'同日バイアスで Spearman 改善: {d_improve}')
    print(f'総合: {verdict}')
    if verdict == 'A':
        print('  → 有効度を一本の軸にできる見込み。まだ画面には出さない。閾値は別確認。')
    elif verdict == 'B':
        print('  → 条件表としては使えるが、0〜100 の「俗説有効度」表示はしない。')
    else:
        print('  → 成立しない。俗説有効度は作らない。トラックバイアスの機能化もしない。')

    summary = {
        'scheme': best,
        'scheme_spearman_train': sch_scores,
        'holdout_c_spearman': c_sp_hold,
        'holdout_c_monotone': bool(mono_ho),
        'd_coverage': d_cov,
        'd_improves': bool(d_improve),
        'd_minus_c_spearman': d_minus_c,
        'holdout_d_spearman_same': d_sp_same,
        'holdout_c_spearman_same': c_sp_same,
        'holdout_q5q1_c': q_spread_c,
        'holdout_q5q1_d': q_spread_d,
        'q_train_c': q_train_c,
        'q_hold_c': q_hold_c,
        'q_rec_c': q_rec_c,
        'q_train_d': q_train_d,
        'q_hold_d': q_hold_d,
        'verdict': verdict,
        'cond_hits': [
            {'folk': a, 'axis': b, 'cell': c, 'resid': s['resid'], 'z': s['z'], 'n': s['n']}
            for a, b, c, s in cond_hits
        ],
        'overall': {
            fid: {
                'holdout_resid': (overall[fid]['holdout']['stats'] or {}).get('resid'),
                'holdout_z': (overall[fid]['holdout']['stats'] or {}).get('z'),
                'holdout_n': (overall[fid]['holdout']['stats'] or {}).get('n'),
                'raw_diff': overall[fid]['holdout']['raw_diff'],
                'year_pos': overall[fid].get('year_pos'),
            } for fid, _ in FOLK
        },
    }
    try:
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f'\n要約: {OUT_JSON}')
    except Exception as e:
        print(f'JSON保存スキップ: {e}')


if __name__ == '__main__':
    main()
