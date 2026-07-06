# -*- coding: utf-8 -*-
"""妙味馬ハンター再現率v2 — scripts/value_hunter_recall_v2.py

Fable案件①(repo/fable_brief_value_hunter_recall.md): 7番人気以下の3着内馬の再現率を
combo≥2(49-54%)から70%へ、精度≥基準1.35倍(目安10%+)を保ったまま引き上げる。

方式: 現行combo(6シグナル二値top3の同時発火数)を『連続量特徴のLightGBM確率モデル』へ置換。
  仮説1(二値top3→連続量)・仮説2(位置取り)・仮説5(recall@k最適化のモデル化)・仮説6(交互作用
  =GBDTが学習)を1本で検証する。全特徴はレース前確定情報+shift(1)厳守の過去履歴のみ(リーク無)。

検証窓: fit≤2023 / しきい値選択=2024(val) / holdout=2025 / 直近3ヶ月(2026-03-21〜06-21)。
combo≥2基準点は value_longshot_research.py と同一コードパス(coreモジュール)で再現して重ねる。

Usage:
  python scripts/value_hunter_recall_v2.py            # フル(combo再現込み・初回は数十分)
  python scripts/value_hunter_recall_v2.py --quick    # 軽量動作確認(combo/plotなし)
  python scripts/value_hunter_recall_v2.py --skip-combo
Output:
  data/value_hunter_recall_v2.json      … カーブ+採否+残差z(機械可読)
  repo/value_hunter_recall_v2_curve.png … recall/precisionカーブ(combo点重ね)
  data/vh2_combo_cache.json             … combo再現のキャッシュ(再実行高速化)
"""
import os
import sys
import json
import sqlite3
import argparse
import time as _time
from collections import defaultdict

import numpy as np
import pandas as pd
import lightgbm as lgb

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.build_ltr_model as bm  # 既存leak-freeパイプラインを再利用(変更しない)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
OUT_JSON = os.path.join(ROOT, 'data', 'value_hunter_recall_v2.json')
OUT_MODEL = os.path.join(ROOT, 'data', 'vh2_model.lgb')
OUT_PNG = os.path.join(ROOT, 'repo', 'value_hunter_recall_v2_curve.png')
COMBO_CACHE = os.path.join(ROOT, 'data', 'vh2_combo_cache.json')

POP_MIN = 7
RECENT_FROM = 20260321
FIT_END = 2023        # モデル学習
VAL_YEAR = 2024       # early stop + しきい値選択(ここまでが"train≤2024")
HOLDOUT_YEAR = 2025

PARAMS = {
    'objective': 'binary', 'metric': ['average_precision'],
    'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 100,
    'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
    'verbose': -1, 'seed': 42, 'bagging_seed': 42, 'feature_fraction_seed': 42,
}

FEATS = [
    # 市場・レース属性(事前確定)
    'ninki', 'log_odds', 'umaban', 'waku_n', 'futan', 'bataiju', 'zogen',
    'sex_code', 'age', 'field_size', 'is_handicap', 'surface_code', 'kyori_int',
    'baba_code', 'jyo_code', 'race_num_code', 'cushion', 'dirt_moisture',
    # 補正T(連続量化: 仮説1)
    'h7_fig', 'h7_pct',
    # 末脚(連続量化: 仮説1・検証済み末脚指数と同定義)
    'spurt_idx', 'spurt_race_pct', 'spurt_mean3',
    # 近走成績
    'prior_top3_rate', 'avg_chaku5', 'prior_margin', 'margin_best3',
    'days_since', 'dist_change',
    # 位置取り(仮説2: 過去平均のみ=リーク無)
    'pos_ratio3', 'avg_pos3',
    # 33ラップ(連続量化)
    'h_lap33', 'course_l33', 'lap_align', 'lap_fit_bin',
    # 血統(連続量化: レース単位rolling=同一レース内リーク無)
    'sire_surf_t3', 'sire_dist_t3', 'bms_surf_t3', 'blood_race_pct',
    # 騎手・厩舎フォーム
    'jockey_form_t3', 'jk_race_pct', 'jockey_jyo_win', 'jockey_dist_win',
    'trainer_jyo_t3', 'trainer_form_t3',
]


# ──────────────────────────── データ構築 ────────────────────────────

