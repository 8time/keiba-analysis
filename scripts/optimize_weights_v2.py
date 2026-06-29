# -*- coding: utf-8 -*-
"""影響率最適化 v2 — jravan.dbからOgura/BattleScore を正確に再現

v1の問題: h7_fig をBattleScore代理にしたが、実アプリのOgura Index
(着順ベース×GI倍率×近走倍率の直近10走平均)と全く違う計算→結果がバラバラ。

v2: jravan.dbからOgura Indexを忠実に再現し、BattleScore→bonus正規化→
weight最適化の全工程をアプリと同じロジックで実行。6000+レースで検証。
"""
import os, sys, json, sqlite3
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scripts.build_ltr_model as bm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
VAL_YEAR = 2024
TEST_FROM = 2025

WEIGHT_KEYS = ['SpeedIndex', 'Popularity', 'AvgAgari', 'Jockey',
               'Suitability', 'Umaban', 'Stress']

GRID = {
    'SpeedIndex':  [0.0, 0.3, 0.6, 1.0],
    'Popularity':  [0.0, 0.3, 0.6, 1.0, 1.5],
    'AvgAgari':    [0.0, 0.3, 0.6, 1.0],
    'Jockey':      [0.0, 0.3, 0.6],
    'Suitability': [0.0, 0.3, 0.6, 1.0],
    'Umaban':      [0.0, 0.3, 0.6, 1.0],
    'Stress':      [0.0, 0.5, 1.0, 2.0, 5.0],
}


def prepare():
    print('=== データ準備 ===')
    df = bm.load_data()
    df = bm.compute_corrected_time(df)
    df = bm.compute_rolling_features(df)
    df = bm.encode_features(df)
    df = bm.compute_trainer_course(df)
    df = bm.compute_jockey_course(df)
    df = bm.compute_jockey_dist(df)
    df = bm.compute_race_ranks(df)

    print('Computing Ogura Index (rolling 10 races)...')
    df = compute_ogura(df)

    print('Computing BattleScore...')
    df = compute_battle_score(df)

    print('Normalizing bonus features...')
    df = normalize_features(df)

    df = df.dropna(subset=['ninki'])
    race_cnt = df.groupby('race_key').size()
    df = df[df['race_key'].isin(race_cnt[race_cnt >= 7].index)]

    yi = df['year'].astype(int)
    val = df[yi == VAL_YEAR].copy()
    test = df[yi >= TEST_FROM].copy()
    print(f'Val {len(val):,} ({val["race_key"].nunique():,}R) / '
          f'Test {len(test):,} ({test["race_key"].nunique():,}R)')
    return val, test


def compute_ogura(df):
    """Ogura Index = avg of last 10 races: max(0, 100-(rank-1)*5) * grade_mult * recency_mult"""
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
    grade_map = pd.read_sql("SELECT race_key, grade FROM races", con)
    con.close()
    gm = dict(zip(grade_map['race_key'], grade_map['grade']))

    df = df.sort_values(['ketto_num', 'day', 'race_num']).reset_index(drop=True)
    n = len(df)
    ogura = np.full(n, np.nan)
    kettos = df['ketto_num'].values
    chakunums = df['chakujun'].values
    rkeys = df['race_key'].values
    days = df['day'].values

    prev_k = None
    hist = []
    for i in range(n):
        k = kettos[i]
        if k != prev_k:
            hist = []
            prev_k = k

        if hist:
            pts = []
            for h_chaku, h_grade, h_day in hist[-10:]:
                base = max(0, 100 - (h_chaku - 1) * 5)
                g_mult = 2.0 if h_grade == 'A' else (1.5 if h_grade == 'B' else
                         (1.2 if h_grade == 'C' else 1.0))
                age_days = days[i] - h_day
                r_mult = 1.2 if age_days <= 180 * 100 else 1.0
                pts.append(base * g_mult * r_mult)
            if pts:
                ogura[i] = np.mean(pts)

        rk = rkeys[i]
        grade = gm.get(rk, 'E')
        hist.append((chakunums[i], grade, days[i]))

    df['ogura'] = ogura
    valid = np.isfinite(ogura).sum()
    print(f'  Ogura valid: {valid:,}/{n:,}')
    return df


