# -*- coding: utf-8 -*-
"""
展開マップ予測のバックテスト基盤（Phase 0）。

過去レースを「そのレース以前の走歴だけ」で予測し、実際の4角通過順位と突き合わせて
精度を測る。旧ロジック（過去走のコーナー平均位置）と新ロジック（build_pace_context の
pos4）を同一プロファイルから導出して比較する。

指標:
  - spearman : 予測順位 vs 実4角順位の順位相関（高いほど良い／1.0で完全一致）
  - leader_hit_rate : 実際に4角先頭だった馬を予測先頭に当てた率
  - top3_overlap : 予測上位3頭と実上位3頭の被り率（0〜1）
"""
import sqlite3
import random

from core import pace_map as pm


def ensure_index(db):
    """馬名検索を高速化するインデックスを用意（初回のみ・恒久的に有効）。"""
    con = sqlite3.connect(db)
    con.execute("CREATE INDEX IF NOT EXISTS idx_results_bamei ON results(bamei)")
    con.commit()
    con.close()


def _spearman(pred, actual):
    """pred/actual: {umaban: value}。共通キーで順位相関を返す。"""
    us = [u for u in pred if u in actual]
    n = len(us)
    if n < 3:
        return None

    def ranks(d):
        order = sorted(us, key=lambda u: (d[u], u))
        return {u: i for i, u in enumerate(order)}

    rp, ra = ranks(pred), ranks(actual)
    d2 = sum((rp[u] - ra[u]) ** 2 for u in us)
    return 1 - 6 * d2 / (n * (n * n - 1))


def _baseline_pos(profiles, horses):
    """旧ロジック相当: 過去走のコーナー平均位置(c4→c3→ten)をそのまま使う。"""
    out = {}
    for h in horses:
        prof = profiles.get(h['name']) or {}
        v = prof.get('c4')
        if v is None:
            v = prof.get('c3')
        if v is None:
            v = prof.get('ten')
        out[h['umaban']] = 0.5 if v is None else v
    return out


def collect_cases(db_path=None, n_races=150, years=('2024', '2025'),
                  seed=42, min_field=8, max_runs=5):
    """DBから評価ケースを収集（重いDB処理はここだけ）。tune を変えた評価は evaluate() で。
    各ケース: {horses, profiles, actual_n, layout, kyori, surface, base}"""
    db = db_path or pm.JV_DB_PATH
    ensure_index(db)
    con = sqlite3.connect(db)
    yfilter = " OR ".join(["year=?"] * len(years))
    rks = [r[0] for r in con.execute(
        f"SELECT race_key FROM races WHERE ({yfilter}) AND shusso_tosu>=?",
        tuple(years) + (min_field,))]
    random.seed(seed)
    random.shuffle(rks)

    cases = []
    for rk in rks:
        if len(cases) >= n_races:
            break
        ra = con.execute(
            "SELECT kyori, surface, shusso_tosu, jyo FROM races WHERE race_key=?", (rk,)
        ).fetchone()
        if not ra:
            continue
        kyori, surface, tosu, jyo = ra
        rows = con.execute(
            "SELECT umaban, bamei, corner3, corner4, chakujun, ninki FROM results "
            "WHERE race_key=? AND chakujun>0", (rk,)).fetchall()
        actual, names, finish_act, ninki = {}, {}, {}, {}
        for u, bamei, c3, c4, chaku, nin in rows:
            names[u] = bamei
            cc = c4 if (c4 and c4 > 0) else (c3 if (c3 and c3 > 0) else None)
            if cc:
                actual[u] = cc
            if chaku and chaku > 0:
                finish_act[u] = chaku
            if nin and nin > 0:
                ninki[u] = nin
        if len(actual) < max(5, tosu * 0.6):
            continue
        amax = max(actual.values())
        actual_n = {u: (v - 1) / max(amax - 1, 1) for u, v in actual.items()}
        fmax = max(finish_act.values()) if finish_act else 1
        finish_n = {u: (v - 1) / max(fmax - 1, 1) for u, v in finish_act.items()}
        profiles = pm.fetch_jv_profiles(
            list({names[u] for u in actual_n}), db_path=db, max_runs=max_runs,
            surface=surface, distance=kyori, before_key=rk)
        horses = [{'umaban': u, 'name': names[u], 'score': None, 'style': '不明'}
                  for u in actual_n]
        if sum(1 for h in horses if h['name'] in profiles) < max(4, len(horses) * 0.4):
            continue
        venue = pm.VENUE_CODES.get(str(jyo).zfill(2), '')
        layout = pm.get_course_layout(venue, surface, kyori)
        cases.append({'horses': horses, 'profiles': profiles, 'actual_n': actual_n,
                      'finish_n': finish_n, 'ninki': ninki,
                      'layout': layout, 'kyori': kyori, 'surface': surface,
                      'base': _baseline_pos(profiles, horses)})
    con.close()
    return cases


