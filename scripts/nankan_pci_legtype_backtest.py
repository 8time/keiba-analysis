# -*- coding: utf-8 -*-
"""NARでのPCI/末脚指数/脚質分類の予測力バックテスト(パイロット版)。

core/nankan_scraper.pyのPastRunsブリッジで計算できるようになった
AvgPCI(race_analysis_tools)・末脚指数(compute_spurt_index)が、
JRAでの検証(verified_spurt_index.md)と同様にNARでも複勝率を持ち上げるかを
実データで確認する。過去走はレース当日より前の走のみを使い、当該レースの
結果情報(着順・上がり3F等)は特徴量計算に混ぜない(リーク防止)。

対象: 大井(nankan内部コード20)。ブルートフォース探索(scripts/debug/nankan_id_bruteforce*.py)で
発見した5開催分(kaiji01〜05・各5日)の確定済みレースをまとめて評価する標本拡大版。
"""
import sys
import io
import re
import time

sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from core import nankan_scraper as nk
from core import race_analysis_tools as rat


def gather_completed_race_ids(candidates):
    completed = []
    for rid in candidates:
        res = nk.fetch_result(rid)
        if res:
            completed.append(rid)
        time.sleep(0.2)
    return completed


def race_date_from_id(rid):
    return rid[:8]


# ブルートフォース探索(scripts/debug/nankan_id_bruteforce*.py)で発見した
# 大井(venue=20)の5開催・各5日分の(date, kaiji, day)一覧。
_MEETINGS = [
    # kaiji01: 2026-04-13〜04-17
    ("20260413", 1, 1), ("20260414", 1, 2), ("20260415", 1, 3),
    ("20260416", 1, 4), ("20260417", 1, 5),
    # kaiji02: 2026-04-27〜05-01
    ("20260427", 2, 1), ("20260428", 2, 2), ("20260429", 2, 3),
    ("20260430", 2, 4), ("20260501", 2, 5),
    # kaiji03: 2026-05-18〜05-22
    ("20260518", 3, 1), ("20260519", 3, 2), ("20260520", 3, 3),
    ("20260521", 3, 4), ("20260522", 3, 5),
    # kaiji04: 2026-06-08〜06-12
    ("20260608", 4, 1), ("20260609", 4, 2), ("20260610", 4, 3),
    ("20260611", 4, 4), ("20260612", 4, 5),
    # kaiji05: 2026-06-30/07-01 (既存パイロットで確認済み)
    ("20260630", 5, 2), ("20260701", 5, 3),
]


def build_candidates():
    ids = []
    for date_str, kaiji, day in _MEETINGS:
        for rn in range(1, 13):
            ids.append(f"{date_str}20{kaiji:02d}{day:02d}{rn:02d}")
    return ids


def leg_type_from_passing(passing, n_horses):
    nums = [int(x) for x in re.findall(r"\d+", str(passing or ""))]
    if not nums or not n_horses:
        return None
    avg_pos = sum(nums) / len(nums)
    ratio = avg_pos / max(n_horses, 1)
    if ratio <= 0.10:
        return "逃げ"
    if ratio <= 0.32:
        return "先行"
    if ratio <= 0.60:
        return "差し"
    return "追込"


