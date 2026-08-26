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
              r.corner3, r.chakujun, r.ninki, r.win_odds, r.kyakushitsu
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


def _kyaku_code(v):
    try:
        return int(str(v).strip())
    except Exception:
        return 0


by_horse = defaultdict(list)
for bamei, y, md, kyori, surf, c3, chaku, ninki, odds, kyaku in rows:
    by_horse[bamei].append({
        'd': ord_days(y, md), 'kyori': kyori or 0, 'surf': surf, 'c3': c3 or 0,
        'chaku': chaku, 'ninki': ninki or 0, 'odds': odds or 0, 'year': y,
        'ymd': f'{y}{md}', 'kyaku': _kyaku_code(kyaku)})


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


def reverse_reach(hist, i):
    """事前に使える①②だけ。今回3角は見ない。"""
    if i == 0:
        return False
    cur, prev = hist[i], hist[i - 1]
    if not (0 < prev['c3'] >= 5):
        return False
    if not (cur['kyori'] < prev['kyori']):
        return False
    return True


def reverse_habit(hist, i):
    """①②＋過去走の平均3角<=8を『今回3角の事前想定』にする。"""
    if not reverse_reach(hist, i):
        return False
    past = [p['c3'] for p in hist[max(0, i - 3):i] if p.get('c3', 0) > 0]
    if not past:
        return False
    return (sum(past) / len(past)) <= 8.0


def reverse_style(hist, i):
    """①②＋前走が逃げ/先行なら今回も前目、と想定する。"""
    if not reverse_reach(hist, i):
        return False
    return hist[i - 1].get('kyaku', 0) in (1, 2)


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


# 対象期間: 引数なし=2023年以降 / 例: python scripts/shocker_backtest.py 20260101 20260630
_ymd_from = sys.argv[1] if len(sys.argv) >= 2 else '20230101'
_ymd_to = sys.argv[2] if len(sys.argv) >= 3 else '99991231'


def in_test(cur):
    if cur['odds'] <= 0 or cur['ninki'] <= 0:
        return False
    return _ymd_from <= cur['ymd'] <= _ymd_to


ALL = agg()
SS, SS_ana = agg(), agg()   # 短縮ショッカー: 全該当 / 6番人気以下(穴)
RS, RS_ana = agg(), agg()   # 逆ショッカー(今回3角リーク込み)
PRE, PRE_ana = agg(), agg()
HAB, HAB_ana = agg(), agg()
STY, STY_ana = agg(), agg()
REACH_OK3, REACH_NG3 = agg(), agg()  # ①②のうち実際に③を満たした/外した
n_reach = n_reach_ok3 = 0
n_hab = n_hab_ok3 = 0
n_sty = n_sty_ok3 = 0
for bamei, hist in by_horse.items():
    for i, cur in enumerate(hist):
        if not in_test(cur):
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
        if reverse_reach(hist, i):
            add(PRE, cur)
            if cur['ninki'] >= 6:
                add(PRE_ana, cur)
            n_reach += 1
            if 0 < cur['c3'] <= 8:
                n_reach_ok3 += 1
                add(REACH_OK3, cur)
            elif cur['c3'] > 8:
                add(REACH_NG3, cur)
        if reverse_habit(hist, i):
            add(HAB, cur)
            n_hab += 1
            if 0 < cur['c3'] <= 8:
                n_hab_ok3 += 1
            if cur['ninki'] >= 6:
                add(HAB_ana, cur)
        if reverse_style(hist, i):
            add(STY, cur)
            n_sty += 1
            if 0 < cur['c3'] <= 8:
                n_sty_ok3 += 1
            if cur['ninki'] >= 6:
                add(STY_ana, cur)

print(f"検証 {_ymd_from}〜{_ymd_to}・JRA平地（残差z>+2 かつ ROI高 = 本物の妙味 / 残差≈0 = 織込み済み）\n")
rep("母集団(全馬)", ALL)
print("\n【短縮ショッカー】(主張: 馬連600%)")
rep("全該当", SS)
rep("6番人気以下(穴)", SS_ana)
print("\n【逆ショッカー】(主張: 単回収100%超) ③今回3角=結果リーク")
rep("全該当", RS)
rep("6番人気以下(穴)", RS_ana)
print("\n【逆ショッカー 事前だけ①②】今回3角を使わない")
rep("全該当", PRE)
rep("6番人気以下(穴)", PRE_ana)
if n_reach:
    print(f"  ①②のうち実際に今回3角8番手以内だった割合: {n_reach_ok3}/{n_reach}={n_reach_ok3/n_reach:.1%}")
print("  ①②のうち、実際の今回3角で分けた場合:")
rep("  実際3角<=8", REACH_OK3)
rep("  実際3角>=9", REACH_NG3)
print("\n【③の事前代理】netkeiba AI3角の履歴はDBに無いので、事前に組める想定だけ測る")
print("  過去走の平均3角<=8 を『今回も前目』と仮定")
rep("全該当", HAB)
rep("6番人気以下(穴)", HAB_ana)
if n_hab:
    print(f"  この代理で実際に今回3角<=8だった割合: {n_hab_ok3}/{n_hab}={n_hab_ok3/n_hab:.1%}")
print("  前走が逃げ/先行 を『今回も前目』と仮定")
rep("全該当", STY)
rep("6番人気以下(穴)", STY_ana)
if n_sty:
    print(f"  この代理で実際に今回3角<=8だった割合: {n_sty_ok3}/{n_sty}={n_sty_ok3/n_sty:.1%}")
print("\n判定: 事前代理の単ROIが①②と同じ(織込み)なら『予測3角を③に使う』は採用しない。"
      " 今回3角の結果を③に入れたときだけROIが上がるのはリーク。")
