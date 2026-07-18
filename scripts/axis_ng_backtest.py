# -*- coding: utf-8 -*-
"""軸馬NG説の検証 — 資料『絶対にNGな軸馬の選び方』の主張を人気/オッズ統制で検定する。

対象(既存台帳で未検証のものだけ):
  A 昇級初戦の過剰人気     → 近似: 前走1着(勝ち上がり直後)の人気馬
  B 距離延長は折り合い/スタミナ切れ → dist_change >= +200m
  C 成績にムラがある馬     → 直近5走の着順の標準偏差(大きいほどムラ)
  D 過酷ローテ(短間隔)     → days_since <= 21日(中1〜2週)

既に答えが出ている主張は検定しない(脚質=verified_legtype_axis / EV>100=verified_tansho_roi_efficient /
長期休養=verified_rotation_weight_demerit / 枠=verified_dirt_draw_bias / 指数1位過剰人気=ガラス人気馬)。

母集団: 軸候補帯 = 1〜5番人気(資料の定義と一致)。
評価: 単体の複勝率ではなく『オッズ統制後の残差』。オッズ帯(20分位)の実複勝率をベースラインに置き、
      そこからの上振れ/下振れをppとzで測る(単体率は人気に織込み済みで必ず priced-in になる)。
分割: train(〜2024) / holdout(2025-) の両方で符号が一致し有意なものだけを採用。
リーク対策: 前走着順/着順分散/距離変化/間隔はすべてshiftした過去情報のみ(当該レース結果は不使用)。
"""
import io
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CSV = 'data/export/horse_races.csv'
POP_MAX = 5          # 軸候補帯(資料の定義: 1〜5番人気)
HOLDOUT_DAY = 20250101


def load():
    cols = ['race_key', 'day', 'ketto_num', 'ninki', 'win_odds',
            'dist_change', 'days_since', 'chakujun', 'top3']
    df = pd.read_csv(CSV, usecols=cols)
    df = df[(df['chakujun'] > 0) & (df['ninki'] > 0) & (df['win_odds'] > 0)].copy()
    df = df.sort_values(['ketto_num', 'race_key'])
    g = df.groupby('ketto_num')['chakujun']
    # 前走着順(shift=過去のみ) と 直近5走の着順の標準偏差(=ムラ)。どちらもリークなし。
    df['prev_chaku'] = g.shift(1)
    df['sd5'] = (g.shift(1).groupby(df['ketto_num'])
                 .rolling(5, min_periods=3).std().reset_index(level=0, drop=True))
    return df


def baseline_resid(df):
    """オッズ帯(20分位)の実複勝率をベースラインにした残差。人気/市場評価を統制する。"""
    df = df.copy()
    df['obin'] = pd.qcut(df['win_odds'], 20, labels=False, duplicates='drop')
    exp = df.groupby('obin')['top3'].transform('mean')
    df['resid'] = df['top3'] - exp
    return df


def report(name, mask, df):
    rows = []
    for tag, sub in (('train', df[df['day'] < HOLDOUT_DAY]),
                     ('holdout', df[df['day'] >= HOLDOUT_DAY])):
        m = mask.reindex(sub.index).fillna(False)
        hit, non = sub[m], sub[~m]
        if len(hit) < 200:
            rows.append((tag, len(hit), None, None, None))
            continue
        r = hit['resid']
        z = r.mean() / (r.std() / np.sqrt(len(r)))
        rows.append((tag, len(hit), hit['top3'].mean() * 100,
                     non['top3'].mean() * 100, (r.mean() * 100, z)))
    print(f"\n■ {name}")
    for tag, n, h3, n3, rz in rows:
        if rz is None:
            print(f"   {tag:8s} n={n:6d}  (標本不足)")
            continue
        pp, z = rz
        mark = '★' if abs(z) >= 2.0 else '　'
        print(f"   {tag:8s} n={n:6d}  複勝率 {h3:5.1f}% (該当外 {n3:5.1f}%)"
              f"  → オッズ統制後の残差 {pp:+5.2f}pp  z={z:+5.2f} {mark}")


def main():
    df = load()
    df = df[df['ninki'] <= POP_MAX]          # 軸候補帯に限定
    df = baseline_resid(df)
    print(f"母集団: 1〜{POP_MAX}番人気  n={len(df):,}"
          f"  (train {len(df[df['day'] < HOLDOUT_DAY]):,} / holdout {len(df[df['day'] >= HOLDOUT_DAY]):,})")
    print("残差 = 複勝率 − 同オッズ帯の平均複勝率。プラス=市場より走る/マイナス=危険な人気馬。")

    report("A 昇級初戦の近似: 前走1着(勝ち上がり直後)の人気馬",
           df['prev_chaku'] == 1, df)
    report("A' 前走1着 かつ 1〜2番人気(資料の言う『連勝で過剰人気』)",
           (df['prev_chaku'] == 1) & (df['ninki'] <= 2), df)
    report("B 距離延長 +200m以上",
           df['dist_change'] >= 200, df)
    report("B' 距離延長 +400m以上(大幅延長)",
           df['dist_change'] >= 400, df)
    report("C 成績にムラ: 直近5走の着順の標準偏差が上位25%(ばらつき大)",
           df['sd5'] >= df['sd5'].quantile(0.75), df)
    report("C' 安定型: 着順の標準偏差が下位25%(常に同じ着順帯)",
           df['sd5'] <= df['sd5'].quantile(0.25), df)
    report("D 短間隔ローテ: 中1〜2週(間隔21日以下)",
           df['days_since'] <= 21, df)
    report("D' 連闘(間隔8日以下)",
           df['days_since'] <= 8, df)


if __name__ == '__main__':
    main()
