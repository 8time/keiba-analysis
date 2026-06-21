# -*- coding: utf-8 -*-
"""
3連複『決着タイプ × よく当たる(出る)配当帯』 — scripts/trio_payout_by_type.py
本線(①: 1・2番人気が両方3着内)と②型(穴2頭: 3着内に5番人気以下が2頭以上)で
3連複配当の分布がどう違うか。「②穴はこの配当帯が母数多い」を可視化(馬券フィルター設計の根拠)。
2016-2026。
"""
import os
import sys
import sqlite3
import time as _time
from collections import defaultdict
from statistics import median

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
Y_FROM, Y_TO = 2016, 2026
PAY_BANDS = [(0, 1000), (1000, 3000), (3000, 7000), (7000, 15000),
             (15000, 30000), (30000, 70000), (70000, 1e12)]


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro()
    res = con.execute(
        f"""SELECT ra.race_key, r.ninki, r.chakujun
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN {Y_FROM} AND {Y_TO}
              AND ra.surface IN ('芝','ダート') AND r.chakujun>0 AND r.ninki>0""").fetchall()
    top3 = defaultdict(list)
    for rk, ninki, chaku in res:
        if chaku <= 3:
            top3[rk].append(int(ninki))
    pay = con.execute(
        f"""SELECT ra.race_key, p.payout
            FROM races ra JOIN payouts p ON p.race_key=ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN {Y_FROM} AND {Y_TO}
              AND p.bet_type='3連複' AND p.payout>0""").fetchall()
    trio_pay = {rk: int(p) for rk, p in pay}
    con.close()

    def kind(ns):
        if len(ns) < 3:
            return None
        n1 = 1 in ns
        n2 = 2 in ns
        ana = sum(1 for n in ns if n >= 5)
        if n1 and n2:
            return '本線(①)'
        if ana >= 2:
            return '②型(穴2頭)'
        return 'その他(中間)'

    rows = []
    for rk, ns in top3.items():
        k = kind(ns)
        p = trio_pay.get(rk)
        if k and p:
            rows.append((k, p))
    print(f"races={len(rows):,}")

    print("=" * 72)
    print(f"3連複 決着タイプ別 配当分布 {Y_FROM}-{Y_TO}")
    print("=" * 72)
    by_k = defaultdict(list)
    for k, p in rows:
        by_k[k].append(p)
    tot = len(rows)
    for k in ['本線(①)', 'その他(中間)', '②型(穴2頭)']:
        ps = by_k.get(k, [])
        if not ps:
            continue
        ps_s = sorted(ps)
        q1 = ps_s[len(ps_s) // 4]; q3 = ps_s[len(ps_s) * 3 // 4]
        print(f"\n■ {k}  発生{len(ps)/tot*100:.1f}%  中央値{median(ps):,.0f}円  "
              f"四分位[{q1:,}〜{q3:,}]円")
        bands = defaultdict(int)
        for p in ps:
            for lo, hi in PAY_BANDS:
                if lo <= p < hi:
                    bands[(lo, hi)] += 1
                    break
        for lo, hi in PAY_BANDS:
            c = bands.get((lo, hi), 0)
            if c:
                lbl = f"{lo:,}-{hi:,}円" if hi < 1e12 else f"{lo:,}円~"
                print(f"    {lbl:>18}: {c/len(ps)*100:5.1f}%  ({c:,}R)")
    print("-" * 72)
    print("『②型(穴2頭)』が出る時の配当帯=②穴狙いで取りにいくべき価格帯。馬券フィルターの根拠。")


if __name__ == '__main__':
    main()
