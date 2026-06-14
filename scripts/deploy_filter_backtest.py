# -*- coding: utf-8 -*-
"""展開フィルター改善の検証。検証済みエンジン(build_pace_context: pace+pos4)で
『展開恩恵スコア』を定義し、恩恵の高い馬が人気以上に3着内へ来るかを測る。
  恩恵: スロー→前(pos4小)が恵まれる / ハイ→差し(pos4大) / ミドル→好位中心
  残差 res3 = (3着内なら1) − オッズ別期待複勝率。恩恵高で res3>0 ならフィルター有効。
"""
import os
import sys
import sqlite3
import random
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import pace_map as pm
from core import jockey_jv as jj   # オッズ期待値較正の再利用

exp = jj.calibrate_odds_expectation()


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


def benefit(pace, p):
    if pace == 'スロー':
        return 1.0 - p
    if pace == 'ハイ':
        return p
    return 1.0 - abs(p - 0.45)


con = sqlite3.connect(pm.JV_DB_PATH)
rks = [r[0] for r in con.execute("""SELECT race_key FROM races
    WHERE year IN ('2024','2025') AND shusso_tosu>=10 ORDER BY race_key""").fetchall()]
random.seed(3); random.shuffle(rks); rks = rks[:180]

buckets = defaultdict(lambda: [0.0, 0])    # 恩恵帯 → [res3合計, n]
pace_buckets = defaultdict(lambda: [0.0, 0])  # (pace,恩恵高低) 確認用
done = 0
for rk in rks:
    ra = con.execute("SELECT kyori, surface, jyo FROM races WHERE race_key=?", (rk,)).fetchone()
    kyori, surface, jyo = ra
    rows = con.execute("""SELECT umaban, bamei, chakujun, win_odds FROM results
        WHERE race_key=? AND chakujun>0 AND win_odds>0""", (rk,)).fetchall()
    if len(rows) < 8:
        continue
    venue = pm.VENUE_CODES.get(str(jyo).zfill(2), '')
    horses = [{'umaban': u, 'name': nm, 'score': 0.5, 'style': '不明'} for u, nm, _, _ in rows]
    profiles = pm.fetch_jv_profiles([h['name'] for h in horses], max_runs=8,
                                    surface=surface, distance=kyori, before_key=rk)
    if sum(1 for h in horses if h['name'] in profiles) < len(horses) * 0.4:
        continue
    layout = pm.get_course_layout(venue, surface, kyori)
    ctx = pm.build_pace_context(horses, profiles, kyori, surface, layout)
    pace = ctx['pace']; pos4 = ctx['pos4']
    for u, nm, c, o in rows:
        if u not in pos4:
            continue
        b = benefit(pace, pos4[u])
        res3 = (1 if c <= 3 else 0) - e3(o)
        bk = '低(<0.4)' if b < 0.4 else '中(0.4-0.6)' if b < 0.6 else '高(0.6-0.75)' if b < 0.75 else '最高(0.75+)'
        buckets[bk][0] += res3; buckets[bk][1] += 1
    done += 1
con.close()

print(f"検証レース {done}")
print("== 展開恩恵スコア別 → 3着内 残差（>0=人気以上に来る＝フィルター有効）==")
for k in ['低(<0.4)', '中(0.4-0.6)', '高(0.6-0.75)', '最高(0.75+)']:
    s, n = buckets.get(k, [0, 0])
    if n:
        print(f"  恩恵 {k:11s}: 複勝残差 {s/n:+.4f}  (n={n})")
