# -*- coding: utf-8 -*-
"""影響率最適化 — 3連単/3連複メトリクス版

v2はrecall@7(勝ち馬をtop7に入れる)で最適化→Popularity=1.5のみ。
ここでは3着以内馬の順位精度で最適化:
  - top3@5: 実3着以内のうち予測top5に入る割合
  - top2in5: 実3着以内のうち2頭以上が予測top5に入るレース率
  - top3@7: 実3着以内のうち予測top7に入る割合
  - trifecta: 予測top3と実top3が完全一致(順不同=3連複的中)
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
               'Suitability', 'Umaban', 'Stress', 'Bloodline',
               'CorrectedTime', 'TrainerCourse', 'AvgPosition']

GRID = {
    'SpeedIndex':    [0.0, 0.3, 0.6, 1.0],
    'Popularity':    [0.0, 0.3, 0.6, 1.0, 1.5, 2.0],
    'AvgAgari':      [0.0, 0.3, 0.6, 1.0],
    'Jockey':        [0.0, 0.3, 0.6, 1.0],
    'Suitability':   [0.0, 0.3, 0.6, 1.0],
    'Umaban':        [0.0, 0.3, 0.6, 1.0],
    'Stress':        [0.0, 0.5, 1.0, 2.0],
    'Bloodline':     [0.0, 0.3, 0.6, 1.0],
    'CorrectedTime': [0.0, 0.3, 0.6, 1.0],
    'TrainerCourse': [0.0, 0.3, 0.6, 1.0],
    'AvgPosition':   [0.0, 0.3, 0.6, 1.0],
}

BLOOD_DB = os.path.join(ROOT, 'data', 'blood_dict.db')
import re

def _normalize_parent(name):
    if not name: return name
    s = name.strip()
    s = re.sub(r'\s*[\(（][^)）]{1,3}[\)）]\s*$', '', s)
    if re.search(r'[぀-ヿ一-鿿]', s):
        last_jp = -1
        for i, c in enumerate(s):
            if '぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or c in '０１２３４５６７８９':
                last_jp = i
        if last_jp >= 0:
            rest = s[last_jp+1:]
            s = s[:last_jp+1]
            m = re.match(r'^(IV|III|II)', rest)
            if m:
                s += {'IV':'４','III':'３','II':'２'}[m.group(1)]
    return s

def _dist_band(k):
    if k is None or k <= 0: return None
    if k <= 1300: return '短距離'
    if k <= 1899: return 'マイル'
    if k <= 2200: return '中距離'
    return '長距離'


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

    print('Computing Ogura Index...')
    df = compute_ogura(df)
    print('Computing BattleScore...')
    df = compute_battle_score(df)
    print('Loading blood data...')
    df = compute_bloodline(df)
    print('Normalizing features...')
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
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
    grade_map = pd.read_sql("SELECT race_key, grade FROM races", con)
    con.close()
    gm = dict(zip(grade_map['race_key'], grade_map['grade']))
    df = df.sort_values(['ketto_num', 'day', 'race_num']).reset_index(drop=True)
    n = len(df)
    ogura = np.full(n, np.nan)
    kettos, chakunums, rkeys, days = df['ketto_num'].values, df['chakujun'].values, df['race_key'].values, df['day'].values
    prev_k, hist = None, []
    for i in range(n):
        k = kettos[i]
        if k != prev_k: hist, prev_k = [], k
        if hist:
            pts = []
            for h_chaku, h_grade, h_day in hist[-10:]:
                base = max(0, 100 - (h_chaku - 1) * 5)
                g_mult = 2.0 if h_grade == 'A' else (1.5 if h_grade == 'B' else (1.2 if h_grade == 'C' else 1.0))
                r_mult = 1.2 if (days[i] - h_day) <= 180 * 100 else 1.0
                pts.append(base * g_mult * r_mult)
            if pts: ogura[i] = np.mean(pts)
        hist.append((chakunums[i], gm.get(rkeys[i], 'E'), days[i]))
    df['ogura'] = ogura
    print(f'  Ogura valid: {np.isfinite(ogura).sum():,}/{n:,}')
    return df


def compute_battle_score(df):
    ogura = pd.to_numeric(df['ogura'], errors='coerce').fillna(50)
    sr = df.groupby('race_key')['spurt_mean3'].rank(method='min', na_option='bottom')
    agari_bonus = np.where(sr == 1, 20, np.where(sr == 2, 15, np.where(sr == 3, 10, 0)))
    c4 = pd.to_numeric(df.get('avg_chaku5', pd.Series(dtype=float)), errors='coerce').fillna(9)
    pos_bonus = np.where(c4 <= 3, 10, np.where(c4 <= 5, 5, 0))
    df['battle_score'] = (ogura * 0.7 + agari_bonus + pos_bonus).round(1)
    return df


def compute_bloodline(df):
    if not os.path.exists(BLOOD_DB):
        df['bloodline_score'] = np.nan
        return df
    bcon = sqlite3.connect(f'file:{BLOOD_DB}?mode=ro', uri=True)
    sire_d, bms_d = {}, {}
    for row in bcon.execute('SELECT parent, surface, dist_band, place_rate FROM sire_stats'):
        sire_d[(row[0], row[1], row[2])] = row[3]
    for row in bcon.execute('SELECT parent, surface, dist_band, place_rate FROM bms_stats'):
        bms_d[(row[0], row[1], row[2])] = row[3]
    bcon.close()
    jcon = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
    hb = {}
    for row in jcon.execute("SELECT ketto_num, sire, bms FROM horses WHERE sire != ''"):
        hb[row[0]] = (_normalize_parent(row[1]), _normalize_parent(row[2]))
    rc = {}
    for row in jcon.execute("SELECT race_key, surface, kyori FROM races"):
        rc[row[0]] = (row[1], row[2])
    jcon.close()

    n = len(df)
    bl = np.full(n, np.nan)
    for i in range(n):
        kt, rk = df.iloc[i]['ketto_num'], df.iloc[i]['race_key']
        if kt not in hb or rk not in rc: continue
        sire, bms = hb[kt]
        surface, kyori = rc[rk]
        band = _dist_band(kyori)
        surf = 'ダート' if 'ダ' in str(surface) else ('芝' if '芝' in str(surface) else None)
        if not band or not surf: continue
        vals = [v for v in [sire_d.get((sire, surf, band)), bms_d.get((bms, surf, band))] if v is not None]
        if vals: bl[i] = np.mean(vals)
    df['bloodline_score'] = bl
    return df


def normalize_features(df):
    feat_map = {
        'SpeedIndex':    ('ogura', True),
        'Popularity':    ('ninki', False),
        'AvgAgari':      ('spurt_mean3', False),
        'Jockey':        ('jockey_jyo_win', True),
        'Suitability':   ('prior_top3_rate', True),
        'Umaban':        ('umaban', False),
        'Bloodline':     ('bloodline_score', True),
        'CorrectedTime': ('h7_fig', True),
        'TrainerCourse': ('trainer_jyo_t3', True),
        'AvgPosition':   ('avg_chaku5', False),
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
        if pd.isna(vmin) or pd.isna(vmax) or vmax <= vmin: continue
        if higher_is_better:
            result.loc[idx] = (vals - vmin) / (vmax - vmin) * 100
        else:
            result.loc[idx] = (vmax - vals) / (vmax - vmin) * 100
    return result.fillna(50.0)


def score(df, w):
    s = df['battle_score'].values * w.get('Base', 1.0)
    for wk in WEIGHT_KEYS:
        if wk == 'Stress': continue
        wv = w.get(wk, 0.0)
        if wv != 0:
            s = s + df[f'_n_{wk}'].values * wv
    sw = w.get('Stress', 0.0)
    if sw > 0:
        m = df['_stress_mult'].values
        s = s - s * (1.0 - m) * sw
    return s


def eval_metrics(df, w):
    """3着以内馬のランキング精度を多角的に評価"""
    df = df.copy()
    df['_s'] = score(df, w)
    win7, t3in5, t2in5_cnt, t3in7, trio_hit = 0, [], 0, [], 0
    total = 0
    for rk, grp in df.groupby('race_key'):
        actual_top3 = set(grp.loc[grp['chakujun'] <= 3, 'umaban'].values)
        winner = set(grp.loc[grp['chakujun'] == 1, 'umaban'].values)
        if not winner or len(actual_top3) < 3:
            continue
        sorted_g = grp.sort_values('_s', ascending=False)
        pred_top3 = set(sorted_g.head(3)['umaban'].values)
        pred_top5 = set(sorted_g.head(5)['umaban'].values)
        pred_top7 = set(sorted_g.head(7)['umaban'].values)

        win7 += int(bool(winner & pred_top7))
        t3_in_5 = len(actual_top3 & pred_top5)
        t3in5.append(t3_in_5 / 3)
        t2in5_cnt += int(t3_in_5 >= 2)
        t3in7.append(len(actual_top3 & pred_top7) / 3)
        trio_hit += int(actual_top3 == pred_top3)
        total += 1

    return {
        'win@7': win7 / total if total else 0,
        'top3@5': np.mean(t3in5) if t3in5 else 0,
        'top2in5': t2in5_cnt / total if total else 0,
        'top3@7': np.mean(t3in7) if t3in7 else 0,
        'trio': trio_hit / total if total else 0,
        'n': total,
    }


def main():
    val_df, test_df = prepare()

    baseline_w = {'Base': 1.0, 'Popularity': 1.5}
    bv = eval_metrics(val_df, baseline_w)
    bt = eval_metrics(test_df, baseline_w)
    print(f'\n{"="*70}')
    print(f'ベースライン (Pop=1.5):')
    print(f'  val  win@7={bv["win@7"]:.4f}  top3@5={bv["top3@5"]:.4f}  top2in5={bv["top2in5"]:.4f}  top3@7={bv["top3@7"]:.4f}  3連複={bv["trio"]:.4f}')
    print(f'  test win@7={bt["win@7"]:.4f}  top3@5={bt["top3@5"]:.4f}  top2in5={bt["top2in5"]:.4f}  top3@7={bt["top3@7"]:.4f}  3連複={bt["trio"]:.4f}')

    # 各特徴量のadd-oneテスト
    print(f'\n{"="*70}')
    print(f'各特徴量 add-one テスト (Pop=1.5 ベース + 1項目追加)')
    print(f'{"feature":20s} {"best_w":>6s}  {"Δwin@7":>8s}  {"Δtop3@5":>8s}  {"Δtop2in5":>9s}  {"Δtop3@7":>8s}  {"Δ3連複":>8s}  {"判定":>4s}')
    print('-' * 100)

    improved = []
    for wk in WEIGHT_KEYS:
        if wk == 'Popularity':
            continue
        best_v, best_score = 0.0, 0.0
        for v in GRID[wk]:
            trial = dict(baseline_w)
            trial[wk] = v
            m = eval_metrics(val_df, trial)
            combined = m['top3@5'] + m['top2in5'] * 0.5
            if combined > best_score:
                best_score = combined
                best_v = v

        trial_w = dict(baseline_w)
        trial_w[wk] = best_v
        mv = eval_metrics(val_df, trial_w)
        mt = eval_metrics(test_df, trial_w)

        dw7 = (mt['win@7'] - bt['win@7']) * 100
        dt5 = (mt['top3@5'] - bt['top3@5']) * 100
        dt2 = (mt['top2in5'] - bt['top2in5']) * 100
        dt7 = (mt['top3@7'] - bt['top3@7']) * 100
        dtrio = (mt['trio'] - bt['trio']) * 100

        ok_val = mv['top3@5'] >= bv['top3@5'] and mv['top2in5'] >= bv['top2in5']
        ok_test = mt['top3@5'] >= bt['top3@5'] and mt['top2in5'] >= bt['top2in5']
        tag = '★' if ok_val and ok_test and best_v > 0 else ''
        if tag:
            improved.append((wk, best_v, mt))

        print(f'  {wk:18s} {best_v:5.1f}  {dw7:+7.2f}pp  {dt5:+7.2f}pp  {dt2:+8.2f}pp  {dt7:+7.2f}pp  {dtrio:+7.2f}pp  {tag}')

    # 改善候補をまとめて適用
    if improved:
        combo_w = dict(baseline_w)
        print(f'\n★改善候補まとめ:')
        for wk, v, _ in improved:
            combo_w[wk] = v
            print(f'  {wk}={v}')
        mc = eval_metrics(test_df, combo_w)
        print(f'  test win@7={mc["win@7"]:.4f}  top3@5={mc["top3@5"]:.4f}  top2in5={mc["top2in5"]:.4f}  top3@7={mc["top3@7"]:.4f}  3連複={mc["trio"]:.4f}')
        dt5c = (mc['top3@5'] - bt['top3@5']) * 100
        dt2c = (mc['top2in5'] - bt['top2in5']) * 100
        print(f'  Δtop3@5={dt5c:+.2f}pp  Δtop2in5={dt2c:+.2f}pp')
        if mc['top3@5'] < bt['top3@5'] or mc['top2in5'] < bt['top2in5']:
            print(f'  ⚠ まとめ適用でtest悪化 → 個別では改善でも組合せで相殺')
    else:
        print(f'\n改善候補なし: Pop=1.5 only が3連単/3連複メトリクスでも最適')

    # Popularity微調整
    print(f'\n--- Popularity微調整 (3連複メトリクス) ---')
    for pv in [0.0, 0.3, 0.6, 1.0, 1.5, 2.0, 2.5, 3.0]:
        trial = {'Base': 1.0, 'Popularity': pv}
        mt = eval_metrics(test_df, trial)
        mark = '←' if pv == 1.5 else ''
        print(f'  Pop={pv:.1f}  win@7={mt["win@7"]:.4f}  top3@5={mt["top3@5"]:.4f}  top2in5={mt["top2in5"]:.4f}  3連複={mt["trio"]:.4f} {mark}')


if __name__ == '__main__':
    main()
