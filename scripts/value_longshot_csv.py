# -*- coding: utf-8 -*-
"""value_longshot_research.py のCSV版(実証: 分→秒)。

DB版(scripts/value_longshot_research.py)は各馬ごとにlap33/騎手力/補正Tを再計算して~3分。
本CSV版は data/export/horse_races.csv の precomputed combo/top3/ninki から同じ集計を数秒で出す。
既知のDB版の数値(train base 7.7% / combo0=4.1%→combo4=18.8%)と一致すれば、CSVと
ローダー(scripts/csv_data.py)の妥当性＝『DB→CSV→分析』への置換が正しいことの実証になる。
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd


def main():
    t0 = time.time()
    # 7番人気以下・combo/top3/ninki だけ読む(列を絞ると更に速い)
    df = cd.load_horses(pop_min=7, cols=['race_key', 'day', 'ninki', 'combo', 'top3', 'h7_rank'])
    # comboは2024+・7番人気以下のみ付与(export仕様)。combo欠損行=対象外。
    df = df[df['combo'].notna()]
    t_load = time.time() - t0
    print(f"CSVロード+絞り込み {len(df):,}行 / {t_load:.2f}秒")

    for period in ('train', 'recent'):
        sub = df[df['period'] == period]
        if len(sub) < 100:
            continue
        base = sub['top3'].mean()
        print(f"\n=== {period}  7番人気以下 ベース3着内率 {base:.1%} (n={len(sub):,}) ===")
        print("[combo別 3着内率] (DB版: 0=4.1/1=7.2/2=9.9/3=13.1/4=18.8%)")
        for c in range(0, 6):
            g = sub[sub['combo'] == c]
            if len(g) >= 20:
                print(f"  combo={c}  n={len(g):6d}  3着内 {g['top3'].mean():6.1%}  (基準比{(g['top3'].mean()-base)*100:+.1f}pp)")
        for thr in (2, 3):
            g = sub[sub['combo'] >= thr]
            if len(g) >= 20:
                rec = g['top3'].sum() / sub['top3'].sum()
                print(f"  combo≥{thr}: 3着内 {g['top3'].mean():6.1%} 再現率 {rec:.1%} (捕捉 {int(g['top3'].sum())}頭)")
        # 補正T top3(h7_rank<=3)の単体リフト
        h = sub[sub['h7_rank'] <= 3]
        if len(h) >= 20:
            print(f"  [参考]補正T top3: n={len(h)} 3着内 {h['top3'].mean():.1%} (基準比{(h['top3'].mean()-base)*100:+.1f}pp)")

    print(f"\n総実行 {time.time()-t0:.2f}秒 (DB版は約180秒) ＝ CSV化で桁違いに高速")


if __name__ == '__main__':
    main()
