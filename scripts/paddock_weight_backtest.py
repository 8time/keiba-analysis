# -*- coding: utf-8 -*-
"""パドック定量(馬体重/増減)の回収率検証。
「パドックで馬のここを見ろ」のうち、過去データで検証できる唯一の定量=馬体重(bataiju)/
増減(zogen)。発走前公開＝事前確定でリーク無し。複勝残差(オッズ統制)＋z＋単勝ROIで、
オッズに織込まれていない妙味があるかを測る(主観項目=歩様/発汗等は履歴が無く検証不可)。

軸: 増減バケツ × 馬体重水準 × 人気帯。2021-25 JRA平地。
※[[verified_stress_debuff]]で小柄×馬体減-2.0pp/馬体増+8kg-1.0pp(係数のみ)は既出。ここは
  単体ROI/残差を広く掃いて『回収率を上げる独立エッジか』を確認する。"""
import os
import sys
import math
import sqlite3
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)
e3 = lambda o: (exp.get(jj._odds_band(o)) or {}).get('top3', 0.22)
e1 = lambda o: (exp.get(jj._odds_band(o)) or {}).get('win', 0.08)


def zo_bucket(z):
    if z <= -10:
        return '大幅減≤-10'
    if z <= -3:
        return '減-3〜-9'
    if z <= 2:
        return '維持-2〜+2'
    if z <= 9:
        return '増+3〜+9'
    return '大幅増≥+10'


def wt_level(w):
    if w <= 440:
        return '小型≤440'
    if w <= 499:
        return '中441-499'
    return '大型≥500'


def band(n):
    if n <= 3:
        return '1-3番'
    if n <= 5:
        return '4-5番'
    if n <= 9:
        return '6-9番'
    return '10番〜'


def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'r3': 0.0, 'var': 0.0}


def add(d, chaku, o):
    d['n'] += 1
    d['t3'] += chaku <= 3
    d['w'] += chaku == 1
    d['pay1'] += o if chaku == 1 else 0
    d['r3'] += (1 if chaku <= 3 else 0) - e3(o)
    d['var'] += e3(o) * (1 - e3(o))


def rep(name, d, ind=2):
    n = max(d['n'], 1)
    z = d['r3'] / math.sqrt(d['var']) if d['var'] > 0 else 0
    print(f"{' '*ind}{name:16s} n={d['n']:7d} 複勝率{d['t3']/n:6.2%} 単ROI{d['pay1']/n:6.1%} "
          f"複勝残差{d['r3']/n:+.4f}(z={z:+.2f})")


con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
rows = con.execute(
    """SELECT r.chakujun, r.ninki, r.win_odds, r.bataiju, r.zogen
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND r.win_odds>0 AND r.ninki>0 AND r.bataiju>0 AND r.zogen IS NOT NULL
         AND ra.surface IN ('芝','ダート') AND ra.year>='2021'
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10""").fetchall()
con.close()

BY_ZO = defaultdict(agg)
BY_WT = defaultdict(agg)
BY_ZO_BAND = defaultdict(lambda: defaultdict(agg))
INTER = defaultdict(agg)  # (wt,zo) 小型×減 等
for chaku, ninki, wo, bw, zg in rows:
    zb = zo_bucket(zg); wl = wt_level(bw); bd = band(ninki)
    add(BY_ZO[zb], chaku, wo)
    add(BY_WT[wl], chaku, wo)
    add(BY_ZO_BAND[zb][bd], chaku, wo)
    add(INTER[(wl, zb)], chaku, wo)

print(f"=== パドック定量(馬体重/増減) 回収率検証 (2021-25 JRA平地 n={len(rows):,}) ===")
print("残差>0&z>+2=オッズ超の妙味 / ≈0=織込み済み / 単ROIは控除後ベース\n")
print("【増減バケツ別】")
for k in ('大幅減≤-10', '減-3〜-9', '維持-2〜+2', '増+3〜+9', '大幅増≥+10'):
    rep(k, BY_ZO[k])
print("\n【馬体重水準別】")
for k in ('小型≤440', '中441-499', '大型≥500'):
    rep(k, BY_WT[k])
print("\n【増減×人気帯(妙味は人気薄に出やすい)】")
for k in ('大幅減≤-10', '増+3〜+9', '大幅増≥+10'):
    print(f" ■{k}")
    for bd in ('1-3番', '4-5番', '6-9番', '10番〜'):
        if BY_ZO_BAND[k][bd]['n'] >= 100:
            rep(bd, BY_ZO_BAND[k][bd], 4)
print("\n【馬体重水準×増減(stress_debuff既出の確認)】")
for wl in ('小型≤440', '大型≥500'):
    for zb in ('大幅減≤-10', '大幅増≥+10'):
        d = INTER[(wl, zb)]
        if d['n'] >= 100:
            rep(f"{wl}×{zb}", d, 2)
print("\n→ z>+2の独立妙味が出るか。出なければ馬体重/増減もオッズに織込み済み"
      "＝パドック定量で回収率は上げられない(主観項目は履歴無しで検証不可)。")
