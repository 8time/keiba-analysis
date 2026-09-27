# -*- coding: utf-8 -*-
"""遅デビュー(35ヶ月+)シグナルの再検証 — 2023年前向き確認用

背景:
  maiden_birth_month_backtest.py の holdout(2018-2022) で
  「デビュー時月齢35ヶ月以上の複勝残差 -2.71pp (z=-4.33)」を探索的に発見。
  事前固定ではない発見のため、同じ期間での再検証は自己撞着。
  → 2023年デビュー馬で再現を確認する（maiden_mode_design.md §6.4）。

事前固定（再最適化禁止）:
  定義     : デビュー時月齢 >= 35ヶ月（発見時と同じ閾値をそのまま使用）
  ベース   : 人気別 複勝率（train 〜2017 で凍結。元検証と同一）
  評価期間 : 2023年デビュー馬
  判定     : 複勝残差 < 0 かつ z <= -2.0 で「生存」。達しなければ破棄

注意（結果の解釈に必ず併記）:
  2023年デビュー馬の birth カバレッジは 76.6%（欠損23.4%）。
  欠損が遅デビューと無相関なら方向は保存されるが、欠損バイアスの可能性は残る。

使い方: python scripts/maiden_late_debut_recheck.py
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
EVAL_YEAR = 2023
LATE_MONTHS = 35      # 事前固定。動かさない
YEAR_MIN = 2010


def zof(m, n, sd=0.42):
    return m / (sd / math.sqrt(n)) if n else 0.0


def months_between(race_ymd, birth_ymd):
    return ((race_ymd // 10000 - birth_ymd // 10000) * 12
            + (race_ymd // 100) % 100 - (birth_ymd // 100) % 100)


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)

    print('=' * 84)
    print('■ データ監査（2023年のカバレッジ）')
    print('=' * 84)
    birth_of = {}
    for kt, b in con.execute(
            "SELECT ketto_num, birth FROM horses WHERE LENGTH(birth)>=8"):
        try:
            birth_of[str(kt)] = int(str(b))
        except ValueError:
            continue

    rows = con.execute(
        "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.win_odds, "
        "       ra.year, ra.monthday "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート') "
        "AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ketto_num<>''"
    ).fetchall()
    con.close()

    by_horse = defaultdict(list)
    for rk, kt, ch, nk, wo, y, md in rows:
        by_horse[str(kt)].append((int(str(y) + str(md).zfill(4)), str(rk),
                                  int(ch), (int(nk) if nk else None),
                                  (float(wo) if wo else None), int(y)))

    debut_all = []
    debut_2023_total = 0
    debut_2023_with_birth = 0
    for kt, lst in by_horse.items():
        lst.sort()
        day, rk, ch, nk, wo, y = lst[0]
        if y == EVAL_YEAR:
            debut_2023_total += 1
            if kt in birth_of:
                debut_2023_with_birth += 1
        if y < YEAR_MIN or y > EVAL_YEAR or nk is None:
            continue
        b = birth_of.get(kt)
        if b is None:
            continue
        debut_all.append(dict(y=y, day=day, ch=ch, nk=nk, wo=wo,
                              age_m=months_between(day, b)))
    print(f'  {EVAL_YEAR}年デビュー馬: {debut_2023_total:,}頭 '
          f'/ birthあり: {debut_2023_with_birth:,} '
          f'({debut_2023_with_birth / max(debut_2023_total, 1) * 100:.1f}%)')

    # ── ベースライン: 人気別 複勝率（train 〜2017 凍結。元検証と同一）──
    bp = defaultdict(lambda: [0, 0])
    for d in debut_all:
        if d['y'] <= TRAIN_END:
            bp[d['nk']][0] += 1 if d['ch'] <= 3 else 0
            bp[d['nk']][1] += 1
    TP = {k: v[0] / v[1] for k, v in bp.items() if v[1] >= 50}

    # ── 評価: 2023年デビュー馬 ──
    ev = [d for d in debut_all if d['y'] == EVAL_YEAR and d['nk'] in TP]
    late = [d for d in ev if d['age_m'] >= LATE_MONTHS]
    normal = [d for d in ev if d['age_m'] < LATE_MONTHS]
    ages = sorted(d['age_m'] for d in ev)
    if ages:
        n_a = len(ages)
        print(f'  評価対象: {len(ev):,}頭 / 月齢分布 '
          f'min={ages[0]} p25={ages[n_a // 4]} median={ages[n_a // 2]} '
          f'p75={ages[3 * n_a // 4]} max={ages[-1]}')
        print(f'  うち 遅デビュー(>={LATE_MONTHS}ヶ月): {len(late):,}頭 '
              f'({len(late) / len(ev) * 100:.1f}%)')

    def residual(group):
        rs = [(1 if d['ch'] <= 3 else 0) - TP[d['nk']] for d in group]
        n = len(rs)
        if n < 100:
            return None
        m = sum(rs) / n
        rois = [d['wo'] if d['ch'] == 1 else 0.0 for d in group if d['wo']]
        roi = sum(rois) / len(rois) * 100 if rois else None
        hit = sum(1 for d in group if d['ch'] <= 3) / n * 100
        return n, m, zof(m, n), hit, roi

    print()
    print('=' * 84)
    print(f'■ 主結果: {EVAL_YEAR}年デビュー馬（人気統制後の複勝残差）')
    print('=' * 84)
    print(f"  {'区分':<26}{'n':>8}{'複勝率':>8}{'複勝残差':>10}{'z':>8}{'単勝ROI':>9}")
    for lbl, grp in ((f'遅デビュー(>={LATE_MONTHS}ヶ月)', late),
                     (f'通常(<{LATE_MONTHS}ヶ月)', normal)):
        r = residual(grp)
        if r is None:
            print(f'  {lbl:<26}{"標本不足":>8}')
            continue
        roi_s = f"{r[4]:>7.1f}%" if r[4] is not None else '      -'
        print(f'  {lbl:<26}{r[0]:>8,}{r[3]:>7.1f}%{r[1]:>+10.4f}{r[2]:>+8.2f}{roi_s:>9}')

    print()
    print('=' * 84)
    print(f'■ bootstrap 95%CI（遅デビュー・{EVAL_YEAR}）')
    print('=' * 84)
    rs = [(1 if d['ch'] <= 3 else 0) - TP[d['nk']] for d in late]
    n = len(rs)
    ci_lo = ci_hi = pt = None
    if n >= 200:
        random.seed(42)
        bs = sorted(sum(rs[random.randrange(n)] for _ in range(n)) / n
                    for _ in range(2000))
        pt = sum(rs) / n
        ci_lo, ci_hi = bs[50], bs[1949]
        print(f'  n={n:,}  {pt * 100:+.2f}pp  95%CI[{ci_lo * 100:+.2f}, {ci_hi * 100:+.2f}]')

    print()
    print('=' * 84)
    print('■ 判定（事前固定ルール: 残差<0 かつ z<=-2.0 で生存）')
    print('=' * 84)
    r_late = residual(late)
    if r_late is None:
        print('  標本不足のため判定不能 → 破棄')
        verdict = '破棄（標本不足）'
    else:
        _, m, z, _, _ = r_late
        survives = (m < 0) and (z <= -2.0)
        verdict = '生存（2023で再現）' if survives else '破棄（再現せず）'
        print(f'  複勝残差 {m * 100:+.2f}pp / z={z:+.2f} → {verdict}')
    print()
    print('  ※カバレッジ注意: 2023年は birth 76.6%。欠損バイアスの可能性を残したままの判定。')
    print('  ※生存でも「消去候補の参考表示」まで。加点・自動消去への接続は別ゲート。')

    # ── 参考: 元発見との対比 ──
    print()
    print('=' * 84)
    print('■ 参考: 元発見（2018-2022 holdout）との対比')
    print('=' * 84)
    orig = [d for d in debut_all if TRAIN_END < d['y'] <= 2022 and d['nk'] in TP]
    orig_late = [d for d in orig if d['age_m'] >= LATE_MONTHS]
    rs_o = [(1 if d['ch'] <= 3 else 0) - TP[d['nk']] for d in orig_late]
    if rs_o:
        m_o = sum(rs_o) / len(rs_o)
        print(f'  2018-2022: n={len(rs_o):,} 残差 {m_o * 100:+.2f}pp z={zof(m_o, len(rs_o)):+.2f}')
    if r_late:
        print(f'  2023     : n={r_late[0]:,} 残差 {r_late[1] * 100:+.2f}pp z={r_late[2]:+.2f}')


if __name__ == '__main__':
    main()
