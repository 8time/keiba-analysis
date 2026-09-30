"""Read-only, point-in-time research for front arrival and front retention.

Exploration is restricted to 2024; 2025 is a frozen holdout.  Current-race
results, final odds and actual pace are never predictors.  This script does
not write to the database or modify production prediction code.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jravan.db"
FEATURE_GROUPS = {
    "stage1": ["past_c4", "past_front_rate", "last_c4", "history_n", "field", "waku_ratio"],
    "ability": ["past_finish", "past_top3", "past_agari", "past_ninki", "history_n", "field", "waku_ratio", "rest_days"],
    "retention_mean": ["front_loss", "front_n"],
    "retention_shape": ["front_good", "front_top3", "front_median", "front_max", "front_sd", "front_fade", "front_gain", "front_recent", "front_n"],
    "condition": ["same_distance_good", "same_course_good", "front_highload_good", "front_highload_n", "pred_pace"],
    "interaction": ["fade_x_pressure", "highload_good_x_pressure"],
}


def number(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def jv_time(x):
    s = str(x or "").strip()
    if not s.isdigit() or not int(s):
        return None
    return int(s[:-3] or 0) * 60 + int(s[-3:-1] or 0) + int(s[-1]) / 10


def date_of(r):
    return datetime.strptime(str(r["year"]) + str(r["monthday"]).zfill(4), "%Y%m%d")


def load_rows(db_path):
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT ra.race_key, ra.race_id, ra.year, ra.monthday, ra.jyo,
                  ra.kyori, ra.surface, ra.shusso_tosu, ra.mae3f,
                  z.ketto_num, z.umaban, z.waku, z.corner4, z.chakujun,
                  z.ato3f, z.time, z.ninki, z.win_odds
             FROM races ra JOIN results z ON z.race_key = ra.race_key
            WHERE CAST(ra.year AS INTEGER) BETWEEN 2018 AND 2026
              AND ra.kyori BETWEEN 1000 AND 1400
              AND ra.surface = (SELECT surface FROM races WHERE race_id='202607010611')
              AND CAST(ra.jyo AS INTEGER) BETWEEN 1 AND 10
            ORDER BY ra.year, ra.monthday, ra.race_key"""
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def race_meta(rows):
    # Fixed before the 2024 exploration year.  Past-race pace is known when
    # forecasting a later race; the current race's measured pace is never read.
    baseline = defaultdict(list)
    baseline_seen = set()
    for r in rows:
        v = number(r["mae3f"])
        if int(r["year"]) <= 2023 and v and 290 <= v <= 380 and r["race_key"] not in baseline_seen:
            baseline[(r["jyo"], r["kyori"])].append(v)
            baseline_seen.add(r["race_key"])
    cutoffs = {k: float(np.quantile(v, .25)) for k, v in baseline.items() if len(v) >= 10}
    by_race = defaultdict(list)
    for r in rows:
        threshold = cutoffs.get((r["jyo"], r["kyori"]))
        r["pace_high"] = bool(threshold and number(r["mae3f"]) and r["mae3f"] <= threshold)
        by_race[r["race_key"]].append(r)
    for group in by_race.values():
        ag = sorted(float(r["ato3f"]) for r in group if number(r["ato3f"]) and float(r["ato3f"]) > 0)
        for r in group:
            c4 = number(r["corner4"])
            fin = number(r["chakujun"])
            n = int(r["shusso_tosu"] or 0)
            r["valid"] = bool(c4 and fin and 1 <= c4 <= n and 1 <= fin <= n and n >= 8)
            r["front"] = bool(r["valid"] and c4 <= math.ceil(n * .4))
            r["finish_rel"] = (fin - 1) / max(1, n - 1) if r["valid"] else None
            a = number(r["ato3f"])
            r["agari_rel"] = (sum(v < a for v in ag) / max(1, len(ag) - 1)) if a and ag else None
            t = jv_time(r["time"])
            r["ten_speed"] = ((t - a / 10) / (r["kyori"] - 600) * 600) if t and a and r["kyori"] > 700 else None
    return by_race