def load_data(base_year=1990):
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=30)
    print('Loading race results...', file=sys.stderr)
    df = pd.read_sql(f"""
        SELECT r.race_key, r.ketto_num, r.umaban, r.waku, r.chakujun, r.ninki, r.win_odds,
               r.bataiju, r.zogen, r.ato3f AS horse_ato3f, r.sex, r.age, r.futan, r.time,
               r.trainer_code, r.jockey_code,
               r.corner1, r.corner2, r.corner3, r.corner4,
               ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori, ra.shusso_tosu,
               ra.juryo, ra.baba_shiba, ra.baba_dirt, ra.race_num,
               ra.mae3f AS race_mae3f, ra.ato3f AS race_ato3f,
               tc.cushion, tc.dirt_moisture
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        LEFT JOIN track_cond tc ON ra.year = tc.year AND ra.monthday = tc.monthday AND ra.jyo = tc.jyo
        WHERE ra.surface IN ('芝','ダート') AND ra.jyo <= '10'
          AND CAST(ra.year AS INTEGER) >= {base_year}
          AND r.chakujun > 0 AND r.chakujun <= 28
    """, con)
    hs = pd.read_sql("SELECT ketto_num, sire, bms FROM horses", con)
    con.close()
    df = df.merge(hs, on='ketto_num', how='left')
    print(f'  loaded {len(df):,} rows', file=sys.stderr)
    return df


def _race_rate(df, keycol, window, minp, out):
    """keycol(系統/厩舎など同一レースに複数出る主体)の『レース単位』複勝率rolling。
    レース単位に集約→shift(1)で当該レースを完全除外=同一レース内リークも無し。"""
    sub = df.dropna(subset=[keycol])
    g = sub.groupby([keycol, 'race_key'], as_index=False).agg(
        _m=('_t3', 'mean'), _d=('day', 'first'), _rn=('race_num', 'first'))
    g = g.sort_values([keycol, '_d', '_rn'])
    g[out] = g.groupby(keycol, sort=False)['_m'].transform(
        lambda x: x.shift(1).rolling(window, min_periods=minp).mean())
    return df.merge(g[[keycol, 'race_key', out]], on=[keycol, 'race_key'], how='left')


