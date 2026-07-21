# -*- coding: utf-8 -*-
"""騎手係数の黄金ライン段(0.30/0.40)を検証結果の形に変えるべきかを recall@7 で検証。

背景: golden_line_backtest.py で連対率帯の3着内残差は 35-40% が最強・40%+ は弱い・
50%+ はほぼゼロ(織込み済み)と判明。一方 jockey_factor の段は 40%+ に最大の×1.07 を
与えており向きが逆。ただし段を変える価値があるかは「順位が良くなるか」で判定すべき。

適用範囲(2026-07 実査): jockey_factor/jockey_coefficient の呼び出しは
app.py:7041(J5表)の1か所のみ。Projected Score / LTR / 買い目 / 消去 / 合議 には
入っていないため、この係数は「J5表の並び順」だけを動かす。よって評価も
J5と同じ『ベーススコア×係数』の並びに対する recall@7 で行う。

評価指標(scripts/auto_feature_search.py と同じ定義):
  win@7   = 勝ち馬が上位7頭に入ったレースの割合
  top3@7  = 3着内馬のうち上位7頭で捕捉できた割合の平均
黄金ライン段のみを差し替え、USM/場相性は全変種で共通(固定)＝段の形だけを比較する。
"""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  'data', 'jravan.db')
MIN_RIDES = 15   # jockey_factor の黄金ライン段と同じゲート


def load_combo():
    """race_key×umaban ごとの『そのレース時点までの』騎手×調教師 連対率(リークフリー)。"""
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT race_key, umaban, year, jockey_name, trainer_code, chakujun "
        "FROM results WHERE chakujun>0 AND year>=2015 "
        "AND jockey_name IS NOT NULL AND trainer_code IS NOT NULL", con)
    con.close()
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df = df[df['chakujun'].notna()]
    df['top2'] = (df['chakujun'] <= 2).astype(int)
    df = df.sort_values('race_key').reset_index(drop=True)
    g = df.groupby(['jockey_name', 'trainer_code'], sort=False)
    df['c_rides'] = g.cumcount()
    df['c_top2'] = g['top2'].cumsum() - df['top2']
    df['combo_rate'] = df['c_top2'] / df['c_rides'].where(df['c_rides'] > 0)
    df['umaban'] = pd.to_numeric(df['umaban'], errors='coerce')
    return df[['race_key', 'umaban', 'c_rides', 'combo_rate']]


# ── 係数の変種(黄金ライン段のみ) ──
def coef_none(rate, rides):
    return np.ones(len(rate))


def coef_current(rate, rides):
    """現行: 40%+ →×1.07 / 30-40% →×1.035"""
    m = np.ones(len(rate))
    ok = rides >= MIN_RIDES
    m = np.where(ok & (rate >= 0.40), 1.07, m)
    m = np.where(ok & (rate >= 0.30) & (rate < 0.40), 1.035, m)
    return m


def coef_revised(rate, rides):
    """検証準拠: 35-40%(最強)→×1.07 / 40%+(織込み済)→×1.035 / 35%未満→×1.0"""
    m = np.ones(len(rate))
    ok = rides >= MIN_RIDES
    m = np.where(ok & (rate >= 0.35) & (rate < 0.40), 1.07, m)
    m = np.where(ok & (rate >= 0.40), 1.035, m)
    return m


def coef_gate35(rate, rides):
    """単純化: 35%以上を一律×1.05(段を作らない)"""
    m = np.ones(len(rate))
    return np.where((rides >= MIN_RIDES) & (rate >= 0.35), 1.05, m)


VARIANTS = [('係数なし(対照)', coef_none), ('現行(40%+が最大)', coef_current),
            ('検証準拠(35-40%が最大)', coef_revised), ('35%一律×1.05', coef_gate35)]


