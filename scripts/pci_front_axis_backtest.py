# -*- coding: utf-8 -*-
"""ユーザー仮説の検証: 『フィールド平均PCIに近い × 本物の先行 × 軸候補』は入着しやすいか。

背景: PCI単体は軸/相手/消しのいずれもエッジ無しで再提案打ち切り([[verified_pci_pricedin]])。
      脚質単体も人気に織込み済み([[verified_legtype_axis]])。
      ただし本仮説は『PCI乖離が小さい(=フィールドの流れに嵌る) かつ 本物の先行 かつ 軸候補』
      という**交差**であり、単体検証では潰せていない。安いので測る。

定義(アプリ実装と一致させる):
  PCI       = (走破タイム − 上がり3F) ÷ (距離/200 − 3) × 3 ÷ 上がり3F × 100 − 50
              (core/race_analysis_tools.PCICalculator.calculate_pci)
  事前平均PCI = 当該レースより前の直近5走のPCI平均(リークなし)
  フィールド平均PCI = そのレースの出走馬の事前平均PCIの平均
  PCI乖離   = 事前平均PCI − フィールド平均PCI  (elim_crossは|乖離|>=6.0を弱フラグにしている)
  本物の先行 = 直近3走の平均通過位置比率 pos_ratio3 < 0.28 (core/calculator.front_threshold)
  軸候補     = 1〜5番人気

評価: オッズ20分位で統制した複勝率残差。人気に織込み済みなら残差≈0。
      train(〜2024)/holdout(2025-)の両窓で|z|>=2のときのみ採用。
"""
import io
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from core.jockey_jv import JV_DB_PATH

HOLD = 20250101
FRONT = 0.28        # 本物の先行(短距離基準・アプリのfront_threshold)
NEAR = 2.0          # 「フィールド平均PCIに近い」= |乖離| がこの値未満


def build():
    con = sqlite3.connect(JV_DB_PATH)
    r = pd.read_sql("SELECT race_key, ketto_num, chakujun, ninki, win_odds, time, ato3f "
                    "FROM results WHERE chakujun>0", con)
    q = pd.read_sql("SELECT race_key, kyori FROM races", con)
    r = r.merge(q, on='race_key', how='left')
    for c in ('time', 'ato3f', 'kyori', 'win_odds', 'ninki'):
        r[c] = pd.to_numeric(r[c], errors='coerce')
    # ★results.time は MSSt 形式(例 1377 = 1分37秒7)。1/10秒の通し値ではないので分を展開する。
    t = (r['time'] // 1000) * 60.0 + (r['time'] % 1000) / 10.0
    a = r['ato3f'] / 10.0                       # 上がり3Fは 1/10秒(例 381 = 38.1秒)
    fb = (r['kyori'] / 200.0) - 3.0
    r['pci'] = np.where((a > 0) & (fb > 0), (t - a) / fb * 3.0 / a * 100.0 - 50.0, np.nan)
    r.loc[(r['pci'] < 20) | (r['pci'] > 90), 'pci'] = np.nan     # 異常値除去

    r = r.sort_values(['ketto_num', 'race_key'])
    g = r.groupby('ketto_num')['pci']
    # 事前平均PCI = 過去5走の平均(shiftでリーク遮断)
    r['pre_pci'] = (g.shift(1).groupby(r['ketto_num'])
                    .rolling(5, min_periods=2).mean().reset_index(level=0, drop=True))
    # フィールド平均PCI = レース内の事前平均PCIの平均 → 乖離
    r['field_pci'] = r.groupby('race_key')['pre_pci'].transform('mean')
    r['pci_dev'] = r['pre_pci'] - r['field_pci']

    r['day'] = r['race_key'].astype(str).str[:8].astype(int)
    r['top3'] = (r.chakujun <= 3).astype(int)

    # 位置取り(本物の先行)はCSV特徴ストアの pos_ratio3 を使う(leak-free既済)
    csv = pd.read_csv('data/export/horse_races.csv',
                      usecols=['race_key', 'ketto_num', 'pos_ratio3', 'combo', 'elim_n'])
    for c in ('race_key', 'ketto_num'):          # DB=TEXT / CSV=int になるため型を揃える
        r[c] = r[c].astype(str)
        csv[c] = csv[c].astype(str)
    r = r.merge(csv, on=['race_key', 'ketto_num'], how='inner')
    r = r[(r.win_odds > 0) & (r.ninki > 0)].dropna(subset=['pci_dev', 'pos_ratio3'])
    return r


def resid(d):
    d = d.copy()
    d['obin'] = pd.qcut(d['win_odds'], 20, labels=False, duplicates='drop')
    d['resid'] = d['top3'] - d.groupby('obin')['top3'].transform('mean')
    return d


def rep(name, mask, d, indent=''):
    print(f"\n{indent}■ {name}")
    for tag, sub in (('train', d[d.day < HOLD]), ('holdout', d[d.day >= HOLD])):
        h = sub[mask.reindex(sub.index).fillna(False)]
        if len(h) < 200:
            print(f"{indent}   {tag:8s} 標本不足 n={len(h)}")
            continue
        rr = h['resid']
        z = rr.mean() / (rr.std() / np.sqrt(len(rr)))
        print(f"{indent}   {tag:8s} n={len(h):6d}  複勝率{h['top3'].mean()*100:5.1f}%"
              f"  残差 {rr.mean()*100:+5.2f}pp  z={z:+5.2f} {'★' if abs(z) >= 2 else ''}")


def main():
    d = build()
    print(f"母集団(PCI・位置取りが揃う出走): {len(d):,}行")
    fav = resid(d[d.ninki <= 5])       # 軸候補帯
    print(f"軸候補帯(1-5番人気): {len(fav):,}行"
          f"  / train {len(fav[fav.day < HOLD]):,} / holdout {len(fav[fav.day >= HOLD]):,}")
    print("残差 = 複勝率 − 同オッズ帯の平均複勝率。プラス=市場より走る。\n"
          "※単体のPCI/脚質は検証済みでエッジ無し。ここで見るのは『交差』に上乗せがあるか。")

    near = fav['pci_dev'].abs() < NEAR          # フィールド平均PCIに近い
    front = fav['pos_ratio3'] < FRONT           # 本物の先行

    print("\n────── 分解(軸候補帯の中で) ──────")
    rep(f"A フィールド平均PCIに近い(|乖離|<{NEAR})だけ", near, fav)
    rep(f"B 本物の先行(位置比率<{FRONT})だけ", front, fav)
    rep("C 【仮説】近いPCI × 本物の先行", near & front, fav)
    rep("C' 参考: 遠いPCI(|乖離|>=6) × 本物の先行", (fav['pci_dev'].abs() >= 6.0) & front, fav)

    print("\n────── さらに『複数条件クリア』を重ねる ──────")
    rep("D 仮説 × 好材料の重複あり(combo>=1)", near & front & (fav['combo'] >= 1), fav)
    rep("E 仮説 × 来にくさフラグなし(elim_n==0)", near & front & (fav['elim_n'] == 0), fav)
    rep("F 仮説 × combo>=1 × elim_n==0(全部クリア=ユーザーの言う理想形)",
        near & front & (fav['combo'] >= 1) & (fav['elim_n'] == 0), fav)

    print("\n────── 『近い』の閾値を振ってみる(ノイズでないかの確認) ──────")
    for th in (1.0, 2.0, 3.0, 4.0):
        rep(f"|乖離|<{th} × 本物の先行", (fav['pci_dev'].abs() < th) & front, fav, indent='  ')


if __name__ == '__main__':
    main()
