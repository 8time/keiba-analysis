# -*- coding: utf-8 -*-
"""レーススキャナー(荒れ予報)v2バックテスト — scripts/scanner_arare_v2.py (Fable案件②)

data/export/races.csv(scripts/export_features_csv.pyの出力)を使い、
「フィールド構造(実力拮抗度など)が市場を超えて荒れを当てるか」を1年holdoutで検証する。

段階比較(すべて同じLightGBM設定・同じ窓):
  M0 市場のみ      … オッズ構造(fav1/比率/エントロピー/実効頭数/ゾーン頭数)
  M1 +構造条件     … ハンデ/頭数/牝馬限定/クラス/馬場/距離/月(検証済み荒れ条件を含む)
  M2 +フィールド特徴… 実力スプレッド(補正T/末脚/血統/騎手/vh2)・combo馬数・消去分布・
                      展開型(先行数)・市場×実力の順位相関
現行スキャナー(race_value_score / trio_lean / no_favorite_flag)の判別力も同じ土俵で実測。

窓: train = 2024-01-01〜2025-06-21(combo特徴の存在期間) / holdout = 2025-06-22〜2026-06-21(1年)
感度: train2021+(combo無し版)も確認。
ラベル: arareA(主)=3着内に7番人気以下 / arareB=勝ち馬6番人気以下 / ana2=②型(5人気以下2頭)
母集団: JRA平地・頭数8+・有効オッズ6頭以上。

Usage: python scripts/scanner_arare_v2.py
Output: data/scanner_arare_v2.json + 標準出力レポート
"""
import os
import sys
import json
import time as _time

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, 'data', 'export', 'races.csv')
OUT = os.path.join(ROOT, 'data', 'scanner_arare_v2.json')

TRAIN_FROM, TRAIN_TO = 20240101, 20250621
HOLD_FROM, HOLD_TO = 20250622, 20260621
OUT_PARAMS = os.path.join(ROOT, 'data', 'scanner_arare_logit.json')

# 配線用の透明ロジスティック(少数・全てvalue_scannerが当日計算できる量)
LOGIT_FEATS = ['fav1', 'r21', 'r31', 'syn3', 'odds_entropy', 'eff_n',
               'live10', 'live30', 'mid515', 'field_size', 'is_handi1', 'fillies']

ODDS = ['fav1', 'r21', 'r31', 'spread31', 'syn3', 'odds_entropy', 'eff_n',
        'live10', 'live30', 'mid515']
STRUCT = ['field_size', 'is_handi1', 'fillies', 'open_cls', 'is_2yo',
          'surface_code', 'kyori', 'baba_code', 'month', 'cushion', 'dirt_moisture']
FIELDX = ([f'{t}_{s}' for t in ('h7', 'spurt', 'blood', 'jk', 'pt3', 'marg', 'vh2')
           for s in ('std', 'mean', 'best', 'top2gap')]
          + ['mkt_ability_corr', 'n_pop7', 'n_combo2', 'n_combo3',
             'mean_elim', 'n_elim3', 'n_lowelim_pop7', 'n_front', 'n_hana', 'mean_posr'])
FIELDX_NOCOMBO = [f for f in FIELDX if f not in ('n_combo2', 'n_combo3')]

PARAMS = {'objective': 'binary', 'metric': ['auc'], 'learning_rate': 0.05,
          'num_leaves': 15, 'min_data_in_leaf': 200, 'feature_fraction': 0.9,
          'bagging_fraction': 0.9, 'bagging_freq': 5, 'verbose': -1,
          'seed': 42, 'bagging_seed': 42, 'feature_fraction_seed': 42}


def train_model(tr, feats, label):
    tr = tr.sort_values('day')
    cut = int(len(tr) * 0.8)
    a, b = tr.iloc[:cut], tr.iloc[cut:]
    ds_a = lgb.Dataset(a[feats].values.astype(np.float64), label=a[label].values,
                       feature_name=feats)
    ds_b = lgb.Dataset(b[feats].values.astype(np.float64), label=b[label].values,
                       feature_name=feats, reference=ds_a)
    return lgb.train(PARAMS, ds_a, num_boost_round=800, valid_sets=[ds_b],
                     callbacks=[lgb.early_stopping(60, verbose=False),
                                lgb.log_evaluation(0)])


def prec_at_topk(y, s, frac):
    k = max(1, int(len(s) * frac))
    idx = np.argsort(-s, kind='stable')[:k]
    hit = y[idx].sum()
    return hit / k, hit / max(y.sum(), 1)


