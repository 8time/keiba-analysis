# -*- coding: utf-8 -*-
"""新馬戦『騎手×調教師コンビ(黄金ライン)』は使えるか — 新馬戦限定スライス検証

主張(動画):
  新馬戦で特定の騎手×厩舎タッグは異常に高成績(例: 横山武史×伊藤圭三 勝率28.6%)。
  陣営の勝負気配を示し、オッズに反映されにくい。

既存資産との関係:
  黄金ライン本体(jockey_trainer_combo)は全レース集計で実装・検証済み
  ([[golden_line_backtest]]: 連対35-40%帯が最強、50%+は織込み済み)。
  本検証は『新馬戦(デビュー戦)に限定したコンビ成績』の残存効果を測る別スライス。

設計(リーク無し・事前固定):
  対象 = 各馬の初出走(デビュー戦)。JRA場01-10、芝/ダート、障害除外。
  シグナル = train期間(〜2017)のデビュー戦における騎手×調教師コンビ成績
             (jockey_name × trainer_code。新馬戦のみで集計)。
  閾値 = 既存定数と同じ GOLD_MIN_RIDES=10, top2 40%/35%/30% 区分。
  評価 = holdout(2018-2022)で人気統制後の複勝残差。残差≈0なら織込み済み。
  副次 = 単勝ROI(参考)、holdout でのコンビ別実績表(記述統計・探索)。

使い方: python scripts/maiden_golden_line_backtest.py
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
HOLDOUT_END = 2022
YEAR_MIN = 2010

# 既存 core/jockey_jv.py の定数と同一(変更禁止・参照のみ)
GOLD_MIN_RIDES = 10
GOLD_TOP2_WEAK = 0.30
GOLD_TOP2_GATE = 0.35
GOLD_TOP2_STRONG = 0.40


def zof(m, n, sd=0.42):
    return m / (sd / math.sqrt(n)) if n else 0.0


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)

    print('=' * 84)
    print('■ データ読み込み')
    print('=' * 84)
    rows = con.execute(
        "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.win_odds, "
        "       r.jockey_name, r.trainer_code, ra.year, ra.monthday "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート') "
        "AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ketto_num<>''"
    ).fetchall()
    con.close()
    print(f'  出走レコード {len(rows):,}件')

    # 馬ごと時系列 → デビュー戦レコードのみ残す
    by_horse = defaultdict(list)
    for rk, kt, ch, nk, wo, jk, tc, y, md in rows:
        by_horse[str(kt)].append((int(str(y) + str(md).zfill(4)), str(rk),
                                  int(ch), (int(nk) if nk else None),
                                  (float(wo) if wo else None),
                                  str(jk or ''), str(tc or ''), int(y)))
    debut = []
    for kt, lst in by_horse.items():
        lst.sort()
        day, rk, ch, nk, wo, jk, tc, y = lst[0]
        if YEAR_MIN <= y <= HOLDOUT_END and nk is not None and jk and tc:
            debut.append(dict(kt=kt, day=day, rk=rk, ch=ch, nk=nk, wo=wo,
                              jk=jk, tc=tc, y=y))
    print(f'  デビュー戦サンプル {len(debut):,}頭')

    # ── train期間の新馬戦コンビ成績 ──
    combo = defaultdict(lambda: [0, 0, 0])   # (jk, tc) -> [wins, top2, rides]
    for d in debut:
        if d['y'] <= TRAIN_END:
            c = combo[(d['jk'], d['tc'])]
            c[0] += 1 if d['ch'] == 1 else 0
            c[1] += 1 if d['ch'] <= 2 else 0
            c[2] += 1
    n_combo = sum(1 for v in combo.values() if v[2] >= GOLD_MIN_RIDES)
    print(f'  train コンビ総数 {len(combo):,} / うち {GOLD_MIN_RIDES}走以上 {n_combo:,}')

    # ── ベースライン: 人気別 勝率/複勝率(train凍結) ──
    bw = defaultdict(lambda: [0, 0])
    bp = defaultdict(lambda: [0, 0])
    for d in debut:
        if d['y'] <= TRAIN_END:
            bw[d['nk']][0] += 1 if d['ch'] == 1 else 0
            bw[d['nk']][1] += 1
            bp[d['nk']][0] += 1 if d['ch'] <= 3 else 0
            bp[d['nk']][1] += 1
    TW = {k: v[0] / v[1] for k, v in bw.items() if v[1] >= 50}
    TP = {k: v[0] / v[1] for k, v in bp.items() if v[1] >= 50}

    def grp_of(d):
        """trainコンビ成績 → 区分。事前固定。"""
        v = combo.get((d['jk'], d['tc']))
        if v is None or v[2] < GOLD_MIN_RIDES:
            return 'E:データ少(train10走未満)'
        t2 = v[1] / v[2]
        if t2 >= GOLD_TOP2_STRONG:
            return 'A:連対40%以上(名門)'
        if t2 >= GOLD_TOP2_GATE:
            return 'B:連対35-40%'
        if t2 >= GOLD_TOP2_WEAK:
            return 'C:連対30-35%'
        return 'D:連対30%未満'

    GROUPS = ['A:連対40%以上(名門)', 'B:連対35-40%', 'C:連対30-35%',
              'D:連対30%未満', 'E:データ少(train10走未満)']

    print()
    print('=' * 84)
    print('■ 1. 新馬戦コンビ区分別 — holdout(2018-2022) 人気統制後の残差')
    print('=' * 84)
    print(f"  {'区分':<24}{'n':>8}{'複勝率':>8}{'複勝残差':>10}{'z':>7}{'勝率残差':>10}{'単勝ROI':>9}")
    ho_results = {}
    for g in GROUPS:
        rs_p, rs_w, rois, hit = [], [], [], 0
        for d in debut:
            if not (TRAIN_END < d['y'] <= HOLDOUT_END):
                continue
            if grp_of(d) != g or d['nk'] not in TP:
                continue
            rs_p.append((1 if d['ch'] <= 3 else 0) - TP[d['nk']])
            rs_w.append((1 if d['ch'] == 1 else 0) - TW[d['nk']])
            hit += 1 if d['ch'] <= 3 else 0
            if d['wo']:
                rois.append(d['wo'] if d['ch'] == 1 else 0.0)
        n = len(rs_p)
        if n < 100:
            print(f'  {g:<24}{"標本不足":>8}')
            continue
        mp = sum(rs_p) / n
        mw = sum(rs_w) / n
        roi = sum(rois) / len(rois) * 100 if rois else None
        ho_results[g] = rs_p
        roi_s = f"{roi:>7.1f}%" if roi is not None else '      -'
        print(f'  {g:<24}{n:>8,}{hit / n * 100:>7.1f}%{mp:>+10.4f}{zof(mp, n):>+7.2f}'
              f'{mw:>+10.4f}{roi_s:>9}')

    print()
    print('=' * 84)
    print('■ 2. bootstrap 95%CI（A:名門コンビ・holdout・複勝残差）')
    print('=' * 84)
    rs = ho_results.get(GROUPS[0], [])
    n = len(rs)
    if n >= 200:
        random.seed(42)
        bs = sorted(sum(rs[random.randrange(n)] for _ in range(n)) / n
                    for _ in range(2000))
        pt = sum(rs) / n
        lo, hi = bs[50], bs[1949]
        verdict = 'CIが0を跨ぐ=有意でない' if lo < 0 < hi else '★0を跨がない'
        print(f'  n={n:,}  {pt * 100:+.2f}pp  95%CI[{lo * 100:+.2f}, {hi * 100:+.2f}]  {verdict}')
    else:
        print(f'  標本不足({n})')

    print()
    print('=' * 84)
    print('■ 3. holdout期のコンビ別実績（記述統計・探索用。判定には使わない）')
    print('=' * 84)
    # holdout で10走以上あるコンビを連対率順に（動画の表に相当する記述）
    hc = defaultdict(lambda: [0, 0, 0, 0.0])  # wins, top2, rides, roi_pay
    for d in debut:
        if TRAIN_END < d['y'] <= HOLDOUT_END:
            c = hc[(d['jk'], d['tc'])]
            c[0] += 1 if d['ch'] == 1 else 0
            c[1] += 1 if d['ch'] <= 2 else 0
            c[2] += 1
            c[3] += (d['wo'] or 0.0) if d['ch'] == 1 else 0.0
    rows_h = [(v[2], v[0], v[1], v[3] / v[2] * 100, k)
              for k, v in hc.items() if v[2] >= 10]
    rows_h.sort(key=lambda r: -(r[2] / r[0]))
    print(f"  {'騎手×調教師':<28}{'騎乗':>5}{'勝':>4}{'勝率':>7}{'連対率':>7}{'単勝ROI':>8}")
    for rides, w, t2, roi, (jk, tc) in rows_h[:15]:
        print(f'  {jk + "×" + tc:<28}{rides:>5}{w:>4}'
              f'{w / rides * 100:>6.1f}%{t2 / rides * 100:>6.1f}%{roi:>7.0f}%')

    print()
    print('=' * 84)
    print('■ 判定基準（事前固定）')
    print('=' * 84)
    print('  ・holdout で A(連対40%+)の複勝残差が有意に正 → 新馬戦限定の残存効果あり')
    print('  ・残差≈0 or CI跨ぎ → 新馬戦でも織込み済み。既存黄金ライン表示のまま')
    print('  ・全レース版の知見(50%+は織込み済み)と新馬版が矛盾する場合は新馬版を優先記録')


if __name__ == '__main__':
    main()
