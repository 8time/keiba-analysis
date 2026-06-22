# -*- coding: utf-8 -*-
"""更新版 value_scanner.trio_lean の組み合わせ精度を検証。
leanの判定('②穴妙味向き'/'中立'/'本線向き')ごとに、実際の本線決着率・②型決着率を出し
分離しているか(=サーチ精度)を確認する。2021-25 平地 tosu>=8。"""
import os
import sys
import sqlite3
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import value_scanner as vs

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2021', '2022', '2023', '2024', '2025')

con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
yf = " OR ".join(["ra.year=?"] * len(YEARS))
rows = con.execute(
    f"""SELECT ra.race_key, ra.shusso_tosu, ra.juryo, ra.kyori, ra.surface,
               ra.baba_shiba, ra.baba_dirt, r.chakujun, r.ninki, r.win_odds
        FROM races ra JOIN results r ON r.race_key=ra.race_key
        WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14')
          AND ra.shusso_tosu>=8 AND r.chakujun>0""", YEARS).fetchall()
con.close()

races = {}
for (rk, tosu, juryo, kyori, surf, bsh, bdt, chaku, ninki, wo) in rows:
    d = races.setdefault(rk, {'tosu': tosu, 'juryo': juryo or '', 'kyori': kyori or 0,
                              'baba': str((bsh if (surf or '') == '芝' else bdt) or ''),
                              'horses': []})
    d['horses'].append({'chaku': chaku, 'ninki': ninki or 99, 'wo': wo or 0})

_BABA = {'3': '重', '4': '不良'}
buckets = defaultdict(lambda: {'n': 0, 'hon': 0, 'ana': 0})
score_buckets = defaultdict(lambda: {'n': 0, 'hon': 0, 'ana': 0})
for rk, d in races.items():
    hs = d['horses']
    odds = [h['wo'] for h in hs if h['wo'] and h['wo'] > 0]
    if len(odds) < 3:
        continue
    top3 = [h for h in hs if h['chaku'] <= 3]
    hon = 1 if (any(h['ninki'] == 1 and h['chaku'] <= 3 for h in hs)
                and any(h['ninki'] == 2 and h['chaku'] <= 3 for h in hs)) else 0
    ana = 1 if sum(1 for h in top3 if h['ninki'] >= 5) >= 2 else 0
    meta = {'is_handicap': d['juryo'] == '1'}
    res = vs.trio_lean(meta=meta, n_horses=d['tosu'], fav_odds=min(odds),
                       dist=d['kyori'], baba=_BABA.get(d['baba']), odds_list=odds)
    b = buckets[res['lean']]
    b['n'] += 1; b['hon'] += hon; b['ana'] += ana
    sc = int(round(res['score']))
    sb = score_buckets[max(-4, min(4, sc))]
    sb['n'] += 1; sb['hon'] += hon; sb['ana'] += ana

tot = sum(b['n'] for b in buckets.values())
thon = sum(b['hon'] for b in buckets.values())
tana = sum(b['ana'] for b in buckets.values())
print(f"母集団 n={tot:,}  本線{thon/tot*100:.1f}%  ②型{tana/tot*100:.1f}%\n")
print("【lean判定別】サーチ精度=判定が実決着率を分離できているか")
print(f"{'lean':<14}{'n':>7}{'本線%':>8}{'②型%':>8}  解釈")
for lean in ('本線向き', '中立', '②穴妙味向き'):
    b = buckets[lean]
    if b['n']:
        print(f"{lean:<14}{b['n']:>7}{b['hon']/b['n']*100:>8.1f}{b['ana']/b['n']*100:>8.1f}")
print("\n→ 本線向きで本線%が母集団超・②穴妙味向きで②型%が母集団超なら精度向上の証拠。")
print("\n【leanスコア勾配】(単調なら良)")
print(f"{'score':>6}{'n':>7}{'本線%':>8}{'②型%':>8}")
for s in range(-4, 5):
    sb = score_buckets[s]
    if sb['n'] >= 50:
        print(f"{s:>+6}{sb['n']:>7}{sb['hon']/sb['n']*100:>8.1f}{sb['ana']/sb['n']*100:>8.1f}")
