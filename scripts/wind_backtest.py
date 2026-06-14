# -*- coding: utf-8 -*-
"""
過去風データ（Open-Meteo アーカイブ=ERA5再解析・無料）を race_key に結合し、
「直線の風成分が着順（脚質）に効くか」を検証するスクリプト。

- 各レースの発走時刻(hasso_time)の風速・風向を取得
- 各競馬場の直線走行方位 _VENUE_STRAIGHT_BEARING に投影 → straight_tail（+ = 直線追い風）
  ※ 向正面成分は単純オーバルでは straight_tail の符号反転なので別軸にしない
- data/jravan.db に race_wind テーブルとしてキャッシュ（再実行は高速）
- 直線追い風/向かい風で「勝ち馬が差し(後方)/先行(前)」に寄るかをバケツ比較＆相関で検証

使い方: python scripts/wind_backtest.py [サンプル数]
"""
import os
import sys
import math
import time
import json
import sqlite3
import urllib.request
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import pace_map as pm

DB = pm.JV_DB_PATH


def ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS race_wind (
        race_key TEXT PRIMARY KEY, wind_speed REAL, wind_dir REAL,
        straight_tail REAL)""")
    con.commit()


def straight_tail(speed, dir_deg, bearing):
    """+ = 直線で追い風（後ろから押す） / - = 向かい風。風は dir_deg『から』吹く。"""
    return -speed * math.cos(math.radians(dir_deg - bearing))


def fetch_day_wind(lat, lon, date_iso):
    """その日の時別風（Asia/Tokyo）。{hour:int -> (speed,dir)} を返す。失敗で {}。"""
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           f"&start_date={date_iso}&end_date={date_iso}"
           f"&hourly=wind_speed_10m,wind_direction_10m&wind_speed_unit=ms&timezone=Asia%2FTokyo")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            j = json.loads(r.read().decode('utf-8'))
        h = j.get('hourly', {})
        out = {}
        for t, s, d in zip(h.get('time', []), h.get('wind_speed_10m', []),
                           h.get('wind_direction_10m', [])):
            if s is None or d is None:
                continue
            hour = int(t[11:13])
            out[hour] = (s, d)
        return out
    except Exception:
        return {}


def populate(n_sample, con):
    ensure_table(con)
    cached = {r[0] for r in con.execute("SELECT race_key FROM race_wind")}
    # JRA10場・芝・発走時刻あり・勝ち馬の4角ありの近年レースを抽出
    rows = con.execute("""
        SELECT ra.race_key, ra.year, ra.monthday, ra.jyo, ra.hasso_time
        FROM races ra
        WHERE ra.year IN ('2023','2024') AND ra.surface='芝'
          AND ra.jyo IN ('01','02','03','04','05','06','07','08','09','10')
          AND ra.hasso_time != '' AND ra.hasso_time != '0000' AND ra.shusso_tosu>=10
        ORDER BY ra.race_key""").fetchall()
    rows = [r for r in rows if r[0] not in cached][:n_sample]
    groups = defaultdict(list)
    for rk, y, md, jyo, htime in rows:
        groups[(jyo, y, md)].append((rk, htime))

    venue_of = pm.VENUE_CODES
    done = 0
    for (jyo, y, md), races in groups.items():
        venue = venue_of.get(jyo)
        coords = pm._VENUE_COORDS.get(venue)
        bearing = pm._VENUE_STRAIGHT_BEARING.get(venue)
        if not coords or bearing is None:
            continue
        date_iso = f"{y}-{md[:2]}-{md[2:]}"
        day = fetch_day_wind(coords[0], coords[1], date_iso)
        time.sleep(0.15)
        if not day:
            continue
        for rk, htime in races:
            try:
                hour = int(str(htime).zfill(4)[:2])
            except Exception:
                continue
            w = day.get(hour) or day.get(min(day, key=lambda h: abs(h - hour))) if day else None
            if not w:
                continue
            spd, drc = w
            st = straight_tail(spd, drc, bearing)
            con.execute("INSERT OR REPLACE INTO race_wind VALUES (?,?,?,?)",
                        (rk, round(spd, 2), round(drc, 1), round(st, 3)))
        con.commit()
        done += 1
        if done % 20 == 0:
            print(f"  ...{done}グループ取得")
    print(f"取得グループ数: {done} / キャッシュ総数: "
          f"{con.execute('SELECT COUNT(*) FROM race_wind').fetchone()[0]}")


def analyze(con):
    # 勝ち馬の4角通過（正規化）と straight_tail の関係
    rows = con.execute("""
        SELECT w.straight_tail, w.wind_speed, r.corner4, ra.shusso_tosu
        FROM race_wind w
        JOIN races ra ON ra.race_key=w.race_key
        JOIN results r ON r.race_key=w.race_key AND r.chakujun=1
        WHERE r.corner4>0 AND ra.shusso_tosu>=10""").fetchall()
    data = [(st, sp, (c4 - 1) / max(t - 1, 1), c4) for st, sp, c4, t in rows if t]
    n = len(data)
    print(f"\n=== 検証対象: {n}レース ===")
    if n < 30:
        print("データ不足"); return

    def bucket(name, pred):
        sub = [d for d in data if pred(d)]
        if not sub:
            print(f"  {name}: n/a"); return
        avg_pos = sum(d[2] for d in sub) / len(sub)        # 0=最前,1=最後方
        front = sum(1 for d in sub if d[3] <= 3) / len(sub)  # 勝ち馬が4角3番手以内
        print(f"  {name:22s} (n={len(sub):4d}): 勝ち馬平均4角位置={avg_pos:.3f}（大=後方差し） / 前残り率={front*100:.1f}%")

    print("勝ち馬の脚質傾向を 直線風成分(straight_tail, +=追い風) で比較:")
    bucket("強い追い風(>=+3)", lambda d: d[0] >= 3)
    bucket("やや追い風(+1〜+3)", lambda d: 1 <= d[0] < 3)
    bucket("無風帯(-1〜+1)", lambda d: -1 < d[0] < 1)
    bucket("やや向かい風(-3〜-1)", lambda d: -3 < d[0] <= -1)
    bucket("強い向かい風(<=-3)", lambda d: d[0] <= -3)

    # 相関（straight_tail vs 勝ち馬正規化4角位置）。正なら「追い風ほど差し勝ち」
    import statistics
    xs = [d[0] for d in data]; ys = [d[2] for d in data]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    r = cov / (sx * sy) if sx and sy else 0
    print(f"\n相関 r(straight_tail, 勝ち馬4角位置) = {r:+.3f}  "
          f"(正=追い風ほど差し決着／弱いほど風は効かない)")


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    con = sqlite3.connect(DB)
    print(f"過去風データを結合中（最大{n}レース）...")
    populate(n, con)
    analyze(con)
    con.close()
