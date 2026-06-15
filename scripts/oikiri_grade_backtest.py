# -*- coding: utf-8 -*-
"""netkeiba 調教評価ランク(A-D)が着順を予測するか検証。
重賞(grade A/B/C)を ~100レース抽出し、各馬の oikiri(type=3)評価ランクを scrape。
jravan.db の results(着順・単勝オッズ)に umaban で結合し、
 ①3着内残差 = (3着内?1:0) − オッズ別期待複勝率
 ②勝利残差   = (1着?1:0)   − オッズ別期待勝率
をランク別に集計。残差>0 = 人気(オッズ)以上に来る = ボーナスの根拠あり。

scrape結果は scratch/oikiri_grade_cache.json にキャッシュ(race_id→{umaban:rank})。
使い方: python scripts/oikiri_grade_backtest.py [--limit 110] [--year 2025]
"""
import os
import sys
import json
import time
import argparse
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import oikiri

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scratch', 'oikiri_grade_cache.json')


def load_cache():
    try:
        with open(CACHE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(c):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='0=上限なし(全件)')
    ap.add_argument('--years', default='2021,2022,2023,2024,2025')
    args = ap.parse_args()
    years = [y.strip() for y in args.years.split(',') if y.strip()]

    con = sqlite3.connect(jj.JV_DB_PATH)
    cur = con.cursor()
    exp = jj.calibrate_odds_expectation(db_path=jj.JV_DB_PATH)

    def e3(o):
        e = exp.get(jj._odds_band(o))
        return e['top3'] if e else 0.22

    def e1(o):
        e = exp.get(jj._odds_band(o))
        return e['win'] if e else 0.08

    qmarks = ','.join('?' for _ in years)
    races = cur.execute(
        f"""SELECT race_key, race_id, race_name FROM races
            WHERE grade IN ('A','B','C') AND year IN ({qmarks}) AND shusso_tosu>=8
            AND CAST(substr(race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
            ORDER BY race_key""", years).fetchall()
    if args.limit and len(races) > args.limit:
        step = len(races) / args.limit
        races = [races[int(i * step)] for i in range(args.limit)]
    print(f"対象重賞(中央のみ): {len(races)}レース ({args.years})")

    cache = load_cache()
    rank_top3 = defaultdict(lambda: [0.0, 0])   # rank -> [残差合計, n]
    rank_sq = defaultdict(float)                # rank -> 残差^2合計(SE用)
    rank_win = defaultdict(lambda: [0.0, 0])
    rank_hit3 = defaultdict(lambda: [0, 0])     # rank -> [3着内数, n]
    n_scraped = 0
    for i, (rk, rid, rname) in enumerate(races, 1):
        if rid in cache:
            ranks = cache[rid]
        else:
            try:
                rev = oikiri.fetch_oikiri_reviews(rid)
            except Exception as e:
                print(f"  [{i}] {rid} {rname} scrape失敗 {e}")
                continue
            ranks = {str(um): d['rank'] for um, d in rev.items() if d.get('rank')}
            cache[rid] = ranks
            n_scraped += 1
            if n_scraped % 5 == 0:
                save_cache(cache)
            time.sleep(0.8)
        if not ranks:
            print(f"  [{i}] {rid} {rname} 評価なし")
            continue
        res = cur.execute(
            "SELECT umaban, chakujun, win_odds FROM results "
            "WHERE race_key=? AND chakujun>0 AND win_odds>0", (rk,)).fetchall()
        rmap = {str(um): (ch, o) for um, ch, o in res}
        used = 0
        for um, rank in ranks.items():
            if um not in rmap:
                continue
            ch, o = rmap[um]
            t3 = 1 if ch <= 3 else 0
            w = 1 if ch == 1 else 0
            r3v = t3 - e3(o)
            rank_top3[rank][0] += r3v; rank_top3[rank][1] += 1
            rank_sq[rank] += r3v * r3v
            rank_win[rank][0] += w - e1(o); rank_win[rank][1] += 1
            rank_hit3[rank][0] += t3; rank_hit3[rank][1] += 1
            used += 1
        print(f"  [{i}/{len(races)}] {rid} {rname[:16]} 評価{len(ranks)}頭 結合{used}")
    save_cache(cache)
    con.close()

    print("\n================ 調教評価ランク別 ================")
    print("rank |  n   | 3着内率 | 3着内残差   | SE     | z     | 勝利残差")
    for rk in ['A', 'B', 'C', 'D', 'E']:
        n = rank_top3[rk][1]
        if not n:
            continue
        hit = rank_hit3[rk][0] / rank_hit3[rk][1]
        r3 = rank_top3[rk][0] / n
        var = max(rank_sq[rk] / n - r3 * r3, 0.0)
        se = (var / n) ** 0.5 if n > 1 else float('inf')
        z = r3 / se if se else 0.0
        rw = rank_win[rk][0] / rank_win[rk][1]
        sig = '  ***' if abs(z) >= 2.58 else '  **' if abs(z) >= 1.96 else '  *' if abs(z) >= 1.64 else ''
        print(f"  {rk}  |{n:5d} |  {hit:5.1%} |  {r3:+.4f}   | {se:.4f} | {z:+.2f}{sig} | {rw:+.4f}")
    total_n = sum(v[1] for v in rank_top3.values())
    print(f"\n総結合頭数: {total_n}")
    print("z: |z|>=1.96=5%有意(**), >=1.64=10%(*)。A残差が正で有意ならAボーナスは妥当、"
          "そうでなければ調教評価は表示・参考用に降格が妥当。")


if __name__ == '__main__':
    main()