def add_v2_features(df):
    """v2追加特徴(全てshift(1)厳守=各レース時点以前の履歴のみ)。dfはketto_num,day,race_num順。"""
    print('Computing v2 features...', file=sys.stderr)
    df['_fs'] = pd.to_numeric(df['shusso_tosu'], errors='coerce')
    df['_t3'] = (df['chakujun'] <= 3).astype(float)

    # 末脚指数(検証済み定義: レース内上がり3F順位pctの過去5走平均・良いほど高い)
    ag = pd.to_numeric(df['horse_ato3f'], errors='coerce')
    df['_ag'] = ag.where(ag > 0)
    df['_ag_pct'] = df.groupby('race_key')['_ag'].rank(pct=True)
    df['_sp1'] = 1.0 - df['_ag_pct']
    df['spurt_idx'] = df.groupby('ketto_num')['_sp1'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=2).mean())

    # 位置取り(過去平均のみ=リーク無)
    cs = pd.concat([pd.to_numeric(df[c], errors='coerce').where(
        lambda s: s > 0) for c in ('corner1', 'corner2', 'corner3', 'corner4')], axis=1)
    df['_pos'] = cs.mean(axis=1)
    df['_pos_r'] = df['_pos'] / df['_fs']
    df['avg_pos3'] = df.groupby('ketto_num')['_pos'].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).mean())
    df['pos_ratio3'] = df.groupby('ketto_num')['_pos_r'].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).mean())

    # 前走着差(勝ち馬との秒差)・直近3走ベスト
    df['_wsec'] = df['sec'].where(df['chakujun'] == 1)
    df['_wsec'] = df.groupby('race_key')['_wsec'].transform('max')
    df['_marg'] = df['sec'] - df['_wsec']
    df['prior_margin'] = df.groupby('ketto_num')['_marg'].shift(1)
    df['margin_best3'] = df.groupby('ketto_num')['_marg'].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).min())

    # 間隔・距離替わり
    dt = pd.to_datetime(df['day'].astype(str), format='%Y%m%d', errors='coerce')
    df['_dord'] = (dt - pd.Timestamp('1985-01-01')).dt.days
    df['days_since'] = df['_dord'] - df.groupby('ketto_num')['_dord'].shift(1)
    df['dist_change'] = df['kyori_int'] - df.groupby('ketto_num')['kyori_int'].shift(1)

    # 33ラップ(core/lap33.pyのベクトル化再現)
    mae = pd.to_numeric(df['race_mae3f'], errors='coerce') / 10.0
    rato = pd.to_numeric(df['race_ato3f'], errors='coerce') / 10.0
    mae = mae.where(mae > 0)
    rato = rato.where(rato > 0)
    ky = df['kyori_int'].astype(float)
    mid_time = df['_wsec'] - mae - rato
    with np.errstate(invalid='ignore', divide='ignore'):
        mid = np.where(ky <= 1200, mae,
                       np.where((ky > 1200) & (mid_time > 0),
                                mid_time * 600.0 / (ky - 1200), np.nan))
    df['_mid3f'] = mid
    hato = pd.to_numeric(df['horse_ato3f'], errors='coerce') / 10.0
    df['_hlap'] = df['_mid3f'] - hato.where(hato > 0)
    df['h_lap33'] = df.groupby('ketto_num')['_hlap'].transform(
        lambda x: x.shift(1).rolling(10, min_periods=3).mean())
    # コース平均33ラップはfit期間(≤2023)のみで固定=将来情報を使わない
    df['_rlap'] = df['_mid3f'] - rato
    rl = df.groupby('race_key').agg(_rl=('_rlap', 'first'), _j=('jyo', 'first'),
                                    _s=('surface', 'first'), _k=('kyori_int', 'first'),
                                    _y=('year', 'first')).reset_index()
    base = rl[(rl['_y'].astype(int) >= 2016) & (rl['_y'].astype(int) <= FIT_END)]
    crs = base.groupby(['_j', '_s', '_k'])['_rl'].agg(['mean', 'count']).reset_index()
    crs = crs[crs['count'] >= 30].rename(columns={'mean': 'course_l33'})
    df = df.merge(crs[['_j', '_s', '_k', 'course_l33']],
                  left_on=['jyo', 'surface', 'kyori_int'],
                  right_on=['_j', '_s', '_k'], how='left').drop(columns=['_j', '_s', '_k'])
    nat = base.groupby(['_s', '_k'])['_rl'].agg(['mean', 'count']).reset_index()
    nat = nat[nat['count'] >= 30].rename(columns={'mean': '_nat33'})
    df = df.merge(nat[['_s', '_k', '_nat33']], left_on=['surface', 'kyori_int'],
                  right_on=['_s', '_k'], how='left').drop(columns=['_s', '_k'])
    df['course_l33'] = df['course_l33'].fillna(df['_nat33'])
    df['lap_align'] = df['h_lap33'] * np.sign(df['course_l33'])
    ok = df['h_lap33'].notna() & df['course_l33'].notna()
    df['lap_fit_bin'] = np.where(ok, ((df['h_lap33'] > 0) == (df['course_l33'] > 0))
                                 .astype(float), np.nan)

    # 血統(種牡馬×馬場・×距離帯・母父×馬場: レース単位rolling=リーク無)
    kyb = np.where(ky <= 1400, 'S', np.where(ky <= 1800, 'M', np.where(ky <= 2200, 'L', 'X')))
    sire_ok = df['sire'].notna() & (df['sire'].astype(str) != '')
    bms_ok = df['bms'].notna() & (df['bms'].astype(str) != '')
    df['_ks'] = np.where(sire_ok, df['sire'].astype(str) + '|' + df['surface'].astype(str), None)
    df['_kd'] = np.where(sire_ok, df['sire'].astype(str) + '|' + df['surface'].astype(str)
                         + '|' + kyb, None)
    df['_kb'] = np.where(bms_ok, df['bms'].astype(str) + '|' + df['surface'].astype(str), None)
    df = _race_rate(df, '_ks', 150, 30, 'sire_surf_t3')
    df = _race_rate(df, '_kd', 120, 25, 'sire_dist_t3')
    df = _race_rate(df, '_kb', 200, 40, 'bms_surf_t3')

    # 騎手直近フォーム(1レース1騎乗なので単純shift(1)でリーク無)・厩舎はレース単位
    tmp = df[['jockey_code', 'day', 'race_num', '_t3']].sort_values(
        ['jockey_code', 'day', 'race_num'])
    df['jockey_form_t3'] = (tmp.groupby('jockey_code', sort=False)['_t3']
                            .transform(lambda x: x.shift(1).rolling(50, min_periods=10).mean())
                            .reindex(df.index))
    df['_kt'] = df['trainer_code'].astype(str)
    df = _race_rate(df, '_kt', 30, 8, 'trainer_form_t3')

    df['waku_n'] = pd.to_numeric(df['waku'], errors='coerce')
    df.drop(columns=['_fs', '_ag', '_ag_pct', '_sp1', '_pos', '_pos_r', '_wsec', '_marg',
                     '_dord', '_mid3f', '_hlap', '_rlap', '_nat33', '_ks', '_kd', '_kb',
                     '_kt', '_t3'], inplace=True)
    return df


