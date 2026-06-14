# -*- coding: utf-8 -*-
"""
J4: 騎手の「連敗ストリーク／調子」が次走を予測するかの検証。
馬の質をオッズ期待値で補正した残差 residual=(勝ったか)-(オッズ別期待勝率) を、
騎乗直前の連敗数・直近調子で層別して、平均残差が動くかを見る。
  residual>0 = 期待(人気)以上に勝っている。
ギャンブラーの誤謬(連敗ほど次勝ちやすい)なら連敗で残差↑。効かないなら平坦。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

con = sqlite3.connect(jj.JV_DB_PATH)
exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)
print("オッズ帯別 実勝率(較正):", {k: v['win'] for k, v in sorted(exp.items())})


def ewin(o):
    e = exp.get(jj._odds_band(o))
    return e['win'] if e else 0.08


# 騎乗数の多い騎手を対象に、年代記順で歩いて状態→次走残差を集計
jockeys = [r[0] for r in con.execute("""
    SELECT jockey_name FROM results WHERE year IN ('2024','2025') AND jockey_name!=''
    GROUP BY jockey_name HAVING COUNT(*)>=300""").fetchall()]
print(f"対象騎手: {len(jockeys)}人")

# 層別バケツ
ls_buckets = defaultdict(lambda: [0.0, 0])      # 連敗数 → [残差合計, 件数]
hot_buckets = defaultdict(lambda: [0.0, 0])     # 直近20複勝率 四分位 → 残差
due_buckets = defaultdict(lambda: [0.0, 0])     # due_ratio帯 → 残差

for jk in jockeys:
    rows = con.execute("""SELECT chakujun, win_odds FROM results r
        WHERE jockey_name=? AND chakujun>0 AND win_odds>0 AND year IN ('2023','2024','2025')
        ORDER BY race_key ASC""", (jk,)).fetchall()
    if len(rows) < 60:
        continue
    chaku = [c for c, _ in rows]
    odds = [o for _, o in rows]
    for i in range(40, len(rows)):       # 40走以上の履歴がある時点のみ
        prior = chaku[:i]
        # 連敗数
        ls = 0
        for c in reversed(prior):
            if c == 1:
                break
            ls += 1
        # 直近20複勝率
        last20 = prior[-20:]
        hot = sum(1 for c in last20 if c <= 3) / len(last20)
        # due_ratio
        win_pos = [j for j, c in enumerate(prior) if c == 1]
        cur_dry = (len(prior) - 1 - win_pos[-1]) if win_pos else len(prior)
        if len(win_pos) >= 2:
            gaps = [win_pos[k+1]-win_pos[k] for k in range(len(win_pos)-1)]
            avg_gap = sum(gaps)/len(gaps)
        else:
            avg_gap = len(prior)/max(len(win_pos), 1)
        due = cur_dry/avg_gap if avg_gap > 0 else 0

        res = (1 if chaku[i] == 1 else 0) - ewin(odds[i])
        lsb = '0' if ls == 0 else '1-2' if ls <= 2 else '3-5' if ls <= 5 else '6-9' if ls <= 9 else '10+'
        ls_buckets[lsb][0] += res; ls_buckets[lsb][1] += 1
        hb = 'cold(<10%)' if hot < 0.10 else 'low(10-20%)' if hot < 0.20 else 'mid(20-30%)' if hot < 0.30 else 'hot(>=30%)'
        hot_buckets[hb][0] += res; hot_buckets[hb][1] += 1
        dueb = '<0.5' if due < 0.5 else '0.5-1' if due < 1 else '1-2' if due < 2 else '2+'
        due_buckets[dueb][0] += res; due_buckets[dueb][1] += 1
con.close()


def show(title, buckets, order):
    print(f"\n== {title}（残差>0=人気以上に勝利）==")
    for k in order:
        s, n = buckets.get(k, [0, 0])
        if n:
            print(f"  {k:12s}: 平均残差 {s/n:+.4f}  (n={n})")


show("連敗ストリーク別（ギャンブラーの誤謬テスト）", ls_buckets, ['0', '1-2', '3-5', '6-9', '10+'])
show("直近20走 複勝率(調子)別（モメンタムテスト）", hot_buckets, ['cold(<10%)', 'low(10-20%)', 'mid(20-30%)', 'hot(>=30%)'])
show("due_ratio別（“そろそろ勝つ”テスト）", due_buckets, ['<0.5', '0.5-1', '1-2', '2+'])
