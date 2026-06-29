# -*- coding: utf-8 -*-
"""影響率最適化(アプリ実特徴量版) — scripts/optimize_weights_app.py

score_cacheのfull.jsonに保存されたアプリ実計算値 + jravan.dbの実着順を使い、
Projected Scoreの影響率を最適化。

proxy版(optimize_weights.py)で Popularity=1.0, Stress=2.0 が最適だった。
ここでは、アプリ固有の特徴量(NIndex, Bloodline, ScoringSignal等)を
追加で足すと改善するかを検証。
"""
import os, sys, json, sqlite3
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BONUS_KEYS = [
    'NIndex', 'SpeedIndex', 'Popularity', 'Jockey', 'Suitability',
    'AvgAgari', 'Umaban', 'Waku', 'AvgPosition', 'Bloodline',
    'ScoringSignal', 'Training', 'Weight', 'WeightCarried',
    'UIndex', 'LaboIndex', 'Strength (X)',
]


def load_cached_races():
    cache_dir = os.path.join(ROOT, 'data', 'score_cache')
    con = sqlite3.connect(os.path.join(ROOT, 'data', 'jravan.db'))
    races = []

    for fn in sorted(os.listdir(cache_dir)):
        if not fn.endswith('.full.json'):
            continue
        app_id = fn.replace('.full.json', '')
        yr = app_id[0:4]
        jyo = app_id[4:6]
        kai = int(app_id[6:8])
        nichi = int(app_id[8:10])
        race_num = int(app_id[10:12])

        jv_rows = con.execute(
            'SELECT race_key, race_name FROM races WHERE year=? AND jyo=? AND kai=? AND nichi=? AND race_num=?',
            (yr, jyo, kai, nichi, race_num)).fetchall()
        if not jv_rows:
            continue
        jv_key = jv_rows[0][0]
        race_name = jv_rows[0][1]

        results = {}
        for r in con.execute('SELECT umaban, chakujun FROM results WHERE race_key=? AND chakujun>0', (jv_key,)):
            results[int(r[0])] = int(r[1])
        if len(results) < 7:
            continue

        with open(os.path.join(cache_dir, fn), 'r', encoding='utf-8') as f:
            d = json.load(f)

        horses = []
        for rec in d.get('records', []):
            u = int(rec.get('Umaban', 0))
            if u <= 0 or u not in results:
                continue
            h = {
                'umaban': u,
                'chakujun': results[u],
                'battle': _float(rec.get('BattleScore')),
            }
            for bk in BONUS_KEYS:
                col = f'{bk}_Bonus'
                h[f'bonus_{bk}'] = _float(rec.get(col))
            h['stress'] = _float(rec.get('Stress'))
            horses.append(h)

        if len(horses) >= 7:
            races.append({'app_id': app_id, 'jv_key': jv_key, 'name': race_name, 'horses': horses})

    con.close()
    return races


def _float(v):
    try:
        f = float(v)
        return f if f == f else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_proj(horses, weights):
    scores = []
    for h in horses:
        s = h['battle'] * weights.get('Base', 1.0)
        for bk in BONUS_KEYS:
            w = weights.get(bk, 0.0)
            if w != 0:
                s += h[f'bonus_{bk}'] * w
        sw = weights.get('Stress', 0.0)
        if sw != 0 and h['stress'] != 0:
            s += h['stress'] * sw
        scores.append((h['umaban'], s, h['chakujun']))
    return scores


def eval_weights(races, weights):
    win_hit = 0
    top3_in7 = []
    for race in races:
        scored = compute_proj(race['horses'], weights)
        scored.sort(key=lambda x: -x[1])
        top7_uma = set(s[0] for s in scored[:7])
        winners = set(s[0] for s in scored if s[2] == 1)
        top3 = set(s[0] for s in scored if s[2] <= 3)
        if winners:
            win_hit += int(bool(winners & top7_uma))
        if top3:
            top3_in7.append(len(top3 & top7_uma) / len(top3))
    n = len(races)
    return (win_hit / n if n else 0, np.mean(top3_in7) if top3_in7 else 0, n)


def show_detail(races, weights, label=''):
    print(f'\n{"="*70}')
    if label:
        print(f'  {label}')
    for race in races:
        scored = compute_proj(race['horses'], weights)
        scored.sort(key=lambda x: -x[1])
        top7_uma = set(s[0] for s in scored[:7])
        top3_actual = [(s[0], s[2]) for s in scored if s[2] <= 3]
        winner = [s for s in scored if s[2] == 1]
        w_uma = winner[0][0] if winner else '?'
        w_rank = next((i+1 for i, s in enumerate(scored) if s[2] == 1), '?')
        ok = w_uma in top7_uma

        print(f'\n  {race["app_id"]} {race["name"]}  勝馬=馬番{w_uma}→予測{w_rank}位 {"✓" if ok else "✗"}')
        for uma, chaku in sorted(top3_actual, key=lambda x: x[1]):
            r = next((i+1 for i, s in enumerate(scored) if s[0] == uma), '?')
            mark = '✓' if uma in top7_uma else '✗'
            print(f'    {chaku}着 馬番{uma} → 予測{r}位 {mark}')