def average(values, default):
    v = [x for x in values if x is not None and math.isfinite(x)]
    return sum(v) / len(v) if v else default


def make_features(current, past):
    """past must contain strictly earlier dates; no current outcome is read."""
    n = int(current["shusso_tosu"])
    old = [r for r in past if r["valid"]][-5:]
    front = [r for r in old if r["front"]]
    losses = [r["chakujun"] - r["corner4"] for r in front]
    good = lambda r: r["chakujun"] <= 3 and r["chakujun"] - r["corner4"] <= 1
    same_dist = [r for r in front if r["kyori"] == current["kyori"]]
    same_course = [r for r in front if r["jyo"] == current["jyo"]]
    fast = [r for r in front if r["pace_high"]]
    rest = (date_of(current) - date_of(old[-1])).days if old else 60
    return {
        "past_c4": average([r["corner4"] / r["shusso_tosu"] for r in old], .5),
        "past_front_rate": average([float(r["front"]) for r in old], .25),
        "last_c4": old[-1]["corner4"] / old[-1]["shusso_tosu"] if old else .5,
        "history_n": len(old), "field": n, "waku_ratio": number(current["umaban"]) / n,
        "rest_days": min(365, rest),
        "past_finish": average([r["finish_rel"] for r in old], .5),
        "past_top3": average([float(r["chakujun"] <= 3) for r in old], .2),
        "past_agari": average([r["agari_rel"] for r in old], .5),
        "past_ninki": average([(number(r["ninki"]) / r["shusso_tosu"])
                                if number(r["ninki"]) is not None else None for r in old], .5),
        "front_n": len(front),
        "front_loss": average(losses, 3.0),
        "front_good": average([float(good(r)) for r in front], .25),
        "front_top3": average([float(r["chakujun"] <= 3) for r in front], .25),
        "front_median": float(np.median(losses)) if losses else 3.0,
        "front_max": max(losses) if losses else 5.0,
        "front_sd": float(np.std(losses)) if losses else 3.0,
        "front_fade": average([float(x >= 5) for x in losses], .3),
        "front_gain": average([float(x < 0) for x in losses], .2),
        "front_recent": float(good(front[-1])) if front else .25,
        "same_distance_good": average([float(good(r)) for r in same_dist], .25),
        "same_course_good": average([float(good(r)) for r in same_course], .25),
        "front_highload_good": average([float(good(r)) for r in fast], .25),
        "front_highload_n": len(fast),
    }


def pre_pace(group, history):
    speeds = []
    for r in group:
        old = [p for p in history[r["ketto_num"]] if p["valid"] and p["ten_speed"] and 25 < p["ten_speed"] < 60][-5:]
        if len(old) < 2:
            continue
        v = old[::-1]
        w = [(.82 ** i) * (1.4 if abs(p["kyori"] - r["kyori"]) <= 400 else .6) for i, p in enumerate(v)]
        speeds.append(sum(p["ten_speed"] * q for p, q in zip(v, w)) / sum(w))
    return average(sorted(speeds)[:3], 36.0) if len(speeds) >= 5 else None


