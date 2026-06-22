# -*- coding: utf-8 -*-
"""POWER側(米国型/シニミニ)の道悪エッジを 含水率 vs baba-code で切り分け再検証。
矛盾: 既存 track_bias._DRY_DIRT_SIRES はシニミニ=乾燥○/高含水×(BT検証済)。
      一方 baba_blood_backtest はシニミニ人気馬が道悪(baba稍重/重/不良)で複勝残差+0.131。
仮説: ダートの「稍重」は散水・シールドの高速馬場(低含水)で、含水率>=8%の深い砂とは別物。
対象: ダートのみ・1-3番人気・track_cond(含水率)のある日。"""
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

US_SIRES = ['シニスターミニスター', 'ダノンレジェンド', 'ヘニーヒューズ', 'パイロ',
            'マジェスティックウォリアー', 'カレンブラックヒル']
POWER_SIRES = US_SIRES + ['ハービンジャー', 'ルーラーシップ', 'スクリーンヒーロー',
            'シンボリクリスエス', 'ブライアンズタイム', 'モーリス', 'ノヴェリスト',
            'ディーマジェスティ', 'キズナ']  # ステゴ系は除外(fade側と判明)


def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'r3': 0.0, 'rw': 0.0}


def add(d, chaku, o):
    d['n'] += 1
    d['t3'] += chaku <= 3
    d['w'] += chaku == 1
    d['pay1'] += o if chaku == 1 else 0
    d['r3'] += (1 if chaku <= 3 else 0) - e3(o)
    d['rw'] += (1 if chaku == 1 else 0) - e1(o)


def rep(name, d, ind=2):
    n = max(d['n'], 1)
    se3 = (0.22 * 0.78 / n) ** 0.5
    z3 = (d['r3'] / n) / se3 if se3 else 0
    print(f"{' '*ind}{name:16s} n={d['n']:5d} | 複勝率{d['t3']/n:6.2%} 単ROI{d['pay1']/n:6.1%} "
          f"| 複勝残差{d['r3']/n:+.4f}(z={z3:+.2f}) 勝残差{d['rw']/n:+.4f}")


con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
sire_of = {str(k): s for k, s in con.execute("SELECT ketto_num, sire FROM horses").fetchall()}
moist = {(y, md, jyo): dm for y, md, jyo, dm in
         con.execute("SELECT year, monthday, jyo, dirt_moisture FROM track_cond "
                     "WHERE dirt_moisture IS NOT NULL").fetchall()}

rows = con.execute(
    """SELECT r.ketto_num, r.chakujun, r.ninki, r.win_odds, ra.baba_dirt,
              ra.year, ra.monthday, ra.jyo
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND r.win_odds>0 AND r.ninki BETWEEN 1 AND 3
         AND ra.surface='ダート' AND ra.year>='2018'""").fetchall()
con.close()


def mbucket(m):
    if m is None:
        return None
    if m <= 4.0:
        return '乾燥<=4'
    if m < 8.0:
        return '中4-8'
    return '高含水>=8'


def classify(sire):
    if not sire:
        return None
    if 'シニスターミニスター' in sire:
        return 'シニミニ単体'
    if any(s in sire for s in US_SIRES):
        return '米国型(他)'
    if any(s in sire for s in POWER_SIRES):
        return '欧州/ロベルト系'
    return None


BABA = {1: '良', 2: '稍重', 3: '重', 4: '不良'}
# Q1: baba_dirt別の平均含水率
baba_moist = defaultdict(list)
# Q2: group × moisture bucket
GM = defaultdict(lambda: defaultdict(agg))
# Q3: group × baba × moisture (シニミニ稍重の含水率分布)
GBM = defaultdict(lambda: defaultdict(lambda: defaultdict(agg)))
# baselineも(全ダート人気馬) moisture別
ALLM = defaultdict(agg)
ALLB = defaultdict(agg)

for ketto, chaku, ninki, odds, bd, y, md, jyo in rows:
    try:
        bd = int(bd)
    except Exception:
        continue
    if bd not in BABA:
        continue
    m = moist.get((y, md, jyo))
    grp = classify(sire_of.get(str(ketto)))
    add(ALLB[BABA[bd]], chaku, odds)
    if m is not None:
        baba_moist[BABA[bd]].append(m)
        add(ALLM[mbucket(m)], chaku, odds)
    if grp:
        if m is not None:
            add(GM[grp][mbucket(m)], chaku, odds)
            add(GBM[grp][BABA[bd]][mbucket(m)], chaku, odds)

print("=== POWER側 含水率 vs baba 切り分け (ダート・1-3番人気・2018+) ===\n")

print("【Q1】baba_dirtコード別の平均含水率(%) ※稍重が低含水=散水高速ダートか?")
for b in ('良', '稍重', '重', '不良'):
    ms = baba_moist[b]
    if ms:
        ms_sorted = sorted(ms)
        med = ms_sorted[len(ms_sorted)//2]
        print(f"  {b:4s} n={len(ms):5d} 平均{sum(ms)/len(ms):5.1f}% 中央{med:5.1f}% "
              f"min{min(ms):4.1f} max{max(ms):4.1f}")

print("\n【基準】全ダート人気馬(1-3番) baba別 と 含水率別")
for b in ('良', '稍重', '重', '不良'):
    rep('baba:'+b, ALLB[b])
print()
for mb in ('乾燥<=4', '中4-8', '高含水>=8'):
    rep('含水:'+mb, ALLM[mb])

print("\n【Q2】グループ × 含水率バケツ (既存『乾燥○/高含水×』の真偽)")
for g in ('シニミニ単体', '米国型(他)', '欧州/ロベルト系'):
    print(f"\n■ {g}")
    for mb in ('乾燥<=4', '中4-8', '高含水>=8'):
        d = GM[g][mb]
        if d['n'] >= 15:
            rep(mb, d, 4)

print("\n【Q3】シニミニ単体 baba×含水率 (道悪+0.131の正体)")
for b in ('良', '稍重', '重', '不良'):
    for mb in ('乾燥<=4', '中4-8', '高含水>=8'):
        d = GBM['シニミニ単体'][b][mb]
        if d['n'] >= 10:
            rep(f"{b}/{mb}", d, 4)

print("\n→ 既存_DRY_DIRT_SIRES(含水率)とbaba-道悪の矛盾を、どちらの軸で測るかで判定。")
