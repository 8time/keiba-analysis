# -*- coding: utf-8 -*-
"""新馬戦『早生まれが強い』は使えるか — 生まれ月シグナル検証

主張(動画):
  2歳戦は生まれ月が早いほど成績が良い（1月生まれ勝率11.3% vs 6月以降5.4%）。
  この情報はオッズにほとんど反映されない → 妙味がある。

設計(リーク無し・事前固定):
  対象 = 各馬の初出走(デビュー戦)。JRA場01-10、芝/ダート、障害(shubetsu18/19)除外。
  シグナル = horses.birth の生まれ月(1-12) / 月齢(レース日-生年月日)。
  比較 = 人気別の勝率・複勝率ベースライン(trainで凍結)からの残差。
         残差≈0なら市場織込み済み(priced-in)=妙味なし。
  分割 = train 〜2017 / holdout 2018-2022
         (horses.birth は2010-2022デビュー馬で100%カバー。2023年以降は欠損のため除外)
  指標 = 複勝残差(主)・勝率残差(副)・単勝ROI(参考)・z・bootstrap95%CI

使い方: python scripts/maiden_birth_month_backtest.py
"""
import os
import sys
import math
import random
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
TRAIN_END = 2017
HOLDOUT_END = 2022   # birthカバレッジ100%の最終年(2023: 76.6%, 2024: 8.5%のため除外)
YEAR_MIN = 2010


def zof(m, n, sd=0.42):
    return m / (sd / math.sqrt(n)) if n else 0.0