def _mean(x):
    return round(sum(x) / len(x), 4) if x else float('nan')


def evaluate(cases, tune=None, label='v2'):
    """収集済みケースを tune で評価。baseline と並べて返す。"""
    agg = {'baseline': [], label: []}
    leader_hit = {'baseline': 0, label: 0}
    top3 = {'baseline': [], label: []}
    used = 0
    for c in cases:
        pos4 = pm.predict_corner_order(c['horses'], c['profiles'], c['kyori'],
                                       c['surface'], c['layout'], tune=tune)
        base, actual_n = c['base'], c['actual_n']
        common = [u for u in actual_n if u in pos4 and u in base]
        if len(common) < 4:
            continue
        a = {u: actual_n[u] for u in common}
        sp_b = _spearman({u: base[u] for u in common}, a)
        sp_v = _spearman({u: pos4[u] for u in common}, a)
        if sp_b is not None:
            agg['baseline'].append(sp_b)
        if sp_v is not None:
            agg[label].append(sp_v)
        al = min(common, key=lambda u: (a[u], u))
        if min(common, key=lambda u: (base[u], u)) == al:
            leader_hit['baseline'] += 1
        if min(common, key=lambda u: (pos4[u], u)) == al:
            leader_hit[label] += 1
        at3 = set(sorted(common, key=lambda u: (a[u], u))[:3])
        top3['baseline'].append(len(at3 & set(sorted(common, key=lambda u: (base[u], u))[:3])) / 3)
        top3[label].append(len(at3 & set(sorted(common, key=lambda u: (pos4[u], u))[:3])) / 3)
        used += 1
    return {
        'races': used,
        'spearman': {k: _mean(v) for k, v in agg.items()},
        'leader_hit_rate': {k: round(leader_hit[k] / used, 4) if used else float('nan')
                            for k in leader_hit},
        'top3_overlap': {k: _mean(v) for k, v in top3.items()},
    }


def evaluate_finish(cases, tune=None):
    """直線=着順予測の精度を、複数モデルを実chakujunと突き合わせて比較する。
    モデル: pos4_only(4角のみ) / power_only(着順履歴のみ) / pop_only(人気のみ) /
            finish(predict_finish=人気込み合成)。"""
    models = ('pos4_only', 'power_only', 'pop_only', 'finish')
    sp = {m: [] for m in models}
    win_hit = {m: 0 for m in models}
    top3 = {m: [] for m in models}
    used = 0
    for c in cases:
        fn = c.get('finish_n')
        if not fn:
            continue
        ctx = pm.build_pace_context(c['horses'], c['profiles'], c['kyori'],
                                    c['surface'], c['layout'])
        pos4 = ctx.get('pos4', {})
        name_of = {h['umaban']: h['name'] for h in c['horses']}
        power = {u: (c['profiles'].get(name_of[u]) or {}).get('finish_hist') for u in pos4}
        power_n = pm._rank_norm(power)
        ninki = c.get('ninki', {})
        pop_n = pm._rank_norm({u: ninki.get(u) for u in pos4})
        extras = {u: {'pop': ninki[u]} for u in ninki}   # 人気を finish に供給
        finish = pm.predict_finish(c['horses'], c['profiles'], ctx, extras=extras, tune=tune)
        preds = {'pos4_only': pos4, 'power_only': power_n, 'pop_only': pop_n, 'finish': finish}

        common = [u for u in fn if u in pos4]
        if len(common) < 4:
            continue
        a = {u: fn[u] for u in common}
        winner = min(common, key=lambda u: (a[u], u))
        at3 = set(sorted(common, key=lambda u: (a[u], u))[:3])
        for m in models:
            pm_pred = {u: preds[m][u] for u in common}
            s = _spearman(pm_pred, a)
            if s is not None:
                sp[m].append(s)
            if min(common, key=lambda u: (pm_pred[u], u)) == winner:
                win_hit[m] += 1
            pt3 = set(sorted(common, key=lambda u: (pm_pred[u], u))[:3])
            top3[m].append(len(at3 & pt3) / 3)
        used += 1
    return {
        'races': used,
        'spearman_vs_chaku': {m: _mean(sp[m]) for m in models},
        'winner_hit': {m: round(win_hit[m] / used, 4) if used else float('nan') for m in models},
        'top3_overlap': {m: _mean(top3[m]) for m in models},
    }


def run_backtest(db_path=None, n_races=150, years=('2024', '2025'),
                 seed=42, min_field=8, max_runs=5, verbose=True, tune=None):
    cases = collect_cases(db_path, n_races, years, seed, min_field, max_runs)
    report = evaluate(cases, tune=tune)
    if verbose:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    run_backtest(n_races=n)
