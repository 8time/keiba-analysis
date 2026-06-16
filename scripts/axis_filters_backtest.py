# -*- coding: utf-8 -*-
"""
軸フィルタ検証 #3 #4 — 軸選定に効くかをjravan.dbで検証。
─────────────────────────────────────────────
#3 オッズ2.5倍の境界線(Racing Quant p2):
   「1番人気はオッズ2.5倍以下でのみ軸として機能する」
   → 1番人気を win_odds帯で割り、複勝率(3着内)がどう変わるか。
     2.5倍超の1番人気は軸の信頼度が落ちるか？

#4 前走0.5秒以内の僅差負け(Racing Quant p4):
   「前走0.5秒以内の負けは複勝率37.5%・0.6秒以上は16.3%」
   → 軸候補(1〜N番人気)で、前走が『負け(2着以下)』だった馬を
     前走着差(=勝ち馬とのタイム差)帯で割り、今回複勝率を比較。
     同人気帯ベースを超える上乗せがあるか(=軸の加点に使えるか)。

判定指標=複勝率(3着内・完全populated)。win_odds欠損のためROIは不可
([[verified_ohtani_trap]])。ただし#3はwin_odds必須なので、odds保有の1番人気のみで集計。
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.jockey_jv import _parse_time_msst as ptime

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(y, m):
    try:
        return int(y) * 10000 + int(m)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2014)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--ninki_max', type=int, default=3, help='#4の軸候補人気上限')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, chakujun, ninki, win_odds, time "
        "FROM results WHERE CAST(year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    con.close()
    print(f"  results: {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    # 各馬の前走(着差付き): hist[ketto] = sorted [(dk, race_key, chakujun, behind_margin)]
    #   behind_margin = 勝ち馬とのタイム差(自分time - 1着time)。負け馬の僅差判定に使う。
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        t1 = None
        for r in rs:
            if r['chakujun'] == 1:
                t1 = ptime(r['time'])
        for r in rs:
            if not r['chakujun'] or r['chakujun'] <= 0:
                continue
            bm = None
            tt = ptime(r['time'])
            if t1 is not None and tt is not None:
                bm = round(tt - t1, 1)
            hist[r['ketto_num']].append((dk, rk, r['chakujun'], bm))
    for k in hist:
        hist[k].sort()

    def prev(ketto, dk):
        h = hist.get(ketto)
        if not h:
            return None
        past = [x for x in h if x[0] < dk]
        return past[-1] if past else None

    # ── #3 集計: 1番人気の win_odds帯別複勝率 ──
    odds_bins = ['1.0-1.5', '1.6-1.9', '2.0-2.4', '2.5-2.9', '3.0-3.4', '3.5-3.9', '4.0+']

    def obin(o):
        if o < 1.6: return '1.0-1.5'
        if o < 2.0: return '1.6-1.9'
        if o < 2.5: return '2.0-2.4'
        if o < 3.0: return '2.5-2.9'
        if o < 3.5: return '3.0-3.4'
        if o < 4.0: return '3.5-3.9'
        return '4.0+'
    f3 = defaultdict(lambda: [0, 0])   # bin -> [n, fuku]

    # ── #4 集計: 軸候補(1〜N番人気)で前走『負け』の着差帯別複勝率 ──
    f4 = {'前走勝ち': [0, 0], '負け0.0-0.5': [0, 0], '負け0.6-1.0': [0, 0],
          '負け1.1-2.0': [0, 0], '負け2.1+': [0, 0], '前走着差不明': [0, 0]}
    f4_base = [0, 0]

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['year']) <= args.test_to):
            continue
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        for r in rs:
            nk = r['ninki']
            if not nk or not r['chakujun'] or r['chakujun'] <= 0:
                continue
            fuku = 1 if r['chakujun'] <= 3 else 0

            # #3: 1番人気 × odds保有
            if nk == 1 and r['win_odds'] and r['win_odds'] > 0:
                b = obin(r['win_odds'])
                f3[b][0] += 1; f3[b][1] += fuku

            # #4: 軸候補(1〜N番人気)
            if 1 <= nk <= args.ninki_max:
                pv = prev(r['ketto_num'], dk)
                if pv is None:
                    continue
                f4_base[0] += 1; f4_base[1] += fuku
                _, _, pchaku, pbm = pv
                if pchaku == 1:
                    key = '前走勝ち'
                elif pbm is None:
                    key = '前走着差不明'
                elif pbm <= 0.5:
                    key = '負け0.0-0.5'
                elif pbm <= 1.0:
                    key = '負け0.6-1.0'
                elif pbm <= 2.0:
                    key = '負け1.1-2.0'
                else:
                    key = '負け2.1+'
                f4[key][0] += 1; f4[key][1] += fuku

    def line(name, nf, base=None):
        n, f = nf
        if n == 0:
            print(f"  {name:<14} n=0"); return
        fr = f / n * 100
        extra = ''
        if base is not None and base[0]:
            br = base[1] / base[0] * 100
            extra = f"  (ベース差 {fr - br:+.1f}pp)"
        print(f"  {name:<14} n={n:>6}  複勝率{fr:5.1f}%{extra}")

    print(f"\n=== #3 オッズ2.5倍の境界線 — 1番人気の単勝オッズ帯別 複勝率 (test {args.test_from}-{args.test_to}) ===")
    print("  ※win_odds保有の1番人気のみ。資料: 2.5倍以下でのみ軸機能。")
    for b in odds_bins:
        line(b, f3[b])

    print(f"\n=== #4 前走僅差負け — 軸候補(1〜{args.ninki_max}番人気)の前走着差帯別 複勝率 ===")
    print(f"  ベース(同人気帯・前走あり): n={f4_base[0]} 複勝率{(f4_base[1]/f4_base[0]*100 if f4_base[0] else 0):.1f}%")
    for k in ['前走勝ち', '負け0.0-0.5', '負け0.6-1.0', '負け1.1-2.0', '負け2.1+', '前走着差不明']:
        line(k, f4[k], f4_base)


if __name__ == '__main__':
    main()
