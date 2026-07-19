# -*- coding: utf-8 -*-
"""『その馬の得意なレース距離』は人気を超えて効くか? の検証(ロジック置き場より)。

ユーザー仮説: そのレース距離での過去3着内実績が高い馬は来やすいのでは。

設計(リーク無し):
  各馬の過去走(その日より前のみ)から2種の事前3着内率を算出:
    - prior_band = 同じ距離帯での過去3着内率
    - prior_all  = 全距離での過去3着内率(その馬の総合力の代理)
  距離適性(affinity) = prior_band − prior_all
    = 「この馬が"この距離帯だけ"どれだけ上振れ/下振れするか」(総合力を差し引き)。
  これで『距離が得意/苦手』を一般的な強さと切り分ける。

  train(〜2023)で ninki→top3ベースと affinity 三分位しきい値を凍結。
  holdout(2024)/2025 で affinity 高群/低群の「人気補正残差」を比較。
    残差 = 実3着内 − ninki別期待(train凍結)。
  仮説が正なら: affinity高群の残差 − 低群の残差 = D が正・z>=2で一貫。
  ゼロ近傍なら: 距離適性は人気に織込み済み(priced-in)=脚質/PCIと同型。

距離帯: 短≤1400 / マイル1401-1800 / 中1801-2200 / 長2201+。
使い方: python scripts/distance_affinity_backtest.py
"""
import os
import sys
import math
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd

TRAIN_END = 2023
MIN_BAND = 2   # 同距離帯の過去走 最低数
MIN_ALL = 3    # 全体の過去走 最低数


def band_of(k):
    if k <= 1400:
        return 'S'
    if k <= 1800:
        return 'M'
    if k <= 2200:
        return 'I'
    return 'L'


def main():
    print("CSV特徴ストア読み込み...")
    df = cd.load_horses(cols=['race_key', 'day', 'kyori_int', 'ketto_num',
                              'ninki', 'top3'])
    df = df[df['ninki'].notna() & df['ketto_num'].notna() & df['kyori_int'].notna()]
    print(f"  {len(df):,}行")

    # 馬ごと・日付順に走査し、走行前の事前率を読む(=過去のみ=リーク無し)
    rows = df.itertuples(index=False)
    rows = sorted(rows, key=lambda r: (int(r.ketto_num), int(r.day)))

    # 各馬の累積: band別[top3,n] と 全体[top3,n]
    band_acc = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    all_acc = defaultdict(lambda: [0, 0])

    samples = []  # (year, ninki, affinity, top3)
    for r in rows:
        kt = int(r.ketto_num)
        b = band_of(int(r.kyori_int))
        t3 = int(r.top3)
        # --- 走行前(=これまでの過去)の事前率を先に読む ---
        ba = band_acc[kt][b]
        aa = all_acc[kt]
        if ba[1] >= MIN_BAND and aa[1] >= MIN_ALL:
            prior_band = ba[0] / ba[1]
            prior_all = aa[0] / aa[1]
            affinity = prior_band - prior_all
            yr = int(str(int(r.race_key))[:4])
            samples.append((yr, int(r.ninki), affinity, t3))
        # --- そのあとで現走を累積に加える ---
        ba[0] += t3; ba[1] += 1
        aa[0] += t3; aa[1] += 1

    print(f"  事前距離適性の付いたサンプル: {len(samples):,}\n")

    # train凍結: ninki→top3ベース と affinity三分位
    tr = [s for s in samples if s[0] <= TRAIN_END]
    base = defaultdict(lambda: [0, 0])
    affs = []
    for (_, nk, af, t3) in tr:
        base[nk][0] += t3; base[nk][1] += 1
        affs.append(af)
    ninki_base = {nk: v[0] / v[1] for nk, v in base.items() if v[1] >= 30}
    affs.sort()
    q1 = affs[len(affs) // 3]
    q2 = affs[2 * len(affs) // 3]
    print(f"  affinity三分位(train凍結): 低<{q1:+.3f} / 中 / 高>{q2:+.3f}")
    print(f"  (affinity=同距離帯top3率−全体top3率。正=この距離が総合力より得意)\n")

    def resid(nk, t3):
        b = ninki_base.get(nk)
        return None if b is None else (t3 - b)

    def analyze(period_name, yr_pred, ninki_filter=None):
        cell = defaultdict(lambda: [0.0, 0])  # 'lo'/'mid'/'hi' -> [sum_resid, n]
        for (yr, nk, af, t3) in samples:
            if not yr_pred(yr):
                continue
            if ninki_filter and not ninki_filter(nk):
                continue
            rz = resid(nk, t3)
            if rz is None:
                continue
            grp = 'lo' if af < q1 else ('hi' if af > q2 else 'mid')
            cell[grp][0] += rz; cell[grp][1] += 1
        sh, nh = cell['hi']; sl, nl = cell['lo']; sm, nm = cell['mid']
        tag = '（6番人気以下）' if ninki_filter else '（全人気）'
        print(f"  === {period_name}{tag} ===")
        for g, (s, n) in (('得意(hi)', cell['hi']), ('中(mid)', cell['mid']), ('苦手(lo)', cell['lo'])):
            m = (s / n) if n else 0.0
            print(f"    {g:>9}: n={n:>7,}  残差={m:>+.4f}")
        if nh >= 30 and nl >= 30:
            d = sh / nh - sl / nl
            se = 0.42 * math.sqrt(1.0 / nh + 1.0 / nl)
            z = d / se if se else 0.0
            print(f"    → 得意−苦手 D={d:+.4f}  z={z:+.2f}")
        print()

    for nm, yp in (('holdout(2024)', lambda y: y == 2024), ('2025+', lambda y: y >= 2025)):
        analyze(nm, yp)
    print("── 穴馬(6番人気以下)限定 ──")
    for nm, yp in (('holdout(2024)', lambda y: y == 2024), ('2025+', lambda y: y >= 2025)):
        analyze(nm, yp, ninki_filter=lambda nk: nk >= 6)

    print("読み方: 得意群と苦手群の『人気補正残差』の差D。")
    print("  D>0でz>=2が両期間一貫なら距離適性は人気を超えるエッジ。")
    print("  z≈0なら距離適性は人気に織込み済み(priced-in)=脚質/PCIと同型。")


if __name__ == '__main__':
    main()