def eval_scores(y, s):
    m = np.isfinite(s)
    y, s = y[m], s[m]
    out = {'n': int(len(y)), 'base': float(y.mean()),
           'auc': float(roc_auc_score(y, s)), 'ap': float(average_precision_score(y, s))}
    for f in (0.10, 0.20, 0.30):
        p, r = prec_at_topk(y, s, f)
        out[f'p@{int(f*100)}'] = float(p)
        out[f'r@{int(f*100)}'] = float(r)
    return out


def fmt(m):
    return (f"AUC{m['auc']:.4f} AP{m['ap']:.3f} "
            f"p@10%{m['p@10']:.1%}(r{m['r@10']:.0%}) p@20%{m['p@20']:.1%}(r{m['r@20']:.0%}) "
            f"p@30%{m['p@30']:.1%}(r{m['r@30']:.0%})")


def resid_z(y, p, mask):
    """オッズベースライン確率pに対する、mask群の残差z(市場超え判定)。"""
    y, p, mask = y[mask.notna()], p[mask.notna()], mask[mask.notna()].astype(bool)
    ys, ps = y[mask.values], p[mask.values]
    if len(ys) < 30:
        return None
    var = (ps * (1 - ps)).sum()
    z = (ys.sum() - ps.sum()) / np.sqrt(var) if var > 0 else 0.0
    return float(ys.mean()), float(z), int(len(ys))