def compute_battle_score(df):
    """BattleScore = Ogura * 0.7 + AgariBonus + PosBonus (same as app)"""
    ogura = pd.to_numeric(df['ogura'], errors='coerce').fillna(50)
    sm = pd.to_numeric(df['spurt_mean3'], errors='coerce')
    sr = df.groupby('race_key')['spurt_mean3'].rank(method='min', na_option='bottom')
    agari_bonus = np.where(sr == 1, 20, np.where(sr == 2, 15, np.where(sr == 3, 10, 0)))

    c4 = pd.to_numeric(df.get('avg_chaku5', pd.Series(dtype=float)), errors='coerce').fillna(9)
    pos_bonus = np.where(c4 <= 3, 10, np.where(c4 <= 5, 5, 0))

    df['battle_score'] = (ogura * 0.7 + agari_bonus + pos_bonus).round(1)
    return df


def normalize_features(df):
    feat_map = {
        'SpeedIndex': ('ogura', True),
        'Popularity': ('ninki', False),
        'AvgAgari':   ('spurt_mean3', False),
        'Jockey':     ('jockey_jyo_win', True),
        'Suitability':('prior_top3_rate', True),
        'Umaban':     ('umaban', False),
    }
    for wk, (col, hib) in feat_map.items():
        raw = pd.to_numeric(df[col], errors='coerce')
        df[f'_n_{wk}'] = _norm_in_race(raw, df['race_key'], hib)

    surface = df['surface'].astype(str)
    bataiju = pd.to_numeric(df['bataiju'], errors='coerce').fillna(460)
    zogen = pd.to_numeric(df['zogen'], errors='coerce').fillna(0)
    c4 = pd.to_numeric(df.get('avg_chaku5', pd.Series(dtype=float)), errors='coerce').fillna(9)
    m = np.ones(len(df))
    m -= np.where((bataiju > 0) & (bataiju < 440) & (zogen <= -6), 0.04, 0)
    m -= np.where(surface.str.contains('芝', na=False) & (c4 >= 7), 0.03, 0)
    m -= np.where(zogen >= 8, 0.02, 0)
    df['_stress_mult'] = np.clip(m, 0.85, 1.0)
    return df


def _norm_in_race(series, race_keys, higher_is_better):
    result = pd.Series(50.0, index=series.index, dtype=float)
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


def score(df, w):
    s = df['battle_score'].values * w.get('Base', 1.0)
    for wk in WEIGHT_KEYS:
        if wk == 'Stress':
            continue
        wv = w.get(wk, 0.0)
        if wv != 0:
            s = s + df[f'_n_{wk}'].values * wv
    sw = w.get('Stress', 0.0)
    if sw > 0:
        m = df['_stress_mult'].values
        s = s - s * (1.0 - m) * sw
    return s


def recall7(df, w):
    df = df.copy()
    df['_s'] = score(df, w)
    win_hit = 0
    t3_sum = []
    total = 0
    for rk, grp in df.groupby('race_key'):
        winner = set(grp.loc[grp['chakujun'] == 1, 'umaban'].values)
        top3 = set(grp.loc[grp['chakujun'] <= 3, 'umaban'].values)
        if not winner:
            continue
        top7 = set(grp.nlargest(7, '_s')['umaban'].values)
        win_hit += int(bool(winner & top7))
        if top3:
            t3_sum.append(len(top3 & top7) / len(top3))
        total += 1
    wr = win_hit / total if total else 0
    t3r = float(np.mean(t3_sum)) if t3_sum else 0
    return wr, t3r, total


def optimize(val_df, test_df, n_rounds=3):
    best_w = {wk: 0.0 for wk in WEIGHT_KEYS}
    best_w['Base'] = 1.0

    wr0_v, t3_v, _ = recall7(val_df, best_w)
    wr0_t, t3_t, nt = recall7(test_df, best_w)
    print(f'\nベースライン (BattleScore only):')
    print(f'  val  win@7={wr0_v:.4f}  top3@7={t3_v:.4f}')
    print(f'  test win@7={wr0_t:.4f}  top3@7={t3_t:.4f}  (races={nt})')

    for rd in range(n_rounds):
        print(f'\n--- ラウンド {rd+1}/{n_rounds} ---')
        for wk in WEIGHT_KEYS:
            grid = GRID[wk]
            best_val = best_w[wk]
            best_wr = recall7(val_df, best_w)[0]
            best_t3 = recall7(val_df, best_w)[1]
            for v in grid:
                trial = dict(best_w)
                trial[wk] = v
                wr, t3, _ = recall7(val_df, trial)
                if wr > best_wr or (wr == best_wr and t3 > best_t3):
                    best_wr = wr
                    best_t3 = t3
                    best_val = v
            if best_val != best_w[wk]:
                print(f'  {wk:15s}: {best_w[wk]:.1f} → {best_val:.1f}  '
                      f'(val win@7={best_wr:.4f} top3@7={best_t3:.4f})')
                best_w[wk] = best_val
            else:
                print(f'  {wk:15s}: {best_w[wk]:.1f} (変更なし)')

    wr_v, t3_v, _ = recall7(val_df, best_w)
    wr_t, t3_t, nt = recall7(test_df, best_w)
    print(f'\n{"="*60}')
    print(f'最適化結果:')
    print(f'  val  win@7={wr_v:.4f}  top3@7={t3_v:.4f}')
    print(f'  test win@7={wr_t:.4f}  top3@7={t3_t:.4f}  (races={nt})')
    print(f'  改善: val {(wr_v-wr0_v)*100:+.2f}pp / test {(wr_t-wr0_t)*100:+.2f}pp')
    return best_w


