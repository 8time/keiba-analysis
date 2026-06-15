# -*- coding: utf-8 -*-
"""調教師(単体)の勝率が着順を予測するか＝オッズを超える妙味があるか検証。
リーク防止のため train(〜2022)で調教師の成績を構築し、test(2023-2025)で評価。
各馬について調教師の「全体勝率」「当コース(場×馬場)勝率」「当距離帯勝率」を引き、
オッズ補正残差(実績 − オッズ別期待)で層別。残差>0=人気以上に来る=妙味あり。

JRA(jyo 01-10)・平地(芝/ダート)・trainer_code!='00000' のみ。
使い方: python scripts/trainer_backtest.py
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
cur = con.cursor()
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o))
    return e['win'] if e else 0.08


BASE = ("FROM results r JOIN races ra ON r.race_key=ra.race_key "
        "WHERE r.trainer_code!='00000' AND r.chakujun>0 "
        "AND ra.surface IN ('芝','ダート') "
        "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10")

# ---- train: 〜2022 で調教師成績を構築 ----
ovr = defaultdict(lambda: [0, 0])           # tc -> [runs, wins]
crs = defaultdict(lambda: [0, 0])           # (tc,jyo,surface) -> [runs, wins]
dst = defaultdict(lambda: [0, 0])           # (tc,surface,distband) -> [runs, wins]
print("train(〜2022)構築中...")
for tc, jyo, surf, kyori, chaku in cur.execute(
        f"SELECT r.trainer_code, ra.jyo, ra.surface, ra.kyori, r.chakujun {BASE} AND ra.year<'2023'"):
    w = 1 if chaku == 1 else 0
    ovr[tc][0] += 1; ovr[tc][1] += w
    crs[(tc, jyo, surf)][0] += 1; crs[(tc, jyo, surf)][1] += w
    db = jj._dist_band(kyori or 0)
    dst[(tc, surf, db)][0] += 1; dst[(tc, surf, db)][1] += w
print(f"  調教師数: {len(ovr)}")


def rate(d, key, min_n):
    v = d.get(key)
    if not v or v[0] < min_n:
        return None
    return v[1] / v[0]


def band_of(r):
    if r is None:
        return 'データ無'
    if r < 0.06:
        return '①<6%'
    if r < 0.10:
        return '②6-10%'
    if r < 0.14:
        return '③10-14%'
    if r < 0.20:
        return '④14-20%'
    return '⑤>20%'


# ---- test: 2023-2025 で残差を層別 ----
buckets = {
    '全体勝率': defaultdict(lambda: [0.0, 0.0, 0]),   # band -> [top3残差, win残差, n]
    '当コース勝率(場x馬場)': defaultdict(lambda: [0.0, 0.0, 0]),
    '当距離帯勝率': defaultdict(lambda: [0.0, 0.0, 0]),
}
n_test = 0
print("test(2023-2025)評価中...")
for tc, jyo, surf, kyori, chaku, o in cur.execute(
        f"SELECT r.trainer_code, ra.jyo, ra.surface, ra.kyori, r.chakujun, r.win_odds "
        f"{BASE} AND ra.year>='2023' AND r.win_odds>0"):
    n_test += 1
    r3 = (1 if chaku <= 3 else 0) - e3(o)
    rw = (1 if chaku == 1 else 0) - e1(o)
    db = jj._dist_band(kyori or 0)
    for label, key, mn in (
            ('全体勝率', tc, 50),
            ('当コース勝率(場x馬場)', (tc, jyo, surf), 20),
            ('当距離帯勝率', (tc, surf, db), 20)):
        src = {'全体勝率': ovr, '当コース勝率(場x馬場)': crs, '当距離帯勝率': dst}[label]
        b = band_of(rate(src, key, mn))
        buckets[label][b][0] += r3
        buckets[label][b][1] += rw
        buckets[label][b][2] += 1
con.close()

ORDER = ['①<6%', '②6-10%', '③10-14%', '④14-20%', '⑤>20%', 'データ無']
print(f"\ntest対象騎乗(延べ): {n_test}\n")
for label in ['全体勝率', '当コース勝率(場x馬場)', '当距離帯勝率']:
    print(f"==== 調教師の{label} 別 → オッズ補正残差 ====")
    print("  band      |   n    | 3着内残差 |  勝利残差")
    for b in ORDER:
        s3, sw, n = buckets[label][b]
        if n:
            print(f"  {b:9s} | {n:6d} |  {s3/n:+.4f} | {sw/n:+.4f}")
    print()
print("残差>0=人気(市場)以上に来る=妙味。各bandで差が無い/平坦なら市場が織り込み済=単体表示は予想に効かない。"
      "高勝率bandだけ残差>0で有意なら、その軸を色分け/数値列にする価値あり。")
