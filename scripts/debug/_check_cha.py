# -*- coding: utf-8 -*-
"""CHA_2025.zip の実データ確認: 調教コースコードの時計特徴と所属別内訳"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from scripts import jrdb_read

CHA_COLS = ['場コード', 'Ｒ', '馬番', '曜日', '調教年月日', '回数', '調教コースコード',
            '追切種類', '追い状態', '乗り役', '調教Ｆ', 'テンＦ', '中間Ｆ', '終いＦ',
            '終いＦ指数', '追切指数', '併せ結果']
KYI_COLS = ['場コード', 'Ｒ', '馬番', '調教師所属']


def load_fast(prefix, cols, limit=None):
    layout, reclen, _ = jrdb_read.build_layout(prefix)
    lay = [f for f in layout if f[0] in cols]
    frames = []
    import zipfile
    path = os.path.join(ROOT, 'data', 'jrdb', 'raw', f'{prefix}_2025.zip')
    with zipfile.ZipFile(path) as z:
        names = sorted(x for x in z.namelist() if x.upper().endswith('.TXT'))
        if limit:
            names = names[:limit]
        for n in names:
            frames.append(jrdb_read.parse_buf(z.read(n), lay, reclen,
                                              jrdb_read._day_from_name(n)))
    return pd.concat(frames, ignore_index=True)


cha = load_fast('CHA', CHA_COLS)
kyi = load_fast('KYI', KYI_COLS)
print(f'CHA {len(cha):,}行 / KYI {len(kyi):,}行')

for c in ('テンＦ', '中間Ｆ', '終いＦ', '調教Ｆ', '追切指数', '終いＦ指数'):
    cha[c] = pd.to_numeric(cha[c], errors='coerce')
cha['total_f'] = cha['テンＦ'] + cha['中間Ｆ'] + cha['終いＦ']

print('\n== 調教コースコード別の時計特徴 ==')
g = cha.groupby('調教コースコード').agg(
    n=('場コード', 'size'),
    f_mode=('調教Ｆ', lambda s: s.mode().iloc[0] if len(s.mode()) else np.nan),
    total_mean=('total_f', 'mean'),
    total_p50=('total_f', 'median'),
    last1f_p50=('終いＦ', 'median'),
)
print(g.sort_values('n', ascending=False).to_string())

print('\n== 追切種類 ==')
print(cha['追切種類'].value_counts())
print('\n== 併せ結果 ==')
print(cha['併せ結果'].value_counts(dropna=False))
print('\n== 調教師所属(KYI) ==')
print(kyi['調教師所属'].value_counts())

# コード×所属のクロス(時計特徴つき)
kyi['場コード'] = kyi['場コード'].astype(int)
kyi['Ｒ'] = kyi['Ｒ'].astype(int)
kyi['馬番'] = kyi['馬番'].astype(int)
kyi['day'] = kyi['day'].astype(int)
m = cha.merge(kyi[['day', '場コード', 'Ｒ', '馬番', '調教師所属']],
              on=['day', '場コード', 'Ｒ', '馬番'], how='left')
print('\n== コースコード × 調教師所属 クロス(n) ==')
print(pd.crosstab(m['調教コースコード'], m['調教師所属']).to_string())
print('\n== コースコード別 4F合計の中央値(調教Ｆ=4のみ) / 終い1F中央値 ==')
sub = m[m['調教Ｆ'] == 4]
print(sub.groupby('調教コースコード').agg(
    n=('場コード', 'size'), total_p50=('total_f', 'median'),
    last1f_p50=('終いＦ', 'median')).to_string())