def safety_net_analysis(df, w):
    df = df.copy()
    df['_s'] = score(df, w)
    leaked = 0
    leaked_won = 0
    total = 0
    for rk, grp in df.groupby('race_key'):
        bs_top3 = set(grp.nlargest(3, 'battle_score')['umaban'].values)
        pr_top7 = set(grp.nlargest(7, '_s')['umaban'].values)
        winners = set(grp.loc[grp['chakujun'] == 1, 'umaban'].values)
        for u in bs_top3:
            if u not in pr_top7:
                leaked += 1
                if u in winners:
                    leaked_won += 1
        total += 1
    print(f'\n🛡️ セーフティネット分析:')
    print(f'  戦闘力top3 → 予測top7漏れ: {leaked}件 / {total}レース')
    print(f'  うち漏れ馬が勝利: {leaked_won}件')


def show_examples(df, w, n=10):
    df = df.copy()
    df['_s'] = score(df, w)
    race_keys = df['race_key'].unique()
    np.random.seed(42)
    sample = np.random.choice(race_keys, min(n, len(race_keys)), replace=False)
    hit = 0
    print(f'\n個別レース検証 ({n}レース):')
    for rk in sample:
        grp = df[df['race_key'] == rk].sort_values('_s', ascending=False)
        w_rows = grp[grp['chakujun'] == 1]
        if w_rows.empty:
            continue
        winner = w_rows.iloc[0]
        w_uma = int(winner['umaban'])
        w_rank = int((grp['umaban'] == w_uma).values.argmax()) + 1
        top7 = set(grp.head(7)['umaban'].values)
        ok = w_uma in top7
        hit += ok
        w_ninki = int(winner['ninki'])
        print(f'  {rk}: 勝馬=馬番{w_uma}(人気{w_ninki})→予測{w_rank}位 {"✓" if ok else "✗"}')
    print(f'  recall: {hit}/{len(sample)}')


def main():
    val_df, test_df = prepare()
    best_w = optimize(val_df, test_df, n_rounds=3)

    out_w = {
        "NIndex": 0.0, "UIndex": 0.0, "LaboIndex": 0.0,
        "SpeedIndex": round(best_w.get('SpeedIndex', 0.0), 1),
        "Popularity": round(best_w.get('Popularity', 0.0), 1),
        "Strength (X)": 0.0,
        "Jockey": round(best_w.get('Jockey', 0.0), 1),
        "Training": 0.0, "Weight": 0.0, "WeightPenalty": 0.0,
        "WeightCarried": 0.0,
        "Suitability": round(best_w.get('Suitability', 0.0), 1),
        "AvgAgari": round(best_w.get('AvgAgari', 0.0), 1),
        "Umaban": round(best_w.get('Umaban', 0.0), 1),
        "Waku": 0.0, "AvgPosition": 0.0, "Bloodline": 0.0,
        "Base": 1.0,
        "Stress": round(best_w.get('Stress', 0.0), 1),
        "ScoringSignal": 0.0, "TopBattleBonus": 0.0,
    }
    print(f'\n推奨 .score_weights_main.json:')
    print(json.dumps(out_w, indent=2, ensure_ascii=False))

    safety_net_analysis(test_df, best_w)
    show_examples(test_df, best_w, n=12)

    p = os.path.join(ROOT, 'data', 'optimized_weights_v2.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(out_w, f, indent=2, ensure_ascii=False)
    print(f'\n保存: {p}')


if __name__ == '__main__':
    main()
