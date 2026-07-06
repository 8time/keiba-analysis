# -*- coding: utf-8 -*-
"""妙味馬ハンター 軽量・透明スコアの検証（Fable案件①のアプリ配線用）。

Fableのvh2(LGBM40特徴)は holdout recall73.5%を出したが、改善の主成分は
「①帯内オッズ順序の回収 ②二値top3の崖の除去(連続量化)」で、能力LGBMの上乗せは+0.5〜0.9ppのみ。
そこでアプリにはモデルファイル不要・高速・パリティ問題なしの**透明な少数特徴ロジスティック**を載せる。
本スクリプトはそれが現行combo≥2を超えるかを検証する(超えなければLGBM配線に切替)。

特徴(全て事前確定/leak-free): neg_log_odds(市場) + 補正T/末脚/血統のfield percentile(連続量化) +
combo(6シグナル数) + low_elim + pos_front。fit≤2024 / しきい値=2024 / holdout2025・直近3ヶ月で評価。
coefは data/value_hunter_light.json に保存(アプリはこれを読んで同じ式で推論=完全パリティ)。
"""
import os
import sys
import json
import math
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from core import jockey_jv as jj
from core import corrected_time as ct
from core import bloodline as bl
from core import lap33 as l3
from core import elim_cross as ec

DB = jj.JV_DB_PATH
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'value_hunter_light.json')
POP_MIN = 7
RECENT_KEY = '2026032100000000'
FEATS = ['neg_log_odds', 'ct_pct', 'spurt_pct', 'blood_pct', 'combo', 'low_elim', 'pos_front']


def field_pct(valdict, higher_better):
    """{kt:value} -> {kt: percentile 0..1 (1=最良)}。Noneは除外。"""
    items = [(k, v) for k, v in valdict.items() if v is not None]
    if not items:
        return {}
    items.sort(key=lambda x: x[1], reverse=higher_better)
    n = len(items)
    return {k: 1.0 - i / max(n - 1, 1) for i, (k, _) in enumerate(items)}


