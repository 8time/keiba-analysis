# -*- coding: utf-8 -*-
"""初ブリンカー(初装着)が着順を予測するか＝オッズを超える妙味かを検証。
test=2023-2025(JRA平地)。各馬の当該レースより前のブリンカー着用回数を数え、
 ・初ブリ   : 今回blinker=1 かつ 過去blinker=0
 ・ブリ継続 : 今回blinker=1 かつ 過去blinker>=1
 ・ブリ無し : 今回blinker=0
に層別し、オッズ補正残差(実績 − オッズ別期待)で比較。残差>0=人気以上に来る=妙味。
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


# 各馬の累積ブリンカー回数(時系列)。results を race_key昇順で走査。
prior_bl = defaultdict(int)   # ketto -> これまでのblinker着用回数
buckets = defaultdict(lambda: [0.0, 0.0, 0])   # label -> [top3残差, win残差, n]

rows = cur.execute(
    "SELECT r.race_key, r.ketto_num, r.blinker, r.chakujun, r.win_odds, ra.year "
    "FROM results r JOIN races ra ON r.race_key=ra.race_key "
    "WHERE r.chakujun>0 AND r.ketto_num!='' AND ra.surface IN ('芝','ダート') "
    "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10 "
    "ORDER BY r.race_key").fetchall()
print(f"全平地結果: {len(rows)}行")

for rk, ketto, bl, chaku, o, year in rows:
    bl = 1 if str(bl) == '1' else 0
    is_test = year >= '2023' and o and o > 0
    if is_test:
        if bl == 1:
            label = '初ブリ' if prior_bl[ketto] == 0 else 'ブリ継続'
        else:
            label = 'ブリ無し'
        r3 = (1 if chaku <= 3 else 0) - e3(o)
        rw = (1 if chaku == 1 else 0) - e1(o)
        buckets[label][0] += r3
        buckets[label][1] += rw
        buckets[label][2] += 1
    # 累積更新(当該レース後)
    if bl == 1:
        prior_bl[ketto] += 1
con.close()

print("\n==== ブリンカー状態別 → オッズ補正残差(test 2023-2025) ====")
print("  状態      |   n    | 3着内残差 |  勝利残差")
for label in ['初ブリ', 'ブリ継続', 'ブリ無し']:
    s3, sw, n = buckets[label]
    if n:
        # 残差の標準誤差(近似: 3着内の二項)
        se = (0.22 * 0.78 / n) ** 0.5
        z = (s3 / n) / se if se else 0
        print(f"  {label:8s} | {n:6d} |  {s3/n:+.4f} | {sw/n:+.4f}  (3着内z={z:+.2f})")
print("\n残差>0かつ有意(|z|>=1.96)なら初ブリは妙味。0近傍なら市場織込み済=表示のみ。")
