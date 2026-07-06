# -*- coding: utf-8 -*-
"""全データCSV化 — scripts/export_features_csv.py (Fable案件②)

このアプリの検証済みシグナルを全てCSVに書き出し、レーススキャナー(荒れ予報)改善の
材料にする。value_hunter_recall_v2.py のleak-freeパイプラインを再利用(変更しない)。

出力(data/export/ … data/はgitignore):
  horse_races.csv … 1行=1馬×1レース(2021+)。全シグナル(補正T/血統/末脚/33/騎手/消去/
                    位置取り/combo/vh2スコア)+事前確定属性+結果(chakujun/top3/win)。
  races.csv       … 1行=1レース(2021+)。フィールド集約(各シグナルのstd/top2差/平均)、
                    オッズ構造(エントロピー/断層/実効頭数)、combo馬数、展開型、
                    現行スキャナー出力(race_value_score/trio_lean/no_favorite_flag)、
                    荒れラベル(A/B/②型/本線/配当代理)。

リーク無し: 履歴系は全てshift(1)(vh2と同一)。オッズ/人気/馬体重/斤量は事前確定。
comboは data/vh2_combo_cache.json (2024+のみ・7番人気以下のみ) から付与。
荒れラベル定義:
  arareA = 3着内に7番人気以下が1頭以上(案件①と直結・主指標)
  arareB = 勝ち馬が6番人気以下
  ana2   = 3着内に5番人気以下が2頭以上(②型・condition_arare_backtestと同一)
  honsen = 1・2番人気が両方3着内(本線・同上)
  ninki_top3_logsum = 3着内3頭の人気の対数和(3連単配当の代理・連続量)

Usage: python scripts/export_features_csv.py
"""
import os
import sys
import json
import sqlite3
import time as _time

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.build_ltr_model as bm
import scripts.value_hunter_recall_v2 as vh2
from core import value_scanner as vs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_DIR = os.path.join(ROOT, 'data', 'export')
HORSE_FROM_DAY = 20210101   # CSV収録開始(履歴計算自体は1990+で行う)

HORSE_COLS = [
    # キー・属性(事前確定)
    'race_key', 'day', 'jyo', 'surface_code', 'kyori_int', 'race_num', 'field_size',
    'ketto_num', 'umaban', 'waku_n', 'ninki', 'win_odds', 'futan', 'bataiju', 'zogen',
    'sex_code', 'age', 'is_handi1',
    # シグナル(leak-free)
    'h7_fig', 'h7_rank', 'h7_pct',
    'spurt_idx', 'spurt_race_pct', 'spurt_mean3',
    'prior_top3_rate', 'avg_chaku5', 'prior_margin', 'margin_best3',
    'days_since', 'dist_change', 'avg_pos3', 'pos_ratio3',
    'h_lap33', 'course_l33', 'lap_align', 'lap_fit_bin',
    'sire_surf_t3', 'sire_dist_t3', 'bms_surf_t3', 'blood_race_pct',
    'jockey_form_t3', 'jk_race_pct', 'jockey_jyo_win', 'jockey_dist_win',
    'trainer_jyo_t3', 'trainer_form_t3',
    'elim_n', 'combo', 'ability_score', 'vh2_score',
    # 結果(ラベル用・リーク源につき特徴には使わないこと)
    'chakujun', 'top3', 'win',
]

# JV GradeCD → value_scanner.OPEN_CLASSES に合わせたクラス文字列
GRADE_CLASS = {'A': 'G1', 'B': 'G2', 'C': 'G3', 'D': 'オープン', 'L': 'L',
               'F': 'G2', 'G': 'G3', 'H': 'オープン'}


