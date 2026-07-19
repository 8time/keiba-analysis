# -*- coding: utf-8 -*-
"""動画『軸馬の選び方』の主張検証: トラック変更(前走→今走の芝/ダ)は軸エッジか?
特に「ダート→芝は単勝回収88%」。

生の単勝ROIは市場効率的で全帯<100%(FLBの再検出)なので、ここでは
人気補正した勝率/複勝率の残差で「人気を超えるエッジか」を厳密に見る。

設計(リーク無し):
  DBで各馬の直前走surfaceを取得→(前走surface→今走surface)を4分類:
    ダ→芝 / 芝→ダ / 芝→芝 / ダ→ダ。
  CSV(ninki/win/top3)と(race_key,umaban)で結合。
  train(〜2023)で ninki別 win/top3 ベースを凍結、holdout(2024)/2025で
  各トラック変更カテゴリの残差(実績−ninki期待)。
  残差>0でz>=2一貫なら人気超えエッジ。z≈0なら生ROI差はpriced-in。

使い方: python scripts/track_change_backtest.py
"""
import os
import sys
import sqlite3
import math
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
TRAIN_END = 2023


def main():
    print("DB読み込み(surface履歴)...")
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        """SELECT r.race_key, r.umaban, r.ketto_num, ra.year, ra.monthday, ra.surface
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND r.chakujun>0
             AND ra.surface IN ('芝','ダート')""").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    # 馬ごと日付順→直前走surface
    by_horse = defaultdict(list)
    for rk, um, kt, y, md, sf in rows:
        dk = int(y) * 10000 + int(md)
        by_horse[kt].append((dk, rk, int(um), sf))
    prev_surf = {}   # (race_key, umaban) -> 前走surface
    for kt, lst in by_horse.items():
        lst.sort(key=lambda z: z[0])
        for i in range(1, len(lst)):
            _, rk, um, _ = lst[i]
            prev_surf[(str(rk), um)] = lst[i - 1][3]

    print("CSV結合(ninki/win/top3)...")
    df = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win', 'top3'])
    df = df[df['ninki'].notna()]

    # サンプル: (year, ninki, cat, win, top3)
    cur_surf = {}
    for rk, um, kt, y, md, sf in rows:
        cur_surf[(str(rk), int(um))] = sf
    samples = []
    for r in df.itertuples(index=False):
        key = (str(int(r.race_key)), int(r.umaban))
        ps = prev_surf.get(key)
        cs = cur_surf.get(key)
        if not ps or not cs:
            continue
        cat = ('ダ→芝' if ps == 'ダート' and cs == '芝' else
               '芝→ダ' if ps == '芝' and cs == 'ダート' else
               '芝→芝' if ps == '芝' and cs == '芝' else 'ダ→ダ')
        yr = int(str(int(r.race_key))[:4])
        samples.append((yr, int(r.ninki), cat, int(r.win), int(r.top3)))
    print(f"  結合サンプル: {len(samples):,}\n")

    # train凍結 ninki別ベース
    tr = [s for s in samples if s[0] <= TRAIN_END]
    bw = defaultdict(lambda: [0, 0]); bt = defaultdict(lambda: [0, 0])
    for (_, nk, _, w, t3) in tr:
        bw[nk][0] += w; bw[nk][1] += 1
        bt[nk][0] += t3; bt[nk][1] += 1
    win_base = {nk: v[0] / v[1] for nk, v in bw.items() if v[1] >= 30}
    top3_base = {nk: v[0] / v[1] for nk, v in bt.items() if v[1] >= 30}

    def analyze(period_name, yr_pred):
        # cat -> [sum_wres, sum_tres, n]
        cell = defaultdict(lambda: [0.0, 0.0, 0])
        for (yr, nk, cat, w, t3) in samples:
            if not yr_pred(yr):
                continue
            wb = win_base.get(nk); tb = top3_base.get(nk)
            if wb is None or tb is None:
                continue
            c = cell[cat]
            c[0] += (w - wb); c[1] += (t3 - tb); c[2] += 1
        print(f"  === {period_name} (残差=実績−人気別期待) ===")
        print(f"  {'トラック変更':>8} | {'n':>7} | {'勝利残差':>9} {'z':>6} | {'複勝残差':>9} {'z':>6}")
        for cat in ('ダ→芝', '芝→ダ', '芝→芝', 'ダ→ダ'):
            sw, st, n = cell[cat]
            if n < 30:
                print(f"  {cat:>8} | {n:>7} | 標本不足")
                continue
            mw, mt = sw / n, st / n
            zw = mw / (0.28 / math.sqrt(n))   # 勝率sd目安~0.28(base~0.09)
            zt = mt / (0.42 / math.sqrt(n))   # 複勝sd目安~0.42
            print(f"  {cat:>8} | {n:>7,} | {mw:>+9.4f} {zw:>+6.2f} | {mt:>+9.4f} {zt:>+6.2f}")
        print()

    for nm, yp in (('holdout(2024)', lambda y: y == 2024), ('2025+', lambda y: y >= 2025)):
        analyze(nm, yp)

    print("読み方: ダ→芝の勝利/複勝残差が >0 で z>=2 両期間一貫なら人気を超えるエッジ。")
    print("  z≈0なら動画の生ROI88%は市場効率(FLB)の見かけ=priced-in。")


if __name__ == '__main__':
    main()
