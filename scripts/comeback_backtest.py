# -*- coding: utf-8 -*-
"""🔄バイアス巻き返し候補(core/track_bias.comeback_flag)の検証。
仮説: 直近走で当日バイアスに逆らって好走した馬は『次走の妙味』。
測るもの: フラグ発火馬の【その対象レース】での 勝率/複勝率/単複ROI と、
          人気(オッズ)補正後の残差(=妙味があるか)。残差≈0/負なら織込み済み or 過剰人気。
test=2023-2025・JRA平地(芝/ダ)。"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import track_bias as tb

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)


def e3(o):
    e = exp.get(jj._odds_band(o)); return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o)); return e['win'] if e else 0.08


con = sqlite3.connect(DB)
cur = con.cursor()

# ── 1) 全レースの「当日逆算バイアス」を precompute (race_key -> bias) ──
# 勝ち馬を 日×場×馬場 でまとめ、race_num昇順に prior_winners を積んで empirical_bias。
winners = cur.execute(
    """SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.race_num,
              ra.race_key, r.corner4, r.umaban, ra.shusso_tosu
       FROM races ra JOIN results r ON r.race_key=ra.race_key
       WHERE r.chakujun=1 AND r.corner4>0 AND ra.surface IN ('芝','ダート')
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10""").fetchall()

# group key -> list of (race_num, race_key, winner_dict)
grp = defaultdict(list)
for y, md, jyo, surf, rnum, rkey, c4, uma, tosu in winners:
    grp[(y, md, jyo, surf)].append(
        (int(rnum), rkey, {'corner4': c4, 'umaban': uma, 'tosu': tosu or 0}))

bias_by_rk = {}   # race_key -> bias dict (confident込み)
for g, lst in grp.items():
    lst.sort(key=lambda x: (x[0], x[1]))
    for i, (rnum, rkey, _w) in enumerate(lst):
        prior = [w for (rn, rk, w) in lst if rn < rnum]
        b = tb.empirical_bias(prior)
        if b:
            bias_by_rk[rkey] = b

# ── 2) 全出走(平地・着順あり)を取得し、馬ごと時系列に ──
rows = cur.execute(
    """SELECT r.bamei, r.race_key, r.chakujun, r.corner4, r.ninki, r.win_odds,
              ra.shusso_tosu, ra.year
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート')
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
       ORDER BY r.bamei, r.race_key""").fetchall()
con.close()

by_horse = defaultdict(list)
for bamei, rkey, chaku, c4, ninki, odds, tosu, year in rows:
    by_horse[bamei].append({
        'rkey': rkey, 'chaku': chaku, 'c4': c4 or 0, 'ninki': ninki or 0,
        'odds': odds or 0, 'tosu': tosu or 0, 'year': year})


def run_qualifies(run):
    """その1走が『当日バイアスに逆らって好走』か(comeback_flagと同条件)。"""
    if run['tosu'] < 8 or run['c4'] <= 0:
        return False
    b = bias_by_rk.get(run['rkey'])
    if not b or not b['confident']:
        return False
    tosu = run['tosu']; chaku = run['chaku']; c4 = run['c4']
    placed = chaku <= max(3, tosu * 0.3)
    back = c4 > max(3, tosu * 0.5)
    front = c4 <= 3
    if b['pace_label'].startswith('前') and placed and back:
        return True
    if b['pace_label'].startswith('後') and placed and front:
        return True
    return False


# ── 3) 各対象レース(直近3走に発火走があるか)を評価 ──
# flagged群 vs 全体(母集団) の 勝率/複勝率/ROI と 人気補正残差。
def agg():
    return {'n': 0, 't3': 0, 'w': 0, 'pay1': 0.0, 'pay3': 0.0, 'r3': 0.0, 'rw': 0.0}


FL, ALL = agg(), agg()
# 人気帯別(妙味は人気薄に出やすい=この企画の既知パターン)
FL_BAND = {'1-3番人気': agg(), '4-5番人気': agg(), '6-9番人気': agg(), '10番人気〜': agg()}


def band_of(ninki):
    if ninki <= 3:
        return '1-3番人気'
    if ninki <= 5:
        return '4-5番人気'
    if ninki <= 9:
        return '6-9番人気'
    return '10番人気〜'


LOOKBACK = 3


def add(d, run):
    o = run['odds']
    d['n'] += 1
    if run['chaku'] <= 3:
        d['t3'] += 1; d['pay3'] += o  # 複勝ROIは近似(単オッズ流用不可)→単勝ROIのみ採用
    if run['chaku'] == 1:
        d['w'] += 1; d['pay1'] += o
    d['r3'] += (1 if run['chaku'] <= 3 else 0) - e3(o)
    d['rw'] += (1 if run['chaku'] == 1 else 0) - e1(o)


for bamei, runs in by_horse.items():
    for i, run in enumerate(runs):
        if run['year'] < '2023':
            continue
        if run['odds'] <= 0 or run['ninki'] <= 0:
            continue
        add(ALL, run)
        prev = runs[max(0, i - LOOKBACK):i]
        if any(run_qualifies(p) for p in prev):
            add(FL, run)
            add(FL_BAND[band_of(run['ninki'])], run)


def rep(name, d):
    n = max(d['n'], 1)
    se3 = (0.22 * 0.78 / n) ** 0.5
    se1 = (0.08 * 0.92 / n) ** 0.5
    z3 = (d['r3'] / n) / se3 if se3 else 0
    z1 = (d['rw'] / n) / se1 if se1 else 0
    print(f"{name:14s} n={d['n']:6d} | 勝率{d['w']/n:6.2%} 複勝率{d['t3']/n:6.2%} "
          f"| 単ROI{d['pay1']/n:6.1%} "
          f"| 複勝残差{d['r3']/n:+.4f}(z={z3:+.2f}) 勝残差{d['rw']/n:+.4f}(z={z1:+.2f})")


print(f"bias precompute: {len(bias_by_rk)} races / 母集団・flagged評価(2023-2025)\n")
rep("母集団(全馬)", ALL)
rep("🔄巻き返しFlag", FL)
print("  --- 人気帯別(巻き返しFlag) ---")
for _b in ('1-3番人気', '4-5番人気', '6-9番人気', '10番人気〜'):
    rep("  " + _b, FL_BAND[_b])
print("\n→ 複勝率/単ROIが母集団より高く、かつ残差z>+2 なら『次走妙味』として有効。"
      "残差≈0=人気に織込み済み / 負=過剰人気。z<2 や ROI<80%台 なら現状の使い方は誇大。")