def add_elim_flags(df):
    """消去クロス(core/elim_cross.compute_flags)のベクトル化再現。
    検証済9フラグ(pcidev=過去PCI必要・train=調教データ無しは除外)の点灯数=elim_n。
    閾値は elim_cross.py の定数と同一。"""
    print('Computing elim flags...', file=sys.stderr)
    df['_t3f'] = (df['chakujun'] <= 3).astype(float)
    g = df.groupby('ketto_num')['_t3f']
    r3 = g.transform(lambda x: x.shift(1).rolling(3, min_periods=3).sum())
    r5 = g.transform(lambda x: x.shift(1).rolling(5, min_periods=3).sum())
    df['is_handi1'] = (df['juryo'].astype(str) == '1').astype(int)  # JV: 1=ハンデ
    futan = pd.to_numeric(df['futan'], errors='coerce')
    flags = {
        'form3': r3 == 0,
        'nofuku5': r5 == 0,
        'slow3f': df['spurt_idx'].notna() & (df['spurt_idx'] <= 0.30),
        'back': df['pos_ratio3'] >= 0.78,
        'layoff': df['days_since'] >= 180,
        'distbig': df['dist_change'].abs() >= 400,
        'zogen16': pd.to_numeric(df['zogen'], errors='coerce').abs() >= 16,
        'age8': pd.to_numeric(df['age'], errors='coerce') >= 8,
        'lhandi': (df['is_handi1'] == 1) & (futan <= 510),
    }
    df['elim_n'] = sum(f.fillna(False).astype(int) for f in flags.values())
    df.drop(columns=['_t3f'], inplace=True)
    return df


def _nth_by_rank(sub, col, n, higher_better=False):
    """レース内でcolをソートしたn番目(0始まり)の値(race_key index)。"""
    s = sub[['race_key', col]].dropna().sort_values(
        ['race_key', col], ascending=[True, not higher_better])
    s['_i'] = s.groupby('race_key').cumcount()
    return s[s['_i'] == n].set_index('race_key')[col]


def _top2(sub, col, higher_better=True):
    """レース内のベスト値と(ベスト−2番手)差。戻り値: (best, gap) race_key index。"""
    b1 = _nth_by_rank(sub, col, 0, higher_better)
    b2 = _nth_by_rank(sub, col, 1, higher_better)
    return b1, (b1 - b2).abs()


