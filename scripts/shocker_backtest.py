# -*- coding: utf-8 -*-
"""Mの法則「短縮ショッカー」「逆ショッカー」の検証。
主張: 短縮ショッカー=馬連回収600%超 / 逆ショッカー=単勝回収100%超。
測るもの: 該当馬の【その対象レース】での 勝率/複勝率/単ROI と 人気(オッズ)補正残差。
残差≈0=人気に織込み済み(妙味なし) / 負=過剰人気 / 正かつz>+2=本物の妙味。
test=2023-2025・JRA平地。前走・履歴は2020以降まで遡って参照。"""
import os
import sys
import sqlite3
from datetime import date
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)
e3 = lambda o: (exp.get(jj._odds_band(o)) or {'top3': .22})['top3']
e1 = lambda o: (exp.get(jj._odds_band(o)) or {'win': .08})['win']

con = sqlite3.connect(DB)
rows = con.execute(
    """SELECT r.bamei, ra.year, ra.monthday, ra.kyori, ra.surface,
              r.corner3, r.chakujun, r.ninki, r.win_odds
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート') AND ra.year>='2020'
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
       ORDER BY r.bamei, ra.year, ra.monthday""").fetchall()
con.close()


def ord_days(y, md):
    try:
        return date(int(y), int(md[:2]), int(md[2:])).toordinal()
    except Exception:
        return 0


by_horse = defaultdict(list)
for bamei, y, md, kyori, surf, c3, chaku, ninki, odds in rows:
    by_horse[bamei].append({
        'd': ord_days(y, md), 'kyori': kyori or 0, 'surf': surf, 'c3': c3 or 0,
        'chaku': chaku, 'ninki': ninki or 0, 'odds': odds or 0, 'year': y})


def shorten_shocker(hist, i):
    """短縮ショッカー: 4条件"""
    if i == 0:
        return False
    cur, prev = hist[i], hist[i - 1]
    if not (prev['kyori'] > cur['kyori']):              # ①前走が今回より長い
        return False
    if not (0 < prev['c3'] <= 5):                       # ③前走3角5番手以内
        return False
    # ②今回距離以下で連対歴(今回より前の全走)
    if not any(p['chaku'] <= 2 and 0 < p['kyori'] <= cur['kyori'] for p in hist[:i]):
        return False
    # ④7ヶ月(≈210日)以内に同じ馬場を経験
    if not any(p['surf'] == cur['surf'] and 0 < (cur['d'] - p['d']) <= 210 for p in hist[:i]):
        return False
    return True


def reverse_shocker(hist, i):
    """逆ショッカー: 3条件(今回3角は結果を使用=主張の検証)"""
    if i == 0:
        return False
    cur, prev = hist[i], hist[i - 1]
    if not (0 < prev['c3'] and prev['c3'] >= 5):        # ①前走3角5番手以降
        return False
    if not (cur['kyori'] < prev['kyori']):              # ②距離短縮
        return False
    if not (0 < cur['c3'] <= 8):                        # ③今回3角8番手以内
        return False
    return True


def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'r3': 0.0, 'rw': 0.0}


def add(d, c):
    o = c['odds']
    d['n'] += 1
    if c['chaku'] <= 3:
        d['t3'] += 1
    if c['chaku'] == 1:
        d['w'] += 1; d['pay1'] += o
    d['r3'] += (1 if c['chaku'] <= 3 else 0) - e3(o)
    d['rw'] += (1 if c['chaku'] == 1 else 0) - e1(o)


def rep(name, d):
    n = max(d['n'], 1)
    se3 = (.22 * .78 / n) ** .5
    se1 = (.08 * .92 / n) ** .5
    print(f"  {name:16s} n={d['n']:6d} | 勝率{d['w']/n:6.2%} 複勝率{d['t3']/n:6.2%} "
          f"単ROI{d['pay1']/n:6.1%} | 複残差{d['r3']/n:+.4f}(z={d['r3']/n/se3:+.2f}) "
          f"勝残差{d['rw']/n:+.4f}(z={d['rw']/n/se1:+.2f})")


ALL = agg()
SS, SS_ana = agg(), agg()   # 短縮ショッカー: 全該当 / 6番人気以下(穴)
RS, RS_ana = agg(), agg()   # 逆ショッカー
for bamei, hist in by_horse.items():
    for i, cur in enumerate(hist):
        if cur['year'] < '2023' or cur['odds'] <= 0 or cur['ninki'] <= 0:
            continue
        add(ALL, cur)
        if shorten_shocker(hist, i):
            add(SS, cur)
            if cur['ninki'] >= 6:
                add(SS_ana, cur)
        if reverse_shocker(hist, i):
            add(RS, cur)
            if cur['ninki'] >= 6:
                add(RS_ana, cur)

print("検証 2023-2025・JRA平地（残差z>+2 かつ ROI高 = 本物の妙味 / 残差≈0 = 織込み済み）\n")
rep("母集団(全馬)", ALL)
print("\n【短縮ショッカー】(主張: 馬連600%)")
rep("全該当", SS)
rep("6番人気以下(穴)", SS_ana)
print("\n【逆ショッカー】(主張: 単回収100%超)")
rep("全該当", RS)
rep("6番人気以下(穴)", RS_ana)