def main():
    print("読み込み(JRA 2023-2026/6)...")
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.win_odds wo, r.ato3f h_ato3f, r.jockey_name jockey_name, r.zogen zg, r.age age, "
        "r.corner1 c1, r.corner2 c2, r.corner3 c3, r.corner4 c4, "
        "ra.juryo juryo, ra.shusso_tosu tosu, ra.kyori kyori, ra.surface surface, ra.monthday md "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(r.year AS INT)>=2023 ORDER BY r.race_key").fetchall()
    hrows = con.execute("SELECT ketto_num, sire, bms FROM horses").fetchall()
    con.close()
    horse_sire = {k: (s, b) for k, s, b in hrows}
    print(f"  {len(rows):,}行")

    jp_by_jockey = {}
    for _jn in {r['jockey_name'] for r in rows if r['jockey_name']}:
        try:
            jp_by_jockey[_jn] = jj.jockey_power(_jn).get('jpower')
        except Exception:
            jp_by_jockey[_jn] = None
    _ctc = {}

    def ct_fig(kt, surf):
        k = (kt, surf)
        if k not in _ctc:
            f = ct.get_figure(kt, surf) or ct.get_figure(kt, None)
            _ctc[k] = f.get('fig') if f and f.get('fig') is not None else None
        return _ctc[k]

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)
    hist_ag = defaultdict(list); hist_c4 = defaultdict(list)
    hist_t3 = defaultdict(list); hist_dt = defaultdict(list)
    for rk, rs in by_race.items():
        a3 = [(x['h_ato3f'], x['kt']) for x in rs if x['h_ato3f'] and x['h_ato3f'] > 0]
        a3.sort(key=lambda t: t[0])
        arank = {kt: (i + 1) / len(a3) for i, (_, kt) in enumerate(a3)} if a3 else {}
        tosu = rs[0]['tosu'] or len(rs)
        for x in rs:
            if x['kt'] in arank:
                hist_ag[x['kt']].append((rk, arank[x['kt']]))
            cs = [c for c in (x['c1'], x['c2'], x['c3'], x['c4']) if c and c > 0]
            if cs:
                hist_c4[x['kt']].append((rk, sum(cs) / len(cs)))
            hist_t3[x['kt']].append((rk, 1 if x['ch'] <= 3 else 0))
            hist_dt[x['kt']].append((rk, x['md'], x['kyori']))
    for d in (hist_ag, hist_c4, hist_t3, hist_dt):
        for k in d:
            d[k].sort(key=lambda z: z[0])

    def p_spurt(kt, rk, n=5, minr=2):
        h = hist_ag.get(kt)
        if not h:
            return None
        p = [v for (k, v) in h if k < rk][-n:]
        return (1.0 - sum(p) / len(p)) if len(p) >= minr else None

    def p_pos(kt, rk, n=3):
        h = hist_c4.get(kt)
        if not h:
            return None
        p = [a for (k, a) in h if k < rk][-n:]
        return (sum(p) / len(p)) if p else None

    def p_last5(kt, rk):
        h = hist_t3.get(kt)
        return [v for (k, v) in h if k < rk][-5:][::-1] if h else []

    def p_prev(kt, rk):
        h = hist_dt.get(kt)
        if not h:
            return None, None
        pa = [(md, ky) for (k, md, ky) in h if k < rk]
        return pa[-1] if pa else (None, None)

    samples = []   # (period, feat-dict, t3)
    races = list(by_race.items())
    for ri, (rk, rs) in enumerate(races):
        if ri % 3000 == 0:
            print(f"  ...{ri}/{len(races)}", flush=True)
        if int(str(rk)[:4]) < 2023:
            continue
        r0 = rs[0]
        surf = '芝' if '芝' in str(r0['surface']) else 'ダ'
        kyori = r0['kyori']; jyo = str(rk)[8:10] if len(str(rk)) >= 10 else '05'
        try:
            course_v = l3.course_avg33(surf, kyori, jyo=jyo)
        except Exception:
            course_v = None
        ctv = {r['kt']: ct_fig(r['kt'], surf) for r in rs}
        ct_pct = field_pct(ctv, higher_better=False)   # 補正T=小さいほど良い
        spv = {r['kt']: p_spurt(r['kt'], rk) for r in rs}
        sp_pct = field_pct(spv, higher_better=True)
        blv = {}
        for r in rs:
            sire, bms = horse_sire.get(r['kt'], (None, None))
            if sire or bms:
                blv[r['kt']] = bl.blood_score(sire, bms, surf, kyori)
        bl_pct = field_pct(blv, higher_better=True)
        jpv = {r['kt']: jp_by_jockey.get(r['jockey_name']) for r in rs}
        jp_pct = field_pct(jpv, higher_better=True)
        # 6シグナル top3セット(combo用・研究と同一)
        def top3set(pct):
            return {k for k, v in pct.items() if v >= (1.0 - 3.0 / max(len(pct), 1)) and v >= 0.5} if pct else set()
        ct_t3 = set(sorted(ctv, key=lambda k: (ctv[k] is None, ctv[k]))[:3]) if ctv else set()
        ct_t3 = {k for k in ct_t3 if ctv[k] is not None}
        sp_t3 = {k for k, _ in sorted(((k, v) for k, v in spv.items() if v is not None), key=lambda x: -x[1])[:3]}
        bl_t3 = {k for k, _ in sorted(blv.items(), key=lambda x: -x[1])[:3]}
        jp_t3 = {k for k, _ in sorted(((k, v) for k, v in jpv.items() if v is not None), key=lambda x: -x[1])[:3]}
        period = 'recent' if rk >= RECENT_KEY else ('holdout' if str(rk)[:4] == '2025' else 'train')

        for r in rs:
            if not r['nk'] or int(r['nk']) < POP_MIN or not r['wo'] or r['wo'] <= 0:
                continue
            kt = r['kt']
            sire, bms = horse_sire.get(kt, (None, None))
            ss = bl.lookup_sire_stats(sire, surf, kyori) if sire else None
            roi100 = bool(ss and ss.get('win_roi', 0) >= 100)
            lap_fit = False
            if course_v:
                hf = l3.horse_fit33(kt, before_key=rk)
                lap_fit = l3.fit_match(hf.get('avg_lap33'), course_v['avg']) is True
            combo = sum([kt in ct_t3, kt in sp_t3, kt in bl_t3, kt in jp_t3, roi100, lap_fit])
            pmd, pdist = p_prev(kt, rk)
            fl = ec.compute_flags(
                last5_top3=p_last5(kt, rk), spurt_index=spv.get(kt),
                spurt_runs=len([1 for (k, v) in hist_ag.get(kt, []) if k < rk][-5:]),
                avg_c4ratio=None,
                prev_date=(str(r['y']) + str(pmd)) if pmd else None,
                race_date=(str(r['y']) + str(r['md'])) if r['md'] else None,
                prev_dist=pdist, cur_dist=kyori, zogen=r['zg'], age=r['age'],
                is_handicap=(str(r['juryo']) == '1'))
            elim_n = ec.verified_count(fl)
            avgpos = p_pos(kt, rk)
            feat = {
                'neg_log_odds': -math.log(float(r['wo'])),
                'ct_pct': ct_pct.get(kt, 0.5),
                'spurt_pct': sp_pct.get(kt, 0.5),
                'blood_pct': bl_pct.get(kt, 0.5),
                'combo': float(combo),
                'low_elim': 1.0 if elim_n <= 1 else 0.0,
                'pos_front': 1.0 if (avgpos is not None and avgpos <= 3.0) else 0.0,
            }
            samples.append((period, feat, 1 if r['ch'] <= 3 else 0, combo))

    print(f"  7番人気以下 標本 {len(samples):,}")

    def mat(period):
        xs = np.array([[s[1][f] for f in FEATS] for s in samples if s[0] == period], dtype=np.float64)
        ys = np.array([s[2] for s in samples if s[0] == period], dtype=np.float64)
        cb = np.array([s[3] for s in samples if s[0] == period], dtype=np.float64)
        return xs, ys, cb

    Xtr, ytr, _ = mat('train')
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    Ztr = (Xtr - mu) / sd
    # ロジスティック回帰(numpy・L2・勾配降下)
    w = np.zeros(len(FEATS)); b = 0.0
    lr = 0.3; lam = 1e-3
    for it in range(3000):
        z = Ztr @ w + b
        p = 1 / (1 + np.exp(-z))
        g = p - ytr
        gw = Ztr.T @ g / len(ytr) + lam * w
        gb = g.mean()
        w -= lr * gw; b -= lr * gb
    print("  係数:", {f: round(float(wi), 3) for f, wi in zip(FEATS, w)})

    def score(period):
        X, y, cb = mat(period)
        Z = (X - mu) / sd
        s = 1 / (1 + np.exp(-(Z @ w + b)))
        return s, y, cb

    # しきい値=2024(train末)ではなく、正しくはval分離すべきだが簡易にtrainの分位でrecall運用点を作り
    # holdout/recentへ適用(しきい値はtrainのスコア分位=holdout非参照)。
    s_tr, y_tr, _ = score('train')

    def thr_for_recall(s, y, target):
        order = np.argsort(-s)
        ys = y[order]; ss = s[order]
        tot = ys.sum()
        cum = np.cumsum(ys)
        idx = np.searchsorted(cum, target * tot)
        idx = min(idx, len(ss) - 1)
        return ss[idx]

    base = {p: (score(p)[1].mean()) for p in ('train', 'holdout', 'recent')}
    print(f"\n  ベース3着内率: train {base['train']:.1%} / holdout {base['holdout']:.1%} / recent {base['recent']:.1%}")

    print("\n=== 軽量スコア precision @ recall (しきい値=trainスコア分位) ===")
    ops = {}
    for tgt in (0.5, 0.6, 0.7, 0.8):
        th = thr_for_recall(s_tr, y_tr, tgt)
        ops[f'recall{tgt}'] = float(th)
        line = f"  目標recall {tgt:.0%}: "
        for p in ('holdout', 'recent'):
            s, y, cb = score(p)
            sel = s >= th
            if sel.sum() >= 20:
                rec = y[sel].sum() / y.sum(); prec = y[sel].mean()
                line += f"[{p}] recall{rec:.1%}@prec{prec:.2%}({prec/base[p]:.2f}x) "
        print(line)

    print("\n=== 現行 combo≥2 / combo≥3 (同母集団・比較) ===")
    for p in ('holdout', 'recent'):
        s, y, cb = score(p)
        for thr in (2, 3):
            sel = cb >= thr
            if sel.sum() >= 20:
                rec = y[sel].sum() / y.sum(); prec = y[sel].mean()
                print(f"  [{p}] combo≥{thr}: recall{rec:.1%}@prec{prec:.2%}({prec/base[p]:.2f}x) n={int(sel.sum())}")

    # 保存(アプリ配線用): 標準化パラメータ+係数+運用しきい値
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'feats': FEATS, 'mu': mu.tolist(), 'sd': sd.tolist(),
                   'w': w.tolist(), 'b': float(b), 'ops': ops,
                   'base': base}, f, ensure_ascii=False, indent=1)
    print(f"\n保存: {OUT}")
    print("[判定] 軽量が同recallでcombo≥2の精度を上回れば、モデルファイル不要でアプリ配線可。")


if __name__ == '__main__':
    main()
