# -*- coding: utf-8 -*-
"""
②穴妙味 バックテスト — 「人気1-穴2の穴を末脚シグナルで選別すると②は良くなるか」
──────────────────────────────────────────────────────────────────────────
背景: 盲目的な②(人気1-穴2)は検証で最悪(的中15.5%/ROI55-67%)。ユーザーは②を捨てず
      『①と別方向＝妙味/穴特化』で残す決定。エンジン実装(trio_engine '②妙味')は
      穴を🔥末脚救出/妙味シグナルで選別する。本当に盲目②より良くなるかを実測する。

検証する仮説: ②の形(人気1-穴2)で勝つレースのうち、穴2頭が末脚指数(ato3f偏差)を
            持つケースに絞れば、買い点数(コスト)が激減し的中の質/ROIが上がる。

戦略(人気=ninki<=P / 穴=A1<=ninki<=A2、買い目=人気1頭×穴2頭の組合せ):
  盲目②      : 穴poolの全2頭組合せを買う
  妙味②(≥1) : 穴pairのうち少なくとも1頭が末脚指数>=thr の組合せだけ買う(エンジンと同じ思想)
  妙味②(両方): 穴pair両方が末脚指数>=thr の組合せだけ買う(最も絞る)
比較: 的中率(②形で勝ったレースを買えていた割合)・ROI(Σ3連複配当/Σ買い点数)・平均買い点数。

注意: 妙味シグナルは jravan.dbで計算可能な末脚指数で代理(単複乖離はplace odds欠落で広域不可)。
      payoutは payouts.bet_type='3連複'(100円あたり配当円)。
"""
import os, sys, sqlite3, statistics, argparse
from math import comb
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def date_key(y, md):
    try:
        return int(y) * 10000 + int(md)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2015)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--k', type=int, default=3, help='末脚指数の直近走数')
    ap.add_argument('--thr', type=float, default=0.8, help='末脚指数しきい値(ライブ採用0.8)')
    ap.add_argument('--P', type=int, default=4, help='人気pool: ninki<=P')
    ap.add_argument('--A1', type=int, default=6, help='穴pool下限ninki')
    ap.add_argument('--A2', type=int, default=12, help='穴pool上限ninki')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, ninki, chakujun, ato3f "
        "FROM results WHERE CAST(year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)
    print(f"  結果 {len(rows):,}行 / {len(by_race):,}レース")

    # 末脚dev履歴(レース内標準化・速い=正)
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        vals = [r['ato3f'] for r in rs if r['ato3f'] and r['ato3f'] > 0]
        if len(vals) < 5:
            continue
        m = statistics.mean(vals); sd = statistics.pstdev(vals)
        if sd <= 0:
            continue
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        for r in rs:
            if r['ato3f'] and r['ato3f'] > 0:
                hist[r['ketto_num']].append((dk, (m - r['ato3f']) / sd))
    for k in hist:
        hist[k].sort()

    def spurt_index(ketto, dk):
        h = hist.get(ketto)
        if not h:
            return None, 0
        past = [v for (d2, v) in h if d2 < dk]
        if len(past) < 2:
            return None, len(past)
        seg = past[-args.k:]
        return sum(seg) / len(seg), len(seg)

    # 3連複配当
    pay = {}
    for r in con.execute("SELECT race_key, payout FROM payouts WHERE bet_type='3連複' AND payout>0"):
        pay[r['race_key']] = r['payout']

    test = con.execute(
        "SELECT race_key, year, monthday FROM races WHERE CAST(year AS INTEGER) BETWEEN ? AND ?",
        (args.test_from, args.test_to)).fetchall()
    con.close()

    P, A1, A2, thr = args.P, args.A1, args.A2, args.thr
    # 集計
    strat = {k: {'cost': 0, 'ret': 0, 'hit': 0, 'active': 0}
             for k in ('盲目②', '妙味②(≥1)', '妙味②(両方)')}
    n_race = 0
    n_2shape = 0           # ②形(人気1-穴2)で決着したレース
    n_2shape_sig1 = 0      # うち勝ち穴の≥1頭が末脚signal
    n_2shape_sig2 = 0      # うち勝ち穴の両方がsignal

    for tr in test:
        rk = tr['race_key']
        rs = by_race.get(rk)
        po = pay.get(rk)
        if not rs or not po:
            continue
        dk = date_key(tr['year'], tr['monthday'])
        # 各馬: ninki, chaku, spurt
        runners = []
        for r in rs:
            if not r['ninki'] or r['ninki'] <= 0:
                continue
            si, sr = spurt_index(r['ketto_num'], dk)
            runners.append({'ninki': r['ninki'], 'chaku': r['chakujun'],
                            'sig': bool(si is not None and si >= thr and sr >= 2)})
        if len(runners) < 8:
            continue
        n_race += 1

        pop_pool = [h for h in runners if h['ninki'] <= P]
        ana_pool = [h for h in runners if A1 <= h['ninki'] <= A2]
        ana_sig = [h for h in ana_pool if h['sig']]
        if len(pop_pool) < 1 or len(ana_pool) < 2:
            continue

        # 勝ち3頭(1-3着)
        top3 = [h for h in runners if h['chaku'] in (1, 2, 3)]
        if len(top3) != 3:
            continue
        w_pop = [h for h in top3 if h['ninki'] <= P]
        w_ana = [h for h in top3 if A1 <= h['ninki'] <= A2]
        is_2 = (len(w_pop) == 1 and len(w_ana) == 2)
        w_ana_sig = sum(1 for h in w_ana if h['sig']) if is_2 else 0
        if is_2:
            n_2shape += 1
            if w_ana_sig >= 1:
                n_2shape_sig1 += 1
            if w_ana_sig >= 2:
                n_2shape_sig2 += 1

        psz, asz, ssz = len(pop_pool), len(ana_pool), len(ana_sig)
        # 各戦略の買い点数(コスト)と的中
        # 盲目②: 人気1頭×穴pool2頭
        c_blind = psz * comb(asz, 2)
        # 妙味②(≥1): 穴pairの少なくとも1頭がsignal = 全pair - 非signalだけのpair
        c_sig1 = psz * (comb(asz, 2) - comb(asz - ssz, 2)) if asz - ssz >= 0 else psz * comb(asz, 2)
        # 妙味②(両方): signal穴同士
        c_sig2 = psz * comb(ssz, 2)

        for name, cost, hit_cond in (
            ('盲目②', c_blind, is_2),
            ('妙味②(≥1)', c_sig1, is_2 and w_ana_sig >= 1),
            ('妙味②(両方)', c_sig2, is_2 and w_ana_sig >= 2)):
            if cost <= 0:
                continue
            s = strat[name]
            s['active'] += 1
            s['cost'] += cost
            if hit_cond:
                s['hit'] += 1
                s['ret'] += po

    def pct(a, b):
        return f"{100*a/b:.1f}%" if b else "-"

    print("\n" + "=" * 72)
    print(f"■ 検証 {n_race:,}R ({args.test_from}-{args.test_to}) / 人気=ninki<={P} 穴={A1}-{A2} / 末脚thr={thr}")
    print("=" * 72)
    print(f"②形(人気1-穴2)で決着: {n_2shape:,}R ({pct(n_2shape, n_race)})")
    print(f"  うち勝ち穴の≥1頭が末脚signal: {n_2shape_sig1:,} ({pct(n_2shape_sig1, n_2shape)} of ②形)")
    print(f"  うち勝ち穴の両方がsignal    : {n_2shape_sig2:,} ({pct(n_2shape_sig2, n_2shape)} of ②形)")
    print(f"\n{'戦略':<14}{'対象R':>8}{'的中R':>8}{'的中率':>9}{'平均点数':>10}{'ROI':>9}")
    print("-" * 72)
    for name in ('盲目②', '妙味②(≥1)', '妙味②(両方)'):
        s = strat[name]
        roi = pct(s['ret'], s['cost'] * 100) if s['cost'] else '-'  # cost点数×100円が分母
        avg = f"{s['cost']/s['active']:.0f}" if s['active'] else '-'
        hr = pct(s['hit'], s['active'])
        print(f"{name:<14}{s['active']:>8}{s['hit']:>8}{hr:>9}{avg:>10}{roi:>9}")
    print("-" * 72)
    print("読み方: 妙味②が盲目②より『平均点数を大きく下げつつROIが上がる/落ちない』なら、")
    print("        末脚signalでの穴選別は有効。的中率(対象R分母)も上がるか要確認。")


if __name__ == '__main__':
    main()
