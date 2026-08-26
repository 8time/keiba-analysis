# -*- coding: utf-8 -*-
"""穴馬ハンター掲載の事前材料を、複合条件で測る。

問い: 1つでは回収が上がらない材料も、A×B / A×B×C が重なった時だけ妙味になるか。
母集団: 6番人気以下。各レースの穴馬スコア1位(🎯精鋭1位)は外す。
③今回3角は使わない。パドックの返し馬はDBに無いので、ページ同じ位置の
↔バウンド（距離を返す）で代用する。

期間: 2023-2025で見る → 2026/1-6 で確認。
判定: 確認期間でも 複残差z>=+2 かつ 単ROIが穴馬母集団より明らかに高い、だけ採用。
組合せを後から全部漁ると当たり年を拾うので、下のリストだけを測る。
"""
import os
import sys
import sqlite3
from collections import defaultdict
from datetime import date

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core.pace_map import _parse_jv_time
from core.gyaku_shocker import _is_bound_shorten, _is_track_bound, _surf_tag
from scripts import csv_data as cd

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)
e3 = lambda o: (exp.get(jj._odds_band(o)) or {"top3": 0.22})["top3"]
e1 = lambda o: (exp.get(jj._odds_band(o)) or {"win": 0.08})["win"]


def to_sec(t):
    return _parse_jv_time(t)


def ymd_of(y, md):
    return f"{y}{md}"


def ord_days(y, md):
    try:
        return date(int(y), int(md[:2]), int(md[2:])).toordinal()
    except Exception:
        return 0


print("CSV 精鋭1位...", flush=True)
horses = pd.read_csv(
    cd.HORSE_CSV,
    usecols=["race_key", "umaban", "ninki", "vh2_score", "combo"],
)
horses["ninki"] = pd.to_numeric(horses["ninki"], errors="coerce")
horses["vh2_score"] = pd.to_numeric(horses["vh2_score"], errors="coerce")
horses["combo"] = pd.to_numeric(horses["combo"], errors="coerce").fillna(0).astype(int)
h6 = horses[(horses["ninki"] >= 6) & horses["vh2_score"].notna()].copy()
elite1 = {}
combo_map = {}
for rk, g in h6.groupby("race_key", sort=False):
    g2 = g.sort_values(["vh2_score", "ninki"], ascending=[False, True])
    elite1[str(rk)] = int(g2.iloc[0]["umaban"])
for r in horses.itertuples(index=False):
    combo_map[(str(r.race_key), int(r.umaban))] = int(r.combo)
print(f"  精鋭1位レース {len(elite1):,}", flush=True)

print("DB読み込み...", flush=True)
con = sqlite3.connect(DB)
rows = con.execute(
    """SELECT r.ketto_num, r.race_key, r.umaban, ra.year, ra.monthday,
              ra.kyori, ra.surface, r.corner1, r.corner3, r.chakujun,
              r.ninki, r.win_odds, r.time
       FROM results r JOIN races ra ON ra.race_key=r.race_key
       WHERE r.chakujun>0 AND ra.surface IN ('芝','ダート') AND ra.year>='2020'
         AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10
       ORDER BY r.ketto_num, ra.year, ra.monthday"""
).fetchall()
con.close()
print(f"  {len(rows):,}行", flush=True)

win_sec = {}
tmp = defaultdict(list)
for kt, rkey, um, y, md, kyori, surf, c1, c3, chaku, ninki, odds, tm in rows:
    s = to_sec(tm)
    if s is not None:
        tmp[rkey].append((chaku, s))
for rkey, lst in tmp.items():
    lst.sort(key=lambda x: (x[0] != 1, x[1]))
    win_sec[rkey] = lst[0][1]

by_horse = defaultdict(list)
for kt, rkey, um, y, md, kyori, surf, c1, c3, chaku, ninki, odds, tm in rows:
    sec = to_sec(tm)
    w = win_sec.get(rkey)
    by_horse[kt].append({
        "rk": rkey, "um": um, "ymd": ymd_of(y, md), "d": ord_days(y, md),
        "kyori": kyori or 0, "surf": _surf_tag(surf),
        "c1": c1 or 0, "c3": c3 or 0, "chaku": chaku,
        "ninki": ninki or 0, "odds": odds or 0,
        "margin": (sec - w) if (sec is not None and w is not None) else None,
    })

starts = []
for hist in by_horse.values():
    for i, cur in enumerate(hist):
        if i == 0 or cur["odds"] <= 0 or cur["ninki"] <= 0:
            continue
        prev = hist[i - 1]
        prev2 = hist[i - 2] if i >= 2 else None
        g = (0 < prev["c3"] >= 5) and (cur["kyori"] < prev["kyori"])
        b = bool(prev2 and _is_bound_shorten(
            prev2["kyori"] or None, prev["kyori"] or None, cur["kyori"] or None))
        u = bool(prev2 and _is_track_bound(prev2["surf"], prev["surf"], cur["surf"]))
        pm = prev.get("margin")
        m = (pm is not None and pm <= 0.3 and prev["chaku"] >= 4)
        c05 = (pm is not None and abs(pm) <= 0.5)
        ds = (prev["kyori"] > 0 and (prev["kyori"] - cur["kyori"]) >= 200)
        dx = (prev["kyori"] > 0 and (cur["kyori"] - prev["kyori"]) >= 200)
        sc = bool(prev["surf"] and cur["surf"] and prev["surf"] != cur["surf"])
        fl = (0 < prev["c1"] <= 3 and prev["chaku"] >= 5)
        fo = (0 < prev["ninki"] <= 5 and prev["chaku"] >= 6)
        cmb = combo_map.get((str(cur["rk"]), int(cur["um"])), 0)
        starts.append({
            **cur, "g": g, "b": b, "u": u, "m": m, "c05": c05,
            "ds": ds, "dx": dx, "sc": sc, "fl": fl, "fo": fo, "cmb": cmb,
        })