def build_dataset(rows):
    by_race = race_meta(rows)
    by_date = defaultdict(list)
    for group in by_race.values():
        by_date[date_of(group[0])].append(group)
    history = defaultdict(list)
    data = []
    for day in sorted(by_date):
        pending = []
        for group in by_date[day]:
            pace = pre_pace(group, history)
            for r in group:
                if not r["valid"]:
                    continue
                if r["kyori"] == 1200 and int(r["year"]) in (2024, 2025, 2026):
                    f = make_features(r, history[r["ketto_num"]])
                    f["pred_pace"] = pace if pace is not None else 36.0
                    f["fade_x_pressure"] = f["front_fade"] * (36.0 - f["pred_pace"])
                    f["highload_good_x_pressure"] = f["front_highload_good"] * (36.0 - f["pred_pace"])
                    f.update({"year": int(r["year"]), "race_id": r["race_id"], "horse_id": r["ketto_num"],
                              "front": int(r["front"]), "top3": int(r["chakujun"] <= 3),
                              "joint": int(r["front"] and r["chakujun"] <= 3),
                              "actual_pace": r["mae3f"] / 10 if number(r["mae3f"]) and r["mae3f"] > 0 else None,
                              "pace_available": int(pace is not None)})
                    data.append(f)
                pending.append(r)
        for r in pending:
            if r["valid"]:
                history[r["ketto_num"]].append(r)
    return data


def matrix(rows, keys):
    return np.array([[float(r[k]) for k in keys] for r in rows], dtype=float)


def fit_logit(rows, target, keys, ridge=1.0):
    x = matrix(rows, keys)
    mean = x.mean(axis=0)
    sd = x.std(axis=0)
    sd[sd < 1e-8] = 1
    x = np.column_stack([np.ones(len(x)), (x - mean) / sd])
    y = np.array([r[target] for r in rows], dtype=float)
    beta = np.zeros(x.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-np.clip(x @ beta, -30, 30)))
        w = np.maximum(p * (1 - p), 1e-7)
        penalty = np.diag([0] + [ridge] * (x.shape[1] - 1))
        delta = np.linalg.solve((x.T * w) @ x + penalty, x.T @ (y - p) - penalty @ beta)
        beta += delta
        if np.max(np.abs(delta)) < 1e-7:
            break
    return keys, mean, sd, beta


def predict(model, rows):
    keys, mean, sd, beta = model
    x = (matrix(rows, keys) - mean) / sd
    return 1 / (1 + np.exp(-np.clip(beta[0] + x @ beta[1:], -30, 30)))


def auc(y, p):
    y = np.asarray(y)
    p = np.asarray(p)
    pos = y.sum()
    if not pos or pos == len(y):
        return None
    order = np.argsort(p, kind="stable")
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    for value in np.unique(p):
        ix = np.flatnonzero(p == value)
        ranks[ix] = ranks[ix].mean()
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (len(y) - pos)))


def pr_auc(y, p):
    y = np.asarray(y)
    ix = np.argsort(-np.asarray(p))
    y = y[ix]
    if not y.sum():
        return None
    precision = np.cumsum(y) / np.arange(1, len(y) + 1)
    return float(np.sum(precision[y == 1]) / y.sum())


def report(rows, target, p, topk=3):
    y = np.array([r[target] for r in rows])
    p = np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    by_race = defaultdict(list)
    for i, r in enumerate(rows):
        by_race[r["race_id"]].append(i)
    chosen = []
    race_hits = []
    for ix in by_race.values():
        sel = sorted(ix, key=lambda i: p[i], reverse=True)[:topk]
        chosen += sel
        race_hits.append(sum(y[i] for i in sel))
    return {"n": len(y), "races": len(by_race), "rate": round(float(y.mean()), 4),
            "auc": round(auc(y, p), 4), "pr_auc": round(pr_auc(y, p), 4),
            "brier": round(float(np.mean((p - y) ** 2)), 4),
            "logloss": round(float(np.mean(-y * np.log(p) - (1-y) * np.log(1-p))), 4),
            "top3_precision": round(float(y[chosen].mean()), 4),
            "top3_recall": round(float(y[chosen].sum() / max(1, y.sum())), 4),
            "race_hit_rate": round(float(np.mean(np.array(race_hits) > 0)), 4),
            "hits_per_race": round(float(np.mean(race_hits)), 4),
            "calibration": [
                {"n": int(sum((p >= a) & (p < b))),
                 "pred": round(float(p[(p >= a) & (p < b)].mean()), 3) if any((p >= a) & (p < b)) else None,
                 "actual": round(float(y[(p >= a) & (p < b)].mean()), 3) if any((p >= a) & (p < b)) else None}
                for a, b in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]],
            }


