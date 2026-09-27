# -*- coding: utf-8 -*-
"""
V Matrix Pace Holdout — Phase 2-1 調査用（本番非接続）。

A: build_pace_context.pace
B: predict_pace_intensity → 既存ラベルからV 3択へ折りたたみ

正解: pace_predict_backtest と同じ mae3f 距離×馬場 z（mae_z）。
3択境界: predict_pace_intensity の既存ラベル閾値（z>=0.7 ハイ / z<=-0.5 スロー / 他ミドル）。
"""
import json
import os
import sys
import sqlite3
import time
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import pace_map as pm
from core.pace_map import _V_COL, _V_ROW, resolve_v_pos

OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'vmatrix_pace_holdout')
YFROM, YTO = 2021, 2025
HOLDOUT_V_FROM = '20240101'
BABA = 'フラット'
PROFILE_MIN = 0.4
JRA_JYO = range(1, 11)
PACE_LABELS = ('スロー', 'ミドル', 'ハイ')


def connect_db():
    for attempt in range(8):
        try:
            return sqlite3.connect(f'file:{pm.JV_DB_PATH}?mode=ro', uri=True, timeout=30)
        except sqlite3.OperationalError:
            time.sleep(4)
    raise sqlite3.OperationalError('DB locked')


def z_to_pace_3(z):
    """predict_pace_intensity ラベル閾値と同じ（改変なし）。"""
    if z is None:
        return None
    if z >= 0.7:
        return 'ハイ'
    if z <= -0.5:
        return 'スロー'
    return 'ミドル'


def pint_label_to_v_pace(pint):
    """既存 label を V 3択へ（新閾値なし）。"""
    if not pint or pint.get('z') is None:
        return None
    lab = pint.get('label')
    if lab == 'ハイ想定':
        return 'ハイ'
    if lab == 'スロー想定':
        return 'スロー'
    if lab in ('ややハイ', '標準'):
        return 'ミドル'
    return None


def v_row(pace):
    v_row_idx = _V_ROW.get(pace, 1)
    vy0, vy1 = (2.0, 3.0) if v_row_idx == 0 else (1.0, 2.0) if v_row_idx == 1 else (0.0, 1.0)
    return vy0, vy1


def v_area_horses(horses, profiles, pos4, pace, baba=BABA):
    horses = [h for h in horses if h.get('umaban')]
    if len(horses) < 2:
        return set()
    max_uma = max(h['umaban'] for h in horses)
    pts = []
    for h in horses:
        pos, _ = resolve_v_pos(
            h['umaban'], h.get('name', ''), h.get('score', 0.5),
            profiles=profiles, pos4=pos4)
        gate = (h['umaban'] - 1) / max(max_uma - 1, 1)
        lane = 0.65 * gate + 0.35 * pos
        y = (1.0 - pos) * 3.0
        pts.append({'umaban': h['umaban'], 'x': lane * 3.0, 'y': y})
    v_col = _V_COL.get(baba, 0)
    vy0, vy1 = v_row(pace)
    vx0, vx1 = float(v_col), float(v_col) + 1.0
    return {p['umaban'] for p in pts if vx0 <= p['x'] <= vx1 and vy0 <= p['y'] <= vy1}


def prf(y_true, y_pred, labels):
    tp = {l: 0 for l in labels}
    fp = {l: 0 for l in labels}
    fn = {l: 0 for l in labels}
    for t, p in zip(y_true, y_pred):
        if t is None or p is None:
            continue
        for l in labels:
            if t == l and p == l:
                tp[l] += 1
            elif p == l and t != l:
                fp[l] += 1
            elif t == l and p != l:
                fn[l] += 1
    prec = {}
    rec = {}
    f1 = {}
    for l in labels:
        prec[l] = tp[l] / (tp[l] + fp[l]) if (tp[l] + fp[l]) else 0.0
        rec[l] = tp[l] / (tp[l] + fn[l]) if (tp[l] + fn[l]) else 0.0
        f1[l] = (2 * prec[l] * rec[l] / (prec[l] + rec[l])
                 if (prec[l] + rec[l]) else 0.0)
    return prec, rec, f1


