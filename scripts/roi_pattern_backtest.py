# -*- coding: utf-8 -*-
"""
第2弾(賢い金の学習) — どの条件×券種(まず単勝)が歴史的に+ROIか scripts/roi_pattern_backtest.py

「成功者の買い方」を直接学習するデータ(個人の馬券履歴)は公開されていない。代わりに
jravan.dbの実払戻(payouts)40年で「市場が間違いやすい＝+ROIになる買い方」を洗い出す。
これが歪み検知/コンシェルジュの提案根拠になる。

検証(2016-2026・オッズ完備):
  ・単勝ROI = Σ(勝ち馬のwin_odds) / 頭数。100%超=理論プラス。
  ・人気別 / オッズ帯別 / 条件別(ハンデ/フルゲート/少頭数/牝限/ダ) を総当たりし
    控除後ベース(約75-80%)を超える+ROIポケットがあるかを探す。
  ・資料の主張「単勝5〜10倍が期待値ゾーン」も直接検証する。
リーク無し: win_odds/人気/条件はすべて事前確定。
"""
import os
import sys
import sqlite3
import time as _time
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
Y_FROM, Y_TO = 2016, 2026
OBANDS = [(1, 1.5), (1.5, 2), (2, 3), (3, 5), (5, 7), (7, 10), (10, 15),
          (15, 30), (30, 70), (70, 1e9)]


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def roi(rows):
    """rows=[(won(bool), odds)] → (n, win%, roi%)."""
    n = len(rows)
    if not n:
        return (0, 0.0, 0.0)
    w = sum(1 for won, _ in rows if won)
    ret = sum(o for won, o in rows if won)
    return (n, w / n * 100, ret / n * 100)


def main():
    con = connect_ro()
    print("loading...", file=sys.stderr)
    rows = con.execute(
        f"""SELECT ra.juryo, ra.shusso_tosu, ra.kigo, ra.surface,
                   r.ninki, r.win_odds, r.chakujun
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN {Y_FROM} AND {Y_TO}
              AND ra.surface IN ('芝','ダート')
              AND r.chakujun>0 AND r.win_odds>0 AND r.ninki>0""").fetchall()
    con.close()
    print(f"runs={len(rows):,}", file=sys.stderr)

    recs = []
    for (juryo, tosu, kigo, surf, ninki, wo, chaku) in rows:
        conds = set()
        if juryo == '1':
            conds.add('ハンデ')
        if tosu and tosu >= 16:
            conds.add('フルゲート16+')
        if tosu and 8 <= tosu <= 10:
            conds.add('少頭数8-10')
        if kigo and len(kigo) >= 2 and kigo[1] == '2':
            conds.add('牝馬限定')
        conds.add('ダ' if 'ダ' in str(surf) else '芝')
        recs.append((int(ninki), float(wo), chaku == 1, conds))

    base = roi([(w, o) for _, o, w, _ in recs])
    print("=" * 84)
    print(f"母集団 {Y_FROM}-{Y_TO}(芝ダ): n={base[0]:,}  単勝的中率{base[1]:.1f}%  単勝ROI{base[2]:.1f}%")
    print("控除後ベース(全馬均等買い)は約75-80%。これを超える群が『市場の歪み=+ROI』候補。")
    print("=" * 84)

    print("\n■ 人気別 単勝ROI")
    by_n = defaultdict(list)
    for ninki, o, w, _ in recs:
        by_n[min(ninki, 18)].append((w, o))
    print(f"{'人気':>4}{'n':>9}{'的中%':>8}{'ROI%':>8}")
    for k in sorted(by_n):
        n, wn, r = roi(by_n[k])
        if n >= 200:
            mark = ' ★+ROI' if r >= 100 else ''
            print(f"{k:>4}{n:>9}{wn:>8.1f}{r:>8.1f}{mark}")

    print("\n■ オッズ帯別 単勝ROI（資料『5〜10倍=期待値ゾーン』検証）")
    by_o = defaultdict(list)
    for _, o, w, _ in recs:
        for lo, hi in OBANDS:
            if lo <= o < hi:
                by_o[(lo, hi)].append((w, o))
                break
    print(f"{'オッズ帯':>12}{'n':>9}{'的中%':>8}{'ROI%':>8}")
    for lo, hi in OBANDS:
        sub = by_o.get((lo, hi), [])
        n, wn, r = roi(sub)
        if n >= 200:
            band = f"{lo}-{hi if hi < 1e9 else '∞'}倍"
            mark = ' ★+ROI' if r >= 100 else ''
            print(f"{band:>12}{n:>9}{wn:>8.1f}{r:>8.1f}{mark}")

    print("\n■ 条件 × 単勝ROI（全馬／人気帯別）")
    conds_all = ['ハンデ', 'フルゲート16+', '少頭数8-10', '牝馬限定', 'ダ', '芝']
    print(f"{'条件':>14}{'群':>10}{'n':>9}{'的中%':>8}{'ROI%':>8}")
    for cond in conds_all:
        for label, fn in [('全馬', lambda r: True),
                          ('1-3番人気', lambda r: r[0] <= 3),
                          ('4-9番人気', lambda r: 4 <= r[0] <= 9),
                          ('10番人気~', lambda r: r[0] >= 10)]:
            sub = [(w, o) for ninki, o, w, c in recs if cond in c and fn((ninki,))]
            n, wn, r = roi(sub)
            if n >= 300:
                mark = ' ★' if r >= 100 else ''
                print(f"{cond:>14}{label:>10}{n:>9}{wn:>8.1f}{r:>8.1f}{mark}")
    print("-" * 84)
    print("★=単勝ROI100%超(+ROIポケット)。控除率20-25%があるため100%超は稀＝出れば本物の歪み。")
    print("出なければ『単勝はどの条件でも市場が正しい』=コンシェルジュは見送り/券種選択で勝つ方針が正解。")


if __name__ == '__main__':
    main()