def race_bootstrap_delta(rows, ykey, baseline, candidate, nboot=400):
    """Race-cluster bootstrap: candidate minus baseline on the frozen holdout."""
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r["race_id"]].append(i)
    ids = list(groups)
    y = np.asarray([r[ykey] for r in rows])
    rng = np.random.default_rng(20260929)
    brier = []
    aucs = []
    for _ in range(nboot):
        selected = rng.integers(0, len(ids), len(ids))
        ix = np.asarray([i for j in selected for i in groups[ids[j]]])
        brier.append(float(np.mean((candidate[ix] - y[ix])**2 - (baseline[ix] - y[ix])**2)))
        a = auc(y[ix], candidate[ix]); b = auc(y[ix], baseline[ix])
        if a is not None and b is not None:
            aucs.append(a - b)
    return {"brier_delta_ci95": [round(float(v), 4) for v in np.quantile(brier, [.025, .975])],
            "auc_delta_ci95": [round(float(v), 4) for v in np.quantile(aucs, [.025, .975])]}


def target_application(snapshot_path, db_path, s1, s2):
    """Frozen models on one pre-race snapshot; this function never reads target results."""
    cutoff = datetime.fromisoformat("2026-09-27T15:40:00+09:00")
    snapshots = []
    with snapshot_path.open(encoding="utf-8") as source:
        for line in source:
            d = json.loads(line)
            stamp = d.get("captured_at")
            if (d.get("race_id") == "202606040911" and stamp and
                    datetime.fromisoformat(stamp) < cutoff
                    and any(h.get("past_runs") for h in d.get("horses", []))):
                snapshots.append(d)
    if not snapshots:
        return {"status": "no eligible pre-race snapshot"}
    d = max(snapshots, key=lambda x: x["captured_at"])
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    # These three post-JV-cutoff race pages were independently checked against
    # the frozen snapshot; any other imputed-only corner is rejected.
    web_verified = {"202609040211", "202601020211", "202610020411"}
    out = []
    for h in d["horses"]:
        if h.get("umaban") not in (16, 6, 15, 4, 14, 5):
            continue
        past = []
        rejected = []
        for p in h.get("past_runs", []):
            rid = p.get("RaceId")
            if not rid or not (1000 <= int(p.get("Distance") or 0) <= 1400):
                rejected.append(p.get("Date")); continue
            from_jv = db.execute("SELECT corner4 FROM results WHERE race_id=? AND umaban=?",
                                 (rid, p.get("PrevUmaban"))).fetchone()
            try:
                c4 = int(str(p.get("Passing", "")).split("-")[-1])
            except ValueError:
                rejected.append(p.get("Date")); continue
            if not ((from_jv and number(from_jv[0]) == c4) or rid in web_verified):
                rejected.append(p.get("Date")); continue
            day = datetime.strptime(p["Date"], "%Y.%m.%d")
            n = int(p["FieldSize"])
            fin = int(p["Rank"])
            r = {"year": str(day.year), "monthday": day.strftime("%m%d"),
                 "jyo": rid[4:6], "kyori": int(p["Distance"]), "shusso_tosu": n,
                 "umaban": int(p["PrevUmaban"]), "corner4": c4, "chakujun": fin,
                 "valid": 1 <= c4 <= n and 1 <= fin <= n,
                 "front": c4 <= math.ceil(n * .4),
                 "finish_rel": (fin - 1) / max(1, n - 1),
                 "agari_rel": None, "ninki": None, "pace_high": False}
            past.append(r)
        past.sort(key=date_of)
        current = {"year": "2026", "monthday": "0927", "jyo": "06", "kyori": 1200,
                   "shusso_tosu": 16, "umaban": int(h["umaban"])}
        f = make_features(current, past)
        out.append({"umaban": h["umaban"], "stage1": round(float(predict(s1, [f])[0]), 3),
                    "stage2": round(float(predict(s2, [f])[0]), 3),
                    "usable_past_runs": len(past), "rejected_past_dates": rejected})
    db.close()
    for x in out:
        x["joint"] = round(x["stage1"] * x["stage2"], 3)
    return {"captured_at": d["captured_at"], "model": "transportable; no prior agari/popularity",
            "horses": sorted(out, key=lambda x: x["umaban"])}