def main():
    t0 = _time.time()
    df = pd.read_csv(CSV)
    df = df[(df['field_size'] >= 8) & df['fav1'].notna() & (df['n_odds'] >= 6)].copy()
    tr = df[(df['day'] >= TRAIN_FROM) & (df['day'] <= TRAIN_TO)]
    ho = df[(df['day'] >= HOLD_FROM) & (df['day'] <= HOLD_TO)]
    tr21 = df[(df['day'] >= 20210101) & (df['day'] <= TRAIN_TO)]
    print(f'races: train={len(tr):,} (2024-01〜2025-06-21) / holdout={len(ho):,} '
          f'(2025-06-22〜2026-06-21) / train21={len(tr21):,}')
    for lb in ('arareA', 'arareB', 'ana2'):
        print(f'  base {lb}: train={tr[lb].mean():.1%} holdout={ho[lb].mean():.1%}')

    report = {'ts': _time.strftime('%Y-%m-%d %H:%M:%S'),
              'n_train': len(tr), 'n_holdout': len(ho), 'labels': {}}

    # ── ① 現行スキャナーの実測(holdout) ──
    print('\n' + '=' * 78)
    print('【① 現行スキャナーの荒れ判別力(holdout 1年・ラベル=arareA)】')
    y_ho = ho['arareA'].values
    cur = {}
    for col in ('vscore', 'lean_score'):
        m = eval_scores(y_ho, ho[col].values.astype(float))
        cur[col] = m
        print(f'  {col:12s} {fmt(m)}')
    print('  [vlabel別 実荒れ率]')
    for lab, g in ho.groupby('vlabel'):
        print(f'    {lab:12s} n={len(g):5,}  arareA={g["arareA"].mean():.1%}  '
              f'arareB={g["arareB"].mean():.1%}  ②型={g["ana2"].mean():.1%}')
    print('  [no_favorite_flag別]')
    for lab, g in ho.groupby(ho['nofav'].fillna('')):
        print(f'    {(lab or "(なし)"):12s} n={len(g):5,}  arareA={g["arareA"].mean():.1%}')
    report['current'] = cur

    # ── ② 段階モデル(M0市場のみ → M1+構造 → M2+フィールド) ──
    tiers = [('M0 市場のみ', ODDS), ('M1 +構造条件', ODDS + STRUCT),
             ('M2 +フィールド', ODDS + STRUCT + FIELDX)]
    models = {}
    for lb in ('arareA', 'arareB', 'ana2'):
        print(f'\n【② 段階モデル比較(train2024-25.6 → holdout1年)  label={lb}  '
              f'base={ho[lb].mean():.1%}】')
        rep = {}
        y = ho[lb].values
        for name, feats in tiers:
            mdl = train_model(tr, feats, lb)
            s = mdl.predict(ho[feats].values.astype(np.float64))
            m = eval_scores(y, s)
            rep[name] = m
            models[(lb, name)] = (mdl, feats)
            print(f'  {name:12s} {fmt(m)}')
        d_auc = rep['M2 +フィールド']['auc'] - rep['M1 +構造条件']['auc']
        print(f'  → M2−M1 AUCゲイン = {d_auc:+.4f}')
        report['labels'][lb] = rep

    # ── ③ フィールド特徴の残差z(M0ベースライン統制・train/holdout) ──
    print('\n【③ フィールド特徴の残差z(M0市場のみベースラインからの上振れ・label=arareA)】')
    mdl0, f0 = models[('arareA', 'M0 市場のみ')]
    zrep = {}
    p_tr = pd.Series(mdl0.predict(tr[f0].values.astype(np.float64)), index=tr.index)
    p_ho = pd.Series(mdl0.predict(ho[f0].values.astype(np.float64)), index=ho.index)
    print(f'  {"feature(上位25%群)":30s}{"train":>26s}{"holdout":>26s}')
    for f in FIELDX:
        q = tr[f].quantile(0.75)
        cells, zr = [], {}
        for nm, w, p in (('train', tr, p_tr), ('holdout', ho, p_ho)):
            r = resid_z(w['arareA'], p, w[f] >= q)
            if r is None:
                cells.append(f'{"n<30":>26s}')
            else:
                cells.append(f'{r[0]:7.1%} z{r[1]:+5.1f} n{r[2]:6,}')
                zr[nm] = {'rate': r[0], 'z': r[1], 'n': r[2]}
        zrep[f] = zr
        print(f'  {f:28s}' + ''.join(cells))
    report['resid_z'] = zrep

    # M2の重要度
    mdl2, f2 = models[('arareA', 'M2 +フィールド')]
    imp = sorted(zip(f2, mdl2.feature_importance('gain')), key=lambda x: -x[1])
    print('\n【M2 feature importance(gain) top20 (label=arareA)】')
    for f, g in imp[:20]:
        print(f'  {f:22s} {g:10.0f}')
    report['importance_m2'] = [{'f': f, 'gain': float(g)} for f, g in imp]

    # ── ③b 配線用: 透明ロジスティック(train2021+で学習・係数凍結出力) ──
    print('\n【③b 配線候補: 透明ロジスティック(12特徴・train2021-25.6学習→holdout)】')
    sub_tr = tr21.dropna(subset=LOGIT_FEATS)
    mu = sub_tr[LOGIT_FEATS].mean()
    sd = sub_tr[LOGIT_FEATS].std().replace(0, 1.0)
    logit_rep = {}
    for lb in ('arareA', 'ana2'):
        clf = LogisticRegression(max_iter=2000, C=1.0)
        clf.fit(((sub_tr[LOGIT_FEATS] - mu) / sd).values, sub_tr[lb].values)
        sub_ho = ho.dropna(subset=LOGIT_FEATS)
        p = clf.predict_proba(((sub_ho[LOGIT_FEATS] - mu) / sd).values)[:, 1]
        m = eval_scores(sub_ho[lb].values, p)
        logit_rep[lb] = m
        print(f'  logit[{lb:6s}] {fmt(m)}')
        if lb == 'arareA':
            coefs = sorted(zip(LOGIT_FEATS, clf.coef_[0]), key=lambda x: -abs(x[1]))
            print('    係数(標準化): ' + '  '.join(f'{f}{c:+.2f}' for f, c in coefs))
            params = {'features': LOGIT_FEATS, 'mu': mu.to_dict(), 'sd': sd.to_dict(),
                      'coef': dict(zip(LOGIT_FEATS, clf.coef_[0].tolist())),
                      'intercept': float(clf.intercept_[0]),
                      'label': 'arareA(3着内に7番人気以下)',
                      'train': 'JRA平地 tosu>=8 2021-01〜2025-06-21',
                      'holdout_metrics': m}
            with open(OUT_PARAMS, 'w', encoding='utf-8') as fp:
                json.dump(params, fp, ensure_ascii=False, indent=1)
            print(f'    → 係数凍結 {OUT_PARAMS}')
    report['logit'] = logit_rep

    # ── ④ 感度: train2021+(combo無し) ──
    print('\n【④ 感度確認: train2021-01〜2025-06(combo特徴なし・label=arareA)】')
    y = ho['arareA'].values
    rep21 = {}
    for name, feats in (('M1 +構造条件', ODDS + STRUCT),
                        ('M2 +フィールド(no combo)', ODDS + STRUCT + FIELDX_NOCOMBO)):
        mdl = train_model(tr21, feats, 'arareA')
        s = mdl.predict(ho[feats].values.astype(np.float64))
        m = eval_scores(y, s)
        rep21[name] = m
        print(f'  {name:24s} {fmt(m)}')
    report['train21'] = rep21

    with open(OUT, 'w', encoding='utf-8') as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)
    print(f'\njson → {OUT}\ndone in {_time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
