# -*- coding: utf-8 -*-
"""影響率(score_weights)最適化 — scripts/optimize_weights.py

jravan.dbの実レース結果を使い、Projected Scoreの影響率を座標降下法で最適化。
勝ち馬がtop-7に入る率(win recall@7)を最大化する重みを探す。

出力: 最適な .score_weights_main.json の推奨値 + 個別レース検証

使い方: python scripts/optimize_weights.py
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.build_ltr_model as bm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAL_YEAR = 2024
TEST_FROM = 2025
MIN_RUNNERS = 7

WEIGHT_KEYS = [
    ('SpeedIndex',  'h7_fig',          False),
    ('Popularity',  'ninki',           False),
    ('AvgAgari',    'spurt_mean3',     False),
    ('Jockey',      'jockey_jyo_win',  True),
    ('Suitability', 'prior_top3_rate', True),
    ('Umaban',      'umaban',          False),
    ('Stress',      '_stress',         None),
]

SEARCH_GRID = {
    'SpeedIndex':  [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    'Popularity':  [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    'AvgAgari':    [0.0, 0.2, 0.4, 0.6, 0.8],
    'Jockey':      [0.0, 0.2, 0.4, 0.6],
    'Suitability': [0.0, 0.3, 0.6, 1.0],
    'Umaban':      [0.0, 0.3, 0.6, 1.0],
    'Stress':      [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
}


def prepare():
    print('=== データ準備(build_ltr_modelパイプライン再利用) ===')
    df = bm.load_data()
    df = bm.compute_corrected_time(df)
    df = bm.compute_rolling_features(df)
    df = bm.encode_features(df)
    df = bm.compute_trainer_course(df)
    df = bm.compute_jockey_course(df)
    df = bm.compute_jockey_dist(df)
    df = bm.compute_race_ranks(df)

    df = df.dropna(subset=['ninki'])
    race_cnt = df.groupby('race_key').size()
    df = df[df['race_key'].isin(race_cnt[race_cnt >= MIN_RUNNERS].index)]

    df['_battle_proxy'] = _battle_proxy(df)
    df['_stress'] = _stress_multiplier(df)

    for wk, feat, hib in WEIGHT_KEYS:
        if feat == '_stress':
            continue
        raw = pd.to_numeric(df[feat], errors='coerce')
        df[f'_norm_{wk}'] = _normalize_in_race(raw, df['race_key'], hib)

    yi = df['year'].astype(int)
    val = df[yi == VAL_YEAR].copy()
    test = df[yi >= TEST_FROM].copy()
    print(f'Val {len(val):,} / Test {len(test):,}')
    print(f'Val races {val["race_key"].nunique():,} / Test races {test["race_key"].nunique():,}')
    return val, test


def _battle_proxy(df):
    h7 = pd.to_numeric(df['h7_fig'], errors='coerce')
    race_med = df.groupby('race_key')['h7_fig'].transform('median')
    h7_filled = h7.fillna(race_med).fillna(0)
    ogura = 80 - h7_filled * 10

    sm = pd.to_numeric(df['spurt_mean3'], errors='coerce')
    sr = df.groupby('race_key')['spurt_mean3'].rank(method='min', na_option='bottom')
    agari_bonus = np.where(sr == 1, 20, np.where(sr == 2, 15, np.where(sr == 3, 10, 0)))

    pt = pd.to_numeric(df['prior_top3_rate'], errors='coerce').fillna(0.15)
    pos_bonus = np.where(pt >= 0.5, 10, np.where(pt >= 0.3, 5, 0))

    return (ogura * 0.7 + agari_bonus + pos_bonus).clip(30, 150)


def _stress_multiplier(df):
    surface = df['surface'].astype(str)
    bataiju = pd.to_numeric(df['bataiju'], errors='coerce').fillna(460)
    zogen = pd.to_numeric(df['zogen'], errors='coerce').fillna(0)
    sm = pd.to_numeric(df['spurt_mean3'], errors='coerce')
    sr = df.groupby('race_key')['spurt_mean3'].rank(method='min', na_option='bottom')
    fs = pd.to_numeric(df['field_size'], errors='coerce').fillna(14)
    avg_pos_proxy = sr / fs * 14

    m = np.ones(len(df))
    m -= np.where((bataiju > 0) & (bataiju < 440) & (zogen <= -6), 0.04, 0)
    m -= np.where(surface.str.contains('芝', na=False) & (avg_pos_proxy >= 7.5), 0.03, 0)
    m -= np.where(zogen >= 8, 0.02, 0)
    return np.clip(m, 0.85, 1.0)


def _normalize_in_race(series, race_keys, higher_is_better):
    result = pd.Series(50.0, index=series.index)
    for rk, idx in series.groupby(race_keys).groups.items():
        vals = series.loc[idx]
        vmin, vmax = vals.min(), vals.max()
        if pd.isna(vmin) or pd.isna(vmax) or vmax <= vmin:
            continue
        if higher_is_better:
            result.loc[idx] = (vals - vmin) / (vmax - vmin) * 100
        else:
            result.loc[idx] = (vmax - vals) / (vmax - vmin) * 100
    return result.fillna(50.0)


def score_df(df, weights):
    total = df['_battle_proxy'].values * weights.get('Base', 1.0)
    for wk, feat, hib in WEIGHT_KEYS:
        if feat == '_stress':
            continue
        w = weights.get(wk, 0.0)
        if w != 0:
            total = total + df[f'_norm_{wk}'].values * w
    sw = weights.get('Stress', 0.0)
    if sw > 0:
        m = df['_stress'].values
        raw = total.copy()
        total = raw - raw * (1.0 - m) * sw
    return total


def eval_recall(df, weights):
    scores = score_df(df, weights)
    df = df.copy()
    df['_proj'] = scores

    win_hit = 0
    top3_in7 = []
    total = 0
    for rk, grp in df.groupby('race_key'):
        winner = set(grp[grp['chakujun'] == 1]['umaban'].values)
        top3 = set(grp[grp['chakujun'] <= 3]['umaban'].values)
        if not winner or not top3:
            continue
        top7 = set(grp.nlargest(7, '_proj')['umaban'].values)
        win_hit += int(bool(winner & top7))
        top3_in7.append(len(top3 & top7) / len(top3))
        total += 1
    wr = win_hit / total if total else 0
    t3r = float(np.mean(top3_in7)) if top3_in7 else 0
    return wr, t3r, total


def coordinate_descent(val_df, test_df, n_rounds=3):
    best_w = {wk: 0.0 for wk, _, _ in WEIGHT_KEYS}
    best_w['Base'] = 1.0

    base_wr_val, base_t3_val, _ = eval_recall(val_df, best_w)
    base_wr_test, base_t3_test, n_test = eval_recall(test_df, best_w)
    print(f'\nベースライン (Base=1.0 only):')
    print(f'  val  win@7={base_wr_val:.4f}  top3@7={base_t3_val:.4f}')
    print(f'  test win@7={base_wr_test:.4f}  top3@7={base_t3_test:.4f}  (races={n_test})')

    for rd in range(n_rounds):
        print(f'\n--- ラウンド {rd+1}/{n_rounds} ---')
        for wk, _, _ in WEIGHT_KEYS:
            grid = SEARCH_GRID[wk]
            best_val = best_w[wk]
            best_score = eval_recall(val_df, best_w)[0]
            for v in grid:
                trial = dict(best_w)
                trial[wk] = v
                wr, t3r, _ = eval_recall(val_df, trial)
                if wr > best_score or (wr == best_score and v < best_val):
                    best_score = wr
                    best_val = v
            if best_val != best_w[wk]:
                print(f'  {wk:15s}: {best_w[wk]:.1f} → {best_val:.1f}  (val win@7={best_score:.4f})')
                best_w[wk] = best_val
            else:
                print(f'  {wk:15s}: {best_w[wk]:.1f} (変更なし)')

    wr_val, t3_val, _ = eval_recall(val_df, best_w)
    wr_test, t3_test, n_test = eval_recall(test_df, best_w)
    print(f'\n{"="*60}')
    print(f'最適化結果:')
    print(f'  val  win@7={wr_val:.4f}  top3@7={t3_val:.4f}')
    print(f'  test win@7={wr_test:.4f}  top3@7={t3_test:.4f}  (races={n_test})')
    print(f'  改善: val {(wr_val-base_wr_val)*100:+.2f}pp / test {(wr_test-base_wr_test)*100:+.2f}pp')
    return best_w


def show_examples(df, weights, n=8):
    scores = score_df(df, weights)
    df = df.copy()
    df['_proj'] = scores

    print(f'\n{"="*60}')
    print(f'個別レース検証 (test集合からランダム{n}レース)')
    print(f'{"="*60}')

    race_keys = df['race_key'].unique()
    np.random.seed(42)
    sample = np.random.choice(race_keys, min(n, len(race_keys)), replace=False)

    hit = 0
    for rk in sample:
        grp = df[df['race_key'] == rk].sort_values('_proj', ascending=False)
        winner = grp[grp['chakujun'] == 1].iloc[0] if len(grp[grp['chakujun'] == 1]) > 0 else None
        if winner is None:
            continue
        top7_uma = set(grp.head(7)['umaban'].values)
        w_uma = int(winner['umaban'])
        w_rank = int((grp['umaban'] == w_uma).values.argmax()) + 1
        ok = w_uma in top7_uma
        if ok:
            hit += 1

        top3 = grp[grp['chakujun'] <= 3][['umaban', 'ninki', 'chakujun', '_proj']].values
        print(f'\n  {rk}  勝馬=馬番{w_uma}(人気{int(winner["ninki"])})→予測{w_rank}位 {"✓" if ok else "✗"}')
        print(f'    top3実着: ', end='')
        for u, n, c, p in top3:
            r = int((grp['umaban'] == u).values.argmax()) + 1
            print(f'馬番{int(u)}({int(c)}着/人気{int(n)})→予測{r}位  ', end='')
        print()
    print(f'\n  recall: {hit}/{len(sample)}')


def safety_net_eval(df, weights):
    """BattleScore top3がProjected top7から漏れるケースを計測"""
    scores = score_df(df, weights)
    df = df.copy()
    df['_proj'] = scores

    leaked = 0
    total = 0
    leaked_won = 0
    for rk, grp in df.groupby('race_key'):
        bp = grp['_battle_proxy'].values
        proj = grp['_proj'].values
        bp_top3 = set(grp.nlargest(3, '_battle_proxy')['umaban'].values)
        pr_top7 = set(grp.nlargest(7, '_proj')['umaban'].values)
        winners = set(grp[grp['chakujun'] == 1]['umaban'].values)
        for u in bp_top3:
            if u not in pr_top7:
                leaked += 1
                if u in winners:
                    leaked_won += 1
        total += 1

    print(f'\n🛡️ セーフティネット分析:')
    print(f'  戦闘力top3 → 予測top7漏れ: {leaked}件 (全{total}レース)')
    print(f'  うち漏れた馬が勝った: {leaked_won}件')
    print(f'  → セーフティネットが無ければ recall が {leaked_won}件 落ちる')


def to_weights_json(w):
    return {
        "NIndex": 0.0,
        "UIndex": 0.0,
        "LaboIndex": 0.0,
        "SpeedIndex": round(w.get('SpeedIndex', 0.0), 1),
        "Popularity": round(w.get('Popularity', 0.0), 1),
        "Strength (X)": 0.0,
        "Jockey": round(w.get('Jockey', 0.0), 1),
        "Training": 0.0,
        "Weight": 0.0,
        "WeightPenalty": 0.0,
        "WeightCarried": 0.0,
        "Suitability": round(w.get('Suitability', 0.0), 1),
        "AvgAgari": round(w.get('AvgAgari', 0.0), 1),
        "Umaban": round(w.get('Umaban', 0.0), 1),
        "Waku": 0.0,
        "AvgPosition": 0.0,
        "Bloodline": 0.0,
        "Base": round(w.get('Base', 1.0), 1),
        "Stress": round(w.get('Stress', 0.0), 1),
        "ScoringSignal": 0.0,
        "TopBattleBonus": 0.0
    }


def main():
    val_df, test_df = prepare()

    best_w = coordinate_descent(val_df, test_df, n_rounds=3)

    print(f'\n推奨 .score_weights_main.json:')
    wj = to_weights_json(best_w)
    print(json.dumps(wj, indent=2, ensure_ascii=False))

    safety_net_eval(test_df, best_w)
    show_examples(test_df, best_w, n=10)

    out = os.path.join(ROOT, 'data', 'optimized_weights.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(wj, f, indent=2, ensure_ascii=False)
    print(f'\n保存先: {out}')


if __name__ == '__main__':
    main()