def target_exclusions(snapshot_path, db_path):
    """Remove inspected example horses and their 2026 prior races from fresh audit."""
    selected = None
    cutoff = datetime.fromisoformat("2026-09-27T15:40:00+09:00")
    with snapshot_path.open(encoding="utf-8") as source:
        for line in source:
            d = json.loads(line)
            if d.get("race_id") == "202606040911" and d.get("captured_at") and \
                    datetime.fromisoformat(d["captured_at"]) < cutoff \
                    and any(h.get("past_runs") for h in d.get("horses", [])):
                if selected is None or d["captured_at"] > selected["captured_at"]:
                    selected = d
    if selected is None:
        return set(), set()
    races = set()
    horses = set()
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    for h in selected["horses"]:
        if h.get("umaban") not in (16, 6, 15, 4, 14, 5):
            continue
        for p in h.get("past_runs", []):
            rid = p.get("RaceId")
            if not rid:
                continue
            if rid.startswith("2026"):
                races.add(rid)
            q = db.execute("SELECT ketto_num FROM results WHERE race_id=? AND umaban=?",
                           (rid, p.get("PrevUmaban"))).fetchone()
            if q:
                horses.add(q[0])
    db.close()
    return races, horses


def pace_audit(train, test):
    """2024-frozen course quartiles; race-level, complete-case diagnostic."""
    t = {r["race_id"]: r for r in train if r["pace_available"] and r["actual_pace"] is not None}
    h = {r["race_id"]: r for r in test if r["pace_available"] and r["actual_pace"] is not None}
    by_course = defaultdict(list)
    for r in t.values():
        by_course[r["race_id"][4:6]].append(r)
    cuts = {j: (float(np.quantile([r["pred_pace"] for r in rs], .25)),
                float(np.quantile([r["actual_pace"] for r in rs], .25)))
            for j, rs in by_course.items() if len(rs) >= 5}
    rows = [r for r in h.values() if r["race_id"][4:6] in cuts]
    predicted = np.array([r["pred_pace"] <= cuts[r["race_id"][4:6]][0] for r in rows])
    actual = np.array([r["actual_pace"] <= cuts[r["race_id"][4:6]][1] for r in rows])
    corr = np.corrcoef([r["pred_pace"] for r in rows], [r["actual_pace"] for r in rows])[0, 1]
    tp = int(sum(predicted & actual))
    return {"train_races": len(t), "test_races": len(rows), "predicted_high": int(sum(predicted)),
            "actual_high": int(sum(actual)), "true_high": tp,
            "pearson_seconds": round(float(corr), 3),
            "high_precision": round(tp / max(1, int(sum(predicted))), 3),
            "high_recall": round(tp / max(1, int(sum(actual))), 3),
            "high_base_rate": round(float(np.mean(actual)), 3),
            "warning": "actual pace is evaluation label only; proxy differs from production pace_map"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args()
    data = build_dataset(load_rows(args.db))
    train = [r for r in data if r["year"] == 2024]
    test = [r for r in data if r["year"] == 2025]
    snap_path = ROOT / "data" / "research" / "forward" / "decisions.jsonl"
    excluded_races, excluded_horses = target_exclusions(snap_path, args.db)
    fresh = [r for r in data if r["year"] == 2026 and r["race_id"] not in excluded_races
             and r["horse_id"] not in excluded_horses]
    result = {"protocol": "2024 train, 2025 untouched holdout; turf 1200m; past date strictly earlier",
              "sample": {"train": len(train), "test": len(test),
                         "train_front": sum(r["front"] for r in train),
                         "test_front": sum(r["front"] for r in test),
                         "pace_coverage_train": round(sum(r["pace_available"] for r in train)/len(train), 3),
                         "pace_coverage_test": round(sum(r["pace_available"] for r in test)/len(test), 3)}}
    s1 = fit_logit(train, "front", FEATURE_GROUPS["stage1"])
    s1p = predict(s1, test)
    result["stage1"] = report(test, "front", s1p)
    trf = [r for r in train if r["front"]]
    tef = [r for r in test if r["front"]]
    models = {
        "past_finish_only": ["past_finish", "history_n"],
        "past_agari_only": ["past_agari", "history_n"],
        "past_top3_only": ["past_top3", "history_n"],
        "past_popularity_only": ["past_ninki", "history_n"],
        "stage1_only": FEATURE_GROUPS["stage1"],
        "ability": FEATURE_GROUPS["ability"],
        "ability_plus_mean": FEATURE_GROUPS["ability"] + FEATURE_GROUPS["retention_mean"],
        "ability_plus_shape": FEATURE_GROUPS["ability"] + FEATURE_GROUPS["retention_shape"],
        "ability_plus_shape_condition": FEATURE_GROUPS["ability"] + FEATURE_GROUPS["retention_shape"] + FEATURE_GROUPS["condition"],
        # Exploratory only: specified after the original 2025 holdout was inspected.
        "ability_plus_condition_interaction": FEATURE_GROUPS["ability"] + FEATURE_GROUPS["retention_shape"]
                                             + FEATURE_GROUPS["condition"] + FEATURE_GROUPS["interaction"],
    }
    result["stage2"] = {}
    predicted = {}
    for name, keys in models.items():
        model = fit_logit(trf, "top3", keys)
        p = predict(model, tef)
        predicted[name] = p
        result["stage2"][name] = report(tef, "top3", p)
        result["stage2"][name]["coefficients"] = {k: round(float(v), 3) for k, v in zip(keys, model[3][1:])}
        if name == "ability_plus_shape":
            allp = predict(model, test)
            result["joint"] = report(test, "joint", s1p * allp)
        if name == "ability":
            result["joint_ability"] = report(test, "joint", s1p * predict(model, test))
    result["joint_stage1_only"] = report(test, "joint", s1p * (sum(r["top3"] for r in trf) / len(trf)))
    result["stage2_shape_uncertainty"] = race_bootstrap_delta(
        tef, "top3", predicted["ability"], predicted["ability_plus_shape"])
    transport_keys = ["past_finish", "past_top3", "history_n", "field", "waku_ratio", "rest_days"]
    transport_base = fit_logit(trf, "top3", transport_keys)
    transport_shape = fit_logit(trf, "top3", transport_keys + FEATURE_GROUPS["retention_shape"])
    result["transportable_stage2"] = {
        "baseline": report(tef, "top3", predict(transport_base, tef)),
        "plus_shape": report(tef, "top3", predict(transport_shape, tef)),
    }
    result["target_snapshot"] = target_application(
        snap_path, args.db, s1, transport_shape)
    result["pace_prediction"] = pace_audit(train, test)
    fresh_front = [r for r in fresh if r["front"]]
    result["fresh_2026_excluding_examples"] = {
        "excluded_race_count": len(excluded_races), "excluded_horse_count": len(excluded_horses),
        "stage1": report(fresh, "front", predict(s1, fresh)) if fresh else None,
        "stage2": {name: report(fresh_front, "top3", predict(fit_logit(trf, "top3", keys), fresh_front))
                   for name, keys in models.items() if name in ("ability", "ability_plus_shape", "ability_plus_shape_condition",
                                                               "ability_plus_condition_interaction")}
                  if fresh_front else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
