# -*- coding: utf-8 -*-
"""既存verified_heavy_track_bias(重不良×1番人気=危険)を血統で精緻化できるか検証。
既存は血統不問で全1番人気を危険判定。仮説:
  FADE血統(サンデー瞬発/ステゴ系)=危険を維持/強化、
  WETPOWER血統(シニミニ等高含水○)=ダ不良でも沈まない→危険免除すべき(既存の偽陽性)。
対象: 1番人気(主)・1-3番人気(補)、芝/ダ × 重/不良、2016+。"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)
e3 = lambda o: (exp.get(jj._odds_band(o)) or {}).get('top3', 0.22)
e1 = lambda o: (exp.get(jj._odds_band(o)) or {}).get('win', 0.08)

FADE_SIRES = ['ディープインパクト', 'ハーツクライ', 'ダイワメジャー', 'エピファネイア',
              'ステイゴールド', 'オルフェーヴル', 'ディープブリランテ', 'リアルインパクト',
              'サンデーサイレンス', 'ドゥラメンテ']
WETPOWER_SIRES = ['シニスターミニスター', 'ヘニーヒューズ', 'パイロ', 'マジェスティックウォリアー',
                  'カレンブラックヒル', 'ダノンレジェンド']


def classify(sire):
    if not sire:
        return None
    if any(s in sire for s in WETPOWER_SIRES):
        return 'WETPOWER(高含水○)'
    if any(s in sire for s in FADE_SIRES):
        return 'FADE(瞬発/ステゴ)'
    return 'その他'


def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'r3': 0.0, 'rw': 0.0}


def add(d, chaku, o):
    d['n'] += 1
    d['t3'] += chaku <= 3
    d['w'] += chaku == 1
    d['pay1'] += o if chaku == 1 else 0
    d['r3'] += (1 if chaku <= 3 else 0) - e3(o)
    d['rw'] += (1 if chaku == 1 else 0) - e1(o)


def rep(name, d, ind=4):
    n = max(d['n'], 1)
    se3 = (0.22 * 0.78 / n) ** 0.5
    z3 = (d['r3'] / n) / se3 if se3 else 0
    print(f"{' '*ind}{name:18s} n={d['n']:5d} | 複勝率{d['t3']/n:6.2%} 単ROI{d['pay1']/n:6.1%} "
          f"| 複勝残差{d['r3']/n:+.4f}(z={z3:+.2f})")


con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
sire_of = {str(k): s for k, s in con.execute("SELECT ketto_num, sire FROM horses").fetchall()}
rows = con.execute(
    """SELECT r.ketto_num, r.chakujun, r.ninki, r.win_odds, ra.surface,
              ra.baba_shiba, ra.baba_dirt
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND r.win_odds>0 AND r.ninki BETWEEN 1 AND 3
         AND ra.surface IN ('芝','ダート') AND ra.year>='2016'""").fetchall()
con.close()

# cell: (surf, baba, ninki_scope, grp) -> agg
BABA = {3: '重', 4: '不良'}
cells = defaultdict(agg)
for ketto, chaku, ninki, odds, surf, bsh, bdt in rows:
    v = bsh if surf == '芝' else bdt
    try:
        v = int(v)
    except Exception:
        continue
    if v not in BABA:
        continue
    grp = classify(sire_of.get(str(ketto)))
    sf = '芝' if surf == '芝' else 'ダ'
    for scope in (('1番', ninki == 1), ('1-3番', True)):
        if scope[1]:
            add(cells[(sf, BABA[v], scope[0], grp)], chaku, odds)
            add(cells[(sf, BABA[v], scope[0], '★全体')], chaku, odds)

print("=== 重不良×人気馬 血統内訳 (既存heavy_track_bias精緻化の検証, 2016+) ===")
print("既存: 芝重×1番-5.57pp / 芝不良×1番-9.23pp / ダ不良×1番-3.66pp (血統不問)")
print("→ FADEが全体より下/WETPOWERが上(or正)なら血統条件化が有効\n")

for sf, baba in (('芝', '重'), ('芝', '不良'), ('ダ', '重'), ('ダ', '不良')):
    for scope in ('1番', '1-3番'):
        print(f"■ {sf}{baba} × {scope}人気")
        for grp in ('★全体', 'FADE(瞬発/ステゴ)', 'WETPOWER(高含水○)', 'その他'):
            d = cells[(sf, baba, scope, grp)]
            if d['n'] >= 12:
                rep(grp, d)
        print()
