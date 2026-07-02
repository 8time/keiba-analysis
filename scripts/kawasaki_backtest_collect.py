# -*- coding: utf-8 -*-
"""川崎(venue=21)の過去レースデータを収集し、バックテスト用JSONに保存。

nankan_pci_legtype_backtest.pyと同じフォーマットで出力。
大井の nankan_backtest_rows.json に kawasaki_backtest_rows.json を追加し、
nar_jra_signal_backtest.py で venue 別分析を可能にする。
"""
import sys
import io
import re
import time
import json

sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from core import nankan_scraper as nk
from core import race_analysis_tools as rat

_KAWASAKI_MEETINGS = [
    # kaiji01: 2026-04-06〜04-10
    ("20260406", 1, 1), ("20260407", 1, 2), ("20260408", 1, 3),
    ("20260409", 1, 4), ("20260410", 1, 5),
    # kaiji02: 2026-05-11〜05-15
    ("20260511", 2, 1), ("20260512", 2, 2), ("20260513", 2, 3),
    ("20260514", 2, 4), ("20260515", 2, 5),
    # kaiji03: 2026-06-15〜06-19
    ("20260615", 3, 1), ("20260616", 3, 2), ("20260617", 3, 3),
    ("20260618", 3, 4), ("20260619", 3, 5),
]

VENUE = 21


def build_candidates():
    ids = []
    for date_str, kaiji, day in _KAWASAKI_MEETINGS:
        for rn in range(1, 13):
            ids.append(f"{date_str}{VENUE}{kaiji:02d}{day:02d}{rn:02d}")
    return ids


def gather_completed_race_ids(candidates):
    completed = []
    for rid in candidates:
        res = nk.fetch_result(rid)
        if res:
            completed.append(rid)
        time.sleep(0.5)
    return completed


def race_date_from_id(rid):
    return rid[:8]


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
    print(f"[1] 川崎候補レース数: {len(candidates)}")
    completed = gather_completed_race_ids(candidates)
    print(f"[1] 確定済みレース数: {len(completed)}")

    horse_cache = {}
    rows = []

    for ri, rid in enumerate(completed):
        race_date = race_date_from_id(rid)
        results = nk.fetch_result(rid)
        if not results:
            continue
        n_horses = len(results)
        prerace = []
        for r in results:
            hid = r.get("horse_id")
            if not hid:
                continue
            if hid not in horse_cache:
                hist = nk.fetch_horse_history(hid)
                horse_cache[hid] = hist
                time.sleep(0.5)
            hist = horse_cache[hid]
            if not hist:
                continue
            past = [x for x in (hist.get("runs") or [])
                    if x.get("date", "9999") < f"{race_date[:4]}/{race_date[4:6]}/{race_date[6:8]}"]
            si, sr = nk.compute_spurt_index(past)
            pastruns = nk.runs_to_pastruns(past)
            pci_stats = rat.PCICalculator().analyze_horse_pci(pastruns)
            avg_pci = pci_stats.get("avg_pci") if pci_stats.get("pci_list") else None
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

        ranked = sorted([p for p in prerace if p["spurt_index"] is not None and p["spurt_runs"] >= 2],
                        key=lambda x: -x["spurt_index"])
        top3_umaban = {p["umaban"] for p in ranked[:3]}

        for p in prerace:
            p["race_id"] = rid
            p["n_horses"] = n_horses
            p["spurt_top3"] = p["umaban"] in top3_umaban
            p["venue"] = "kawasaki"
            rows.append(p)

        print(f"  [{ri+1}/{len(completed)}] {rid}: {n_horses}頭 処理完了")

    print(f"\n[2] 川崎レコード数: {len(rows)}")

    out_path = "scripts/debug/kawasaki_backtest_rows.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"保存: {out_path}")

    # 簡易集計
    def fukusho_rate(subset):
        n = len(subset)
        if n == 0:
            return None, 0
        hits = sum(1 for x in subset if x["rank"] is not None and 1 <= x["rank"] <= 3)
        return hits / n, n

    base_rate, base_n = fukusho_rate(rows)
    print(f"\n[ベースライン] 全馬複勝率: {base_rate:.1%} (n={base_n})" if base_rate is not None else "n=0")

    for lo, hi, label in [(1, 3, '1-3人気'), (4, 5, '4-5人気'), (6, 9, '6-9人気'), (10, 99, '10+人気')]:
        sub = [r for r in rows if r.get('popularity') and lo <= r['popularity'] <= hi]
        h = sum(1 for r in sub if r.get('rank') and 1 <= r['rank'] <= 3)
        print(f'  {label}: {h}/{len(sub)} = {h/len(sub):.1%}' if sub else f'  {label}: n=0')


if __name__ == "__main__":
    main()
