# -*- coding: utf-8 -*-
"""
脚質と軸馬の信頼度バックテスト
─────────────────────────────────────────────
資料(Racing Quant p4)の主張:
  「追い込みは罠。4角10番手以内の先行馬を選ぶ(複勝率27.4% vs 11番手以下5.2%)」

重要: results.kyakushitsu / corner4 は『そのレースの結果＝事後情報』。
      レース前に4角位置は分からないので、軸選定に使うには
      過去走から作る『習性脚質(pre-race)』でなければ意味がない。

検証2本立て:
  [A] 事後(hindsight): 今回の kyakushitsu / corner4 別の複勝率(資料の再現確認)。
  [B] 事前(pre-race) : 過去K走の平均 kyakushitsu から習性脚質を作り、
                       1〜N番人気(軸候補)の中で 前型 vs 後型 の複勝率を比較。
                       ベースライン=同人気帯全体。これが軸選定に使える本命の指標。

kyakushitsu: 1=逃げ 2=先行 3=差し 4=追込 0=不明
複勝率(3着内)を主指標とする(win_odds欠損のためROIは不可。[[verified_ohtani_trap]]参照)。
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(year, monthday):
    try:
        return int(year) * 10000 + int(monthday)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2014)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--ninki_max', type=int, default=3, help='軸候補とする人気上限')
    ap.add_argument('--k', type=int, default=5, help='習性脚質に使う直近走数')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT r.race_key, r.year AS year, r.monthday AS monthday, r.ketto_num, r.chakujun, "
        "r.ninki, r.kyakushitsu, r.corner4, ra.shusso_tosu "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    con.close()
    print(f"  rows: {len(rows):,}")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    # 習性脚質: ketto -> sorted [(date_key, kyakushitsu)]  (kyakushitsu>0のみ)
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        for r in rs:
            ky = r['kyakushitsu']
            try:
                ky = int(ky)
            except Exception:
                ky = 0
            if r['chakujun'] and r['chakujun'] > 0 and ky in (1, 2, 3, 4):
                hist[r['ketto_num']].append((dk, ky))
    for k in hist:
        hist[k].sort()

    def habit_style(ketto, dk):
        h = hist.get(ketto)
        if not h:
            return None
        past = [ky for (d, ky) in h if d < dk][-args.k:]
        if len(past) < 2:
            return None
        return sum(past) / len(past)   # 1.0(逃げ)〜4.0(追込)

    # ── [A] 事後 ──
    A_ky = defaultdict(lambda: [0, 0])     # kyakushitsu -> [n, fuku]
    A_c4 = defaultdict(lambda: [0, 0])     # corner4 bucket -> [n, fuku]
    # ── [B] 事前 ──
    B = {'前型(<=2.0)': [0, 0], '中型(2.0-3.0)': [0, 0], '後型(>3.0)': [0, 0]}
    B_all = [0, 0]   # 同人気帯ベース(習性算出可の母集団)

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['year']) <= args.test_to):
            continue
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        fld = rs[0]['shusso_tosu'] or 0
        for r in rs:
            nk = r['ninki']
            if not nk or nk < 1 or nk > args.ninki_max:
                continue
            if not r['chakujun'] or r['chakujun'] <= 0:
                continue
            fuku = 1 if r['chakujun'] <= 3 else 0

            # [A] hindsight
            try:
                ky = int(r['kyakushitsu'])
            except Exception:
                ky = 0
            if ky in (1, 2, 3, 4):
                A_ky[ky][0] += 1; A_ky[ky][1] += fuku
            c4 = r['corner4']
            if c4 and c4 > 0:
                # 相対4角位置(頭数で正規化したくないが資料に合わせ絶対順位bucketも見る)
                if c4 <= 5:
                    bk = '4角1-5番手'
                elif c4 <= 10:
                    bk = '4角6-10番手'
                else:
                    bk = '4角11番手以下'
                A_c4[bk][0] += 1; A_c4[bk][1] += fuku

            # [B] pre-race habit
            hs = habit_style(r['ketto_num'], dk)
            if hs is not None:
                B_all[0] += 1; B_all[1] += fuku
                if hs <= 2.0:
                    key = '前型(<=2.0)'
                elif hs <= 3.0:
                    key = '中型(2.0-3.0)'
                else:
                    key = '後型(>3.0)'
                B[key][0] += 1; B[key][1] += fuku

    def line(name, nf):
        n, f = nf
        if n == 0:
            print(f"  {name:<16} n=0"); return None
        fr = f / n * 100
        print(f"  {name:<16} n={n:>7}  複勝率{fr:5.1f}%")
        return fr

    print(f"\n=== 脚質×軸 検証 (test {args.test_from}-{args.test_to} / 軸候補=1〜{args.ninki_max}番人気) ===")
    print("  ※複勝率=3着内率。win_odds欠損のためROIは出さない。")

    print(f"\n[A] 事後(hindsight) — 今回の脚質コード別 (資料の再現)")
    names = {1: '逃げ', 2: '先行', 3: '差し', 4: '追込'}
    for ky in (1, 2, 3, 4):
        line(names[ky], A_ky[ky])
    print(f"\n[A'] 事後 — 今回の4角通過順 別 (資料: 10番手以内27.4% vs 11番手以下5.2%)")
    for bk in ['4角1-5番手', '4角6-10番手', '4角11番手以下']:
        line(bk, A_c4[bk])

    print(f"\n[B] 事前(pre-race) — 過去{args.k}走の習性脚質別 ★軸選定に使える指標")
    base = line('同人気帯ベース', B_all)
    for key in ['前型(<=2.0)', '中型(2.0-3.0)', '後型(>3.0)']:
        fr = line(key, B[key])
        if fr is not None and base is not None:
            print(f"      → ベース差 {fr - base:+.1f}pp")


if __name__ == '__main__':
    main()
