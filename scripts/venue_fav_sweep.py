# -*- coding: utf-8 -*-
"""場×馬場×1-3人気の軸信頼度 全場総当たり(頭数帯コントロール・train2021-24/holdout2025)。

core/blood_course._VENUE_FAVの検証元。採用基準=|z_tr|>=2.5かつholdout符号一致。
採用(2026-07-03): 東京芝+3.8/小倉芝-3.1/函館芝-4.0/川崎ダ-4.8。
NARはNAR専用の(人気,頭数帯)ベースで較正。実行: python scripts/venue_fav_sweep.py
"""
import sys, os, sqlite3, math
from collections import defaultdict
import os
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "jravan.db")
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
rows = con.execute(
    "SELECT r.year, r.ninki, r.chakujun, r.jyo, ra.surface, ra.shusso_tosu "
    "FROM results r JOIN races ra ON ra.race_key=r.race_key "
    "WHERE CAST(r.year AS INT) BETWEEN 2021 AND 2025 "
    "AND r.chakujun>0 AND r.ninki>0").fetchall()
con.close()

def fs(st): st = st or 0; return 0 if st <= 9 else 1 if st <= 13 else 2
def surf(s): return '芝' if '芝' in str(s) else 'ダ'
def region(j): return 'JRA' if str(j).zfill(2) <= '10' else 'NAR'

# base: (region, ninki, fs帯)
base = defaultdict(lambda: [0, 0])
for y, nk, ch, j, sf, st in rows:
    base[(region(j), int(nk), fs(st))][0] += 1 if ch <= 3 else 0
    base[(region(j), int(nk), fs(st))][1] += 1
br = {k: v[0]/v[1] for k, v in base.items() if v[1]}

VN = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京',
      '08':'京都','09':'阪神','10':'小倉','42':'浦和','43':'船橋','44':'大井','45':'川崎'}
agg = defaultdict(lambda: {'tr':[0,0,0.0],'ho':[0,0,0.0]})
for y, nk, ch, j, sf, st in rows:
    j2 = str(j).zfill(2)
    if j2 not in VN or int(nk) > 3: continue
    k = (j2, surf(sf))
    e = br.get((region(j), int(nk), fs(st)))
    if e is None: continue
    tgt = 'ho' if int(y) == 2025 else 'tr'
    a = agg[k][tgt]
    a[0] += 1 if ch <= 3 else 0; a[1] += 1; a[2] += e

print(f"{'場':<6}{'面':>3}{'n_tr':>8}{'残差tr':>9}{'z_tr':>7}{'n_25':>7}{'残差25':>9}{'z_25':>7}  判定(採用=|z_tr|>=2.5かつ符号一致)")
for k in sorted(agg, key=lambda x: (x[0], x[1])):
    d = agg[k]
    out = []
    zs = {}
    for tag in ('tr','ho'):
        t3, n, exp = d[tag]
        if n < 100: zs[tag]=None; out += [n, None, None]; continue
        e = exp/n; z = (t3-exp)/math.sqrt(n*e*(1-e))
        zs[tag] = (t3/n-e, z)
        out += [n, 100*(t3/n-e), z]
    if zs['tr'] is None: continue
    rtr, ztr = zs['tr']
    if zs['ho']: rho, zho = zs['ho']
    else: rho, zho = 0.0, 0.0
    ok = abs(ztr) >= 2.5 and (rtr*rho > 0 or zs['ho'] is None)
    mark = '✅採用' if ok else ('△境界' if abs(ztr) >= 2.0 else '')
    print(f"{VN[k[0]]:<6}{k[1]:>3}{out[0]:>8,}{100*rtr:>+8.2f}pp{ztr:>+7.1f}"
          f"{out[3]:>7,}{100*rho:>+8.2f}pp{zho:>+7.1f}  {mark}")
