# -*- coding: utf-8 -*-
"""J5較正: 合成騎手係数 jockey_factor.mult（直前時点）が、オッズ以上の残差を生むか。
mult帯別に 勝ち/複勝 残差を見て、係数の強さが妥当か・どの重みで統合すべきかを判断する。"""
import os
import sys
import sqlite3
import random
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e_of(o):
    e = exp.get(jj._odds_band(o))
    return (e['win'], e['top3']) if e else (0.08, 0.22)


rks = [r[0] for r in con.execute("""SELECT race_key FROM races
    WHERE year IN ('2024','2025') AND shusso_tosu>=10 AND surface='芝'""").fetchall()]
random.seed(1); random.shuffle(rks); rks = rks[:200]

buckets = defaultdict(lambda: [0.0, 0.0, 0])
for rk in rks:
    venue = jj._venue_name(con.execute("SELECT jyo FROM races WHERE race_key=?", (rk,)).fetchone()[0])
    kyori = con.execute("SELECT kyori FROM races WHERE race_key=?", (rk,)).fetchone()[0]
    for jk, tr, ketto, c, o in con.execute(
        "SELECT jockey_name, trainer_code, ketto_num, chakujun, win_odds "
        "FROM results WHERE race_key=? AND chakujun>0 AND win_odds>0", (rk,)).fetchall():
        fac = jj.jockey_factor(jk, venue=venue, distance=kyori, trainer_code=tr,
                               expected=exp, before_key=rk)
        m = fac['mult']
        ew, e3 = e_of(o)
        rw = (1 if c == 1 else 0) - ew
        r3 = (1 if c <= 3 else 0) - e3
        b = ('<0.97' if m < 0.97 else '0.97-1.0' if m < 1.0 else '1.0-1.03' if m < 1.03
             else '1.03-1.06' if m < 1.06 else '1.06+')
        buckets[b][0] += rw; buckets[b][1] += r3; buckets[b][2] += 1
con.close()

print("== 合成騎手係数 mult帯別 → オッズ補正残差（>0=人気以上）==")
for b in ['<0.97', '0.97-1.0', '1.0-1.03', '1.03-1.06', '1.06+']:
    rw, r3, n = buckets.get(b, [0, 0, 0])
    if n:
        print(f"  mult {b:9s}: 勝ち残差{rw/n:+.4f} / 複勝残差{r3/n:+.4f}  (n={n})")
