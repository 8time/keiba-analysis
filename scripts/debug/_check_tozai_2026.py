# -*- coding: utf-8 -*-
"""栗東坂路52.7-12.2 の recent(2026) 符号確認。
jravan training(〜2026-06)の t4f 二峰性で坂路帯(48-60秒)を抽出し、
tozai=栗東 に限定。CHA不要の代理検証。"""
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

Z_SE_P = 15.4
con = sqlite3.connect(os.path.join(ROOT, 'data', 'jravan.db'))
df = pd.read_sql(
    "SELECT r.race_key, r.year, r.monthday, r.jyo, t.ketto_num, t.umaban,"
    " t.chakujun, t.ninki, t.ijo, t.tozai"
    " FROM races r JOIN results t ON r.race_key = t.race_key"
    " WHERE r.jyo IN ('01','02','03','04','05','06','07','08','09','10')"
    "   AND r.surface IN ('芝','ダート') AND r.year IN ('2021','2022','2023','2024','2025','2026')", con)
tr = pd.read_sql("SELECT ketto_num, cho_date, t4f, lap_20 FROM training", con)
con.close()
print('tozai values:', df['tozai'].value_counts().head(6).to_dict())

df['day'] = (df['year'].astype(int) * 10000
             + pd.to_numeric(df['monthday'], errors='coerce')).astype(int)
df['dt'] = pd.to_datetime(df['day'], format='%Y%m%d', errors='coerce')
df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
df['valid'] = (df['ijo'].astype(str) == '0') & df['chakujun'].between(1, 30)

trn = df[df['valid'] & df['year'].astype(int).between(2021, 2024) & df['ninki'].between(1, 18)]
base = trn.assign(t3=trn['chakujun'] <= 3).groupby('ninki')['t3'].mean()

# 直近7日以内の追切(坂路帯のみ)を各出走に紐付け
tr2 = tr[tr['t4f'].between(480, 600)].copy()  # 坂路帯のみ
tr2['cho_dt'] = pd.to_datetime(pd.to_numeric(tr2['cho_date'], errors='coerce'),
                               format='%Y%m%d', errors='coerce')
tr2 = tr2[tr2['lap_20'] > 0].sort_values('cho_dt')

# tozai コード確認: 2025行にKYI調教師所属を結合して対応を見る
import zipfile
from scripts import jrdb_read
lay = [f for f in jrdb_read.build_layout('KYI')[0] if f[0] in ('場コード', 'Ｒ', '馬番', '調教師所属')]
frames = []
with zipfile.ZipFile(os.path.join(ROOT, 'data', 'jrdb', 'raw', 'KYI_2025.zip')) as z:
    for n in sorted(x for x in z.namelist() if x.upper().endswith('.TXT'))[:10]:
        frames.append(jrdb_read.parse_buf(z.read(n), lay, 1024, jrdb_read._day_from_name(n)))
kyi = pd.concat(frames, ignore_index=True)
kyi['day'] = kyi['day'].astype(int)
kyi['jyo_i'] = kyi['場コード'].astype(int)
kyi['R'] = kyi['Ｒ'].astype(int)
kyi['umaban'] = kyi['馬番'].astype(int)
chk = df[df['year'] == '2025'].copy()
chk['jyo_i'] = chk['jyo'].astype(int)
chk['R'] = pd.to_numeric(chk['race_key'].astype(str).str[-2:], errors='coerce')
chk = chk.merge(kyi[['day', 'jyo_i', 'R', 'umaban', '調教師所属']],
                on=['day', 'jyo_i', 'R', 'umaban'], how='left')
print(pd.crosstab(chk['tozai'], chk['調教師所属']).to_string())

ev = df[df['day'].between(20260101, 20260630)].copy()
print(f'2026年1-6月 出走行: {len(ev):,}')
ev = ev.sort_values('dt')
m = pd.merge_asof(ev, tr2[['ketto_num', 'cho_dt', 't4f', 'lap_20']],
                  left_on='dt', right_on='cho_dt', by='ketto_num',
                  direction='backward', tolerance=pd.Timedelta('7D'))
have = m['t4f'].notna()
print(f'直近7日内に坂路帯追切あり: {have.sum():,}')

def stats(sub):
    sub = sub[sub['valid'] & sub['ninki'].between(1, 18)]
    n = len(sub)
    if n == 0:
        return 'n=0'
    top3 = (sub['chakujun'] <= 3).mean() * 100
    exp = sub['ninki'].map(base).mean() * 100
    z = (top3 - exp) / (Z_SE_P / np.sqrt(n))
    return f'n={n:,} 複勝{top3:.1f}% (基準{exp:.1f}%) 残差{top3-exp:+.1f}pp z={z:+.1f}'

ritto = m['tozai'].astype(str).str.strip() == '2'  # tozai '2'=栗東(クロス集計で確認済)
cond = have & ritto & (m['t4f'] <= 527) & (m['lap_20'] <= 122)
print('\n== recent 2026.1-6 栗東&坂路帯(48-60) ==')
print('  t4f<=52.7 & lap<=12.2 :', stats(m[cond]))
print('  それ以外の栗東坂路帯   :', stats(m[have & ritto & ~cond]))
# 2025下半期を同じ代理手順で再現（手順の妥当性確認: CHA正確版は+2.3pp z2.5だった）
ev25 = df[df['day'].between(20250701, 20251231)].copy().sort_values('dt')
m25 = pd.merge_asof(ev25, tr2[['ketto_num', 'cho_dt', 't4f', 'lap_20']],
                    left_on='dt', right_on='cho_dt', by='ketto_num',
                    direction='backward', tolerance=pd.Timedelta('7D'))
ritto25 = m25['tozai'].astype(str).str.strip() == '2'
have25 = m25['t4f'].notna()
cond25 = have25 & ritto25 & (m25['t4f'] <= 527) & (m25['lap_20'] <= 122)
print('\n== 同一代理手順の2025下半期(CHA正確版 +2.3pp z2.5 の再現確認) ==')
print('  t4f<=52.7 & lap<=12.2 :', stats(m25[cond25]))