def main():
    races = load_cached_races()
    print(f'キャッシュレース: {len(races)}件 (jravan結果あり)')
    for r in races:
        print(f'  {r["app_id"]} {r["name"]} ({len(r["horses"])}頭)')

    # ① ベースライン: Base=1.0 のみ
    base_w = {'Base': 1.0}
    wr, t3r, n = eval_weights(races, base_w)
    print(f'\n① Base=1.0 only: win@7={wr:.3f} top3@7={t3r:.3f} (n={n})')

    # ② proxy最適結果: Popularity=1.0, Stress=2.0
    proxy_w = {'Base': 1.0, 'Popularity': 1.0, 'Stress': 2.0}
    wr2, t3r2, _ = eval_weights(races, proxy_w)
    print(f'② Proxy最適 (Pop=1.0,Stress=2.0): win@7={wr2:.3f} top3@7={t3r2:.3f}')

    # ③ 各ボーナスの add-one テスト (proxy最適 + 1項目追加)
    print(f'\n③ add-one テスト (proxy最適ベース + 各項目)')
    candidates = []
    for bk in BONUS_KEYS:
        if bk == 'Popularity':
            continue
        best_v = 0.0
        best_score = wr2
        for v in [0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0]:
            trial = dict(proxy_w)
            trial[bk] = v
            wr_t, t3_t, _ = eval_weights(races, trial)
            if wr_t > best_score or (wr_t == best_score and t3_t > t3r2):
                best_score = wr_t
                best_v = v
        wr_b, t3_b, _ = eval_weights(races, {**proxy_w, bk: best_v})
        d_wr = wr_b - wr2
        d_t3 = t3_b - t3r2
        tag = f'★改善' if d_wr > 0 or (d_wr == 0 and d_t3 > 0.01) else ''
        print(f'  +{bk:20s} best_w={best_v:.1f}  win@7={wr_b:.3f}({d_wr*100:+.1f}pp)  '
              f'top3@7={t3_b:.3f}({d_t3*100:+.1f}pp) {tag}')
        candidates.append((bk, best_v, d_wr, d_t3))

    # ④ 改善候補をまとめて足す
    improved = [(bk, v) for bk, v, dw, dt in candidates if dw > 0 or (dw == 0 and dt > 0.01)]
    if improved:
        combo_w = dict(proxy_w)
        for bk, v in improved:
            combo_w[bk] = v
        wr_c, t3_c, _ = eval_weights(races, combo_w)
        print(f'\n④ 改善候補まとめ:')
        for bk, v in improved:
            print(f'  {bk}={v}')
        print(f'  win@7={wr_c:.3f} top3@7={t3_c:.3f}')
    else:
        combo_w = dict(proxy_w)
        print(f'\n④ 改善候補なし (proxy最適が最良)')

    # ⑤ Stress微調整
    print(f'\n⑤ Stress微調整:')
    best_stress = combo_w.get('Stress', 2.0)
    best_combo_wr = eval_weights(races, combo_w)[0]
    for sv in [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]:
        trial = dict(combo_w)
        trial['Stress'] = sv
        wr_s, t3_s, _ = eval_weights(races, trial)
        mark = '←' if sv == best_stress else ''
        if wr_s > best_combo_wr or (wr_s == best_combo_wr and sv < best_stress):
            best_combo_wr = wr_s
            best_stress = sv
            mark = '★'
        print(f'  Stress={sv:4.1f}  win@7={wr_s:.3f}  top3@7={t3_s:.3f} {mark}')
    combo_w['Stress'] = best_stress

    # 最終結果
    wr_f, t3_f, _ = eval_weights(races, combo_w)
    print(f'\n{"="*70}')
    print(f'最終推奨:')
    for k, v in sorted(combo_w.items()):
        if v != 0:
            print(f'  {k}: {v}')
    print(f'  win@7={wr_f:.3f}  top3@7={t3_f:.3f}')

    show_detail(races, combo_w, '最終推奨での各レース詳細')

    # JSON出力
    out = {
        "NIndex": 0.0, "UIndex": 0.0, "LaboIndex": 0.0,
        "SpeedIndex": 0.0, "Popularity": 0.0, "Strength (X)": 0.0,
        "Jockey": 0.0, "Training": 0.0, "Weight": 0.0,
        "WeightPenalty": 0.0, "WeightCarried": 0.0,
        "Suitability": 0.0, "AvgAgari": 0.0, "Umaban": 0.0,
        "Waku": 0.0, "AvgPosition": 0.0, "Bloodline": 0.0,
        "Base": 1.0, "Stress": 0.0, "ScoringSignal": 0.0,
        "TopBattleBonus": 0.0,
    }
    for k, v in combo_w.items():
        if k in out:
            out[k] = round(v, 1)
    print(f'\n推奨 .score_weights_main.json:')
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
