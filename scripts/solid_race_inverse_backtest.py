# -*- coding: utf-8 -*-
"""堅いレース条件の逆転検証 — scripts/solid_race_inverse_backtest.py

ユーザー仮説(逆転の発想): 『鉄板/堅いレースの条件が正確に分かれば、その裏返しで
荒れ・大荒れの精度も上がるのでは?』
インフォグラフィック『データで勝つ競馬』/PDF『The Rational Bettor's Blueprint』の
『堅いレース』3条件を定量化し、既存の荒れロジット(scanner_arare_logit・AUC0.690)を
超える"追加の"判別力があるかを1年holdoutで実測する。

PDFの堅い条件(逆=荒れ):
  ①単勝1番人気オッズ 1.9倍以下(圧倒的本命)
  ②出走頭数 12頭以下(少頭数)
  ③オッズ断層(上位と下位の間に2.8倍以上の乖離)＝上位が抜けている
  否定条件: 3強・4強(上位拮抗)は堅くない=荒れ側

検証の問い:
  Q1 堅さ条件の充足数で arareA(3着内に7番人気以下) は単調に下がるか(較正)
  Q2 『大荒れ』(arareB=勝ち馬6番人気以下)は非堅レース側でどれだけ濃縮されるか
  Q3 堅さ複合スコアは既存エントロピー・ロジット(12特徴)に"上乗せ"AUCを出すか
      → 出なければ priced-in(逆転の発想は既存軸と同一)。出れば新規エッジ。

Usage: python scripts/solid_race_inverse_backtest.py
"""
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, 'data', 'export', 'races.csv')

# 既存荒れロジットの特徴(scanner_arare_logit.json と同じ)
LOGIT_FEATS = ['fav1', 'r21', 'r31', 'syn3', 'odds_entropy', 'eff_n',
               'live10', 'live30', 'mid515', 'field_size', 'is_handi1', 'fillies']
TRAIN_FROM, TRAIN_TO = 20210101, 20250621
HOLD_FROM, HOLD_TO = 20250622, 20260621


def auc(y, s):
    m = np.isfinite(s)
    return roc_auc_score(y[m], s[m]) if y[m].sum() > 0 else float('nan')