def recall7(df, score_col):
    """win@7 / top3@7 / レース数。scoreは大きいほど上位。"""
    win_hit, tot, t3 = 0, 0, []
    for _, grp in df.groupby('race_key', sort=False):
        winner = set(grp.loc[grp['chakujun'] == 1, 'umaban'])
        top3 = set(grp.loc[grp['chakujun'] <= 3, 'umaban'])
        if not winner or not top3:
            continue
        top7 = set(grp.nlargest(7, score_col)['umaban'])
        win_hit += int(bool(winner & top7))
        t3.append(len(top3 & top7) / len(top3))
        tot += 1
    return (win_hit / tot if tot else 0.0,
            float(np.mean(t3)) if t3 else 0.0, tot)


def main():
    print("=" * 78)
    print("騎手係数(黄金ライン段)の recall@7 検証  ※係数の用途はJ5表の並びのみ")
    print("=" * 78)
    h = csv_data.load_horses(cols=['race_key', 'day', 'umaban', 'ninki',
                                   'ability_score', 'win_odds', 'chakujun'])
    h['umaban'] = pd.to_numeric(h['umaban'], errors='coerce')
    h['chakujun'] = pd.to_numeric(h['chakujun'], errors='coerce')
    h = h[h['chakujun'].notna() & h['umaban'].notna()]
    combo = load_combo()
    # race_key は CSV=int64 / DB=TEXT なので文字列に揃える
    h['race_key'] = h['race_key'].astype(str)
    combo['race_key'] = combo['race_key'].astype(str)
    df = h.merge(combo, on=['race_key', 'umaban'], how='left')
    df['combo_rate'] = df['combo_rate'].fillna(0.0)
    df['c_rides'] = df['c_rides'].fillna(0)
    print(f"対象 {len(df):,}頭 / {df['race_key'].nunique():,}レース  "
          f"(黄金ライン計算可 {(df['c_rides'] >= MIN_RIDES).mean()*100:.0f}%)")

    # ベースは必ず「正の値・大きいほど良い」にする。負値だと×1.07が順位を下げる逆効果になり
    # 検証が成立しない(2026-07に一度この符号ミスで『全変種が同一』という誤結果を出した)。
    #  ①能力スコア: ability_scoreはレース内percentile平均で低い=良い → 1-x で反転
    #  ②市場ベース: 単勝オッズ逆数(=市場の勝率推定)。Projected Scoreは人気主成分なのでその代理。
    # ※『頭数-人気+1』の線形尺度は7/8位の隣接比が1.09〜1.11で最大係数1.07を上回り、
    #   構造的に一切逆転が起きない(実測0/31,419レース)ため代理として不適=不採用。
    df['base_ability'] = 1.0 - pd.to_numeric(df['ability_score'], errors='coerce')
    _od = pd.to_numeric(df['win_odds'], errors='coerce')
    df['base_market'] = np.where(_od > 0, 1.0 / _od, np.nan)

    for base_col, base_lbl in (('base_market', '市場ベース(単勝オッズ逆数=Projected Scoreの代理)'),
                               ('base_ability', '能力スコアベース(オッズ非依存)')):
        d = df[df[base_col].notna()].copy()
        r, rd = d['combo_rate'].to_numpy(), d['c_rides'].to_numpy()
        print(f"\n■ ベース: {base_lbl}")
        for per in ('train', 'holdout'):
            w = d[d['period'] == per] if per == 'train' else \
                d[d['period'].isin(['holdout', 'recent'])]
            if w.empty:
                continue
            rw, rdw = w['combo_rate'].to_numpy(), w['c_rides'].to_numpy()
            print(f"  --- {per} ---")
            base_win = base_t3 = None
            for lbl, fn in VARIANTS:
                w = w.copy()
                w['_s'] = w[base_col] * fn(rw, rdw)
                win, t3, n = recall7(w, '_s')
                if base_win is None:
                    base_win, base_t3 = win, t3
                    print(f"    {lbl:22s}: win@7 {win*100:5.2f}%  top3@7 {t3*100:5.2f}%  "
                          f"races={n:,}")
                else:
                    print(f"    {lbl:22s}: win@7 {win*100:5.2f}% ({(win-base_win)*100:+5.2f}pp) "
                          f" top3@7 {t3*100:5.2f}% ({(t3-base_t3)*100:+5.2f}pp)")


if __name__ == '__main__':
    main()
