# -*- coding: utf-8 -*-
"""ユーザー観測の検証: 3着内のうち2頭が上位ランク(≤5)・残り1頭が伏兵(ランク≥8=7圏外)の
決着が最近/夏競馬に多いか。

『ランク』=強適Ranking Tableの順位(予測スコア順)だが、これは各レースのnetkeibaライブ取得が
必要でオフライン再現不可。→ 人気(単勝オッズ)順位を代理指標に使う(強適Rankは市場オッズに強相関、
かつ"伏兵=市場が期待してない=人気薄"は人気順位で定義できる)。

決着タイプ(3着内3頭の人気構成)を分類し、月別(夏6-8月 vs その他)・年別で発生率を比較。
JRA平地・2016-2025。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def classify(pops):
    """3着内3頭の人気(ninki)リスト → 決着タイプ。"""
    pops = sorted(pops)
    in5 = sum(1 for p in pops if p <= 5)
    in7 = sum(1 for p in pops if p <= 7)
    long8 = sum(1 for p in pops if p >= 8)   # 伏兵(7圏外)
    if in5 == 3:
        return '堅(3頭とも5位以内)'
    if in5 == 2 and long8 == 1:
        return '★2頭5位以内+1頭伏兵(8位以下)'   # ユーザー観測パターン
    if in5 == 2 and long8 == 0:
        return '2頭5位以内+1頭中位(6-7位)'
    if in5 == 1:
        return '1頭5位以内+2頭中穴以下'
    return '0頭5位以内(大波乱)'


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        "SELECT race_key, ninki FROM results "
        "WHERE jyo<='10' AND chakujun>0 AND chakujun<=3 AND ninki>0 "
        "AND CAST(year AS INT)>=2016").fetchall()
    con.close()

    by_race = defaultdict(list)
    for rk, nk in rows:
        by_race[rk].append(nk)

    # race_key: YYYYMMDD... → month, year
    def meta(rk):
        s = str(rk)
        return int(s[:4]), int(s[4:6])

    # 集計: (期間ラベル) -> {タイプ: count}, total
    periods = defaultdict(lambda: defaultdict(int))
    ptotal = defaultdict(int)

    for rk, pops in by_race.items():
        if len(pops) != 3:
            continue
        yr, mo = meta(rk)
        typ = classify(pops)
        season = '夏(6-8月)' if mo in (6, 7, 8) else 'その他期'
        era = '最近(2024-25)' if yr >= 2024 else '過去(2016-23)'
        for key in ('全体', season, era, f'{era}×{season}'):
            periods[key][typ] += 1
            ptotal[key] += 1

    TYPES = ['堅(3頭とも5位以内)', '2頭5位以内+1頭中位(6-7位)',
             '★2頭5位以内+1頭伏兵(8位以下)', '1頭5位以内+2頭中穴以下', '0頭5位以内(大波乱)']

    def show(key):
        tot = ptotal[key]
        if not tot:
            return
        print(f"\n【{key}】 n={tot:,}")
        for t in TYPES:
            c = periods[key][t]
            print(f"  {t:26s} {c/tot:6.1%} ({c:,})")

    print("3着内3頭の人気構成タイプ(強適Rankの代理=単勝人気順位)\n" + "=" * 60)
    for key in ['全体', '夏(6-8月)', 'その他期', '最近(2024-25)', '過去(2016-23)',
                '最近(2024-25)×夏(6-8月)', '最近(2024-25)×その他期',
                '過去(2016-23)×夏(6-8月)', '過去(2016-23)×その他期']:
        show(key)

    # ★パターンだけを期間比較(夏効果/最近効果の有無)
    print("\n" + "=" * 60)
    print("★『2頭5位以内+1頭伏兵(8位以下)』の発生率だけ抜粋:")
    for key in ['夏(6-8月)', 'その他期', '最近(2024-25)', '過去(2016-23)']:
        tot = ptotal[key]
        c = periods[key]['★2頭5位以内+1頭伏兵(8位以下)']
        if tot:
            se = (0.2 * 0.8 / tot) ** 0.5
            print(f"  {key:16s} {c/tot:6.2%} (n={tot:,})")
    print("\n[判定] 夏とその他期で発生率が明確に違えば『夏競馬で伏兵1頭の波乱が多い』は本物。"
          "ほぼ同じなら『たまたま/通年こういうもの』。最近と過去の差も同様に見る。")


if __name__ == '__main__':
    main()