def aggregate_races(d):
    """馬行→レース行の集約(全て事前確定情報)。"""
    print('Aggregating races...', file=sys.stderr)
    d = d.copy()
    d['win_odds'] = pd.to_numeric(d['win_odds'], errors='coerce')
    d.loc[d['win_odds'] <= 0, 'win_odds'] = np.nan

    base = d.groupby('race_key').agg(
        day=('day', 'first'), jyo=('jyo', 'first'), surface_code=('surface_code', 'first'),
        kyori=('kyori_int', 'first'), field_size=('field_size', 'first'),
        race_num=('race_num_code', 'first'), baba_code=('baba_code', 'first'),
        is_handi1=('is_handi1', 'first'), n_run=('umaban', 'count'),
        cushion=('cushion', 'first'), dirt_moisture=('dirt_moisture', 'first'))
    base['month'] = (base['day'] // 100) % 100

    # ── オッズ構造 ──
    v = d.dropna(subset=['win_odds']).sort_values(['race_key', 'win_odds'])
    for n in (0, 1, 2):
        base[f'fav{n+1}'] = _nth_by_rank(v, 'win_odds', n)
    base['r21'] = base['fav2'] / base['fav1']
    base['r31'] = base['fav3'] / base['fav1']
    base['spread31'] = base['fav3'] - base['fav1']
    inv = v.assign(_p=1.0 / v['win_odds'])
    inv['_pn'] = inv['_p'] / inv.groupby('race_key')['_p'].transform('sum')
    base['odds_entropy'] = (-(inv['_pn'] * np.log(inv['_pn']))
                            .groupby(inv['race_key']).sum())
    base['eff_n'] = np.exp(base['odds_entropy'])
    base['syn3'] = 3.0 / (1.0 / base['fav1'] + 1.0 / base['fav2'] + 1.0 / base['fav3'])
    base['live10'] = (v['win_odds'] < 10).groupby(v['race_key']).sum()
    base['live30'] = (v['win_odds'] < 30).groupby(v['race_key']).sum()
    base['mid515'] = ((v['win_odds'] >= 5) & (v['win_odds'] <= 15)).groupby(v['race_key']).sum()
    base['n_odds'] = v.groupby('race_key')['win_odds'].count()

    # ── フィールド実力の拮抗度(スプレッド/突出) ──
    d['_h7neg'] = -d['h7_fig']            # 高いほど良い向きに揃える
    d['_margneg'] = -d['margin_best3']
    spread_cols = [('_h7neg', 'h7'), ('spurt_idx', 'spurt'), ('sire_surf_t3', 'blood'),
                   ('jockey_form_t3', 'jk'), ('prior_top3_rate', 'pt3'),
                   ('_margneg', 'marg'), ('vh2_score', 'vh2')]
    for col, tag in spread_cols:
        grp = d.groupby('race_key')[col]
        base[f'{tag}_std'] = grp.std()
        base[f'{tag}_mean'] = grp.mean()
        best, gap = _top2(d, col, higher_better=True)
        base[f'{tag}_best'] = best
        base[f'{tag}_top2gap'] = gap

    # 市場と実力評価の一致度(順位相関)。低い=市場が実力序列を信じていない
    sub = d[['race_key', 'win_odds', 'ability_score']].dropna()
    sub = sub[sub.groupby('race_key')['race_key'].transform('count') >= 6]
    sub['_or'] = sub.groupby('race_key')['win_odds'].rank()
    sub['_ar'] = sub.groupby('race_key')['ability_score'].rank()
    base['mkt_ability_corr'] = sub.groupby('race_key').apply(
        lambda g: g['_or'].corr(g['_ar']))

    # ── combo(案件①)・消去・展開型 ──
    pop7 = d['ninki'] >= 7
    base['n_pop7'] = pop7.groupby(d['race_key']).sum()
    base['n_combo2'] = (pop7 & (d['combo'] >= 2)).groupby(d['race_key']).sum()
    base['n_combo3'] = (pop7 & (d['combo'] >= 3)).groupby(d['race_key']).sum()
    base['combo_cov'] = d['combo'].notna().groupby(d['race_key']).mean()
    base['mean_elim'] = d.groupby('race_key')['elim_n'].mean()
    base['n_elim3'] = (d['elim_n'] >= 3).groupby(d['race_key']).sum()
    base['n_lowelim_pop7'] = (pop7 & (d['elim_n'] <= 1)).groupby(d['race_key']).sum()
    base['n_front'] = (d['avg_pos3'] <= 3).groupby(d['race_key']).sum()
    base['n_hana'] = (d['pos_ratio3'] <= 0.20).groupby(d['race_key']).sum()
    base['mean_posr'] = d.groupby('race_key')['pos_ratio3'].mean()

    # ── 荒れラベル(結果由来・特徴に使わない) ──
    t3 = d['chakujun'] <= 3
    base['arareA'] = ((t3 & (d['ninki'] >= 7)).groupby(d['race_key']).sum() > 0).astype(int)
    winner_nk = d[d['chakujun'] == 1].groupby('race_key')['ninki'].min()
    base['arareB'] = (winner_nk >= 6).astype(int)
    base['ana2'] = ((t3 & (d['ninki'] >= 5)).groupby(d['race_key']).sum() >= 2).astype(int)
    base['honsen'] = ((t3 & (d['ninki'] <= 2)).groupby(d['race_key']).sum() >= 2).astype(int)
    nk3 = d[t3].groupby('race_key')['ninki'].apply(lambda x: float(np.log(x).sum()))
    base['ninki_top3_logsum'] = nk3
    return base.reset_index()


def add_scanner_outputs(races, d):
    """現行スキャナー(core/value_scanner)のオフライン再現出力を付与。
    pace_zはライブ専用インフラのためNone(現行運用でも常時は入らない・注記)。"""
    print('Scoring current scanner...', file=sys.stderr)
    con = sqlite3.connect(f'file:{os.path.join(ROOT, "data", "jravan.db")}?mode=ro',
                          uri=True, timeout=30)
    meta = pd.read_sql(
        "SELECT race_key, grade, kigo, shubetsu, race_name FROM races", con)
    con.close()
    races = races.merge(meta, on='race_key', how='left')
    races['fillies'] = (races['kigo'].astype(str).str[1] == '2').astype(int)
    races['is_2yo'] = (races['shubetsu'].astype(str) == '11').astype(int)
    races['open_cls'] = races['grade'].astype(str).map(
        lambda g: 1 if g in GRADE_CLASS else 0)

    odds_lists = d.dropna(subset=['win_odds']).groupby('race_key')['win_odds'].apply(list)
    out = {'vscore': [], 'vlabel': [], 'lean_score': [], 'lean_label': [], 'nofav': []}
    for row in races.itertuples(index=False):
        ol = odds_lists.get(row.race_key, [])
        surf = 'ダ' if row.surface_code == 1 else '芝'
        baba = vs.baba_code_to_label(row.baba_code)
        m = {'is_handicap': bool(row.is_handi1), 'condition': baba,
             'class': GRADE_CLASS.get(str(row.grade), '')}
        try:
            rv = vs.race_value_score(ol, m, jyo=str(row.jyo), surface=surf,
                                     dist=int(row.kyori), n_horses=int(row.field_size))
            ln = vs.trio_lean(m, n_horses=int(row.field_size), fav_odds=rv['fav_odds'],
                              dist=int(row.kyori), baba=baba, odds_list=ol)
            nf = vs.no_favorite_flag(ol)
        except Exception:
            rv, ln, nf = {'score': np.nan, 'label': ''}, {'score': np.nan, 'lean': ''}, None
        out['vscore'].append(rv['score'])
        out['vlabel'].append(rv['label'])
        out['lean_score'].append(ln['score'])
        out['lean_label'].append(ln['lean'])
        out['nofav'].append(nf or '')
    for k, vv in out.items():
        races[k] = vv
    return races


def main():
    t0 = _time.time()
    os.makedirs(EXPORT_DIR, exist_ok=True)

    df = vh2.load_data(base_year=1990)
    df = bm.compute_corrected_time(df)
    df = bm.compute_rolling_features(df)
    df = bm.compute_trainer_course(df)
    df = bm.compute_jockey_course(df)
    df = bm.compute_jockey_dist(df)
    df = vh2.add_v2_features(df)
    df = df[df['year'].astype(int) >= 2016].copy()
    df = bm.encode_features(df)
    df = bm.compute_race_ranks(df)
    df = vh2.add_race_pcts(df)
    df = add_elim_flags(df)

    # 総合実力スコア(オッズ非依存・レース内pct平均・低い=良い)と vh2スコア
    pcts = df[['h7_pct', 'spurt_race_pct', 'blood_race_pct', 'jk_race_pct']]
    df['ability_score'] = pcts.mean(axis=1)
    import lightgbm as lgb
    if os.path.exists(vh2.OUT_MODEL):
        print('Scoring vh2 model...', file=sys.stderr)
        booster = lgb.Booster(model_file=vh2.OUT_MODEL)
        df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
        df['vh2_score'] = booster.predict(df[vh2.FEATS].values.astype(np.float64))
    else:
        df['vh2_score'] = np.nan

    # combo(2024+・7番人気以下のみ)
    combo = {}
    if os.path.exists(vh2.COMBO_CACHE):
        with open(vh2.COMBO_CACHE, encoding='utf-8') as f:
            combo = json.load(f)
    key = df['race_key'].astype(str) + '|' + df['ketto_num'].astype(str)
    df['combo'] = key.map(combo)

    df['top3'] = (df['chakujun'] <= 3).astype(int)
    df['win'] = (df['chakujun'] == 1).astype(int)

    d = df[df['day'] >= HORSE_FROM_DAY].copy()
    del df
    print(f'export rows: {len(d):,} ({HORSE_FROM_DAY}+)', file=sys.stderr)

    horse_path = os.path.join(EXPORT_DIR, 'horse_races.csv')
    d[HORSE_COLS].to_csv(horse_path, index=False, encoding='utf-8')
    print(f'→ {horse_path} ({os.path.getsize(horse_path)/1e6:.0f}MB)')

    races = aggregate_races(d)
    races = add_scanner_outputs(races, d)
    races_path = os.path.join(EXPORT_DIR, 'races.csv')
    races.to_csv(races_path, index=False, encoding='utf-8')
    print(f'→ {races_path} ({len(races):,}レース)')
    print(f'done in {_time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
