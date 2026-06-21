# -*- coding: utf-8 -*-
"""
馬場状態(良/稍重/重/不良)別バイアス検証 — scripts/baba_bias_backtest.py
2016-2026・芝/ダ別。重馬場で『枠順』『人気帯』がオッズを超えて偏るか(=事前に使える構造バイアス)。

指標: win_oddsバンドで複勝(3着内)期待を統制し、群の残差(pp)とzで測る。
リーク無し: 馬場コード・枠・人気・オッズは事前確定。脚質(kyakushitsu)は結果リークなので不使用。
"""
import os
import sys
import sqlite3
import math
import time as _time
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
Y_FROM, Y_TO = 2016, 2026
OE = [1.5, 2.5, 4, 7, 12, 25, 60, 1e9]
BABA = {'1': '良', '2': '稍重', '3': '重', '4': '不良'}


def ob(o):
    for i, e in enumerate(OE):
        if o <= e:
            return i
    return len(OE)


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro()
    rows = con.execute(
        f"""SELECT ra.surface, ra.baba_shiba, ra.baba_dirt, ra.shusso_tosu,
                   r.waku, r.ninki, r.win_odds, r.chakujun
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN {Y_FROM} AND {Y_TO}
              AND ra.surface IN ('芝','ダート') AND r.chakujun>0 AND r.win_odds>0
              AND r.ninki>0 AND r.waku>0""").fetchall()
    con.close()

    recs = []
    for (surf, bs, bd, tosu, waku, ninki, wo, chaku) in rows:
        code = bd if 'ダ' in str(surf) else bs
        baba = BABA.get(str(code))
        if not baba:
            continue
        sf = 'ダ' if 'ダ' in str(surf) else '芝'
        recs.append((sf, baba, int(tosu or 0), int(waku), int(ninki), float(wo), chaku <= 3))
    print(f"runs={len(recs):,}", file=sys.stderr)

    # baseline 複勝 by odds band (全体)
    bt = defaultdict(int); bf = defaultdict(int)
    for r in recs:
        bt[ob(r[5])] += 1; bf[ob(r[5])] += 1 if r[6] else 0
    exp = {k: bf[k] / bt[k] for k in bt}

    def stat(sub):
        n = len(sub)
        if not n:
            return None
        f = sum(1 for r in sub if r[6])
        e = sum(exp[ob(r[5])] for r in sub)
        var = sum(exp[ob(r[5])] * (1 - exp[ob(r[5])]) for r in sub)
        z = (f - e) / math.sqrt(var) if var > 0 else 0
        return {'n': n, 'fuk': f / n * 100, 'resid': (f - e) / n * 100, 'z': z}

    print("=" * 80)
    print(f"馬場状態別バイアス {Y_FROM}-{Y_TO}  残差=オッズ帯期待からの複勝乖離pp / z")
    print("=" * 80)
    for sf in ['芝', 'ダ']:
        print(f"\n■ {sf}")
        # 1番人気の堅さ(馬場別)
        print("  [1番人気の複勝残差=堅い/荒れ]")
        for baba in ['良', '稍重', '重', '不良']:
            s = stat([r for r in recs if r[0] == sf and r[1] == baba and r[4] == 1])
            if s and s['n'] >= 150:
                print(f"    {baba:<3} 1番人気 n={s['n']:>5} 複勝{s['fuk']:.1f}% 残差{s['resid']:+.2f} z{s['z']:+.2f}")
        # 内枠(1-3) vs 外枠(6-8) 残差(馬場別) ※16頭立て近辺の枠バイアス
        print("  [内枠1-3 vs 外枠6-8 の複勝残差=枠バイアス]")
        for baba in ['良', '重', '不良']:
            si = stat([r for r in recs if r[0] == sf and r[1] == baba and r[3] <= 3 and r[2] >= 13])
            so = stat([r for r in recs if r[0] == sf and r[1] == baba and r[3] >= 6 and r[2] >= 13])
            if si and so and si['n'] >= 150 and so['n'] >= 150:
                print(f"    {baba:<3} 内枠 残差{si['resid']:+.2f}(z{si['z']:+.2f}) / 外枠 残差{so['resid']:+.2f}(z{so['z']:+.2f})")
    print("-" * 80)
    print("z>+2/<-2 かつ良との差が大きければ『重馬場で事前に使える枠/堅さバイアス』。")
    print("残差≈0(良と同程度)なら、馬場状態はオッズに織込み済み=補正タイム較正で十分。")


if __name__ == '__main__':
    main()