print(f"  前走付き {len(starts):,}走", flush=True)


def agg():
    return {"n": 0, "t3": 0, "w": 0, "pay1": 0.0, "r3": 0.0, "rw": 0.0}


def add(d, c):
    o = c["odds"]
    d["n"] += 1
    if c["chaku"] <= 3:
        d["t3"] += 1
    if c["chaku"] == 1:
        d["w"] += 1
        d["pay1"] += o
    d["r3"] += (1 if c["chaku"] <= 3 else 0) - e3(o)
    d["rw"] += (1 if c["chaku"] == 1 else 0) - e1(o)


def rep(name, d):
    n = d["n"]
    if n < 30:
        print(f"  {name:22s} n={n:5d} (少)")
        return
    se3 = (0.22 * 0.78 / n) ** 0.5
    se1 = (0.08 * 0.92 / n) ** 0.5
    z3 = (d["r3"] / n) / se3
    mark = " ★" if z3 >= 2.0 and d["pay1"] / n >= 1.0 else ""
    print(
        f"  {name:22s} n={n:5d} | 勝{d['w']/n:5.1%} 複{d['t3']/n:5.1%} "
        f"単ROI{d['pay1']/n:6.1%} | 複残差{d['r3']/n:+.3f}(z={z3:+.2f}) "
        f"勝残差{d['rw']/n:+.3f}(z={(d['rw']/n)/se1:+.2f}){mark}"
    )


def in_win(c, lo, hi):
    return lo <= c["ymd"] <= hi


def is_hunter(c):
    if c["ninki"] < 6:
        return False
    e = elite1.get(str(c["rk"]))
    if e is None:
        return False
    return int(c["um"]) != e


_NAME = {
    "g": "ショッカー", "b": "バウンド", "u": "芝ダ往復",
    "m": "僅差0.3", "c05": "秒差0.5", "ds": "短縮200",
    "fl": "先行負け", "fo": "力出せず",
}


def pred(flags):
    def _p(c):
        return all(c[k] for k in flags)
    _p.label = "×".join(_NAME[k] for k in flags)
    return _p


def cmb2(c):
    return c["cmb"] >= 2


cmb2.label = "検証済材料2+"


def g_cmb2(c):
    return c["g"] and c["cmb"] >= 2


g_cmb2.label = "ショッカー×検証済材料2+"


def gb_cmb2(c):
    return c["g"] and c["b"] and c["cmb"] >= 2


gb_cmb2.label = "ショッカー×バウンド×検証済材料2+"

def k_ge(n):
    keys = ("g", "b", "u", "m", "fl", "fo")

    def _p(c):
        return sum(1 for k in keys if c[k]) >= n
    _p.label = f"ページ材料{n}+"
    return _p


# ユーザー指定に近い、先に決めた組合せだけ
CHECKS = [
    pred(("g",)),
    pred(("b",)),
    pred(("u",)),
    pred(("m",)),
    pred(("c05",)),
    pred(("ds",)),
    pred(("fl",)),
    pred(("fo",)),
    cmb2,
    g_cmb2,
    gb_cmb2,
    pred(("g", "b")),
    pred(("g", "u")),
    pred(("g", "m")),
    pred(("g", "c05")),
    pred(("g", "ds")),
    pred(("g", "fl")),
    pred(("g", "fo")),
    pred(("b", "m")),
    pred(("b", "u")),
    pred(("m", "ds")),
    pred(("g", "b", "m")),
    pred(("g", "b", "u")),
    pred(("g", "m", "u")),
    pred(("g", "b", "c05")),
    k_ge(2),
    k_ge(3),
]


def run_period(title, lo, hi):
    print(f"\n======== {title} ({lo}〜{hi}) 6番人気以下・精鋭1位除外 ========")
    pool = [c for c in starts if in_win(c, lo, hi) and is_hunter(c)]
    base = agg()
    for c in pool:
        add(base, c)
    rep("穴馬母集団", base)
    for fn in CHECKS:
        d = agg()
        for c in pool:
            if fn(c):
                add(d, c)
        lab = getattr(fn, "label", "?")
        rep(lab, d)


run_period("見る期間", "20230101", "20251231")
run_period("確認 2026年前半", "20260101", "20260630")
print(
    "\n判定: ★=確認用に残差z>=2かつ単ROI>=100%。"
    "見る期間だけで★の組合せは採用しない。"
    " g=逆ショッカー①② / b=バウンド(距離を返す) / 材料2+=検証済シグナル2つ以上。"
)