def jaccard(a, b):
    if not a and not b:
        return 1.0
    u = a | b
    return len(a & b) / len(u) if u else 1.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    con = connect_db()

    # mae_z 用: 全期間から (surf,band) 統計（pace_predict_backtest 同型）
    mae_rows = con.execute(
        """SELECT ra.surface, ra.kyori, ra.mae3f
           FROM races ra
           WHERE CAST(ra.year AS INTEGER) >= 2018 AND ra.mae3f > 0"""
    ).fetchall()
    grp_mae = defaultdict(list)
    for surf, ky, mae in mae_rows:
        grp_mae[(surf, (ky or 0) // 400)].append(mae)
    mae_stats = {}
    for g, vals in grp_mae.items():
        if len(vals) >= 30:
            m = sum(vals) / len(vals)
            sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5 or 1.0
            mae_stats[g] = (m, sd)

    rks = [r[0] for r in con.execute(
        """SELECT ra.race_key FROM races ra
           WHERE CAST(ra.year AS INTEGER) BETWEEN ? AND ?
             AND ra.shusso_tosu >= 8
             AND CAST(ra.jyo AS INTEGER) BETWEEN 1 AND 10
           ORDER BY ra.race_key""",
        (YFROM, YTO)).fetchall()]

    y_true, pred_a, pred_b = [], [], []
    pace_agree_ab = 0
    b_better, a_better, tie_pace = 0, 0, 0
    conf_a = defaultdict(int)
    conf_b = defaultdict(int)

    v_jaccard = []
    v_cnt_a, v_cnt_b = [], []
    place_a = {'hit': 0, 'n': 0, 'stake': 0, 'ret': 0}
    place_b = {'hit': 0, 'n': 0, 'stake': 0, 'ret': 0}
    pace_changed = []
    v_subset_n = 0

    done_pace = 0
    for rk in rks:
        ra = con.execute(
            'SELECT kyori, surface, jyo, mae3f FROM races WHERE race_key=?', (rk,)).fetchone()
        if not ra:
            continue
        kyori, surface, jyo, mae3f = ra
        if not mae3f or mae3f <= 0:
            continue
        g = (surface, (kyori or 0) // 400)
        if g not in mae_stats:
            continue
        m, sd = mae_stats[g]
        mae_z = -(mae3f - m) / sd

        rows = con.execute(
            """SELECT umaban, bamei, chakujun, win_odds FROM results
               WHERE race_key=? AND chakujun>0""", (rk,)).fetchall()
        if len(rows) < 8:
            continue

        venue = pm.VENUE_CODES.get(str(jyo).zfill(2), '')
        horses = [{'umaban': u, 'name': nm, 'score': 0.5, 'style': '不明'}
                  for u, nm, _, _ in rows]
        profiles = pm.fetch_jv_profiles(
            [h['name'] for h in horses], max_runs=8,
            surface=surface, distance=kyori, before_key=rk)
        if sum(1 for h in horses if h['name'] in profiles) < len(horses) * PROFILE_MIN:
            continue

        layout = pm.get_course_layout(venue, surface, kyori)
        ctx = pm.build_pace_context(horses, profiles, kyori, surface, layout)
        pace_a = ctx.get('pace')
        pint = pm.predict_pace_intensity(profiles, kyori, surface)
        pace_b = pint_label_to_v_pace(pint)

        if pace_a not in PACE_LABELS or pace_b not in PACE_LABELS:
            continue

        gt = z_to_pace_3(mae_z)
        y_true.append(gt)
        pred_a.append(pace_a)
        pred_b.append(pace_b)
        conf_a[(gt, pace_a)] += 1
        conf_b[(gt, pace_b)] += 1

        ok_a = pace_a == gt
        ok_b = pace_b == gt
        if ok_b and not ok_a:
            b_better += 1
        elif ok_a and not ok_b:
            a_better += 1
        else:
            tie_pace += 1
        if pace_a == pace_b:
            pace_agree_ab += 1
        done_pace += 1

        # V impact (pos4固定・baba固定)
        pos4 = ctx.get('pos4') or {}
        if len(pos4) < len(horses) * 0.5:
            continue
        if rk[:8] < HOLDOUT_V_FROM:
            continue

        va = v_area_horses(horses, profiles, pos4, pace_a, BABA)
        vb = v_area_horses(horses, profiles, pos4, pace_b, BABA)
        v_jaccard.append(jaccard(va, vb))
        v_cnt_a.append(len(va))
        v_cnt_b.append(len(vb))
        odds = {u: o for u, _, _, o in rows if o and o > 0}
        chak = {u: c for u, _, c, _ in rows}
        for acc, vset in ((place_a, va), (place_b, vb)):
            for u in vset:
                c, o = chak.get(u), odds.get(u)
                if c is None or o is None:
                    continue
                acc['n'] += 1
                acc['stake'] += 100
                if c <= 3:
                    acc['hit'] += 1
                if c == 1:
                    acc['ret'] += int(o * 100)
        if pace_a != pace_b:
            pa_hit = sum(1 for u in va if chak.get(u, 99) <= 3)
            pb_hit = sum(1 for u in vb if chak.get(u, 99) <= 3)
            na = len(va) or 1
            nb = len(vb) or 1
            pace_changed.append({
                'pa': pa_hit / na, 'pb': pb_hit / nb,
                'va': len(va), 'vb': len(vb),
            })
        v_subset_n += 1

    con.close()

    labels = list(PACE_LABELS)
    acc_a = sum(1 for t, p in zip(y_true, pred_a) if t == p) / len(y_true) if y_true else 0
    acc_b = sum(1 for t, p in zip(y_true, pred_b) if t == p) / len(y_true) if y_true else 0
    pa, ra_, fa = prf(y_true, pred_a, labels)
    pb, rb, fb = prf(y_true, pred_b, labels)
    macro_f1_a = sum(fa.values()) / 3
    macro_f1_b = sum(fb.values()) / 3

    def place_rate(acc):
        return acc['hit'] / acc['n'] if acc['n'] else None

    def win_roi(acc):
        return (acc['ret'] - acc['stake']) / acc['stake'] if acc['stake'] else None

    summary = {
        'period': f'{YFROM}-{YTO}',
        'pace_races': done_pace,
        'v_races': v_subset_n,
        'v_from': HOLDOUT_V_FROM,
        'ground_truth': 'mae3f z (surf,band) thresholds z>=0.7ハイ z<=-0.5スロー',
        'accuracy_a': acc_a,
        'accuracy_b': acc_b,
        'macro_f1_a': macro_f1_a,
        'macro_f1_b': macro_f1_b,
        'precision_a': pa,
        'precision_b': pb,
        'recall_a': ra_,
        'recall_b': rb,
        'f1_a': fa,
        'f1_b': fb,
        'confusion_a': {f'{k}->{v}': c for k, v in conf_a for c in [conf_a[(k, v)]]},
        'confusion_b': {f'{k}->{v}': c for k, v in conf_b for c in [conf_b[(k, v)]]},
        'conf_a_raw': {f'{k[0]}->{k[1]}': v for k, v in conf_a.items()},
        'conf_b_raw': {f'{k[0]}->{k[1]}': v for k, v in conf_b.items()},
        'b_better': b_better,
        'a_better': a_better,
        'tie_pace': tie_pace,
        'ab_agree_rate': pace_agree_ab / done_pace if done_pace else 0,
        'v_jaccard_mean': sum(v_jaccard) / len(v_jaccard) if v_jaccard else None,
        'v_count_a_mean': sum(v_cnt_a) / len(v_cnt_a) if v_cnt_a else None,
        'v_count_b_mean': sum(v_cnt_b) / len(v_cnt_b) if v_cnt_b else None,
        'place_rate_a': place_rate(place_a),
        'place_rate_b': place_rate(place_b),
        'win_roi_a': win_roi(place_a),
        'win_roi_b': win_roi(place_b),
        'pace_changed_races': len(pace_changed),
        'pace_changed_place_a': (sum(x['pa'] for x in pace_changed) / len(pace_changed)
                                 if pace_changed else None),
        'pace_changed_place_b': (sum(x['pb'] for x in pace_changed) / len(pace_changed)
                                 if pace_changed else None),
    }

    with open(os.path.join(OUT_DIR, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print('=' * 60)
    print(f'pace holdout {done_pace}R ({YFROM}-{YTO})  V subset {v_subset_n}R (>={HOLDOUT_V_FROM})')
    print(f'Accuracy  A={acc_a:.4f}  B={acc_b:.4f}')
    print(f'Macro F1  A={macro_f1_a:.4f}  B={macro_f1_b:.4f}')
    print(f'Per-race  B better={b_better}  A better={a_better}  tie={tie_pace}')
    print(f'A-B agree pace={summary["ab_agree_rate"]:.4f}')
    print(f'V Jaccard={summary["v_jaccard_mean"]:.4f}  count A={summary["v_count_a_mean"]:.3f} B={summary["v_count_b_mean"]:.3f}')
    pr_a = place_rate(place_a)
    pr_b = place_rate(place_b)
    if pr_a is not None:
        print(f'Place A={pr_a*100:.2f}% B={pr_b*100:.2f}%')
    roi_a = win_roi(place_a)
    roi_b = win_roi(place_b)
    if roi_a is not None:
        print(f'WinROI A={roi_a*100:+.2f}% B={roi_b*100:+.2f}%')


if __name__ == '__main__':
    main()
