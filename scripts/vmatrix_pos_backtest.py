# -*- coding: utf-8 -*-
"""
Vマトリクス Y軸(隊列ポジション)の予測精度検証。

問い: 『今走の早い位置取り(corner1の相対位置)』を事前に当てるには、
  (A) 習性コーナー位置 = 過去走の平均corner1位置(=現build_v_matrixのprof['ten']相当)
  (B) 習性テン速力     = 過去走の平均ten_speed(秒/600m, 小=速い)
  (C) A+Bブレンド
  のどれが効くか。レース内スピアマン順位相関の平均で比較。
すべて『その走より前の走』のみ使用=リーク無し。
"""
import os
import sys
import sqlite3
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2023', '2024', '2025')


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def main():
    for attempt in range(8):
        try:
            con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
            yf = " OR ".join(["ra.year=?"] * len(YEARS))
            rows = con.execute(
                f"""SELECT r.ketto_num, r.race_key, ra.shusso_tosu,
                           r.corner1, r.corner2, r.corner3, r.corner4,
                           r.time, r.ato3f, ra.kyori, ra.surface
                    FROM races ra JOIN results r ON r.race_key=ra.race_key
                    WHERE ({yf}) AND ra.shusso_tosu>=8 AND r.chakujun>0""",
                YEARS).fetchall()
            con.close()
            break
        except sqlite3.OperationalError:
            import time
            time.sleep(4)
    else:
        print("DB locked", file=sys.stderr)
        return
    print(f"rows={len(rows)}", file=sys.stderr)

    # per-horse chronological history; collect (race_key, c1ratio, ten_speed)
    by_horse = defaultdict(list)
    race_field = defaultdict(list)  # race_key -> list of (ketto, c1ratio_target, tosu, surf, kyori)
    def parse_time(t):
        """JV time テキスト 'MSSs'(例 '1168'=1分16.8秒) を秒に。"""
        try:
            ds = int(str(t).strip())
        except (TypeError, ValueError):
            return None
        if ds <= 0:
            return None
        tenths = ds % 10
        sec = (ds // 10) % 100
        minute = ds // 1000
        v = minute * 60 + sec + tenths / 10.0
        return v if v > 0 else None

    for (ketto, rkey, tosu, c1, c2, c3, c4, tm, a3f, kyori, surf) in rows:
        if not ketto or not tosu or tosu < 2:
            continue
        # 位置: c1〜c4の最初の有効コーナー(prof['ten']と同じ採り方)。0=先頭
        corner = next((c for c in (c1, c2, c3, c4) if c and c > 0), None)
        c1r = (corner - 1) / (tosu - 1) if corner else None
        # ten_speed of THIS run = (走破秒 − 上がり3F秒)/(距離−600)*600
        ts = None
        try:
            tsec = parse_time(tm)
            a3 = (a3f / 10.0) if a3f and a3f > 0 else None
            if tsec and a3 and kyori and kyori > 600:
                ts = (tsec - a3) / (kyori - 600) * 600
                if ts <= 0 or ts > 60:
                    ts = None
        except Exception:
            ts = None
        by_horse[ketto].append({'rkey': rkey, 'c1r': c1r, 'ts': ts})
        race_field[rkey].append({'ketto': ketto, 'c1r': c1r})

    # sort each horse's runs chronologically by race_key (string sortable)
    for k in by_horse:
        by_horse[k].sort(key=lambda d: d['rkey'])

    # build prior-habit lookups: for each (ketto, rkey) -> habit_corner, habit_ts from runs before
    habit = {}  # (ketto,rkey) -> (habit_corner, habit_ts)
    for k, runs in by_horse.items():
        seen_c, seen_ts = [], []
        for d in runs:
            hc = sum(seen_c) / len(seen_c) if seen_c else None
            ht = sum(seen_ts) / len(seen_ts) if seen_ts else None
            habit[(k, d['rkey'])] = (hc, ht)
            if d['c1r'] is not None:
                seen_c.append(d['c1r'])
            if d['ts'] is not None:
                seen_ts.append(d['ts'])

    # per race, build vectors and correlate with target c1r
    accA = []  # habit_corner vs target
    accB = []  # habit_ts vs target (note: low ts=front=low c1r, expect +corr)
    accC = []  # blend
    for rkey, field in race_field.items():
        tgt, A, B = [], [], []
        for h in field:
            if h['c1r'] is None:
                continue
            hc, ht = habit.get((h['ketto'], rkey), (None, None))
            if hc is None or ht is None:
                continue
            tgt.append(h['c1r'])
            A.append(hc)
            B.append(ht)
        if len(tgt) < 4:
            continue
        sA = spearman(A, tgt)
        sB = spearman(B, tgt)
        # blend: z-normalize within race then average
        def zn(v):
            m = sum(v) / len(v)
            sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 or 1.0
            return [(x - m) / sd for x in v]
        C = [a + b for a, b in zip(zn(A), zn(B))]
        sC = spearman(C, tgt)
        if sA is not None:
            accA.append(sA)
        if sB is not None:
            accB.append(sB)
        if sC is not None:
            accC.append(sC)

    def rep(name, arr):
        if not arr:
            print(f"{name}: n/a")
            return
        m = sum(arr) / len(arr)
        print(f"{name}: 平均ρ={m:+.4f}  (races={len(arr)})")

    print("=" * 60)
    print("Y軸位置予測: 事前指標 vs 今走corner1相対位置(0=先頭) のレース内ρ")
    print("=" * 60)
    rep("(A) 習性コーナー位置 prof['ten']相当", accA)
    rep("(B) 習性テン速力 ten_speed       ", accB)
    rep("(C) A+Bブレンド(z正規化)         ", accC)
    print("-" * 60)
    print("ρが高いほど今走の前/後を当てている。Bが有意にA以上ならYをten_speedへ。")


if __name__ == '__main__':
    main()