def main():
    df = pd.read_csv(CSV)
    df = df[(df['field_size'] >= 8) & df['fav1'].notna() & (df['n_odds'] >= 6)].copy()

    # ── 堅さ条件の定量化(PDF準拠) ──
    # r21=2番人気/1番人気オッズ比, r31=3番人気/1番人気オッズ比(大=上位が抜け=断層)
    df['c_fav'] = (df['fav1'] <= 1.9).astype(int)         # ①圧倒的本命
    df['c_few'] = (df['field_size'] <= 12).astype(int)    # ②少頭数
    df['c_gap'] = (df['r21'] >= 2.0).astype(int)          # ③2番手との断層(1強)
    df['c_notkyoko'] = (df['r31'] >= 2.8).astype(int)     # 3強否定(3番手が2.8倍以上離れ)
    df['solid_n'] = df[['c_fav', 'c_few', 'c_gap']].sum(axis=1)
    # 堅さ複合スコア(連続): 本命の強さ+断層の深さ-頭数。全てオッズ/頭数の関数
    df['solid_score'] = (-df['fav1'].clip(1.0, 6.0)
                         + df['r21'].clip(0, 6) * 0.7
                         + df['r31'].clip(0, 10) * 0.3
                         - df['field_size'] * 0.15)

    tr = df[(df['day'] >= TRAIN_FROM) & (df['day'] <= TRAIN_TO)].copy()
    ho = df[(df['day'] >= HOLD_FROM) & (df['day'] <= HOLD_TO)].copy()
    print(f'races: train={len(tr):,}(2021-01〜2025-06) holdout={len(ho):,}(1年)')
    print(f'  base holdout: arareA(3着内7人気-)={ho.arareA.mean():.1%} '
          f'arareB(勝馬6人気-)={ho.arareB.mean():.1%}')

    # ── Q1: 堅さ充足数 × 実荒れ率(holdout・較正) ──
    print('\n【Q1 堅さ条件(本命1.9倍-/12頭-/断層)の充足数 × 実荒れ率(holdout)】')
    print(f'  {"充足数":6s}{"n":>7s}{"arareA":>9s}{"arareB(大荒)":>12s}{"1番人気勝率*":>12s}')
    for k in range(4):
        g = ho[ho.solid_n == k]
        if len(g) == 0:
            continue
        # 1番人気勝率の代理: fav1が低いほど堅い→ここでは荒れの裏返しとして参考表示
        print(f'  {k:<6d}{len(g):7,}{g.arareA.mean():9.1%}{g.arareB.mean():12.1%}'
              f'{(1-g.arareA.mean()):12.1%}')
    g3 = ho[(ho.solid_n == 3) & (ho.c_notkyoko == 1)]
    print(f'  3+否定なし(完全堅) n={len(g3):,} arareA={g3.arareA.mean():.1%} '
          f'arareB={g3.arareB.mean():.1%}')

    # ── Q2: 非堅レース側(荒れ抽出)の濃縮度 ──
    print('\n【Q2 『非堅(荒れ候補)』の濃縮: 条件0個 vs 全体】')
    loose = ho[ho.solid_n == 0]
    print(f'  非堅(条件0個)  n={len(loose):,} arareA={loose.arareA.mean():.1%} '
          f'arareB={loose.arareB.mean():.1%} (全体比 arareA {loose.arareA.mean()/ho.arareA.mean():.2f}x)')

    # ── Q3: 既存ロジットに上乗せするか(核心) ──
    print('\n【Q3 既存エントロピー・ロジットに堅さスコアが"上乗せ"するか(holdout AUC)】')
    sub_tr = tr.dropna(subset=LOGIT_FEATS + ['solid_score'])
    sub_ho = ho.dropna(subset=LOGIT_FEATS + ['solid_score'])
    for label in ('arareA', 'arareB'):
        y_ho = sub_ho[label].values
        results = {}
        # (a) 堅さスコア単体(符号反転=荒れ方向)
        results['堅さスコア単体(逆)'] = auc(y_ho, -sub_ho['solid_score'].values)
        # (b) 既存ロジット12特徴
        mu = sub_tr[LOGIT_FEATS].mean()
        sd = sub_tr[LOGIT_FEATS].std().replace(0, 1.0)
        clf = LogisticRegression(max_iter=2000, C=1.0)
        clf.fit(((sub_tr[LOGIT_FEATS] - mu) / sd).values, sub_tr[label].values)
        p_base = clf.predict_proba(((sub_ho[LOGIT_FEATS] - mu) / sd).values)[:, 1]
        results['既存ロジット12特徴'] = auc(y_ho, p_base)
        # (c) 既存ロジット + 堅さスコア
        feats2 = LOGIT_FEATS + ['solid_score']
        mu2 = sub_tr[feats2].mean()
        sd2 = sub_tr[feats2].std().replace(0, 1.0)
        clf2 = LogisticRegression(max_iter=2000, C=1.0)
        clf2.fit(((sub_tr[feats2] - mu2) / sd2).values, sub_tr[label].values)
        p2 = clf2.predict_proba(((sub_ho[feats2] - mu2) / sd2).values)[:, 1]
        results['+堅さスコア'] = auc(y_ho, p2)
        print(f'  [{label}] base={y_ho.mean():.1%}')
        for k, v in results.items():
            print(f'     {k:22s} AUC {v:.4f}')
        print(f'     → 上乗せAUC = {results["+堅さスコア"]-results["既存ロジット12特徴"]:+.4f}')

    # ── Q3b: 残差z(既存ロジットで説明できない堅レースの上振れ/下振れ) ──
    print('\n【Q3b 堅レース(完全堅)は既存ロジットで既に低荒れ確率と予測されているか】')
    p_all = clf.predict_proba(((sub_ho[LOGIT_FEATS] - mu) / sd).values)[:, 1]  # arareB base(最後のclf)
    # arareA用に取り直し
    clfA = LogisticRegression(max_iter=2000, C=1.0)
    clfA.fit(((sub_tr[LOGIT_FEATS] - mu) / sd).values, sub_tr['arareA'].values)
    pA = pd.Series(clfA.predict_proba(((sub_ho[LOGIT_FEATS] - mu) / sd).values)[:, 1],
                   index=sub_ho.index)
    for lab, mask in (('完全堅(3条件+否定)', (sub_ho.solid_n == 3) & (sub_ho.c_notkyoko == 1)),
                      ('堅(3条件)', sub_ho.solid_n == 3),
                      ('非堅(0条件)', sub_ho.solid_n == 0)):
        s = sub_ho[mask]
        if len(s) < 30:
            print(f'  {lab:18s} n={len(s)}(小)')
            continue
        pm = pA[mask]
        var = (pm * (1 - pm)).sum()
        z = (s.arareA.sum() - pm.sum()) / np.sqrt(var) if var > 0 else 0
        print(f'  {lab:18s} n={len(s):5,} 実arareA={s.arareA.mean():6.1%} '
              f'ロジット予測={pm.mean():6.1%} 残差z={z:+.1f}')

    print('\n判定の読み方: 上乗せAUC≈0かつ残差z≈0 → 堅さ条件は既存エントロピー軸に'
          '含まれ済み(priced-in・逆転の発想は新規エッジにならず/較正確認のみ)。'
          '上乗せAUC>0.01 or |z|>2 → 新規情報あり=配線候補。')


if __name__ == '__main__':
    main()
