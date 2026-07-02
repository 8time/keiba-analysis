# -*- coding: utf-8 -*-
"""Phase 2: 川崎レース結果から馬歴を取得し、バックテスト用JSONを構築。

Phase 1で収集したkawasaki_races_phase1.jsonから、各馬の過去走を取得し、
末脚指数・PCI・脚質を算出。大井版(nankan_backtest_rows.json)と同じフォーマットで
kawasaki_backtest_rows.json に保存する。
"""
import sys
import io
import os
import re
import time
import json

sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from core import nankan_scraper as nk
from core import race_analysis_tools as rat

PHASE1_PATH = 'scripts/debug/kawasaki_races_phase1.json'
OUTPUT_PATH = 'scripts/debug/kawasaki_backtest_rows.json'
CACHE_PATH = 'scripts/debug/kawasaki_horse_cache.json'
PROGRESS_PATH = 'scripts/debug/kawasaki_progress.json'


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
    with open(PHASE1_PATH, encoding='utf-8') as f:
        races = json.load(f)
    print(f'Phase 2: {len(races)} races, building horse features...')

    # Resume support: load cached horse histories and progress
    horse_cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding='utf-8') as f:
            horse_cache = json.load(f)
        print(f'  Resumed: {len(horse_cache)} cached horses loaded')

    done_races = set()
    rows = []
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, encoding='utf-8') as f:
            prog = json.load(f)
            done_races = set(prog.get('done_races', []))
            rows = prog.get('rows', [])
        print(f'  Resumed: {len(done_races)} races done, {len(rows)} rows')

    total_horses = sum(len(hs) for hs in races.values())
    processed = sum(len(races[rid]) for rid in done_races if rid in races)

    for ri, (rid, results) in enumerate(races.items()):
        if rid in done_races:
            continue
        race_date = race_date_from_id(rid)
        n_horses = len(results)
        prerace = []

        for r in results:
            hid = r.get("horse_id")
            if not hid:
                processed += 1
                continue

            if hid not in horse_cache:
                hist = nk.fetch_horse_history(hid)
                horse_cache[hid] = hist
                time.sleep(0.5)
            hist = horse_cache[hid]
            processed += 1

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

        done_races.add(rid)

        if (ri + 1) % 10 == 0 or ri == len(races) - 1:
            unique_horses = len(horse_cache)
            print(f'  [{ri+1}/{len(races)}] {rid}: {n_horses}頭 (累計rows={len(rows)}, unique_horses={unique_horses}, processed={processed}/{total_horses})')
            # Checkpoint save every 20 races
            if (ri + 1) % 20 == 0:
                with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(horse_cache, f, ensure_ascii=False)
                with open(PROGRESS_PATH, 'w', encoding='utf-8') as f:
                    json.dump({'done_races': list(done_races), 'rows': rows}, f, ensure_ascii=False)
                print(f'    [checkpoint saved]')

    print(f'\nPhase 2 done: {len(rows)} rows, {len(horse_cache)} unique horses')

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f'Saved: {OUTPUT_PATH}')

    # Final checkpoint
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(horse_cache, f, ensure_ascii=False)
    with open(PROGRESS_PATH, 'w', encoding='utf-8') as f:
        json.dump({'done_races': list(done_races), 'rows': rows}, f, ensure_ascii=False)

    # Quick stats
    hits = sum(1 for r in rows if r.get('rank') and 1 <= r['rank'] <= 3)
    print(f'\n全馬複勝率: {hits}/{len(rows)} = {hits/len(rows):.1%}' if rows else 'n=0')
    for lo, hi, label in [(1, 3, '1-3人気'), (4, 5, '4-5人気'), (6, 9, '6-9人気'), (10, 99, '10+人気')]:
        sub = [r for r in rows if r.get('popularity') and lo <= r['popularity'] <= hi]
        if sub:
            h = sum(1 for r in sub if r.get('rank') and 1 <= r['rank'] <= 3)
            print(f'  {label}: {h}/{len(sub)} = {h/len(sub):.1%}')


if __name__ == '__main__':
    main()
