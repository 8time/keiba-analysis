# -*- coding: utf-8 -*-
"""調教(坂路HC)が着順を予測するか検証。各馬のレース直前の最終坂路追い切りから
 ①4F全体タイムの同日同トレセン偏差(z) ②加速ラップ(終いに向けラップ短縮)
を作り、オッズ補正残差(3着内 − オッズ別期待複勝率)で層別。残差>0=人気以上に来る。"""
import os
import sys
import sqlite3
import statistics
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


# 同日・同トレセンの4Fタイム母集団キャッシュ（偏差値用）
_pop_cache = {}
cur = con.cursor()


def day_pop(date, center):
    k = (date, center)
    if k not in _pop_cache:
        v = [r[0] for r in cur.execute(
            "SELECT t4f FROM training WHERE cho_date=? AND center=? AND t4f>0", (date, center))]
        if len(v) >= 8:
            m = statistics.mean(v)
            sd = statistics.pstdev(v) or 1e-9
            _pop_cache[k] = (m, sd)
        else:
            _pop_cache[k] = None
    return _pop_cache[k]


# 2025-09以降のレース（直前に追い切り履歴がある）をサンプル
rks = [r[0] for r in con.execute(
    """SELECT race_key FROM races WHERE ((year='2025' AND monthday>='0901') OR year='2026')
       AND shusso_tosu>=8""").fetchall()]
print(f"対象レース候補: {len(rks)}")

accel_b = defaultdict(lambda: [0.0, 0])    # 加速ラップ有無 → [残差合計, n]
z_b = defaultdict(lambda: [0.0, 0])        # 4F偏差z帯 → 残差
shubi_b = defaultdict(lambda: [0.0, 0])    # ラスト1F帯 → 残差
used_rides = 0
for rk in rks:
    ymd = con.execute("SELECT year||monthday FROM races WHERE race_key=?", (rk,)).fetchone()[0]
    rows = cur.execute(
        "SELECT ketto_num, chakujun, win_odds FROM results "
        "WHERE race_key=? AND chakujun>0 AND win_odds>0 AND ketto_num!=''", (rk,)).fetchall()
    if len(rows) < 8:
        continue
    for ketto, chaku, o in rows:
        w = cur.execute(
            "SELECT center,t4f,lap_86,lap_64,lap_42,lap_20 FROM training "
            "WHERE ketto_num=? AND cho_date<? AND t4f>0 ORDER BY cho_date DESC LIMIT 1",
            (ketto, ymd)).fetchone()
        if not w:
            continue
        center, t4f, l86, l64, l42, l20 = w
        res3 = (1 if chaku <= 3 else 0) - e3(o)
        used_rides += 1
        # 加速ラップ: 終いに向けラップ時間が短縮(=加速)。許容0.2秒
        if all(x and x > 0 for x in (l86, l64, l42, l20)):
            accel = (l86 >= l64 - 2 and l64 >= l42 - 2 and l42 >= l20 - 2)
            accel_b['加速ラップ◯' if accel else '加速ラップ✕'][0] += res3
            accel_b['加速ラップ◯' if accel else '加速ラップ✕'][1] += 1
            sb = 'ラスト<12.5' if l20 <= 125 else 'ラスト12.5-13.5' if l20 <= 135 else 'ラスト>13.5'
            shubi_b[sb][0] += res3; shubi_b[sb][1] += 1
        # 4F偏差z（同日同トレセン・速いほど高z）
        pop = day_pop(con.execute("SELECT cho_date FROM training WHERE ketto_num=? AND cho_date<? AND t4f>0 ORDER BY cho_date DESC LIMIT 1", (ketto, ymd)).fetchone()[0], center)
        if pop:
            m, sd = pop
            z = (m - t4f) / sd
            zb = 'z<-0.5(遅)' if z < -0.5 else 'z-0.5〜0.5' if z < 0.5 else 'z0.5〜1.2' if z < 1.2 else 'z>1.2(速)'
            z_b[zb][0] += z * 0  # placeholder no-op
            z_b[zb][0] += res3; z_b[zb][1] += 1
con.close()

print(f"\n調教データ紐付き騎乗: {used_rides}")
print("\n== 加速ラップ別 → 3着内残差（>0=人気以上）==")
for k in ['加速ラップ◯', '加速ラップ✕']:
    s, n = accel_b.get(k, [0, 0])
    if n:
        print(f"  {k}: {s/n:+.4f} (n={n})")
print("\n== 4F全体タイム偏差(同日同トレセン)別 → 残差 ==")
for k in ['z<-0.5(遅)', 'z-0.5〜0.5', 'z0.5〜1.2', 'z>1.2(速)']:
    s, n = z_b.get(k, [0, 0])
    if n:
        print(f"  {k}: {s/n:+.4f} (n={n})")
print("\n== ラスト1F(終い)別 → 残差 ==")
for k in ['ラスト<12.5', 'ラスト12.5-13.5', 'ラスト>13.5']:
    s, n = shubi_b.get(k, [0, 0])
    if n:
        print(f"  {k}: {s/n:+.4f} (n={n})")
