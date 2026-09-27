# -*- coding: utf-8 -*-
"""umai_baken JSONL 分析 (2026-09-08)
- 4レース全てが大荒れレースであることの確認(配当倍率から)
- 券種×スタイル×点数と的中/ROIの関係
- 他LLMの主張(流し高的中率/的中3連単は大点数)の検証
"""
import json
import collections
import statistics

PATH = r"C:\Users\kimnhaty\.gemini\antigravity\scratch\keiba_analysis\data\shapes_umai_baken_20260908_1002.jsonl"
recs = [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]
print(f"records={len(recs)}")

# ---------- 1. レース別サマリ(荒れ度の推定) ----------
print("\n=== 1. レース別 ===")
by_race = collections.defaultdict(list)
for r in recs:
    by_race[(r["venue"], r["race_no"], r["date"])].append(r)
for k, rs in sorted(by_race.items()):
    w = [r for r in rs if r["pl"] > 0]
    st = sum(r["total_stake"] for r in rs)
    po = sum(r["payout"] for r in rs)
    # 的中ticketの実効倍率(payout / 的中ticketのstake)を推定
    mults = []
    for r in rs:
        hit_stake = sum(t["n_points"] * t["stake_each"] for t in r["tickets"] if t.get("hit"))
        if hit_stake > 0 and r["payout"] > 0:
            mults.append(r["payout"] / hit_stake)
    med_mult = statistics.median(mults) if mults else 0
    print(f"{k}: n={len(rs)} PL>0={len(w)}({len(w)/len(rs)*100:.0f}%) "
          f"ROI={po/st*100:.0f}% 的中ticket実効倍率中央値={med_mult:.1f}x")

# ---------- 2. 券種×スタイル 的中率(kindを統制) ----------
print("\n=== 2. kind別に見たstyle効果(ticket的中率) ===")
ks = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
for r in recs:
    for t in r["tickets"]:
        ks[t["kind"]][t["style"]][0] += 1
        if t.get("hit"):
            ks[t["kind"]][t["style"]][1] += 1
for kind in ["3連複", "3連単", "馬連", "ワイド", "馬単", "単勝"]:
    print(f"-- {kind} --")
    for style, (n, h) in sorted(ks[kind].items(), key=lambda x: -x[1][0]):
        if n >= 3:
            print(f"   {style:14s} n={n:4d} hit={h:3d} ({h/n*100:5.1f}%)")

# ---------- 3. 的中ticketの点数分布 vs ROI(他LLM主張の検証) ----------
print("\n=== 3. 的中ticketの点数と『その的中で実際いくら得したか』 ===")
for kind in ["3連単", "3連複"]:
    hits, miss = [], []
    for r in recs:
        for t in r["tickets"]:
            if t["kind"] != kind:
                continue
            (hits if t.get("hit") else miss).append(t["n_points"])
    print(f"{kind}: 的中n={len(hits)} 平均{statistics.mean(hits):.1f}点 / "
          f"外れn={len(miss)} 平均{statistics.mean(miss):.1f}点")
    # 的中ticketの点数帯別に、そのticketが属するrecordのPLを見る
    b = collections.defaultdict(lambda: [0, 0, 0])
    for r in recs:
        hit_pts = [t["n_points"] for t in r["tickets"] if t["kind"] == kind and t.get("hit")]
        for p in hit_pts:
            bk = "1-6" if p <= 6 else ("7-20" if p <= 20 else ("21-50" if p <= 50 else "51+"))
            b[bk][0] += 1
            b[bk][1] += r["pl"]
            b[bk][2] += r["total_stake"]
    for bk in ["1-6", "7-20", "21-50", "51+"]:
        n, pl, st = b[bk]
        if n:
            print(f"   的中{kind} {bk:5s}点: n={n:2d} 所属record平均PL={pl/n:>9,.0f}円")

# ---------- 4. 本命サイド vs 穴サイド(配当から逆算) ----------
print("\n=== 4. PL>0 recordの『主的中』の性質 ===")
main_hit_kind = collections.Counter()
for r in recs:
    if r["pl"] <= 0:
        continue
    hits = [t for t in r["tickets"] if t.get("hit")]
    if not hits:
        continue
    main = max(hits, key=lambda t: t["n_points"] * t["stake_each"])
    main_hit_kind[main["kind"]] += 1
print("PL>0 recordの主的中(最大stake的中ticket)の券種:", main_hit_kind.most_common())

# ---------- 5. 利益集中度 ----------
pls = sorted((r["pl"] for r in recs), reverse=True)
print(f"\n=== 5. 利益集中度 ===")
print(f"全record PL合計: {sum(pls):,}円")
print(f"上位5件: {sum(pls[:5]):,}円 / 上位10件: {sum(pls[:10]):,}円")
wp = [p for p in pls if p > 0]
print(f"PL>0は{len(wp)}件 中央値{statistics.median(wp):,}円 平均{statistics.mean(wp):,.0f}円")

# ---------- 6. 1点あたり stake_each の分布(100円 vs 厚張り) ----------
print("\n=== 6. stake_eachと結果 ===")
b = collections.defaultdict(lambda: [0, 0])
for r in recs:
    mx = max(t["stake_each"] for t in r["tickets"])
    bk = "100-300" if mx <= 300 else ("400-1000" if mx <= 1000 else ("1100-3000" if mx <= 3000 else "3100+"))
    b[bk][0] += 1
    if r["pl"] > 0:
        b[bk][1] += 1
for bk in ["100-300", "400-1000", "1100-3000", "3100+"]:
    n, w = b[bk]
    print(f"最大stake_each {bk:9s}: n={n:3d} PL>0率={w/n*100:5.1f}%")

# ---------- 7. 的中ticketの実効オッズ帯 ----------
print("\n=== 7. 的中ticketの実効倍率(payout/的中stake)帯別の貢献 ===")
b = collections.defaultdict(lambda: [0, 0])
for r in recs:
    hs = sum(t["n_points"] * t["stake_each"] for t in r["tickets"] if t.get("hit"))
    if hs <= 0 or r["payout"] <= 0:
        continue
    m = r["payout"] / hs
    bk = "~5x" if m <= 5 else ("5-20x" if m <= 20 else ("20-100x" if m <= 100 else "100x+"))
    b[bk][0] += 1
    b[bk][1] += r["pl"]
for bk in ["~5x", "5-20x", "20-100x", "100x+"]:
    n, pl = b[bk]
    print(f"{bk:8s}: records={n:3d} PL合計={pl:>11,}円")
