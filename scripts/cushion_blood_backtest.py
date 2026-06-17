# -*- coding: utf-8 -*-
"""
前日比クッション値 × 種牡馬シフト適性 バックテスト

track_cond + jravan.db(races/results/horses) を使い、
前日比[+]硬化 / [△]軟化 の日に _SIRE_CUSHION_AFFINITY の各種牡馬産駒が
実際にどの程度の勝率・複勝率・単勝回収率を出したかを検証する。

出力: 種牡馬×シフト方向 の成績マトリクス
"""
import sys, io, os, sqlite3
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, 'data', 'jravan.db')

JRA = ('01','02','03','04','05','06','07','08','09','10')
SHIFT_TH = 0.3

# 検証対象種牡馬と仮説
TARGETS = {
    'ディープインパクト': '+',
    'キズナ': '+',
    'レイデオロ': '+',
    'エピファネイア': '+',
    'キタサンブラック': '△',
    'モーリス': '△',   # danger: △時に沈む仮説
    'ロードカナロア': None,  # 対照群
    'ドゥラメンテ': None,    # 対照群
}


def main():
    con = sqlite3.connect(DB)

    # Step 1: 前日比シフトを全日×場で算出
    tc_rows = con.execute(
        "SELECT year, monthday, jyo, cushion FROM track_cond "
        "WHERE cushion IS NOT NULL ORDER BY jyo, year||monthday"
    ).fetchall()

    prev_by_jyo = {}
    shift_map = {}  # (year, monthday, jyo) -> shift '+' / '△' / '±0'
    for year, md, jyo, cv in tc_rows:
        key = (year, md, jyo)
        if jyo in prev_by_jyo:
            delta = cv - prev_by_jyo[jyo]
            if delta >= SHIFT_TH:
                shift_map[key] = '+'
            elif delta <= -SHIFT_TH:
                shift_map[key] = '△'
            else:
                shift_map[key] = '±0'
        prev_by_jyo[jyo] = cv

    print(f"シフト算出: {len(shift_map)} 日×場")
    cnt = defaultdict(int)
    for v in shift_map.values():
        cnt[v] += 1
    print(f"  [+]硬化={cnt['+']} / [△]軟化={cnt['△']} / [±0]={cnt['±0']}")

    # Step 2: 芝レースで各種牡馬産駒の成績をシフト別に集計
    # agg[(sire, shift)] = [runs, wins, top3, win_payout_sum]
    agg = defaultdict(lambda: [0, 0, 0, 0])

    sire_names = set(TARGETS.keys())

    query = """
    SELECT ra.year, ra.monthday, ra.jyo, h.sire,
           r.chakujun, r.ninki,
           COALESCE(pw.payout, 0) as win_ret
    FROM races ra
    JOIN results r ON r.race_key = ra.race_key
    JOIN horses h ON h.ketto_num = r.ketto_num
    LEFT JOIN payouts pw ON pw.race_key = ra.race_key
        AND pw.bet_type = '単勝' AND CAST(pw.combo AS INTEGER) = r.umaban
    WHERE ra.surface = '芝'
      AND ra.jyo IN ({})
      AND r.chakujun >= 1
      AND ra.year >= '2020'
    """.format(','.join(f"'{j}'" for j in JRA))

    total = 0
    matched = 0
    for row in con.execute(query):
        year, md, jyo, sire, chaku, ninki, wret = row
        if sire not in sire_names:
            continue
        total += 1
        key = (year, md, jyo)
        shift = shift_map.get(key)
        if not shift:
            continue
        matched += 1
        a = agg[(sire, shift)]
        a[0] += 1
        if chaku == 1:
            a[1] += 1
        if chaku <= 3:
            a[2] += 1
        a[3] += wret

    con.close()
    print(f"\n対象走数: {total} (シフト一致: {matched})")

    # Step 3: 結果表示
    print(f"\n{'='*90}")
    print(f"{'種牡馬':16s} {'仮説':4s} {'シフト':4s} {'走数':>6s} {'勝率':>6s} {'複勝率':>6s} {'単回収':>7s} {'判定':6s}")
    print(f"{'='*90}")

    for sire, hypothesis in TARGETS.items():
        for shift in ['+', '△', '±0']:
            a = agg.get((sire, shift))
            if not a or a[0] < 10:
                continue
            runs, wins, top3, wret = a
            wr = wins / runs * 100
            pr = top3 / runs * 100
            roi = wret / (runs * 100) * 100

            if hypothesis:
                if shift == hypothesis:
                    verdict = '★活性' if pr >= 25.0 else '○微活'
                elif shift != '±0':
                    verdict = '✗逆風' if pr <= 20.0 else '△中立'
                else:
                    verdict = '-'
            else:
                verdict = '(対照)'

            print(f"{sire:16s} {hypothesis or '-':4s} [{shift:2s}] {runs:>5d}  {wr:>5.1f}% {pr:>5.1f}%  {roi:>6.1f}%  {verdict}")
        print()


if __name__ == '__main__':
    main()
