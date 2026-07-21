# -*- coding: utf-8 -*-
"""黄金ライン(騎手×調教師 連対率40%+×騎乗10回+)は軽視されているか？の検証。

きっかけ: 202609011010(阪神ダ1800 レグルスS)で黄金ライン該当3頭が1-2-3着を独占し、
「黄金ラインの馬を軽視したから当たらないのでは」との指摘。1レースの一致は過学習の
典型なので、全期間で人気統制残差を測って本当にエッジがあるかを判定する。

リーク対策: 各レース時点より前(race_key <)の騎乗のみで連対率を累積計算する
(app.pyのライブ呼び出しはbefore_key無し=当日時点で全過去が使えるので等価)。
判定: train(≤2024)/holdout(2025+)の両窓で符号一致かつ有意なら本物。
"""
import os
import sqlite3
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  'data', 'jravan.db')
MIN_RIDES = 10      # app.py と同じゲート
MIN_TOP2 = 0.40


def load():
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT race_key, year, jockey_name, trainer_code, chakujun, ninki, win_odds "
        "FROM results WHERE chakujun>0 AND year>=2016 AND jockey_name IS NOT NULL "
        "AND trainer_code IS NOT NULL", con)
    con.close()
    return df


def main():
    print("=" * 74)
    print("黄金ライン(騎手×調教師 連対40%+ / 騎乗10+)の人気統制残差検証")
    print("=" * 74)
    df = load()
    df['year'] = pd.to_numeric(df['year'], errors='coerce')   # DBはTEXT保存
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df = df[df['year'].notna()]
    df = df[df['ninki'].notna() & (df['ninki'] > 0) & df['chakujun'].notna()]
    df['top3'] = (df['chakujun'] <= 3).astype(int)
    df['top2'] = (df['chakujun'] <= 2).astype(int)
    df = df.sort_values('race_key').reset_index(drop=True)
    print(f"対象: {len(df):,}騎乗 ({df['year'].min()}〜{df['year'].max()})")

    # ── 過去のみ(shift)で騎手×調教師の累積連対率を作る ──
    g = df.groupby(['jockey_name', 'trainer_code'], sort=False)
    df['c_rides'] = g.cumcount()                       # 今回を含まない騎乗数
    df['c_top2'] = g['top2'].cumsum() - df['top2']     # 今回を含まない連対数
    df['combo_rate'] = df['c_top2'] / df['c_rides'].where(df['c_rides'] > 0)
    df['gold'] = ((df['c_rides'] >= MIN_RIDES) & (df['combo_rate'] >= MIN_TOP2)).astype(int)

    df['period'] = 'train'
    df.loc[df['year'] >= 2025, 'period'] = 'holdout'
    base = df.groupby(df['ninki'].astype(int))['top3'].mean().to_dict()

    def resid(sub):
        n = len(sub)
        if n < 50:
            return None
        rate = sub['top3'].mean()
        exp = sub['ninki'].astype(int).map(base).mean()
        se = (0.15 * 0.85 / n) ** 0.5
        return rate, exp, (rate - exp) / se, n

    def show(sub, lbl):
        r = resid(sub)
        if r is None:
            print(f"   {lbl:34s}: n<50")
            return
        rate, exp, z, n = r
        print(f"   {lbl:34s}: 実{rate*100:5.1f}% 期待{exp*100:5.1f}% "
              f"残差{(rate-exp)*100:+5.2f}pp z={z:+6.1f} n={n:,}")

    print(f"\n黄金ライン該当率: {df['gold'].mean()*100:.1f}% "
          f"({df['gold'].sum():,}騎乗)")

    print("\n【1】黄金ライン該当 vs 非該当(人気統制残差)")
    for per in ('train', 'holdout'):
        w = df[df['period'] == per]
        print(f"  --- {per} ---")
        show(w[w['gold'] == 1], '黄金ライン該当')
        show(w[w['gold'] == 0], '非該当(対照)')

    print("\n【2】人気帯別(妙味は人気薄に出るのが通例)")
    for per in ('train', 'holdout'):
        w = df[(df['period'] == per) & (df['gold'] == 1)]
        print(f"  --- {per} ---")
        for lo, hi, lbl in ((1, 3, '1-3人気'), (4, 6, '4-6人気'),
                            (7, 9, '7-9人気'), (10, 99, '10人気-')):
            show(w[(w['ninki'] >= lo) & (w['ninki'] <= hi)], f'黄金×{lbl}')

    print("\n【3】連対率の水準別(閾値40%は妥当か)")
    for per in ('train', 'holdout'):
        w = df[(df['period'] == per) & (df['c_rides'] >= MIN_RIDES)]
        print(f"  --- {per} ---")
        for lo, hi, lbl in ((0.0, 0.25, '〜25%'), (0.25, 0.35, '25-35%'),
                            (0.35, 0.40, '35-40%'), (0.40, 0.50, '40-50%'),
                            (0.50, 1.01, '50%+')):
            show(w[(w['combo_rate'] >= lo) & (w['combo_rate'] < hi)], f'連対{lbl}')

    print("\n【4】単勝ROI(黄金ライン該当 vs 非該当)")
    df['win_odds'] = pd.to_numeric(df['win_odds'], errors='coerce')
    ro = df[df['win_odds'].notna() & (df['win_odds'] > 0)].copy()
    ro['ret'] = (ro['chakujun'] == 1) * ro['win_odds'] * 100
    print(f"   win_odds有効: {len(ro):,}騎乗 ({len(ro)/len(df)*100:.0f}%)")
    for per in ('train', 'holdout'):
        w = ro[ro['period'] == per]
        for flag, lbl in ((1, '黄金ライン該当'), (0, '非該当(対照)')):
            s = w[w['gold'] == flag]
            if len(s) < 50:
                continue
            print(f"   {per:8s} {lbl:14s}: 単ROI {s['ret'].mean():5.1f}% n={len(s):,}")


if __name__ == '__main__':
    main()
