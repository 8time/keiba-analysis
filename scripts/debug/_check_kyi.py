# -*- coding: utf-8 -*-
"""KYI_2025.zip の実データ確認: 放牧先/放牧先ランク/入厩年月日/入厩何日前 の充足と値例"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8')

from scripts import jrdb_read

df = jrdb_read.load('KYI', limit_files=6)
print(f'{len(df):,}行 x {len(df.columns)}列  day={df["day"].min()}〜{df["day"].max()}')

for c in ('場コード', '年', '回', '日', 'Ｒ', '馬番', '血統登録番号', '馬名',
          '入厩何走目', '入厩年月日', '入厩何日前', '放牧先', '放牧先ランク',
          'ブリンカー', '降級フラグ', '条件クラス', 'クラスコード', '輸送区分'):
    if c not in df.columns:
        print(f'{c}: **列なし**')
        continue
    s = df[c]
    if s.dtype == object:
        fill = (s.astype(str).str.strip() != '').mean()
    else:
        fill = s.notna().mean()
    ex = df.loc[s.astype(str).str.strip() != '', c].head(3).tolist() if s.dtype == object else s.dropna().head(3).tolist()
    print(f'{c:12s} 充足{fill*100:6.1f}%  例={ex}')

print('\n== 放牧先の値の分布(top20) ==')
print(df['放牧先'].value_counts().head(20))

print('\n== 放牧先ランク ==')
print(df['放牧先ランク'].value_counts())

print('\n== 入厩何日前の分布 ==')
print(df['入厩何日前'].value_counts().sort_index().head(30))

print('\n== 入厩年月日 ==')
print(df['入厩年月日'].describe())