def main():
    candidates = build_candidates()
    print(f"[1] 候補レース数: {len(candidates)}")
    completed = gather_completed_race_ids(candidates)
    print(f"[1] 確定済みレース数: {len(completed)}")

    horse_cache = {}
    rows = []  # per-horse pre-race feature + actual result

    for ri, rid in enumerate(completed):
        race_date = race_date_from_id(rid)
        results = nk.fetch_result(rid)
        if not results:
            continue
        n_horses = len(results)
        # レース内 spurt_index 順位付け用に先に全馬計算
        prerace = []
        for r in results:
            hid = r.get("horse_id")
            if not hid:
                continue
            if hid not in horse_cache:
                hist = nk.fetch_horse_history(hid)
                horse_cache[hid] = hist
                time.sleep(0.15)
            hist = horse_cache[hid]
            if not hist:
                continue
            # リーク防止: 当該レース当日より前の過去走のみ使用
            past = [x for x in (hist.get("runs") or []) if x.get("date", "9999") < f"{race_date[:4]}/{race_date[4:6]}/{race_date[6:8]}"]
            si, sr = nk.compute_spurt_index(past)
            pastruns = nk.runs_to_pastruns(past)
            pci_stats = rat.PCICalculator().analyze_horse_pci(pastruns)
            avg_pci = pci_stats.get("avg_pci") if pci_stats.get("pci_list") else None
            # 直近走の脚質(通過順ベース)
            leg = leg_type_from_passing(past[0].get("passing"), past[0].get("n_horses")) if past else None
            prerace.append({
                "umaban": r.get("umaban"),
                "popularity": r.get("popularity"),
                "rank": r.get("rank"),
                "spurt_index": si,
                "spurt_runs": sr,
                "avg_pci": avg_pci,
                "leg_type": leg,
                "n_prior_runs": len(past),
            })

        # レース内 spurt_index top3 (2走以上ある馬に限定)
        ranked = sorted([p for p in prerace if p["spurt_index"] is not None and p["spurt_runs"] >= 2],
                        key=lambda x: -x["spurt_index"])
        top3_umaban = {p["umaban"] for p in ranked[:3]}

        for p in prerace:
            p["race_id"] = rid
            p["n_horses"] = n_horses
            p["spurt_top3"] = p["umaban"] in top3_umaban
            rows.append(p)

        print(f"  [{ri+1}/{len(completed)}] {rid}: {n_horses}頭 処理完了")

    print(f"\n[2] 集計対象レコード数: {len(rows)}")

    def fukusho_rate(subset):
        n = len(subset)
        if n == 0:
            return None, 0
        hits = sum(1 for x in subset if x["rank"] is not None and 1 <= x["rank"] <= 3)
        return hits / n, n

    # ベースライン(全馬)
    base_rate, base_n = fukusho_rate(rows)
    print(f"\n[ベースライン] 全馬複勝率: {base_rate:.1%} (n={base_n})" if base_rate is not None else "n=0")

    # 検証1: 6番人気以下 × 末脚top3 (verified_spurt_indexと同条件)
    ana_pop = [r for r in rows if r.get("popularity") and r["popularity"] >= 6]
    ana_base_rate, ana_base_n = fukusho_rate(ana_pop)
    ana_spurt = [r for r in ana_pop if r["spurt_top3"]]
    ana_spurt_rate, ana_spurt_n = fukusho_rate(ana_spurt)
    print(f"\n[検証1] 6番人気以下ベース: {ana_base_rate:.1%} (n={ana_base_n})" if ana_base_rate is not None else "n=0")
    print(f"[検証1] 6番人気以下×末脚top3: {ana_spurt_rate:.1%} (n={ana_spurt_n})" if ana_spurt_rate is not None else "n=0(該当なし)")

    # 検証2: AvgPCIの分布(データがどれだけ算出できたか)
    with_pci = [r for r in rows if r["avg_pci"] is not None]
    print(f"\n[検証2] AvgPCI算出できた頭数: {len(with_pci)}/{len(rows)}")
    if with_pci:
        vals = sorted(r["avg_pci"] for r in with_pci)
        print(f"  min={vals[0]:.1f} median={vals[len(vals)//2]:.1f} max={vals[-1]:.1f}")

    # 検証3: 脚質分布
    from collections import Counter
    leg_counts = Counter(r["leg_type"] for r in rows if r["leg_type"])
    print(f"\n[検証3] 脚質分布: {dict(leg_counts)}")

    import json
    with open("scripts/debug/nankan_backtest_rows.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\n生データ保存: scripts/debug/nankan_backtest_rows.json")


if __name__ == "__main__":
    main()
