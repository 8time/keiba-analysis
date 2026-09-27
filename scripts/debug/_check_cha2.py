# -*- coding: utf-8 -*-
"""CHA コースコードの同定: 所属別クロス + jravan training(t4f/lap_20)との照合"""
import os
import sys
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from scripts import jrdb_read

CHA_COLS = ['場コード', 'Ｒ', '馬番', '調教年月日', '調教コースコード', '追切種類',
            '調教Ｆ', 'テンＦ', '中間Ｆ', '終いＦ']
KYI_COLS = ['場コード', 'Ｒ', '馬番', '調教師所属']


def load_fast(prefix, cols):
    import zipfile
    layout, reclen, _ = jrdb_read.build_layout(prefix)
    lay = [f for f in layout if f[0] in cols]
    frames = []
    path = os.path.join(ROOT, 'data', 'jrdb', 'raw', f'{prefix}_2025.zip')
    with zipfile.ZipFile(path) as z:
        for n in sorted(x for x in z.namelist() if x.upper().endswith('.TXT')):
            frames.append(jrdb_read.parse_buf(z.read(n), lay, reclen,
                                              jrdb_read._day_from_name(n)))
    return pd.concat(frames, ignore_index=True)


cha = load_fast('CHA', CHA_COLS)
kyi = load_fast('KYI', KYI_COLS)
for df, cc in ((cha, '場コード'), (kyi, '場コード')):
    df['jyo_i'] = df[cc].astype(int)
for df in (cha, kyi):
    df['R'] = df['Ｒ'].astype(int)
    df['umaban'] = df['馬番'].astype(int)
    df['day'] = df['day'].astype(int)
for c in ('テンＦ', '中間Ｆ', '終いＦ', '調教Ｆ'):
    cha[c] = pd.to_numeric(cha[c], errors='coerce')

m = cha.merge(kyi[['day', 'jyo_i', 'R', 'umaban', '調教師所属']],
              on=['day', 'jyo_i', 'R', 'umaban'], how='left')
top_codes = cha['調教コースコード'].value_counts().head(8).index
print('== コースコード × 所属 クロス（主要コード） ==')
print(pd.crosstab(m.loc[m['調教コースコード'].isin(top_codes), '調教コースコード'],
                  m['調教師所属']).to_string())

# jravan training と照合 (調教年月日 = cho_date, ketto_num 経由)
con = sqlite3.connect(os.path.join(ROOT, 'data', 'jravan.db'))
res25 = pd.read_sql(
    "SELECT r.race_key, r.year, r.monthday, r.jyo, r.race_num,"
    " t.ketto_num, t.umaban FROM races r JOIN results t ON r.race_key=t.race_key"
    " WHERE r.jyo IN ('01','02','03','04','05','06','07','08','09','10')"
    "   AND r.surface IN ('芝','ダート') AND r.year='2025'", con)
tr = pd.read_sql("SELECT ketto_num, cho_date, t4f, lap_20 FROM training", con)
con.close()
tr['cho_date'] = pd.to_numeric(tr['cho_date'], errors='coerce')
res25['day'] = (res25['year'].astype(int) * 10000
                + pd.to_numeric(res25['monthday'], errors='coerce')).astype(int)
res25['jyo_i'] = res25['jyo'].astype(int)
res25['R'] = res25['race_num'].astype(int)
m2 = m.merge(res25[['day', 'jyo_i', 'R', 'umaban', 'ketto_num']],
             on=['day', 'jyo_i', 'R', 'umaban'], how='left')
m2 = m2.merge(tr, left_on=['ketto_num', '調教年月日'],
              right_on=['ketto_num', 'cho_date'], how='left')
hit = m2['t4f'].notna() & (m2['t4f'] > 0)
print(f'\njravan training 結合: {hit.sum():,}/{len(m2):,} ({hit.mean()*100:.1f}%)')
print('(trainingは2025-06〜のみ。6月以降の本追切ならほぼ結合するはず)')
late = m2['day'] >= 20250601
print(f'  うち6月以降: {(hit & late).sum():,}/{late.sum():,} ({(hit & late).sum()/late.sum()*100:.1f}%)')

print('\n== コード別: jravan t4f中央値 / lap_20中央値 / CHA終いＦ中央値 (結合行のみ) ==')
v = m2[hit].copy()
v['t4f_s'] = v['t4f'] / 10.0
v['lap1f'] = v['lap_20'] / 10.0
v['owari'] = v['終いＦ'] / 10.0
print(v.groupby('調教コースコード').agg(
    n=('t4f_s', 'size'), t4f_p50=('t4f_s', 'median'),
    lap1f_p50=('lap1f', 'median'), owari_p50=('owari', 'median'),
    f_mode=('調教Ｆ', lambda s: s.mode().iloc[0] if len(s.mode()) else np.nan),
).sort_values('n', ascending=False).head(12).to_string())

print('\n== 終いＦ(CHA) vs lap_20(jravan) の一致度 (参考) ==')
d = (v['owari'] - v['lap1f']).abs()
print(f'  |差|<=0.2秒: {(d<=0.2).mean()*100:.1f}%  中央差: {(v["owari"]-v["lap1f"]).median():.2f}秒')