def add_race_pcts(df):
    """全出走馬でのレース内相対順位(母集団フィルタ前に計算すること)。"""
    fs = df['field_size'].replace(0, np.nan)
    df['h7_pct'] = df['h7_rank'] / fs
    for src, rank_col, pct_col in (
            ('spurt_idx', 'spurt_rank_f', 'spurt_race_pct'),
            ('sire_surf_t3', 'blood_rank_f', 'blood_race_pct'),
            ('jockey_form_t3', 'jk_rank_f', 'jk_race_pct')):
        df[rank_col] = df.groupby('race_key')[src].rank(
            method='min', ascending=False, na_option='bottom')
        df[pct_col] = df[rank_col] / fs
    return df


# ──────────────────────────── combo基準の再現(元研究と同一コードパス) ────────────────────────────

def build_combo_map():
    """value_longshot_research.pyと同一ロジックで、2024+の7番人気以下に combo(0-6) を付与。
    coreモジュール(補正T/血統/末脚/33/騎手)の実装をそのまま使う=公表基準点の正確な再現。"""
    if os.path.exists(COMBO_CACHE):
        with open(COMBO_CACHE, encoding='utf-8') as f:
            m = json.load(f)
        print(f'combo cache loaded: {len(m):,} entries', file=sys.stderr)
        return m
    from core import jockey_jv as jj
    from core import corrected_time as ct
    from core import bloodline as bl
    from core import lap33 as l3
    print('combo再現(元研究と同一コードパス・初回は時間がかかる)...', file=sys.stderr)
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.ato3f h_ato3f, r.jockey_name jockey_name, "
        "ra.kyori kyori, ra.surface surface "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(r.year AS INT)>=2023 "
        "ORDER BY r.race_key").fetchall()
    hrows = con.execute("SELECT ketto_num, sire, bms FROM horses").fetchall()
    con.close()
    horse_sire = {k: (s, b) for k, s, b in hrows}

    jp_by_jockey = {}
    for _jn in {r['jockey_name'] for r in rows if r['jockey_name']}:
        try:
            jp_by_jockey[_jn] = jj.jockey_power(_jn).get('jpower')
        except Exception:
            jp_by_jockey[_jn] = None
    _ct_cache = {}

    def ct_fig(kt, surf):
        key = (kt, surf)
        if key not in _ct_cache:
            fig = ct.get_figure(kt, surf) or ct.get_figure(kt, None)
            _ct_cache[key] = fig.get('fig') if fig and fig.get('fig') is not None else None
        return _ct_cache[key]

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)
    hist_ag = defaultdict(list)
    for rk, rs in by_race.items():
        a3 = [(x['h_ato3f'], x['kt']) for x in rs if x['h_ato3f'] and x['h_ato3f'] > 0]
        a3.sort(key=lambda t: t[0])
        for i, (_, kt) in enumerate(a3):
            hist_ag[kt].append((rk, (i + 1) / len(a3)))
    for k in hist_ag:
        hist_ag[k].sort(key=lambda z: z[0])

    def past_spurt(kt, rk, n=5, minr=2):
        h = hist_ag.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk][-n:]
        return (1.0 - sum(past) / len(past)) if len(past) >= minr else None

    combo_map = {}
    races = sorted(by_race.items())
    for ri, (rk, rs) in enumerate(races):
        if ri % 2000 == 0:
            print(f'  ...{ri}/{len(races)}', file=sys.stderr, flush=True)
        if int(str(rk)[:4]) < 2024:
            continue
        r0 = rs[0]
        surf = '芝' if '芝' in str(r0['surface']) else 'ダ'
        kyori = r0['kyori']
        jyo = str(rk)[8:10] if len(str(rk)) >= 10 else '05'
        try:
            course_v = l3.course_avg33(surf, kyori, jyo=jyo)
        except Exception:
            course_v = None
        ct_vals = {r['kt']: ct_fig(r['kt'], surf) for r in rs}
        ct_vals = {k: v for k, v in ct_vals.items() if v is not None}
        ct_top3 = {k for k, _ in sorted(ct_vals.items(), key=lambda x: x[1])[:3]}
        sp_vals = {r['kt']: past_spurt(r['kt'], rk) for r in rs}
        sp_top3 = {k for k, v in sorted(((k, v) for k, v in sp_vals.items() if v is not None),
                                        key=lambda x: -x[1])[:3]}
        bl_vals = {}
        for r in rs:
            sire, bms = horse_sire.get(r['kt'], (None, None))
            if sire or bms:
                bl_vals[r['kt']] = bl.blood_score(sire, bms, surf, kyori)
        bl_top3 = {k for k, _ in sorted(bl_vals.items(), key=lambda x: -x[1])[:3]}
        jp_vals = {r['kt']: jp_by_jockey.get(r['jockey_name']) for r in rs}
        jp_top3 = {k for k, v in sorted(((k, v) for k, v in jp_vals.items() if v is not None),
                                        key=lambda x: -x[1])[:3]}
        for r in rs:
            if not r['nk'] or int(r['nk']) < POP_MIN:
                continue
            kt = r['kt']
            sire, bms = horse_sire.get(kt, (None, None))
            ss = bl.lookup_sire_stats(sire, surf, kyori) if sire else None
            roi100 = bool(ss and ss.get('win_roi', 0) >= 100)
            lap_fit = False
            if course_v:
                hf = l3.horse_fit33(kt, before_key=rk)
                lap_fit = l3.fit_match(hf.get('avg_lap33'), course_v['avg']) is True
            combo6 = (int(kt in ct_top3) + int(kt in bl_top3) + int(roi100)
                      + int(kt in sp_top3) + int(lap_fit) + int(kt in jp_top3))
            combo_map[f'{rk}|{kt}'] = combo6
    with open(COMBO_CACHE, 'w', encoding='utf-8') as f:
        json.dump(combo_map, f)
    print(f'combo map: {len(combo_map):,} entries → cached', file=sys.stderr)
    return combo_map


