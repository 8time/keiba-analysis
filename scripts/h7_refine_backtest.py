# -*- coding: utf-8 -*-
"""
#2 H7化リファインの検証 — scripts/h7_refine_backtest.py

補正T図(過去走の最高=最速corrected)の定義を3通りで比較し、どれが
「フィールド内 図トップ3」の複勝予測力(人気を超える残差)を最大化するか測る。

  A: best_all     = 過去全走・芝ダ混在 の最小corrected (現行 corrected_time.db)
  B: h7_surf      = 直近7走・今走と同一芝ダ の最小corrected (資料のH7定義)
  C: last7_all    = 直近7走・芝ダ混在 の最小corrected (窓だけ7走/サーフェス効果を分離)

評価: 各定義でレース内 図トップ3 を作り、人気順位統制の複勝残差を
  ①全top3 ②1-2番人気×top3(本命補強) ③6番人気以下×top3(穴) で比較。
  併せて winner-in-top3%(勝ち馬が図トップ3に入る率=recall代理)も。

リーク無し: 図は今走より前のレースのみ。corrected は [[verified_corrected_time]] と同一。
"""
import os
import sys
import sqlite3
import math
import time as _time
from collections import defaultdict
from statistics import median

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
BASELINE_FROM = 1990
TEST_FROM, TEST_TO = 2019, 2025
FIG_TOP = 3


