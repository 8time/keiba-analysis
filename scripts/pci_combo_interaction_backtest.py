# -*- coding: utf-8 -*-
"""PCIは『他の弱い/検証済みシグナルが重なった時だけ』要因になるか? の検証。

ユーザー仮説: 単体では要因になりえないもの(PCI)も、複数重なれば要因になるのでは?
  (comboがまさにその発想=検証済みシグナルの同時発火数)。

問い: PCIの主効果はゼロ(verified_pci_pricedin)だが、combo水準で層別すると、
      高combo馬の中ではPCI高低が3着内率に効く(交互作用)ということはないか?

設計(リーク無し):
  - PCI = 各馬の直近5走(芝)の平均prior_avg_pci(そのレース以前のみ=リーク無し)。
    DBのtime/ato3f/kyoriからpci_of()で算出(pci_course_shape_backtestと同一公式)。
  - combo/ninki/top3/period = CSV特徴ストア(leak-free済)。(race_key,umaban)で結合。
  - train(〜2023)でPCIの高/低しきい値(中央値)と ninki→top3ベースを凍結。
  - holdout(2024)と2025(other)で、combo層(0 / 1 / 2+)ごとに
    「PCI高群の残差 − PCI低群の残差」の差 D と z を出す。
    残差 = 実3着内 − ninki別期待(train凍結)。
  仮説が正なら: 高combo層(2+)で D の z>=2(PCI高低が効く)。
  ゼロ近傍なら: 「重なっても効かない=priced-inは層別でも不変」と記録。

使い方: python scripts/pci_combo_interaction_backtest.py
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
MIN_PCI_RUNS = 3
TRAIN_END = 2023   # 〜2023=train / 2024=holdout / 2025+=other


def t_sec(s):
    s = ''.join(ch for ch in str(s) if ch.isdigit())
    if not s:
        return None
    return int(s) / 10.0 if len(s) <= 3 else int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def pci_of(time, ato3f, kyori):
    t = t_sec(time)
    if t is None or not ato3f or not kyori:
        return None
    a = ato3f / 10.0
    d = float(kyori)
    if a <= 0 or d <= 600:
        return None
    fb = d / 200.0 - 3.0
    if fb <= 0:
        return None
    p = (t - a) / fb * 3.0 / a * 100.0 - 50.0
    return p if 20.0 <= p <= 100.0 else None


def main():
    print("DB読み込み(芝・PCI算出用)...")
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        """SELECT ra.year, ra.monthday, r.race_key, r.umaban, r.ketto_num,
                  r.time, r.ato3f, ra.kyori
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE CAST(ra.year AS INTEGER) >= 2015 AND ra.jyo BETWEEN '01' AND '10'
             AND ra.surface='芝' AND r.chakujun>0""").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    # 馬ごとPCI履歴(日付順)→ prior_avg_pci(そのレース以前の直近5走)
    hist = defaultdict(list)
    for (y, md, rk, um, kt, tm, a3, ki) in rows:
        dk = int(y) * 10000 + int(md)
        hist[kt].append((dk, pci_of(tm, a3, ki)))
    for k in hist:
        hist[k].sort(key=lambda z: z[0])

    def prior_pci(kt, dk):
        ps = [p for (d, p) in hist.get(kt, []) if d < dk and p is not None][-5:]
        return (sum(ps) / len(ps)) if len(ps) >= MIN_PCI_RUNS else None

    # (race_key,umaban) -> prior_avg_pci
    pci_map = {}
    for (y, md, rk, um, kt, tm, a3, ki) in rows:
        dk = int(y) * 10000 + int(md)
        ap = prior_pci(kt, dk)
        if ap is not None:
            pci_map[(str(rk), int(um))] = ap
    print(f"  prior_avg_pci 確定: {len(pci_map):,}頭レース")

    print("CSV特徴ストア読み込み(combo/ninki/top3)...")
    df = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'combo', 'top3'])
    df = df[df['ninki'].notna() & df['umaban'].notna()]

    # 結合してサンプル化
    samples = []  # (period, ninki, combo, pci, top3)
    for r in df.itertuples(index=False):
        key = (str(int(r.race_key)), int(r.umaban))
        pci = pci_map.get(key)
        if pci is None:
            continue
        yr = int(str(int(r.race_key))[:4])  # race_keyの先頭4桁=年
        period = 'train' if yr <= TRAIN_END else ('holdout' if yr == TRAIN_END + 1 else 'other')
        _cb = 0 if (r.combo is None or r.combo != r.combo) else int(r.combo)  # NaN→0
        samples.append((period, int(r.ninki), _cb, pci, int(r.top3)))
    print(f"  結合サンプル: {len(samples):,}")

    # train凍結: ninki別top3ベース と PCI中央値
    tr = [s for s in samples if s[0] == 'train']
    base = defaultdict(lambda: [0, 0])
    pci_vals = []
    for (_, nk, cb, pci, t3) in tr:
        base[nk][0] += t3
        base[nk][1] += 1
        pci_vals.append(pci)
    ninki_base = {nk: (v[0] / v[1]) for nk, v in base.items() if v[1] >= 30}
    pci_vals.sort()
    pci_med = pci_vals[len(pci_vals) // 2]
    print(f"  PCI中央値(train凍結)= {pci_med:.1f}  / ninkiベース {len(ninki_base)}帯\n")

    def resid(nk, t3):
        b = ninki_base.get(nk)
        return None if b is None else (t3 - b)

    # combo層 × PCI高低 の残差(holdout/other)
    def analyze(period, ninki_filter=None):
        # cell[(combo_band, hi)] -> [sum_resid, n]
        cell = defaultdict(lambda: [0.0, 0])
        for (pp, nk, cb, pci, t3) in samples:
            if pp != period:
                continue
            if ninki_filter and not ninki_filter(nk):
                continue
            rz = resid(nk, t3)
            if rz is None:
                continue
            cbb = '0' if cb == 0 else ('1' if cb == 1 else '2+')
            hi = pci >= pci_med
            c = cell[(cbb, hi)]
            c[0] += rz
            c[1] += 1
        print(f"  === {period}{'（6番人気以下）' if ninki_filter else '（全人気）'} ===")
        print(f"  {'combo層':>7} | {'PCI高 n':>8} {'残差':>8} | {'PCI低 n':>8} {'残差':>8} | "
              f"{'差D(高-低)':>10} {'z':>6}")
        for cbb in ('0', '1', '2+'):
            sh, nh = cell[(cbb, True)]
            sl, nl = cell[(cbb, False)]
            if nh < 20 or nl < 20:
                print(f"  {cbb:>7} | {nh:>8} {'—':>8} | {nl:>8} {'—':>8} | {'標本不足':>10}")
                continue
            mh, ml = sh / nh, sl / nl
            d = mh - ml
            # 残差の標準偏差~0.42(0/1指標)で近似したzの目安
            se = 0.42 * math.sqrt(1.0 / nh + 1.0 / nl)
            z = d / se if se else 0.0
            print(f"  {cbb:>7} | {nh:>8,} {mh:>+8.4f} | {nl:>8,} {ml:>+8.4f} | "
                  f"{d:>+10.4f} {z:>+6.2f}")
        print()

    for pr in ('holdout', 'other'):
        analyze(pr)
    print("── 穴馬(6番人気以下)限定 ──")
    for pr in ('holdout', 'other'):
        analyze(pr, ninki_filter=lambda nk: nk >= 6)

    print("読み方: 各combo層で『PCI高群の残差 − PCI低群の残差』= D。")
    print("  仮説(重なれば効く)が正なら combo=2+ 層で D の z>=2(方向一貫)。")
    print("  全層で z≈0 なら『他シグナルが重なってもPCIは効かない=priced-inは層別でも不変』。")


if __name__ == '__main__':
    main()
