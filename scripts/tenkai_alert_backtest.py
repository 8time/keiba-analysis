# -*- coding: utf-8 -*-
"""🔍 展開妙味アラートの検証（大標本＋z値＋アラート実ロジック）。
ユーザー報告「展開妙味アラートが当たらなすぎる」を裏取りする。

検証する仮説:
  (A) 展開恩恵スコア帯別の複勝残差（恩恵高い=人気以上に来るか）
  (B) アラート実ロジック=『恩恵ゾーン該当 × 人気薄(≥5番人気)』の前残り穴候補に妙味があるか
      さらに『中ゾーン(好位妙味0.4-0.6) × 人気薄』『極端恩恵(0.75+) × 人気薄』に分解

測るもの: 複勝残差 res3 = (3着内なら1) − オッズ別期待複勝率。z>+2 かつ ROI高 = 本物。
pos4 は before_key で過去走のみ＝事前確定（リーク無し）。test=2024-2025・JRA・10頭以上。"""
import os
import sys
import sqlite3
import random
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import pace_map as pm
from core import jockey_jv as jj

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
random.seed(7); random.shuffle(rks); rks = rks[:550]

# 恩恵帯別
buckets = defaultdict(lambda: [0.0, 0, 0, 0.0])   # [res3和, n, t3数, 単勝払戻和]
# アラート実ロジック別
alert = defaultdict(lambda: [0.0, 0, 0, 0.0])
done = 0
for rk in rks:
    ra = con.execute("SELECT kyori, surface, jyo FROM races WHERE race_key=?", (rk,)).fetchone()
    kyori, surface, jyo = ra
    rows = con.execute("""SELECT umaban, bamei, chakujun, win_odds, ninki FROM results
        WHERE race_key=? AND chakujun>0 AND win_odds>0 AND ninki>0""", (rk,)).fetchall()
    if len(rows) < 8:
        continue
    venue = pm.VENUE_CODES.get(str(jyo).zfill(2), '')
    horses = [{'umaban': u, 'name': nm, 'score': 0.5, 'style': '不明'} for u, nm, _, _, _ in rows]
    profiles = pm.fetch_jv_profiles([h['name'] for h in horses], max_runs=8,
                                    surface=surface, distance=kyori, before_key=rk)
    if sum(1 for h in horses if h['name'] in profiles) < len(horses) * 0.4:
        continue
    layout = pm.get_course_layout(venue, surface, kyori)
    ctx = pm.build_pace_context(horses, profiles, kyori, surface, layout)
    pace = ctx['pace']; pos4 = ctx['pos4']
    for u, nm, c, o, ninki in rows:
        if u not in pos4:
            continue
        b = benefit(pace, pos4[u])
        res3 = (1 if c <= 3 else 0) - e3(o)
        pay1 = o if c == 1 else 0.0
        bk = ('低(<0.4)' if b < 0.4 else '中(0.4-0.6)' if b < 0.6
              else '高(0.6-0.75)' if b < 0.75 else '最高(0.75+)')
        d = buckets[bk]; d[0] += res3; d[1] += 1; d[2] += (1 if c <= 3 else 0); d[3] += pay1
        # アラート実ロジック: 恩恵ゾーン × 人気薄(≥5番人気)
        unpop = ninki >= 5
        if unpop:
            tags = []
            if b >= 0.6:
                tags.append('恩恵高×人気薄(現アラート寄り)')
            if 0.4 <= b < 0.6:
                tags.append('好位妙味ゾーン×人気薄')
            if pace == 'スロー' and b >= 0.6:
                tags.append('スロー前残り×人気薄(資料の主張)')
            for tg in tags:
                a = alert[tg]; a[0] += res3; a[1] += 1; a[2] += (1 if c <= 3 else 0); a[3] += pay1
    done += 1
con.close()


def rep(name, d):
    s, n, t3, pay = d
    if not n:
        print(f"  {name:28s} n=0"); return
    se = (0.22 * 0.78 / n) ** 0.5
    print(f"  {name:28s} n={n:5d} | 複勝率{t3/n:6.2%} 単ROI{pay/n:6.1%} "
          f"| 複勝残差{s/n:+.4f}(z={(s/n)/se:+.2f})")


print(f"検証レース {done}\n")
print("== (A) 展開恩恵スコア帯別 → 3着内 複勝残差 ==")
for k in ['低(<0.4)', '中(0.4-0.6)', '高(0.6-0.75)', '最高(0.75+)']:
    rep(k, buckets.get(k, [0, 0, 0, 0]))
print("\n== (B) アラート実ロジック（恩恵ゾーン × 人気薄≥5番人気）==")
for k in ['恩恵高×人気薄(現アラート寄り)', '好位妙味ゾーン×人気薄', 'スロー前残り×人気薄(資料の主張)']:
    rep(k, alert.get(k, [0, 0, 0, 0]))
