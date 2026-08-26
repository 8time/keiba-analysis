# -*- coding: utf-8 -*-
"""実験『血統期待値』の答え合わせ。通常の期待値・血統期待値・両方高い、を比較する。

使う式は core/blood_ev.py と同じ。スマート出馬表のデータは使わない。
見る期間=2023-2025 / 確認=2026年1〜6月。残差z>=2 かつ 回収が母集団より良い、だけ採用。
"""
import os
import sys
import sqlite3

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import blood_ev as bev
from core import bloodline as bl
from core import jockey_jv as jj

print("較正...", flush=True)
bands = bev.calibrate_bands()
print("DB...", flush=True)
con = sqlite3.connect(f"file:{jj.JV_DB_PATH}?mode=ro", uri=True)
rows = con.execute(
    """SELECT ra.race_key, ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori,
              r.ninki, r.win_odds, r.chakujun, h.sire, h.bms
       FROM results r
       JOIN races ra ON ra.race_key=r.race_key
       LEFT JOIN horses h ON h.ketto_num=r.ketto_num
       WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート') AND ra.year>='2023'
         AND r.win_odds>0 AND r.ninki>0
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
       ORDER BY ra.race_key"""
).fetchall()
con.close()
print(f"  {len(rows):,}走", flush=True)

from collections import defaultdict
by_race = defaultdict(list)
meta = {}
for rk, y, md, jyo, surf, kyori, ninki, odds, chaku, sire, bms in rows:
    meta[rk] = (f"{y}{md}", jyo, surf, kyori)
    by_race[rk].append({
        'sire': sire, 'bms': bms, 'odds': odds, 'ninki': ninki, 'chaku': chaku,
    })


def agg():
    return {"n": 0, "t3": 0, "w": 0, "pay1": 0.0, "r3": 0.0}


def add(d, odds, chaku, e3):
    d["n"] += 1
    if chaku <= 3:
        d["t3"] += 1
    if chaku == 1:
        d["w"] += 1
        d["pay1"] += odds
    d["r3"] += (1 if chaku <= 3 else 0) - e3


def rep(name, d):
    n = d["n"]
    if n < 40:
        print(f"  {name:22s} n={n:5d} (少)")
        return
    se = (0.22 * 0.78 / n) ** 0.5
    z = (d["r3"] / n) / se
    print(
        f"  {name:22s} n={n:5d} | 勝{d['w']/n:5.1%} 複{d['t3']/n:5.1%} "
        f"単ROI{d['pay1']/n:6.1%} | 複残差{d['r3']/n:+.3f}(z={z:+.2f})"
        + (" ★" if z >= 2 and d["pay1"] / n >= 1.0 else "")
    )


def run(title, lo, hi, local_dirt=False):
    print(f"\n======== {title} ({lo}〜{hi}"
          + ("・地方場ダ短〜1700" if local_dirt else "") + ") ========")
    keys = ("all", "win_hi", "blood_hi", "overlap", "blood_hi_no_e")
    buckets = {k: agg() for k in keys}
    for rk, hs in by_race.items():
        ymd, jyo, surf, kyori = meta[rk]
        if not (lo <= ymd <= hi):
            continue
        if local_dirt:
            if str(surf) != "ダート" or str(jyo) not in ("01", "02", "03", "04", "10"):
                continue
            if not (1150 <= int(kyori or 0) <= 1800):
                continue
        marked = bev.annotate_race(hs, surf, kyori, bands)
        for r in marked:
            odds, chaku = r["odds"], r["chaku"]
            b = bev.odds_band_i(odds)
            e3 = (bands.get(b) or {}).get("top3", 0.22)
            add(buckets["all"], odds, chaku, e3)
            if r["win_label"] == "高い" and not r["skip_e"]:
                add(buckets["win_hi"], odds, chaku, e3)
            if r["blood_label"] == "高い":
                add(buckets["blood_hi"], odds, chaku, e3)
                if not r["skip_e"]:
                    add(buckets["blood_hi_no_e"], odds, chaku, e3)
            if r["overlap"]:
                add(buckets["overlap"], odds, chaku, e3)
    rep("母集団", buckets["all"])
    rep("通常の期待値=高い", buckets["win_hi"])
    rep("血統期待値=高い", buckets["blood_hi"])
    rep("血統高い・大穴除外", buckets["blood_hi_no_e"])
    rep("両方高い(重なり)", buckets["overlap"])


run("見る期間", "20230101", "20251231")
run("確認 2026年前半", "20260101", "20260630")
run("確認 ローカルダ", "20230101", "20251231", local_dirt=True)
run("確認 ローカルダ2026", "20260101", "20260630", local_dirt=True)
print("\n★=残差z>=2かつ単ROI>=100%。通常の期待値は帯の平均回収なので個体予想ではない。")