# ──────────────────────────── 評価 ────────────────────────────

def pr_curve(y, s):
    order = np.argsort(-s, kind='stable')
    ys = y[order]
    tp = np.cumsum(ys)
    n = np.arange(1, len(ys) + 1)
    pos = ys.sum()
    return tp / max(pos, 1), tp / n, s[order]


def prec_at_recall(rec, prec, target):
    idx = int(np.searchsorted(rec, target))
    idx = min(idx, len(prec) - 1)
    return float(prec[idx]), idx


def resid_z(sub, base_map, gbase):
    """人気別ベース3着内率(fit期間)に対する残差z=市場超えの判定。"""
    if len(sub) == 0:
        return None
    p = sub['ninki_c'].map(base_map).fillna(gbase)
    obs = sub['t3'].sum()
    exp = p.sum()
    var = (p * (1 - p)).sum()
    z = (obs - exp) / np.sqrt(var) if var > 0 else 0.0
    return sub['t3'].mean(), float(z), len(sub)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--skip-combo', action='store_true')
    ap.add_argument('--no-plot', action='store_true')
    args = ap.parse_args()
    t0 = _time.time()

    df = load_data(base_year=2015 if args.quick else 1990)
    df = bm.compute_corrected_time(df)
    df = bm.compute_rolling_features(df)
    df = bm.compute_trainer_course(df)
    df = bm.compute_jockey_course(df)
    df = bm.compute_jockey_dist(df)
    df = add_v2_features(df)
    df = df[df['year'].astype(int) >= (2019 if args.quick else 2016)].copy()
    df = bm.encode_features(df)
    df = bm.compute_race_ranks(df)
    df = add_race_pcts(df)

    # ── 母集団: JRA平地・7番人気以下・完走 ──
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    pop = df[df['ninki'] >= POP_MIN].copy()
    pop['t3'] = (pop['chakujun'] <= 3).astype(int)
    pop['ninki_c'] = pop['ninki'].clip(upper=16)
    del df

    yi = pop['year'].astype(int)
    w_fit = pop[yi <= FIT_END]
    w_val = pop[yi == VAL_YEAR]
    w_hold = pop[yi == HOLDOUT_YEAR]
    w_recent = pop[pop['day'] >= RECENT_FROM]
    print(f'母集団(7番人気以下): fit={len(w_fit):,} val2024={len(w_val):,} '
          f'holdout2025={len(w_hold):,} recent={len(w_recent):,}', file=sys.stderr)
    for nm, w in (('fit', w_fit), ('val', w_val), ('hold', w_hold), ('recent', w_recent)):
        print(f'  {nm}: base3着内率={w["t3"].mean():.3%}', file=sys.stderr)

    # ── 学習 ──
    def _train(feats):
        ds_tr = lgb.Dataset(w_fit[feats].values.astype(np.float64), label=w_fit['t3'].values,
                            feature_name=feats)
        ds_va = lgb.Dataset(w_val[feats].values.astype(np.float64), label=w_val['t3'].values,
                            feature_name=feats, reference=ds_tr)
        rounds = 300 if args.quick else 2000
        return lgb.train(PARAMS, ds_tr, num_boost_round=rounds, valid_sets=[ds_va],
                         callbacks=[lgb.early_stopping(100, verbose=False),
                                    lgb.log_evaluation(0)])

    model = _train(FEATS)
    print(f'best_iteration={model.best_iteration}', file=sys.stderr)
    if not args.quick:
        model.save_model(OUT_MODEL)
        print(f'model → {OUT_MODEL}', file=sys.stderr)
    # アブレーション: 市場情報(ninki/log_odds)抜き=能力特徴だけで何処まで行けるか
    FEATS_ABIL = [f for f in FEATS if f not in ('ninki', 'log_odds')]
    model_abil = _train(FEATS_ABIL)

    windows = {'val2024': w_val, 'holdout2025': w_hold, 'recent3mo': w_recent}
    scores, curves, mkt_curves, abil_curves = {}, {}, {}, {}
    for nm, w in windows.items():
        s = model.predict(w[FEATS].values.astype(np.float64))
        scores[nm] = s
        rec, prec, ssorted = pr_curve(w['t3'].values, s)
        curves[nm] = (rec, prec, ssorted)
        # 市場のみベースライン(オッズ昇順=人気寄りから選ぶ): 特徴量の上乗せ分を分離する対照
        od = pd.to_numeric(w['win_odds'], errors='coerce').values.astype(np.float64)
        s_mkt = np.where(np.isfinite(od) & (od > 0), -od, -1e12)
        mkt_curves[nm] = pr_curve(w['t3'].values, s_mkt)
        abil_curves[nm] = pr_curve(w['t3'].values,
                                   model_abil.predict(w[FEATS_ABIL].values.astype(np.float64)))

    # ── しきい値はval2024で選ぶ(holdoutを触らない) ──
    rec_v, prec_v, s_v = curves['val2024']
    targets = [0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    thresholds = {}
    for t in targets:
        _, idx = prec_at_recall(rec_v, prec_v, t)
        thresholds[t] = float(s_v[idx])

    print('\n' + '=' * 78)
    print('【precision-recallテーブル】 しきい値はval2024で固定→各窓に適用(リーク無し)')
    results_op = {}
    for nm, w in windows.items():
        base = w['t3'].mean()
        s = scores[nm]
        print(f'\n--- {nm}  base={base:.2%}  n={len(w):,}  正例={int(w["t3"].sum()):,} ---')
        print('  目標recall(val) | 実recall | precision | 精度/基準 | 選択頭数(比率)')
        results_op[nm] = []
        for t in targets:
            sel = s >= thresholds[t]
            nsel = int(sel.sum())
            if nsel == 0:
                continue
            hit = int(w['t3'].values[sel].sum())
            rc = hit / max(int(w['t3'].sum()), 1)
            pr = hit / nsel
            results_op[nm].append({'target': t, 'recall': rc, 'precision': pr,
                                   'lift': pr / base, 'n_sel': nsel,
                                   'frac': nsel / len(w), 'thr': thresholds[t]})
            m_rec, m_prec, _ = mkt_curves[nm]
            mp, _ = prec_at_recall(m_rec, m_prec, rc)
            results_op[nm][-1]['mkt_precision'] = mp
            mark = ' ◀◀' if t == 0.70 else ''
            print(f'  {t:.2f}            | {rc:6.1%}  | {pr:7.2%}  | {pr/base:5.2f}x   '
                  f'| {nsel:6,} ({nsel/len(w):5.1%})  市場のみ{mp:6.2%}{mark}')

    # ── 3スコアラー比較(同一窓・自身のカーブ上でrecall固定時のprecision) ──
    print('\n【分解: フルモデル vs 市場のみ vs 能力特徴のみ(市場情報抜き)】')
    decomp = {}
    for nm in windows:
        base = windows[nm]['t3'].mean()
        rec_f, prec_f, _ = curves[nm]
        rec_m, prec_m, _ = mkt_curves[nm]
        rec_a, prec_a, _ = abil_curves[nm]
        print(f'  --- {nm} (base {base:.2%}) recall→precision ---')
        decomp[nm] = []
        for t in (0.50, 0.60, 0.70, 0.80):
            pf, _ = prec_at_recall(rec_f, prec_f, t)
            pm, _ = prec_at_recall(rec_m, prec_m, t)
            pa, _ = prec_at_recall(rec_a, prec_a, t)
            decomp[nm].append({'recall': t, 'full': pf, 'market': pm, 'ability': pa})
            print(f'    recall{t:.2f}: フル{pf:7.2%}  市場のみ{pm:7.2%}  能力のみ{pa:7.2%}'
                  f'  (フル-市場{(pf-pm)*100:+.2f}pp)')

    # ── combo基準点 ──
    combo_pts = {}
    if not args.skip_combo and not args.quick:
        cm = build_combo_map()
        for nm, w in windows.items():
            key = w['race_key'].astype(str) + '|' + w['ketto_num'].astype(str)
            cvals = key.map(cm)
            cov = cvals.notna().mean()
            base_pos = int(w['t3'].sum())
            combo_pts[nm] = {}
            print(f'\n--- combo基準点({nm})  カバレッジ{cov:.1%} ---')
            for cmin in (1, 2, 3):
                sel = cvals >= cmin
                nsel = int(sel.sum())
                hit = int(w['t3'][sel].sum())
                rc, pr = hit / max(base_pos, 1), hit / max(nsel, 1)
                combo_pts[nm][f'combo>={cmin}'] = {'recall': rc, 'precision': pr, 'n_sel': nsel}
                # 同予算(同じ選択頭数)でのモデル
                s = scores[nm]
                top_idx = np.argsort(-s, kind='stable')[:nsel]
                hit_m = int(w['t3'].values[top_idx].sum())
                print(f'  combo>={cmin}: recall={rc:6.1%} precision={pr:6.2%} n={nsel:,}'
                      f'  ‖ モデル同頭数: recall={hit_m/max(base_pos,1):6.1%} '
                      f'precision={hit_m/max(nsel,1):6.2%}')
            # 0.70運用点で捕捉した好走馬のcombo内訳(combo0天井の突破確認)
            sel70 = scores[nm] >= thresholds[0.70]
            pos_mask = w['t3'].values == 1
            cv = cvals.values
            c0 = (pd.to_numeric(pd.Series(cv), errors='coerce').fillna(-1).values == 0)
            pos_c0 = pos_mask & c0
            if pos_c0.sum() > 0:
                got = (sel70 & pos_c0).sum() / pos_c0.sum()
                print(f'  combo=0の好走馬(現方式で原理的に不可視の層): '
                      f'{int(pos_c0.sum())}頭中 {got:.1%} をモデル0.70運用点が捕捉')

    # ── 特徴量の採否: 残差z(人気統制)とholdout安定性 ──
    base_map = w_fit.groupby('ninki_c')['t3'].mean().to_dict()
    gbase = w_fit['t3'].mean()
    flags = {
        '🔵補正T top3(現行)': lambda w: w['h7_rank'] <= 3,
        '補正T 連続上位40%(緩和)': lambda w: w['h7_pct'] <= 0.4,
        '🔥末脚 top3(現行)': lambda w: w['spurt_rank_f'] <= 3,
        '末脚 連続上位40%(緩和)': lambda w: w['spurt_race_pct'] <= 0.4,
        '🧬血統 race top3': lambda w: w['blood_rank_f'] <= 3,
        '👑騎手form race top3': lambda w: w['jk_rank_f'] <= 3,
        '⚡33ラップ適合': lambda w: w['lap_fit_bin'] == 1,
        '🏃位置3以内(過去平均)': lambda w: w['avg_pos3'] <= 3,
        '前走着差≤0.3s(3走ベスト)': lambda w: w['margin_best3'] <= 0.3,
        '厩舎form上位(≥0.25)': lambda w: w['trainer_form_t3'] >= 0.25,
    }
    print('\n' + '=' * 78)
    print('【特徴量の残差z(人気別ベース比=市場超え判定)】 rate/z/n')
    zrep = {}
    hdr = f'  {"flag":30s}' + ''.join(f'{nm:>24s}' for nm in windows)
    print(hdr)
    for label, fn in flags.items():
        cells, zrow = [], {}
        for nm, w in windows.items():
            m = fn(w)
            r = resid_z(w[m.fillna(False)], base_map, gbase)
            if r is None or r[2] < 30:
                cells.append(f'{"n<30":>24s}')
            else:
                cells.append(f'{r[0]:7.1%} z{r[1]:+5.1f} n{r[2]:6,}')
                zrow[nm] = {'rate': r[0], 'z': r[1], 'n': r[2]}
        zrep[label] = zrow
        print(f'  {label:28s}' + ''.join(cells))
    # モデルスコア自体の市場超え
    for nm, w in windows.items():
        sel = scores[nm] >= thresholds[0.70]
        r = resid_z(w[sel], base_map, gbase)
        if r:
            print(f'  [モデル0.70運用点 {nm}] rate={r[0]:.1%} 残差z={r[1]:+.1f} n={r[2]:,}')

    imp = sorted(zip(FEATS, model.feature_importance('gain')), key=lambda x: -x[1])
    print('\n【feature importance(gain) top20】')
    for f, g in imp[:20]:
        print(f'  {f:20s} {g:12.0f}')

    # ── 出力 ──
    out = {
        'ts': _time.strftime('%Y-%m-%d %H:%M:%S'), 'quick': args.quick,
        'population': 'JRA平地 7番人気以下 完走', 'features': FEATS,
        'best_iteration': model.best_iteration,
        'windows': {nm: {'n': len(w), 'positives': int(w['t3'].sum()),
                         'base': float(w['t3'].mean())} for nm, w in windows.items()},
        'operating_points': results_op,
        'combo_points': combo_pts,
        'resid_z': zrep,
        'importance': [{'f': f, 'gain': float(g)} for f, g in imp],
        'curves': {nm: {'recall': [float(x) for x in curves[nm][0][::max(1, len(curves[nm][0])//400)]],
                        'precision': [float(x) for x in curves[nm][1][::max(1, len(curves[nm][1])//400)]]}
                   for nm in windows},
        'market_curves': {nm: {'recall': [float(x) for x in mkt_curves[nm][0][::max(1, len(mkt_curves[nm][0])//400)]],
                               'precision': [float(x) for x in mkt_curves[nm][1][::max(1, len(mkt_curves[nm][1])//400)]]}
                          for nm in windows},
        'ability_curves': {nm: {'recall': [float(x) for x in abil_curves[nm][0][::max(1, len(abil_curves[nm][0])//400)]],
                                'precision': [float(x) for x in abil_curves[nm][1][::max(1, len(abil_curves[nm][1])//400)]]}
                           for nm in windows},
        'decomposition': decomp,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'\njson → {OUT_JSON}')

    if not args.no_plot and not args.quick:
        try:
            plot_curves(curves, windows, combo_pts, mkt_curves, abil_curves)
            print(f'png  → {OUT_PNG}')
        except Exception as e:
            print(f'plot skipped: {e}', file=sys.stderr)
    print(f'done in {_time.time()-t0:.0f}s')


def plot_curves(curves, windows, combo_pts, mkt_curves, abil_curves):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = ['Meiryo', 'Yu Gothic', 'MS Gothic', 'sans-serif']
    colors = {'val2024': '#eda100', 'holdout2025': '#2a78d6', 'recent3mo': '#1baf7a'}
    fig, ax = plt.subplots(figsize=(9, 6.2), facecolor='#fcfcfb')
    ax.set_facecolor('#fcfcfb')
    for nm in ('val2024', 'holdout2025', 'recent3mo'):
        rec, prec, _ = curves[nm]
        step = max(1, len(rec) // 2000)
        ax.plot(rec[::step], prec[::step], color=colors[nm], lw=2,
                label=f'モデルv2 {nm} (base {windows[nm]["t3"].mean():.1%})')
    m_rec, m_prec, _ = mkt_curves['holdout2025']
    step = max(1, len(m_rec) // 2000)
    ax.plot(m_rec[::step], m_prec[::step], color='#52514e', lw=1.5, ls='--', alpha=0.7,
            label='市場のみ(オッズ昇順) holdout2025')
    a_rec, a_prec, _ = abil_curves['holdout2025']
    step = max(1, len(a_rec) // 2000)
    ax.plot(a_rec[::step], a_prec[::step], color='#4a3aa7', lw=1.5, ls=':',
            label='能力特徴のみ(市場情報抜き) holdout2025')
    for nm, pts in (combo_pts or {}).items():
        for k, v in pts.items():
            ax.scatter(v['recall'], v['precision'], color=colors[nm], marker='D', s=55,
                       zorder=5, edgecolors='#fcfcfb', linewidths=1.5)
            if nm == 'holdout2025' or k == 'combo>=2':
                ax.annotate(f'{k} ({nm[:4]})', (v['recall'], v['precision']),
                            textcoords='offset points', xytext=(8, 6),
                            fontsize=8, color='#52514e')
    hb = windows['holdout2025']['t3'].mean()
    ax.axhline(hb * 1.35, color='#52514e', lw=1, ls='--', alpha=0.6)
    ax.text(0.01, hb * 1.35, '精度目標 = 基準×1.35 (holdout)', fontsize=8,
            color='#52514e', va='bottom')
    ax.axvline(0.70, color='#52514e', lw=1, ls=':', alpha=0.5)
    ax.text(0.70, ax.get_ylim()[1] * 0.97, ' recall目標0.70', fontsize=8,
            color='#52514e', va='top')
    ax.set_xlabel('recall(7番人気以下の3着内馬の捕捉率)')
    ax.set_ylabel('precision(選択馬の3着内率)')
    ax.set_title('妙味馬ハンター v2: precision–recall(現行combo点を重ねる)')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 0.30)
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(frameon=False, fontsize=9)
    for sp in ('top', 'right'):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)


if __name__ == '__main__':
    main()
