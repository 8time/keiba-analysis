# -*- coding: utf-8 -*-
"""
ダート含水率 × 血統型（米国/欧州） バックテスト

仮説: 乾燥(≤3.5%)=欧州型有利、湿潤(≥8.0%)=米国型有利
"""
import sys, io, os, sqlite3
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'data', 'jravan.db')

JRA = ('01','02','03','04','05','06','07','08','09','10')

US_SIRES = {'ヘニーヒューズ', 'パイロ', 'マジェスティックウォリアー', 'カジノドライヴ',
            'サウスヴィグラス', 'ゴールドアリュール', 'シニスターミニスター'}
EU_SIRES = {'ハービンジャー', 'キングカメハメハ', 'ルーラーシップ',
            'モーリス', 'エピファネイア', 'ドゥラメンテ'}


def classify(sire):
    if sire in US_SIRES:
        return 'US'
    if sire in EU_SIRES:
        return 'EU'
    return None


def moisture_zone(m):
    if m <= 3.5:
        return '乾燥'
    if m >= 8.0:
        return '湿潤'
    return '標準'


def main():
    con = sqlite3.connect(DB)

    # Build moisture map: (year, monthday, jyo) -> moisture
    moist_map = {}
    for y, md, jyo, m in con.execute(
        "SELECT year, monthday, jyo, dirt_moisture FROM track_cond WHERE dirt_moisture IS NOT NULL"
    ):
        moist_map[(y, md, jyo)] = m

    zones = defaultdict(int)
    for m in moist_map.values():
        zones[moisture_zone(m)] += 1
    print(f"含水率分布: 乾燥(≤3.5%)={zones['乾燥']} / 標準={zones['標準']} / 湿潤(≥8.0%)={zones['湿潤']}")

    # Query dirt races
    agg = defaultdict(lambda: [0, 0, 0, 0])  # (type, zone) -> [runs, wins, top3, win_ret]

    query = """
    SELECT ra.year, ra.monthday, ra.jyo, h.sire,
           r.chakujun,
           COALESCE(pw.payout, 0) as win_ret
    FROM races ra
    JOIN results r ON r.race_key = ra.race_key
    JOIN horses h ON h.ketto_num = r.ketto_num
    LEFT JOIN payouts pw ON pw.race_key = ra.race_key
        AND pw.bet_type = '単勝' AND CAST(pw.combo AS INTEGER) = r.umaban
    WHERE ra.surface LIKE 'ダ%'
      AND ra.jyo IN ({})
      AND r.chakujun >= 1
      AND ra.year >= '2018'
    """.format(','.join(f"'{j}'" for j in JRA))

    total = 0
    matched = 0
    for row in con.execute(query):
        year, md, jyo, sire, chaku, wret = row
        bt = classify(sire)
        if not bt:
            continue
        total += 1
        m = moist_map.get((year, md, jyo))
        if m is None:
            continue
        matched += 1
        zone = moisture_zone(m)
        a = agg[(bt, zone)]
        a[0] += 1
        if chaku == 1:
            a[1] += 1
        if chaku <= 3:
            a[2] += 1
        a[3] += wret

    con.close()
    print(f"対象走数: {total} (含水率一致: {matched})\n")

    print(f"{'='*70}")
    print(f"{'血統型':8s} {'含水率':6s} {'走数':>6s} {'勝率':>6s} {'複勝率':>6s} {'単回収':>7s} {'仮説':6s}")
    print(f"{'='*70}")

    for bt in ['US', 'EU']:
        for zone in ['乾燥', '標準', '湿潤']:
            a = agg.get((bt, zone))
            if not a or a[0] < 30:
                print(f"{bt:8s} {zone:6s}   サンプル不足")
                continue
            runs, wins, top3, wret = a
            wr = wins / runs * 100
            pr = top3 / runs * 100
            roi = wret / (runs * 100) * 100
            if bt == 'US':
                hyp = '★' if zone == '湿潤' else ('✗' if zone == '乾燥' else '-')
            else:
                hyp = '★' if zone == '乾燥' else ('✗' if zone == '湿潤' else '-')
            print(f"{bt:8s} {zone:6s} {runs:>5d}  {wr:>5.1f}% {pr:>5.1f}%  {roi:>6.1f}%  {hyp}")
        print()

    # Also show by individual sire
    print(f"\n{'='*70}")
    print(f"種牡馬別詳細:")
    print(f"{'='*70}")
    agg2 = defaultdict(lambda: [0, 0, 0, 0])
    con = sqlite3.connect(DB)
    for row in con.execute(query):
        year, md, jyo, sire, chaku, wret = row
        if sire not in US_SIRES and sire not in EU_SIRES:
            continue
        m = moist_map.get((year, md, jyo))
        if m is None:
            continue
        zone = moisture_zone(m)
        a = agg2[(sire, zone)]
        a[0] += 1
        if chaku == 1: a[1] += 1
        if chaku <= 3: a[2] += 1
        a[3] += wret
    con.close()

    for sire in sorted(US_SIRES | EU_SIRES):
        bt = classify(sire)
        line = f"  {sire:16s} ({bt}): "
        parts = []
        for zone in ['乾燥', '標準', '湿潤']:
            a = agg2.get((sire, zone))
            if a and a[0] >= 20:
                pr = a[2] / a[0] * 100
                roi = a[3] / (a[0] * 100) * 100
                parts.append(f"{zone}={pr:.0f}%/回{roi:.0f}%({a[0]}走)")
        if parts:
            print(line + ' | '.join(parts))


if __name__ == '__main__':
    main()
