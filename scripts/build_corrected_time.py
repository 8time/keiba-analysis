# -*- coding: utf-8 -*-
"""
補正タイム較正資産ビルダー (scripts/build_corrected_time.py)

jravan.db の全走破タイムから「補正タイム(偏差)」を計算し、馬(ketto)ごとに集計して
data/corrected_time.db (table horse_fig) に書き出す。ライブ採点(core/corrected_time.py)が
これを read-only で引く。検証ロジックは scripts/corrected_time_backtest.py と同一:

  sec=走破タイム秒 → baseline=(surface,距離)中央値 → raw_dev=sec−baseline
  → track_bias=(開催日,競馬場,surface)のraw_dev中央値 → corrected=raw_dev−track_bias (負=速い)

馬場コード非依存(同日同コース偏差で馬場差を吸収)。
horse_fig(H7化・検証 scripts/h7_refine_backtest.py で best_all より recall 38.6→44.6%):
  ketto, fig_shiba(直近7走中の芝の最小=最速), fig_dirt(直近7走中のダの最小),
  runs_shiba, runs_dirt, last_day。図=「直近7走 × 芝ダ別の最高補正」。
※新レースが増えたら再実行して更新する(古いと直近7走がズレる)。
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', 'jravan.db')
OUT = os.path.join(ROOT, 'data', 'corrected_time.db')
BASELINE_FROM = 1990


def to_sec(t):
    if not t or len(t) != 4 or not t.isdigit() or t == '0000':
        return None
    m = int(t[0]); ss = int(t[1:3]); f = int(t[3])
    sec = m * 60 + ss + f / 10.0
    return sec if 50 <= sec <= 360 else None


def connect_ro(path):
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro(SRC)
    print("loading rows...", file=sys.stderr)
    q = f"""SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori,
                   r.ketto_num, r.time
            FROM races ra JOIN results r ON r.race_key = ra.race_key
            WHERE ra.surface IN ('芝','ダート')
              AND CAST(ra.year AS INTEGER) >= {BASELINE_FROM}
              AND r.chakujun > 0"""
    rows = []
    for (yr, md, jyo, surf, kyori, ketto, tm) in con.execute(q):
        sec = to_sec(tm)
        if sec is None or not ketto:
            continue
        try:
            day = int(yr) * 10000 + int(md)
        except Exception:
            continue
        # x = [day, jyo, surf, kyori, ketto, sec, corrected]
        rows.append([day, jyo, surf, int(kyori), str(ketto), sec, None])
    con.close()
    print(f"valid runs: {len(rows):,}", file=sys.stderr)

    # baseline median per (surface, kyori)
    by_sk = defaultdict(list)
    for x in rows:
        by_sk[(x[2], x[3])].append(x[5])
    baseline = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}
    for x in rows:
        b = baseline.get((x[2], x[3]))
        x[6] = (x[5] - b) if b is not None else None

    # track bias per (day, jyo, surface)
    by_tr = defaultdict(list)
    for x in rows:
        if x[6] is not None:
            by_tr[(x[0], x[1], x[2])].append(x[6])
    track_bias = {k: median(v) for k, v in by_tr.items() if len(v) >= 4}
    for x in rows:
        if x[6] is None:
            continue
        tb = track_bias.get((x[0], x[1], x[2]))
        x[6] = (x[6] - tb) if tb is not None else None

    # aggregate per ketto: 直近7走 × 芝ダ別の最小corrected(=H7化)
    hist = defaultdict(list)  # ketto -> [(day, corrected, surface)]
    for x in rows:
        if x[6] is not None:
            hist[x[4]].append((x[0], x[6], x[2]))
    print(f"horses: {len(hist):,}", file=sys.stderr)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    out = sqlite3.connect(OUT)
    out.execute("""CREATE TABLE horse_fig(
        ketto TEXT PRIMARY KEY, fig_shiba REAL, fig_dirt REAL,
        runs_shiba INTEGER, runs_dirt INTEGER, last_day INTEGER)""")
    batch = []
    for k, arr in hist.items():
        arr.sort()                      # 古→新
        last7 = arr[-7:]                # 直近7走(全体)
        shiba = [c for (_, c, s) in last7 if s == '芝']
        dirt = [c for (_, c, s) in last7 if s == 'ダート']
        fig_s = round(min(shiba), 3) if shiba else None
        fig_d = round(min(dirt), 3) if dirt else None
        batch.append((k, fig_s, fig_d, len(shiba), len(dirt), arr[-1][0]))
        if len(batch) >= 5000:
            out.executemany("INSERT INTO horse_fig VALUES(?,?,?,?,?,?)", batch)
            batch = []
    if batch:
        out.executemany("INSERT INTO horse_fig VALUES(?,?,?,?,?,?)", batch)
    out.commit()
    n = out.execute("SELECT COUNT(*) FROM horse_fig").fetchone()[0]
    out.close()
    print(f"wrote {n:,} horses -> {OUT}")


if __name__ == '__main__':
    main()
