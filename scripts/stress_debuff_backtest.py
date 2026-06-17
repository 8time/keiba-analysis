# -*- coding: utf-8 -*-
"""🐎 Stress Analyst(乗算デバフ)の各条件を検証する。
仮説: 当日環境ストレス条件に該当する馬は『能力にリミッターが掛かり、人気のわりに走らない』
       =過剰評価(危険人気)。 測るもの: 条件発火馬の 複勝率/単ROI と 人気(オッズ)補正残差。
残差が負(z<-2)=本当に過剰評価で減点が正当 / 残差≈0=人気に織込み済み(=デバフ無意味) / 正=逆効果。
analystは『人気馬の罠あぶり出し』なので 全体 と 1-5番人気 の両方を見る。
test=2023-2025・JRA平地(芝/ダ)。"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


con = sqlite3.connect(DB)
cur = con.cursor()
rows = cur.execute(
    """SELECT r.waku, r.umaban, r.bataiju, r.zogen, r.kyakushitsu,
              r.chakujun, r.ninki, r.win_odds, ra.surface, ra.kyori
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND ra.year>='2023' AND ra.surface IN ('芝','ダート')
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10""").fetchall()
con.close()


# ── 検証する条件（appの A/B/C/D を当該走の属性で再現）──
def cond_A(waku, umaban, bataiju, zogen, kyaku, surf, kyori):
    return surf == 'ダート' and waku <= 3 and kyaku in ('3', '4')      # 砂かぶり(内枠×後方)


def cond_D(waku, umaban, bataiju, zogen, kyaku, surf, kyori):
    return surf == 'ダート' and kyori >= 1800 and waku <= 3            # 長距離ダ×内枠


def cond_B(waku, umaban, bataiju, zogen, kyaku, surf, kyori):
    return umaban % 2 == 1 and kyaku == '1'                           # 奇数枠×逃げ


def cond_C(waku, umaban, bataiju, zogen, kyaku, surf, kyori):
    return 0 < bataiju < 440 and zogen <= -6                          # 小柄馬×大幅馬体減


CONDS = {'A 砂かぶり(ダ内枠×後方)': cond_A, 'D 長ダ×内枠': cond_D,
         'B 奇数枠×逃げ': cond_B, 'C 小柄馬×馬体減6kg超': cond_C}


def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'r3': 0.0, 'rw': 0.0}


def add(d, chaku, o):
    d['n'] += 1
    if chaku <= 3:
        d['t3'] += 1
    if chaku == 1:
        d['w'] += 1; d['pay1'] += o
    d['r3'] += (1 if chaku <= 3 else 0) - e3(o)
    d['rw'] += (1 if chaku == 1 else 0) - e1(o)


def rep(name, d):
    n = max(d['n'], 1)
    se3 = (0.22 * 0.78 / n) ** 0.5
    se1 = (0.08 * 0.92 / n) ** 0.5
    z3 = (d['r3'] / n) / se3 if se3 else 0
    z1 = (d['rw'] / n) / se1 if se1 else 0
    print(f"  {name:18s} n={d['n']:6d} | 複勝率{d['t3']/n:6.2%} 単ROI{d['pay1']/n:6.1%} "
          f"| 複勝残差{d['r3']/n:+.4f}(z={z3:+.2f}) 勝残差{d['rw']/n:+.4f}(z={z1:+.2f})")


print("母集団 2023-2025・JRA平地（残差<0 かつ z<-2 = 過剰評価でデバフ正当）\n")
for cname, fn in CONDS.items():
    ALL, NINKI = agg(), agg()   # NINKI=1〜5番人気のみ(analystの主対象=危険人気)
    for waku, umaban, bataiju, zogen, kyaku, chaku, ninki, odds, surf, kyori in rows:
        if not odds or odds <= 0 or not ninki or ninki <= 0:
            continue
        waku = waku or 0; umaban = umaban or 0; bataiju = bataiju or 0
        zogen = zogen if zogen is not None else 0; kyori = kyori or 0
        kyaku = str(kyaku or '0')
        if fn(waku, umaban, bataiju, zogen, kyaku, surf, kyori):
            add(ALL, chaku, odds)
            if ninki <= 5:
                add(NINKI, chaku, odds)
    print(f"【{cname}】")
    rep("全体", ALL)
    rep("1-5番人気", NINKI)
    print()
