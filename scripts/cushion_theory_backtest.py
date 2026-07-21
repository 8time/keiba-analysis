# -*- coding: utf-8 -*-
"""クッション値理論(ユーザー提供資料 2026-07)の検証バックテスト。

検証する主張:
  A. 高クッション値(硬い馬場)は前残り=先行有利になる
  B. 種牡馬×クッション9.5閾値で成績が激変する(資料の名指し種牡馬)
  C. 前走「標準(8-10)」→今走「硬め(>10)」×前走末脚上位 = 激走パターン

方法: CSV特徴ストア(leak-free)。人気統制残差(resid_z)で「市場に織込み済みか」を判定。
train(≤2024) / holdout(2025+recent2026) の両窓で符号・有意性が一致したものだけ採用。
クッション値はraces.csv(track_cond由来・2020-09以降の芝レースのみ有効)。
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data  # noqa: E402


def band(c):
    if pd.isna(c):
        return None
    if c < 8.0:
        return '軟(<8)'
    if c < 10.0:
        return '標準(8-10)'
    if c < 11.0:
        return 'やや硬(10-11)'
    return '硬(11+)'


def fmt(r):
    if r is None:
        return '  n<20'
    rate, exp, z, n = r
    return f"実{rate*100:5.1f}% 期待{exp*100:5.1f}% 残差{(rate-exp)*100:+5.2f}pp z={z:+5.1f} n={n}"


def main():
    print("=" * 78)
    print("クッション値理論の検証 (人気統制残差・train≤2024 / holdout=2025+2026)")
    print("=" * 78)

    races = csv_data.load_races(cols=['race_key', 'day', 'jyo', 'surface_code', 'cushion'],
                                with_period=False)
    horses = csv_data.load_horses(cols=[
        'race_key', 'day', 'jyo', 'surface_code', 'ketto_num', 'ninki', 'win_odds',
        'pos_ratio3', 'spurt_idx', 'sire', 'top3', 'win'])
    df = horses.merge(races[['race_key', 'cushion']], on='race_key', how='left')
    df = df[(df['surface_code'] == 1) & df['cushion'].notna()].copy()  # 芝×クッション有
    print(f"\n対象: 芝×クッション値あり {len(df):,}頭 / "
          f"{df['race_key'].nunique():,}レース (期間 {df['day'].min()}〜{df['day'].max()})")
    df['band'] = df['cushion'].map(band)
    base = csv_data.base_top3_by_ninki(csv_data.load_horses(cols=['race_key', 'ninki', 'top3'],
                                                            with_period=False))
    tr = df[df['period'] == 'train']
    ho = df[df['period'].isin(['holdout', 'recent'])]

    # ── A. 高クッション×先行(前残り)は妙味か ──
    print("\n【A】高クッション×先行習性(pos_ratio3≤0.28=本物の先行) 人気統制残差")
    print("     ※資料の主張: 硬い馬場=前残り有利。市場が知っていれば残差≈0(織込み済み)")
    for w, lbl in ((tr, 'train'), (ho, 'holdout')):
        print(f"  --- {lbl} ---")
        for b in ('軟(<8)', '標準(8-10)', 'やや硬(10-11)', '硬(11+)'):
            sub = w[(w['band'] == b) & (w['pos_ratio3'].notna()) & (w['pos_ratio3'] <= 0.28)]
            print(f"   {b:12s} 先行: {fmt(csv_data.resid_z(sub, base))}")

    # ── B. 種牡馬×クッション9.5閾値 ──
    print("\n【B】種牡馬×クッション9.5閾値 (資料の名指し種牡馬・全コースpooled)")
    print("     コントラスト = 残差(≥9.5) - 残差(≤9.4)。両窓で同符号かつ|z差|大なら本物")
    sires = ['ディープインパクト', 'キズナ', 'エピファネイア', 'ロードカナロア',
             'キタサンブラック', 'ルーラーシップ', 'ダイワメジャー', 'ハービンジャー',
             'リアルスティール', 'イスラボニータ', 'サトノダイヤモンド', 'ミッキーアイル',
             'ドゥラメンテ', 'スワーヴリチャード', 'アドマイヤムーン', 'モーリス']
    print(f"  {'種牡馬':<10s} {'train高-低(pp)':>14s} {'holdout高-低(pp)':>16s}  判定")
    for s in sires:
        row = []
        ok = True
        for w in (tr, ho):
            hi = csv_data.resid_z(w[(w['sire'] == s) & (w['cushion'] >= 9.5)], base)
            lo = csv_data.resid_z(w[(w['sire'] == s) & (w['cushion'] <= 9.4)], base)
            if hi is None or lo is None:
                row.append(None)
                ok = False
                continue
            row.append(((hi[0] - hi[1]) - (lo[0] - lo[1])) * 100)
        t_c = f"{row[0]:+6.1f}" if row[0] is not None else '  n/a'
        h_c = f"{row[1]:+6.1f}" if row[1] is not None else '  n/a'
        verdict = ''
        if ok and row[0] is not None and row[1] is not None:
            same_sign = (row[0] > 0) == (row[1] > 0)
            big = abs(row[0]) >= 2.0 and abs(row[1]) >= 2.0
            verdict = '★両窓一致' if (same_sign and big) else ('~符号一致' if same_sign else '✗崩落')
        print(f"  {s:<10s} {t_c:>14s} {h_c:>16s}  {verdict}")

    # ── C. クッション遷移(前走→今走)×前走末脚上位 ──
    print("\n【C】クッション遷移×末脚top3(レース内spurt_idx上位3頭・検証済み定義)")
    print("     資料の主張: 前走標準→今走硬め×前走上がり上位=激走")
    d2 = df.sort_values(['ketto_num', 'day']).copy()
    d2['prev_cushion'] = d2.groupby('ketto_num')['cushion'].shift(1)
    d2['prev_band'] = d2['prev_cushion'].map(band)
    d2['spurt_rank'] = d2.groupby('race_key')['spurt_idx'].rank(ascending=False, method='min')
    d2['spurt_top3'] = d2['spurt_rank'] <= 3
    trans = [('標準(8-10)', 'やや硬(10-11)', '標準→やや硬'),
             ('標準(8-10)', '硬(11+)', '標準→硬'),
             ('軟(<8)', 'やや硬(10-11)', '軟→やや硬'),
             ('やや硬(10-11)', '標準(8-10)', 'やや硬→標準'),
             ('やや硬(10-11)', '軟(<8)', '硬→軟')]
    for per_lbl, w0 in (('train', tr), ('holdout', ho)):
        w = d2[d2.index.isin(w0.index)]
        print(f"  --- {per_lbl} ---")
        for pb, nb, lbl in trans:
            sub = w[(w['prev_band'] == pb) & (w['band'] == nb) & w['spurt_top3']]
            print(f"   {lbl:12s}×末脚top3: {fmt(csv_data.resid_z(sub, base))}")
        # 対照: 遷移だけ(末脚不問)
        sub_all = w[(w['prev_band'] == '標準(8-10)') & (w['band'].isin(['やや硬(10-11)', '硬(11+)']))]
        print(f"   標準→硬系(末脚不問・対照): {fmt(csv_data.resid_z(sub_all, base))}")

    # C-2: 人気帯別(妙味は人気薄限定が通例)
    print("\n【C-2】標準→硬系×末脚top3 を人気帯で分割")
    for per_lbl, w0 in (('train', tr), ('holdout', ho)):
        w = d2[d2.index.isin(w0.index)]
        cond = (w['prev_band'] == '標準(8-10)') & \
               (w['band'].isin(['やや硬(10-11)', '硬(11+)'])) & w['spurt_top3']
        for pmin, pmax, plbl in ((1, 3, '1-3人気'), (4, 6, '4-6人気'), (7, 99, '7人気-')):
            sub = w[cond & (w['ninki'] >= pmin) & (w['ninki'] <= pmax)]
            print(f"  {per_lbl:8s} {plbl:8s}: {fmt(csv_data.resid_z(sub, base))}")


if __name__ == '__main__':
    main()
