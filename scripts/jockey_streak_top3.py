# -*- coding: utf-8 -*-
"""「そろそろ来る＝3着以内」版の検証。
連続圏外(4着以下が続く)ストリークが、次走の『3着以内』を予測するか。
オッズ別期待複勝率で補正した残差 res3=(3着内なら1)-期待複勝率 を層別平均。
平坦ならギャンブラーの誤謬（複勝でも『そろそろ来る』は幻想）。"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


jockeys = [r[0] for r in con.execute("""SELECT jockey_name FROM results
    WHERE year IN ('2024','2025') AND jockey_name!='' GROUP BY jockey_name
    HAVING COUNT(*)>=300""").fetchall()]

streak_b = defaultdict(lambda: [0.0, 0])   # 連続圏外数 → [res3合計, n]
due_b = defaultdict(lambda: [0.0, 0])      # 複勝due比 → [res3合計, n]
for jk in jockeys:
    rows = con.execute("""SELECT chakujun, win_odds FROM results
        WHERE jockey_name=? AND chakujun>0 AND win_odds>0 AND year IN ('2023','2024','2025')
        ORDER BY race_key ASC""", (jk,)).fetchall()
    if len(rows) < 60:
        continue
    chaku = [c for c, _ in rows]; odds = [o for _, o in rows]
    for i in range(40, len(rows)):
        prior = chaku[:i]
        # 連続圏外（4着以下が続く）
        ns = 0
        for c in reversed(prior):
            if c <= 3:
                break
            ns += 1
        # 複勝due: 最後の複勝からの経過 / 平均複勝間隔
        t3_pos = [j for j, c in enumerate(prior) if c <= 3]
        cur_dry = (len(prior) - 1 - t3_pos[-1]) if t3_pos else len(prior)
        if len(t3_pos) >= 2:
            gaps = [t3_pos[k+1]-t3_pos[k] for k in range(len(t3_pos)-1)]
            avg = sum(gaps)/len(gaps)
        else:
            avg = len(prior)/max(len(t3_pos), 1)
        due = cur_dry/avg if avg > 0 else 0
        res3 = (1 if chaku[i] <= 3 else 0) - e3(odds[i])
        sb = '0' if ns == 0 else '1-2' if ns <= 2 else '3-5' if ns <= 5 else '6-9' if ns <= 9 else '10+'
        streak_b[sb][0] += res3; streak_b[sb][1] += 1
        db = '<0.5' if due < 0.5 else '0.5-1' if due < 1 else '1-2' if due < 2 else '2+'
        due_b[db][0] += res3; due_b[db][1] += 1
con.close()

print("== 連続圏外(4着以下)ストリーク別 → 次走『3着以内』残差（>0=人気以上に来る）==")
for k in ['0', '1-2', '3-5', '6-9', '10+']:
    s, n = streak_b.get(k, [0, 0])
    if n:
        print(f"  連続圏外 {k:5s}: 複勝残差 {s/n:+.4f}  (n={n})")
print("\n== 複勝due比別（“そろそろ3着内に来る”）==")
for k in ['<0.5', '0.5-1', '1-2', '2+']:
    s, n = due_b.get(k, [0, 0])
    if n:
        print(f"  due {k:6s}: 複勝残差 {s/n:+.4f}  (n={n})")