def to_sec(t):
    if not t or len(t) != 4 or not t.isdigit() or t == '0000':
        return None
    s = int(t[0]) * 60 + int(t[1:3]) + int(t[3]) / 10.0
    return s if 50 <= s <= 360 else None


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro()
    print("loading...", file=sys.stderr)
    q = f"""SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori, ra.race_id,
                   r.ketto_num, r.chakujun, r.ninki, r.time
            FROM races ra JOIN results r ON r.race_key = ra.race_key
            WHERE ra.surface IN ('芝','ダート')
              AND CAST(ra.year AS INTEGER) >= {BASELINE_FROM}
              AND r.chakujun > 0"""
    rows = []
    for (yr, md, jyo, surf, kyori, rid, ketto, chaku, ninki, tm) in con.execute(q):
        sec = to_sec(tm)
        if sec is None or not ketto:
            continue
        try:
            day = int(yr) * 10000 + int(md)
        except Exception:
            continue
        rows.append([day, surf, int(kyori), jyo, rid, str(ketto), int(chaku),
                     (int(ninki) if ninki else 99), sec, None])
    con.close()
    print(f"runs={len(rows):,}", file=sys.stderr)

    by_sk = defaultdict(list)
    for x in rows:
        by_sk[(x[1], x[2])].append(x[8])
    baseline = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}
    for x in rows:
        b = baseline.get((x[1], x[2]))
        x[9] = (x[8] - b) if b is not None else None
    by_tr = defaultdict(list)
    for x in rows:
        if x[9] is not None:
            by_tr[(x[0], x[3], x[1])].append(x[9])
    tb = {k: median(v) for k, v in by_tr.items() if len(v) >= 4}
    for x in rows:
        if x[9] is None:
            continue
        b = tb.get((x[0], x[3], x[1]))
        x[9] = (x[9] - b) if b is not None else None

    # per-horse history: (day, corrected, surface)
    hist = defaultdict(list)
    for x in rows:
        if x[9] is not None:
            hist[x[5]].append((x[0], x[9], x[1]))
    for k in hist:
        hist[k].sort()

    def figs_for(ketto, day, surf):
        arr = hist.get(ketto, [])
        prior = [(d, c, s) for (d, c, s) in arr if d < day][::-1]  # 新→古
        if not prior:
            return (None, None, None)
        a = min(c for (_, c, _) in prior)                                  # best_all
        last7 = prior[:7]
        c_all = min(c for (_, c, _) in last7)                              # last7_all
        same = [c for (_, c, s) in last7 if s == surf]
        b = min(same) if same else None                                   # h7_surf
        return (a, b, c_all)

    # races in test window
    races = defaultdict(list)
    for x in rows:
        if TEST_FROM <= x[0] // 10000 <= TEST_TO:
            races[x[4]].append(x)

    # per-def accumulation
    DEFS = ['best_all(現行)', 'h7_surf(直近7・芝ダ別)', 'last7_all(直近7・混在)']
    recs = {d: [] for d in DEFS}      # (ninki, fuk, is_top3)
    winner_top3 = {d: [0, 0] for d in DEFS}  # [hit, total_races_with_winner_fig]

    for rid, hs in races.items():
        day = hs[0][0]
        surf = hs[0][1]
        fmap = {}  # um_idx -> (a,b,c)
        for i, x in enumerate(hs):
            fmap[i] = figs_for(x[5], day, surf)
        for di, dname in enumerate(DEFS):
            vals = {i: fmap[i][di] for i in range(len(hs))}
            valid = [(i, v) for i, v in vals.items() if v is not None]
            valid.sort(key=lambda t: t[1])
            top3 = {i for i, _ in valid[:FIG_TOP]}
            for i, x in enumerate(hs):
                recs[dname].append((x[7], 1 if x[6] <= 3 else 0, i in top3))
            # winner in top3?
            win_idx = [i for i, x in enumerate(hs) if x[6] == 1]
            if win_idx and any(fmap[wi][di] is not None for wi in win_idx):
                winner_top3[dname][1] += 1
                if any(wi in top3 for wi in win_idx):
                    winner_top3[dname][0] += 1

    def nb(n):
        return min(n, 15) if n < 99 else 99

    # baseline per def (same recs set, identical rows, so exp same — compute once per def anyway)
    def analyze(dname):
        rr = recs[dname]
        bt = defaultdict(int); bf = defaultdict(int)
        for (ninki, fuk, t3) in rr:
            bt[nb(ninki)] += 1; bf[nb(ninki)] += fuk
        exp = {k: bf[k] / bt[k] for k in bt}

        def stat(sub):
            n = len(sub)
            if n == 0:
                return None
            fuk = sum(r[1] for r in sub)
            e = sum(exp[nb(r[0])] for r in sub)
            var = sum(exp[nb(r[0])] * (1 - exp[nb(r[0])]) for r in sub)
            z = (fuk - e) / math.sqrt(var) if var > 0 else 0
            return {'n': n, 'fuk': fuk / n * 100, 'resid': (fuk - e) / n * 100, 'z': z}
        out = {}
        out['top3'] = stat([r for r in rr if r[2]])
        out['fav'] = stat([r for r in rr if r[2] and r[0] <= 2])
        out['mid'] = stat([r for r in rr if r[2] and 3 <= r[0] <= 5])
        out['ana'] = stat([r for r in rr if r[2] and r[0] >= 6])
        wt = winner_top3[dname]
        out['wtop3'] = (wt[0] / wt[1] * 100) if wt[1] else 0
        return out

    print("=" * 104)
    print(f"H7化リファイン比較 {TEST_FROM}-{TEST_TO}  図トップ{FIG_TOP}・人気順位統制の複勝残差pp / z")
    print("=" * 104)
    hdr = (f"{'定義':<24}{'全top3 n':>9}{'残差':>7}{'z':>6}"
           f"{'｜1-2人気':>9}{'残差':>7}{'z':>6}{'｜6人気↓':>9}{'残差':>7}{'z':>6}{'｜勝馬top3%':>11}")
    print(hdr); print("-" * 104)
    for dname in DEFS:
        o = analyze(dname)
        def cell(s):
            return (s['n'], s['resid'], s['z']) if s else (0, 0, 0)
        t = cell(o['top3']); f = cell(o['fav']); a = cell(o['ana'])
        print(f"{dname:<24}{t[0]:>9}{t[1]:>+7.2f}{t[2]:>+6.1f}"
              f"{f[0]:>9}{f[1]:>+7.2f}{f[2]:>+6.1f}"
              f"{a[0]:>9}{a[1]:>+7.2f}{a[2]:>+6.1f}{o['wtop3']:>10.1f}%")
    print("-" * 104)
    print("残差大(特に1-2番人気=本命補強, 6番人気↓=穴)＆勝馬top3%高 が良い図。")
    print("best_allを上回ればH7化(直近7・芝ダ別)を採用、変わらなければ現行維持。")


if __name__ == '__main__':
    main()
