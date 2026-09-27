# -*- coding: utf-8 -*-
"""crank導出の検証: 2025年の新馬/未勝利レースをkigo・shubetsu・月で分布確認"""
import os
import sqlite3
import sys

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

con = sqlite3.connect('file:data/jravan.db?mode=ro', uri=True)
q = """
SELECT r.race_key, r.ketto_num, r.chakujun, r.ijo, ra.year, ra.monthday, ra.grade, ra.kigo, ra.shubetsu
FROM results r JOIN races ra ON r.race_key = ra.race_key
WHERE ra.year IN ('2024','2025') AND ra.surface IN ('芝','ダート')
  AND ra.jyo IN ('01','02','03','04','05','06','07','08','09','10')
"""
df = pd.read_sql(q, con)
con.close()

df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
df['valid'] = (df['ijo'].astype(str) == '0') & df['chakujun'].between(1, 30)
df['month'] = (pd.to_numeric(df['monthday'], errors='coerce') // 100).astype(int)
df = df.sort_values(['ketto_num', 'year', 'monthday', 'race_key'])
v = df[df['valid']].copy()
g = v.groupby('ketto_num', sort=False)
v['runs_before'] = g.cumcount()
wi = (v['chakujun'] == 1).astype(int)
v['wins_before'] = (wi.groupby(g.ngroup()).cumsum() - wi).to_numpy()

v25 = v[v['year'] == '2025']
rmax_w = v25.groupby('race_key')['wins_before'].max()
rmax_r = v25.groupby('race_key')['runs_before'].max()
meta = v25.groupby('race_key')[['grade', 'kigo', 'shubetsu', 'month']].first()
meta['maxw'] = rmax_w
meta['maxr'] = rmax_r

gmap = {'A': 8, 'B': 7, 'C': 6, 'L': 5}
meta['crank'] = meta['grade'].astype(str).map(gmap)
rest = meta['crank'].isna()
w = meta.loc[rest, 'maxw']
r = meta.loc[rest, 'maxr']
meta.loc[rest, 'crank'] = pd.Series(__import__('numpy').where(r == 0, 0, __import__('numpy').where(w >= 4, 5, w + 1)), index=meta.index[rest])

print('== crank x shubetsu (2025) ==')
print(meta.groupby(['crank', 'shubetsu']).size().unstack(fill_value=0))

print('\n== crank==0 (新馬) by month x shubetsu ==')
print(meta[meta['crank'] == 0].groupby(['shubetsu', 'month']).size().unstack(fill_value=0))

print('\n== crank==1 (未勝利) by kigo ==')
print(meta[meta['crank'] == 1].groupby('kigo').size().sort_values(ascending=False))

print('\n== crank==2 (1勝) by kigo top10 ==')
print(meta[meta['crank'] == 2].groupby('kigo').size().sort_values(ascending=False).head(10))

print('\n== 2歳(11)のcrank分布 ==')
print(meta[meta['shubetsu'] == '11']['crank'].value_counts().sort_index())

print('\n== 3歳(12)のcrank分布 ==')
print(meta[meta['shubetsu'] == '12']['crank'].value_counts().sort_index())