def months_between(race_ymd, birth_ymd):
    return ((race_ymd // 10000 - birth_ymd // 10000) * 12
            + (race_ymd // 100) % 100 - (birth_ymd // 100) % 100)


def birth_group(bm):
    if bm <= 3:
        return 'A:1-3月生まれ(早生まれ)'
    if bm == 4:
        return 'B:4月生まれ'
    if bm == 5:
        return 'C:5月生まれ'
    return 'D:6月以降(遅生まれ)'


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)

    print('=' * 84)
    print('■ データ監査')
    print('=' * 84)
    birth_of = {}
    for kt, b in con.execute(
            "SELECT ketto_num, birth FROM horses WHERE LENGTH(birth)>=8"):
        try:
            birth_of[str(kt)] = int(str(b))
        except ValueError:
            continue
    print(f'  birth あり馬 {len(birth_of):,}頭')

    rows = con.execute(
        "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.win_odds, "
        "       ra.year, ra.monthday "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート') "
        "AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ketto_num<>''"
    ).fetchall()
    con.close()
    print(f'  出走レコード {len(rows):,}件')

    # 馬ごと時系列 → デビュー戦
    by_horse = defaultdict(list)
    for rk, kt, ch, nk, wo, y, md in rows:
        by_horse[str(kt)].append((int(str(y) + str(md).zfill(4)), str(rk),
                                  int(ch), (int(nk) if nk else None),
                                  (float(wo) if wo else None), int(y)))
    samples = []
    for kt, lst in by_horse.items():
        lst.sort()
        day, rk, ch, nk, wo, y = lst[0]
        if y < YEAR_MIN or y > HOLDOUT_END:
            continue
        if nk is None:
            continue
        b = birth_of.get(kt)
        if b is None:
            continue
        bm = (b // 100) % 100
        if not 1 <= bm <= 12:
            continue
        samples.append(dict(y=y, day=day, ch=ch, nk=nk, wo=wo,
                            bm=bm, grp=birth_group(bm),
                            age_m=months_between(day, b)))
    print(f'  デビュー戦サンプル(birthあり・{YEAR_MIN}-{HOLDOUT_END}) {len(samples):,}頭')

    # ── ベースライン: 人気別 勝率/複勝率(train凍結) ──
    bw = defaultdict(lambda: [0, 0])
    bp = defaultdict(lambda: [0, 0])
    for s in samples:
        if s['y'] <= TRAIN_END:
            bw[s['nk']][0] += 1 if s['ch'] == 1 else 0
            bw[s['nk']][1] += 1
            bp[s['nk']][0] += 1 if s['ch'] <= 3 else 0
            bp[s['nk']][1] += 1
    TW = {k: v[0] / v[1] for k, v in bw.items() if v[1] >= 50}
    TP = {k: v[0] / v[1] for k, v in bp.items() if v[1] >= 50}

    def stat(keep, period):
        rs_p, rs_w, rois = [], [], []
        for s in samples:
            if not period(s) or not keep(s) or s['nk'] not in TP:
                continue
            rs_p.append((1 if s['ch'] <= 3 else 0) - TP[s['nk']])
            rs_w.append((1 if s['ch'] == 1 else 0) - TW[s['nk']])
            if s['wo']:
                rois.append(s['wo'] if s['ch'] == 1 else 0.0)
        n = len(rs_p)
        if n < 100:
            return None
        mp = sum(rs_p) / n
        mw = sum(rs_w) / n
        roi = sum(rois) / len(rois) * 100 if rois else None
        return (n, mp, zof(mp, n), mw, zof(mw, n, 0.35), roi)

    GROUPS = ['A:1-3月生まれ(早生まれ)', 'B:4月生まれ', 'C:5月生まれ', 'D:6月以降(遅生まれ)']
    PERIODS = [('train 〜2017', lambda s: s['y'] <= TRAIN_END),
               ('holdout 2018-2022', lambda s: TRAIN_END < s['y'] <= HOLDOUT_END)]

    print()
    print('=' * 84)
    print('■ 1. 生まれ月グループ別 — 人気統制後の残差（主結果）')
    print('=' * 84)
    for pl, pf in PERIODS:
        print(f'\n  === {pl} ===')
        print(f"  {'区分':<26}{'n':>8}{'複勝残差':>10}{'z':>7}{'勝率残差':>10}{'z':>7}{'単勝ROI':>9}")
        for g in GROUPS:
            r = stat(lambda s, gg=g: s['grp'] == gg, pf)
            if r is None:
                print(f'  {g:<26}{"標本不足":>8}')
                continue
            roi = f"{r[5]:>7.1f}%" if r[5] is not None else '      -'
            print(f'  {g:<26}{r[0]:>8,}{r[1]:>+10.4f}{r[2]:>+7.2f}'
                  f'{r[3]:>+10.4f}{r[4]:>+7.2f}{roi:>9}')

    print()
    print('=' * 84)
    print('■ 2. 生まれ月別の素の成績（参考・統制なし・holdout）')
    print('=' * 84)
    print(f"  {'月':>4}{'n':>8}{'勝率':>8}{'複勝率':>8}{'単勝ROI':>9}")
    for m in range(1, 13):
        sub = [s for s in samples if s['bm'] == m and TRAIN_END < s['y'] <= HOLDOUT_END]
        n = len(sub)
        if n < 100:
            continue
        w = sum(1 for s in sub if s['ch'] == 1) / n * 100
        p = sum(1 for s in sub if s['ch'] <= 3) / n * 100
        rois = [s['wo'] if s['ch'] == 1 else 0.0 for s in sub if s['wo']]
        roi = sum(rois) / len(rois) * 100 if rois else 0
        print(f'  {m:>3}月{n:>8,}{w:>7.1f}%{p:>7.1f}%{roi:>8.1f}%')

    print()
    print('=' * 84)
    print('■ 3. 月齢（デビュー時点の満月齢）四分位 — 人気統制後の残差（holdout）')
    print('=' * 84)
    ho = [s for s in samples if TRAIN_END < s['y'] <= HOLDOUT_END and s['nk'] in TP]
    ages = sorted(s['age_m'] for s in ho)
    q1, q2, q3 = ages[len(ages) // 4], ages[len(ages) // 2], ages[3 * len(ages) // 4]
    print(f'  四分位境界: {q1} / {q2} / {q3} ヶ月')
    QGROUPS = [(f'Q1 最若 〜{q1}ヶ月', lambda a: a <= q1),
               (f'Q2 {q1 + 1}-{q2}ヶ月', lambda a: q1 < a <= q2),
               (f'Q3 {q2 + 1}-{q3}ヶ月', lambda a: q2 < a <= q3),
               (f'Q4 最長 {q3 + 1}ヶ月〜', lambda a: a > q3)]
    print(f"  {'区分':<22}{'n':>8}{'複勝残差':>10}{'z':>7}{'単勝ROI':>9}")
    for lbl, qf in QGROUPS:
        r = stat(lambda s, f=qf: f(s['age_m']), lambda s: TRAIN_END < s['y'] <= HOLDOUT_END)
        if r is None:
            continue
        roi = f"{r[5]:>7.1f}%" if r[5] is not None else '      -'
        print(f'  {lbl:<22}{r[0]:>8,}{r[1]:>+10.4f}{r[2]:>+7.2f}{roi:>9}')

    print()
    print('=' * 84)
    print('■ 4. bootstrap 95%CI（A:1-3月生まれ・holdout・複勝残差）')
    print('=' * 84)
    rs = [(1 if s['ch'] <= 3 else 0) - TP[s['nk']]
          for s in ho if s['grp'] == GROUPS[0]]
    n = len(rs)
    if n >= 200:
        random.seed(42)
        bs = sorted(sum(rs[random.randrange(n)] for _ in range(n)) / n
                    for _ in range(2000))
        pt = sum(rs) / n
        lo, hi = bs[50], bs[1949]
        verdict = 'CIが0を跨ぐ=有意でない' if lo < 0 < hi else '★0を跨がない'
        print(f'  n={n:,}  {pt * 100:+.2f}pp  95%CI[{lo * 100:+.2f}, {hi * 100:+.2f}]  {verdict}')

    print()
    print('=' * 84)
    print('■ 判定基準（事前固定）')
    print('=' * 84)
    print('  ・holdout で早生まれ(A)の複勝残差が有意に正 (CIが0を跨がない) → シグナル生存')
    print('  ・残差≈0 or CI跨ぎ → priced-in（動画の「オッズに反映されない」は不成立）')
    print('  ・素の成績差(■2)が残るのは当然。見るのは人気統制後の残差(■1)。')


if __name__ == '__main__':
    main()
