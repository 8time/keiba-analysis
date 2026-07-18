# -*- coding: utf-8 -*-
"""荒れ予報メッセージの発火条件検証: 現行lean=='②' vs lean OR arare_prob>=θ。
target=arareA(3着内に7番人気以下=メッセージ文言と一致)。holdoutで recall/precision/lift。"""
import sys, os, json, math
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'scripts')
sys.path.insert(0, '.')
import csv_data
import pandas as pd

df = csv_data.load_races(with_period=True)
P = json.load(open('data/scanner_arare_logit.json', encoding='utf-8'))
mu, sd, coef, b, feats = P['mu'], P['sd'], P['coef'], P['intercept'], P['features']

def arare_prob(row):
    z = b
    for f in feats:
        s = sd[f] if sd[f] else 1.0
        try:
            z += coef[f] * ((float(row[f]) - mu[f]) / s)
        except Exception:
            return None
    return 1.0/(1.0+math.exp(-z))

df['ap'] = df.apply(arare_prob, axis=1)
df = df[df['ap'].notna()].copy()
# period列の値確認
print('period値:', df['period'].value_counts().to_dict() if 'period' in df.columns else 'なし')

# holdout = 2025以降(period列 or day)
if 'period' in df.columns and (df['period']=='holdout').any():
    ho = df[df['period']=='holdout'].copy()
else:
    ho = df[df['day'].astype(str).str[:4] >= '2025'].copy()
print(f'holdout レース数: {len(ho)}')

y = ho['arareA'].astype(int)
base = y.mean()
print(f'\nベース arareA率(全holdout): {base:.1%}  (top7圏外に3着馬が来るレース割合)')

A = (ho['lean_label'] == '②穴妙味向き')

def report(name, fire):
    fire = fire.astype(bool)
    n_fire = fire.sum()
    if n_fire == 0:
        print(f'{name:32s} 発火0'); return
    prec = y[fire].mean()          # 発火レースでarareAが起きた率
    rec = (fire & (y==1)).sum()/max((y==1).sum(),1)  # arareAレースを発火で捉えた率
    lift = prec/base
    print(f'{name:32s} 発火{n_fire:4d}R({n_fire/len(ho):4.0%})  precision{prec:5.1%}  recall{rec:5.1%}  lift{lift:.2f}')

print('\n=== target: arareA (top7圏外に3着馬) ===')
report('現行: lean==②のみ', A)
for th in (0.70, 0.65, 0.62, 0.60, 0.55):
    B = A | (ho['ap'] >= th)
    report(f'lean② OR arare_prob>={th}', B)
print('  (参考) arare_prob単独:')
for th in (0.70, 0.65, 0.62, 0.60):
    report(f'  arare_prob>={th} のみ', ho['ap'] >= th)

# 副次: ana2(②型決着)でも見る
print('\n=== 副次 target: ana2 (3着内に5番人気以下2頭=②型決着) ===')
y2 = ho['ana2'].astype(int); base2 = y2.mean()
print(f'ベース ana2率: {base2:.1%}')
def report2(name, fire):
    fire=fire.astype(bool); n=fire.sum()
    if n==0: print(f'{name:32s} 発火0'); return
    prec=y2[fire].mean(); rec=(fire&(y2==1)).sum()/max((y2==1).sum(),1)
    print(f'{name:32s} precision{prec:5.1%}  recall{rec:5.1%}  lift{prec/base2:.2f}')
report2('現行: lean==②のみ', A)
for th in (0.65, 0.62, 0.60):
    report2(f'lean② OR arare_prob>={th}', A | (ho['ap']>=th))
