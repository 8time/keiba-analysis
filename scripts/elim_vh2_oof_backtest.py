# -*- coding: utf-8 -*-
"""消去順ML案の再挑戦 ―― Phase 0で落ちた2列を『正直な版』に作り直して再判定する。

前段(scripts/elim_ml_ranking_backtest.py --phase0)の結論:
  E(全43列)の -1.23pp は実質 vh2_score と combo の2列だけで出来ていた。しかし
  ① vh2_score は data/vh2_model.lgb(fit≤2023/val2024)の出力なので、学習期(2016-2024)の
     行は **in-sample** ＝ スコアと結果の関係が評価期(2025+)と別物。
  ② combo は data/vh2_combo_cache.json が2024+しか作っていないため学習期6%/評価期57%の
     カバレッジ差。しかも中身は ct.get_figure / bl.lookup_sire_stats / jj.jockey_power と
     『現在時点の集計』を過去レースに当てており6成分中4つがリーク。
  → どちらも「作り方が悪いだけ」の可能性が残る。ここでその2列を正直に作り直して再判定する。

このスクリプトがやること:
  ① vh2_score の out-of-fold 化
     年ごとの expanding window (target年Yのスコアは year<Y のみで学習したモデルで付ける)。
     これで学習期の行も評価期と同じ『未知データに対するスコア』になる。ライブ推論時も
     凍結vh2にとって当日は未知＝評価条件と一致する。
     入力はCSV特徴ストア+jravan.db(baba/cushion)から vh2.FEATS を再構成(パイプライン再実行不要)。
     fold毎の round 数は凍結モデルの best_iteration(112) に固定(early stoppingのval漏れを避ける)。
  ② combo のリークフリー再構築(combo_lf)
     6成分をCSVストアのleak-free列だけで作り直し、全期間(2016+)・全人気帯に付与する。
       補正T top3 = h7_rank<=3 / 血統 top3 = sire_surf_t3のレース内降順top3 /
       種牡馬ROI100%+ = sire_winroi>=1.0 / 末脚 top3 = spurt_idxのレース内降順top3 /
       33ラップ適合 = lap_fit_bin==1 / 騎手 top3 = jockey_form_t3のレース内降順top3

【結論(2026-07-22) ―― ①②とも改善せず・不採用確定】
  健全性: 自作vh2入力の再現度は凍結vh2_scoreとspearman 0.9900(=入力の再構成は正しい)。
  train 2018-2024 → eval 2025+ でのこぼし率(現行=人気順 12.15%):
    F1: live+vh2(凍結)          11.28%  -0.88pp ❌
    F2: live+vh2_oof   ←①      11.40%  -0.75pp ❌  … OOF化しても改善しない(むしろ僅かに悪化)
    F3: vh2_oof 単独            11.46%  -0.69pp ❌
    F4: live+vh2_oof+combo_lf ←② 11.28%  -0.88pp ❌  … リークフリーcomboの上乗せは+0.13ppのみ
    F5: live+combo_lf(vh2抜き)   16.78%  +4.63pp ❌  … combo_lf単体は人気順より大幅に悪い
    F6: live+vh2_oof+combo(リーク版) 11.15%  -1.00pp ✅ … ゲートに届くのはリーク列入りだけ
  → ①の仮説(in-sample歪みが足を引っ張っている)は棄却。②のリークフリーcomboは
    live列(連続量)と情報が重複していて上乗せがほぼ無い。**ゲートに到達する唯一の変種が
    リーク列を含むもの**という事実が、前段の -1.23pp が本物でなかったことの決定的な裏付け。
  → 消去順の人気→ML置換は不採用で確定。app.py は変更しない。

判定は前段と同じ: 実効消去数(下半分-ボーダー3)でのこぼし率が、現行(人気順)比 -1.0pp以上。
学習期は OOF が作れる 2018-2024、評価期は 2025+(標準分割)。凍結vh2版も同じ学習期で並べ、
『vh2の作り方だけを変えた』対照になるようにしてある。

Usage:
  python scripts/elim_vh2_oof_backtest.py            # キャッシュがあれば再利用
  python scripts/elim_vh2_oof_backtest.py --rebuild  # OOFを作り直す
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data                      # noqa: E402
from scripts import elim_ml_ranking_backtest as bt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
OOF_CACHE = os.path.join(ROOT, 'data', 'vh2_oof_cache.csv')

VH2_POP_MIN = 7      # vh2の学習母集団(7番人気以下)。value_hunter_recall_v2.POP_MIN と同一
VH2_ROUNDS = 112     # 凍結モデルの best_iteration(data/value_hunter_recall_v2.json)
VH2_PARAMS = {
    'objective': 'binary', 'metric': ['average_precision'],
    'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 100,
    'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 5,
    'verbose': -1, 'seed': 42, 'bagging_seed': 42, 'feature_fraction_seed': 42,
}
# scripts/value_hunter_recall_v2.FEATS と同一(順序込み)
VH2_FEATS = [
    'ninki', 'log_odds', 'umaban', 'waku_n', 'futan', 'bataiju', 'zogen',
    'sex_code', 'age', 'field_size', 'is_handicap', 'surface_code', 'kyori_int',
    'baba_code', 'jyo_code', 'race_num_code', 'cushion', 'dirt_moisture',
    'h7_fig', 'h7_pct',
    'spurt_idx', 'spurt_race_pct', 'spurt_mean3',
    'prior_top3_rate', 'avg_chaku5', 'prior_margin', 'margin_best3',
    'days_since', 'dist_change',
    'pos_ratio3', 'avg_pos3',
    'h_lap33', 'course_l33', 'lap_align', 'lap_fit_bin',
    'sire_surf_t3', 'sire_dist_t3', 'bms_surf_t3', 'blood_race_pct',
    'jockey_form_t3', 'jk_race_pct', 'jockey_jyo_win', 'jockey_dist_win',
    'trainer_jyo_t3', 'trainer_form_t3',
]

OOF_FIRST_YEAR = 2018   # fold開始年(これ未満は学習履歴が足りずOOFを作らない)
ELIM_TRAIN_FROM = 2018  # 消去モデルの学習開始年(OOFが存在する範囲に合わせる)
ELIM_TRAIN_END = 2024
ELIM_EVAL_FROM = 2025


# ──────────────────────────── vh2入力の再構成 ────────────────────────────

def add_race_meta(df):
    """CSVストアに無い vh2入力(baba_code/cushion/dirt_moisture)をjravan.dbから補う。
    bm.encode_features と同じ定義: baba_code は芝ならbaba_shiba・ダならbaba_dirt。"""
    import sqlite3
    print('Merging race meta (baba/cushion)...', file=sys.stderr)
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=30)
    meta = pd.read_sql("""
        SELECT ra.race_key, ra.baba_shiba, ra.baba_dirt, tc.cushion, tc.dirt_moisture
        FROM races ra
        LEFT JOIN track_cond tc ON ra.year = tc.year AND ra.monthday = tc.monthday
                               AND ra.jyo = tc.jyo
        WHERE CAST(ra.year AS INTEGER) >= 2016 AND ra.jyo <= '10'
    """, con)
    con.close()
    meta['race_key'] = pd.to_numeric(meta['race_key'], errors='coerce')
    df = df.merge(meta, on='race_key', how='left')
    bs = pd.to_numeric(df['baba_shiba'], errors='coerce').fillna(0)
    bd = pd.to_numeric(df['baba_dirt'], errors='coerce').fillna(0)
    df['baba_code'] = np.where(df['surface_code'] == 0, bs, bd).astype(int)
    df['cushion'] = pd.to_numeric(df['cushion'], errors='coerce')
    df['dirt_moisture'] = pd.to_numeric(df['dirt_moisture'], errors='coerce')
    df.drop(columns=['baba_shiba', 'baba_dirt'], inplace=True)
    return df


def add_vh2_inputs(df):
    """CSV列名 → vh2の特徴名に揃える(値の定義は build_ltr_model.encode_features と同じ)。"""
    df['log_odds'] = np.log1p(pd.to_numeric(df['win_odds'], errors='coerce').fillna(0))
    df['is_handicap'] = pd.to_numeric(df['is_handi1'], errors='coerce').fillna(0).astype(int)
    df['jyo_code'] = pd.to_numeric(df['jyo'], errors='coerce').fillna(0).astype(int)
    df['race_num_code'] = pd.to_numeric(df['race_num'], errors='coerce').fillna(0).astype(int)
    missing = [c for c in VH2_FEATS if c not in df.columns]
    if missing:
        raise SystemExit(f'vh2入力が足りない: {missing}')
    return df


def build_vh2_oof(df, rebuild=False):
    """年ごとの expanding window で vh2スコアを out-of-fold 付与する。

    target年Y のスコアは『year<Y の7番人気以下』だけで学習したモデルで付ける。
    (凍結vh2と同じパラメータ・同じround数。early stoppingは使わない=valの漏れを断つ)
    """
    key = df[['race_key', 'ketto_num']].copy()
    if os.path.exists(OOF_CACHE) and not rebuild:
        cache = pd.read_csv(OOF_CACHE)
        merged = key.merge(cache, on=['race_key', 'ketto_num'], how='left')
        cov = merged['vh2_oof'].notna().mean()
        print(f'OOF cache hit: {OOF_CACHE} (カバレッジ {cov:.1%})', file=sys.stderr)
        return merged['vh2_oof'].values

    import lightgbm as lgb
    yr = (pd.to_numeric(df['day'], errors='coerce') // 10000).astype(int)
    t3 = pd.to_numeric(df['top3'], errors='coerce').fillna(0).astype(int)
    ninki = pd.to_numeric(df['ninki'], errors='coerce')
    X = df[VH2_FEATS].values.astype(np.float64)
    out = np.full(len(df), np.nan)
    for y in range(OOF_FIRST_YEAR, int(yr.max()) + 1):
        fit_m = (yr < y) & (ninki >= VH2_POP_MIN)
        tgt_m = (yr == y).values
        if fit_m.sum() < 5000 or not tgt_m.any():
            continue
        ds = lgb.Dataset(X[fit_m.values], label=t3.values[fit_m.values],
                         feature_name=VH2_FEATS)
        model = lgb.train(VH2_PARAMS, ds, num_boost_round=VH2_ROUNDS)
        out[tgt_m] = model.predict(X[tgt_m])
        print(f'  OOF {y}: fit {int(fit_m.sum()):,}頭(<{y}・{VH2_POP_MIN}番人気以下) '
              f'→ scored {int(tgt_m.sum()):,}頭', file=sys.stderr)
    key['vh2_oof'] = out
    key.to_csv(OOF_CACHE, index=False)
    print(f'→ {OOF_CACHE}', file=sys.stderr)
    return out


def check_vh2_reconstruction(df):
    """自作したvh2入力が正しいかの健全性チェック。
    凍結モデルと同条件(fit≤2023・7番人気以下・112round)で組み直したスコアが、
    CSVの vh2_score 列とレース内順位でどれだけ一致するかを見る。低ければ入力の再構成ミス。"""
    import lightgbm as lgb
    yr = (pd.to_numeric(df['day'], errors='coerce') // 10000).astype(int)
    ninki = pd.to_numeric(df['ninki'], errors='coerce')
    fit_m = ((yr <= 2023) & (ninki >= VH2_POP_MIN)).values
    X = df[VH2_FEATS].values.astype(np.float64)
    t3 = pd.to_numeric(df['top3'], errors='coerce').fillna(0).astype(int).values
    ds = lgb.Dataset(X[fit_m], label=t3[fit_m], feature_name=VH2_FEATS)
    m = lgb.train(VH2_PARAMS, ds, num_boost_round=VH2_ROUNDS)
    ev = (yr >= 2025).values
    repro = m.predict(X[ev])
    frozen = pd.to_numeric(df['vh2_score'], errors='coerce').values[ev]
    ok = np.isfinite(repro) & np.isfinite(frozen)
    r = pd.Series(repro[ok]).corr(pd.Series(frozen[ok]), method='spearman')
    print(f'\n[健全性] 自作vh2入力の再現度(2025+ n={ok.sum():,}): '
          f'凍結vh2_scoreとのspearman = {r:.4f}', file=sys.stderr)
    if r < 0.95:
        print('  ⚠ 0.95未満。vh2入力の再構成がズレている可能性がある。', file=sys.stderr)
    return float(r)


# ──────────────────────────── combo のリークフリー再構築 ────────────────────────────

def add_combo_leakfree(df):
    """combo6をCSVストアのleak-free列だけで作り直す(全期間・全人気帯)。

    キャッシュ版(data/vh2_combo_cache.json)は補正T図/血統stats/騎手powerを『現在時点の集計』で
    引いており過去レースにとってリーク。ここでは同じ6成分を、レース時点までの情報だけで
    計算済みのCSV列から作る。レース内top3判定は build_combo_map と同じ向き。
    """
    print('Building leak-free combo6...', file=sys.stderr)
    g = df.groupby('race_key')

    def _rank_desc(col):
        return g[col].rank(method='min', ascending=False, na_option='bottom')
    h7r = pd.to_numeric(df['h7_rank'], errors='coerce')
    parts = {
        'ct': (h7r <= 3) & h7r.notna() & df['h7_fig'].notna(),
        'blood': _rank_desc('sire_surf_t3') <= 3,
        'roi': pd.to_numeric(df['sire_winroi'], errors='coerce') >= 1.0,
        'spurt': _rank_desc('spurt_idx') <= 3,
        'lap': pd.to_numeric(df['lap_fit_bin'], errors='coerce') == 1,
        'jockey': _rank_desc('jockey_form_t3') <= 3,
    }
    # 素材が全部欠損の馬に top3 を与えないよう、順位系は元の列がnotnaの馬に限る
    for k, src in (('blood', 'sire_surf_t3'), ('spurt', 'spurt_idx'),
                   ('jockey', 'jockey_form_t3')):
        parts[k] = parts[k] & df[src].notna()
    df['combo_lf'] = sum(p.fillna(False).astype(int) for p in parts.values())
    for k, p in parts.items():
        print(f'  {k:7s} 点灯率 {p.fillna(False).mean():.1%}', file=sys.stderr)
    print(f"  combo_lf 平均 {df['combo_lf'].mean():.2f} / "
          f"≥2 の割合 {(df['combo_lf'] >= 2).mean():.1%}", file=sys.stderr)
    return df


# ──────────────────────────── 判定 ────────────────────────────

def run_variants(df):
    yr = (pd.to_numeric(df['day'], errors='coerce') // 10000).astype(int)
    tr = df[(yr >= ELIM_TRAIN_FROM) & (yr <= ELIM_TRAIN_END)]
    ev = df[yr >= ELIM_EVAL_FROM].copy()
    live = bt.LIVE_EASY + bt.LIVE_DB + bt.LIVE_BLOOD + bt.LIVE_DERIVED
    ev['neg_ninki'] = -pd.to_numeric(ev['ninki'], errors='coerce')
    base = bt.evaluate(ev[ev['neg_ninki'].notna()], 'neg_ninki', ascending=True)

    print('\n' + '=' * 78)
    print(f'再判定  train {ELIM_TRAIN_FROM}-{ELIM_TRAIN_END} ({len(tr):,}頭) → '
          f'eval {ELIM_EVAL_FROM}+ ({len(ev):,}頭)')
    print('=' * 78)
    print(f"{'消去順':34s} {'こぼし率':>8s} {'lost3':>7s} {'対現行':>10s} {'列数':>5s}")
    print(f"{'A : 人気(現行)':34s} {base['miss_eff']*100:7.2f}% "
          f"{base['lost_eff']*100:6.2f}% {'—':>10s} {'—':>5s}")
    variants = [
        ('F1: live+vh2(凍結・in-sample)', live + ['vh2_score']),
        ('F2: live+vh2_oof  ←①の答え', live + ['vh2_oof']),
        ('F3: vh2_oof 単独', ['vh2_oof']),
        ('F4: live+vh2_oof+combo_lf ←②', live + ['vh2_oof', 'combo_lf']),
        ('F5: live+combo_lf(vh2抜き)', live + ['combo_lf']),
        ('F6: live+vh2_oof+combo(リーク版)', live + ['vh2_oof', 'combo']),
    ]
    for lbl, feats in variants:
        ev['_p'] = bt._fit_predict(tr, ev, feats)
        r = bt.evaluate(ev, '_p', ascending=True)
        d = (r['miss_eff'] - base['miss_eff']) * 100
        print(f"{lbl:34s} {r['miss_eff']*100:7.2f}% {r['lost_eff']*100:6.2f}% "
              f"{d:+9.2f}pp{'✅' if d <= -1.0 else '❌'} {len(feats):5d}")
    print('\n※ ゲート: 対現行 -1.0pp以上。F6は前段の-1.23ppがリーク列由来だったかの確認用。')


def main():
    rebuild = '--rebuild' in sys.argv
    df = csv_data.load_horses()
    df['umaban'] = pd.to_numeric(df['umaban'], errors='coerce')
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df = df[df['chakujun'].notna() & df['umaban'].notna()].reset_index(drop=True)
    df = add_race_meta(df)
    df = add_vh2_inputs(df)
    if rebuild or not os.path.exists(OOF_CACHE):
        check_vh2_reconstruction(df)
    df['vh2_oof'] = build_vh2_oof(df, rebuild=rebuild)
    df = add_combo_leakfree(df)
    run_variants(df)


if __name__ == '__main__':
    main()
