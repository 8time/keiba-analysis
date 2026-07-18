# -*- coding: utf-8 -*-
"""調教『加速ラップ』の検証 — 最終追い切りでラスト1Fが加速しているか。

資料(『データ駆動型・競馬予想の極意』)の主張:
  「勝ち馬の50%以上が最終追い切りで加速ラップを記録」「ラスト1Fが12秒台前半なら軸」
  「13秒台での失速は加速ラップでも信頼度が著しく低下」

データ: jravan.db の training テーブル(50万件・当初『調教時計は無い』と誤認していたが実在した)。
  t4f/t3f/t2f = 4F/3F/2Fの累計タイム、lap_86/lap_64/lap_42/lap_20 = 各200m区間のラップ。
  すべて 1/10秒単位(例: 171 = 17.1秒)。lap_20 = ラスト1F。

定義:
  加速量 accel = lap_42 - lap_20   … 正なら『ラスト1Fが直前1Fより速い』= 加速ラップ
  加速フラグ  = accel > 0
  最終追い切り = レース当日より前で最も近い調教(14日以内・全区間>0の有効行)

評価: 単体の複勝率ではなく『オッズ20分位で統制した残差』。人気に織込み済みなら残差≈0になる。
      train(〜2024) / holdout(2025-) の両方で有意なものだけ採用する。
リーク: 調教はレース前に確定する事前情報。cho_date < race day で厳格に絞る。
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
MAX_DAYS = 14        # 最終追い切りとみなす最大日数(レース前)


def load():
    con = sqlite3.connect(JV_DB_PATH)
    res = pd.read_sql(
        "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.win_odds "
        "FROM results r WHERE r.chakujun>0 AND r.ninki>0 AND r.win_odds>0", con)
    res['day'] = res['race_key'].astype(str).str[:8].astype(int)
    res['top3'] = (res.chakujun <= 3).astype(int)

    tr = pd.read_sql(
        "SELECT ketto_num, cho_date, t4f, t3f, t2f, lap_42, lap_20 "
        "FROM training WHERE lap_20>0 AND lap_42>0", con)
    tr['cho_date'] = pd.to_numeric(tr['cho_date'], errors='coerce')
    tr = tr.dropna(subset=['cho_date'])
    tr['cho_date'] = tr['cho_date'].astype(int)
    print(f"出走: {len(res):,}行 / 有効な調教: {len(tr):,}行")

    # 各出走に『直前の追い切り』を紐づける(merge_asof: 同一馬・レース日より前で最も近い)
    res = res.sort_values('day')
    tr = tr.sort_values('cho_date')
    m = pd.merge_asof(res, tr, left_on='day', right_on='cho_date', by='ketto_num',
                      direction='backward', allow_exact_matches=False)
    m['gap'] = m['day'] - m['cho_date']
    m = m[(m['gap'] >= 0) & (m['gap'] <= MAX_DAYS)].copy()
    print(f"最終追い切りが紐づいた出走: {len(m):,}行 ({len(m)/len(res)*100:.1f}%)")
    return m


def add_resid(d):
    d = d.copy()
    d['obin'] = pd.qcut(d['win_odds'], 20, labels=False, duplicates='drop')
    d['resid'] = d['top3'] - d.groupby('obin')['top3'].transform('mean')
    return d


def report(name, mask, d):
    print(f"\n■ {name}")
    for tag, sub in (('train', d[d.day < HOLD]), ('holdout', d[d.day >= HOLD])):
        h = sub[mask.reindex(sub.index).fillna(False)]
        if len(h) < 300:
            print(f"   {tag:8s} 標本不足 n={len(h)}")
            continue
        r = h['resid']
        z = r.mean() / (r.std() / np.sqrt(len(r)))
        star = '★' if abs(z) >= 2 else ''
        print(f"   {tag:8s} n={len(h):7d}  複勝率{h['top3'].mean()*100:5.1f}%"
              f"  残差 {r.mean()*100:+5.2f}pp  z={z:+5.2f} {star}")


def main():
    d = load()
    d['accel'] = (d['lap_42'] - d['lap_20']) / 10.0      # 正=加速(ラスト1Fが速い)
    d['last1f'] = d['lap_20'] / 10.0
    print(f"\n加速ラップの発生率: {(d['accel'] > 0).mean()*100:.1f}%"
          f"  / ラスト1F中央値 {d['last1f'].median():.1f}秒")

    d = add_resid(d)
    print("\n残差 = 複勝率 − 同オッズ帯の平均複勝率。プラス=市場より走る＝妙味。")

    report("① 加速ラップ(ラスト1Fが直前1Fより速い) 全馬", d['accel'] > 0, d)
    report("② 強い加速(0.5秒以上速い) 全馬", d['accel'] >= 0.5, d)
    report("③ 失速ラップ(ラスト1Fが0.5秒以上遅い) 全馬", d['accel'] <= -0.5, d)
    report("④ 資料の主張: ラスト1F 12秒台前半(12.5秒以下)", d['last1f'] <= 12.5, d)
    report("⑤ 資料の主張: 加速 かつ ラスト1F 12.5秒以下(最高評価)",
           (d['accel'] > 0) & (d['last1f'] <= 12.5), d)
    report("⑥ 資料の主張: 13秒台での失速(信頼度低下)",
           (d['accel'] <= 0) & (d['last1f'] >= 13.0), d)

    print("\n────── 人気帯で分ける(軸=1-5番人気 / 妙味=6番人気以下) ──────")
    fav = d[d.ninki <= 5]
    ana = d[d.ninki >= 6]
    for lbl, sub in (('軸候補帯(1-5番人気)', fav), ('人気薄帯(6番人気以下)', ana)):
        sub = add_resid(sub)
        print(f"\n【{lbl}】")
        report("  加速ラップ", sub['accel'] > 0, sub)
        report("  強い加速(0.5秒+)", sub['accel'] >= 0.5, sub)
        report("  加速 かつ ラスト1F 12.5秒以下", (sub['accel'] > 0) & (sub['last1f'] <= 12.5), sub)


if __name__ == '__main__':
    main()
