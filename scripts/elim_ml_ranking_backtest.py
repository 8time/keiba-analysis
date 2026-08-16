# -*- coding: utf-8 -*-
"""消去エンジンの高度化検証 ―― 消去順を『人気』から『ML予測』に変えると
3着内の取りこぼしは減るか / 同じこぼし率でもっと多く消せるか。

背景:
  現行の消去は支配項=-人気で下位半分カット+ボーダー3頭戻し(こぼし≈15%→≈10%)。
  ルール追加路線は検証済みで頭打ち(elim_frontier: フラグ加重は却下)。
  残る本命 = 消去順そのものを学習器に置き換える案。

方式(リーク無し):
  - CSV特徴ストア(全特徴leak-free)でLGBM二値(label=3着内)をtrain(≤2024)で学習。
  - holdout(2025+2026)で消去順を比較:
      A: 人気順(現行の支配項)
      B: ability_score(オッズ非依存の実力pct)
      C: vh2_score(妙味馬モデル)
      D: ML予測(市場情報込み)
      E: ML予測(オッズ・人気を特徴から除いた市場非依存版)
  - 指標:
      こぼし率: 消した中に3着内馬が1頭でもいたレースの割合
      lost3   : 3着内馬のうち消された頭数の平均割合
    を「現行と同じ実効消去数(下半分-ボーダー3)」と「+2頭多く消す」で測る。

採用ゲート: holdoutで こぼし率が現行(人気順)より1pp以上低い、または
            同じこぼし率で消去数を2頭以上増やせること。

【Phase 0の結論(2026-07-22) ―― 採用ゲート未達・配線せず】
  `--phase0` のアブレーションで、Eの -1.23pp は次の2列だけで作られていたと判明した:
    ・vh2_score … 単独で -0.58pp(標準分割)。ただし内部に ninki/log_odds を含むので
                  「市場なし(E)」という建前は元々成立していない。
    ・combo     … 学習期6.1% / 評価期57.1% のカバレッジ差(2024+しか作っていない)。
                  単独では +2.54pp(役に立たない)のに、vh2と組むと標準分割で -0.6pp 稼ぎ、
                  別分割では逆に +0.11pp 悪化する＝分割の副産物(`--coverage` 参照)。
  ライブ再現可能な列だけの最良変種 E4(live+vh2_score)は標準分割 -0.63pp で
  ゲート(-1.0pp)未達。しかもその成績は実質 vh2_score 単独(E6 -0.58pp)と同じで、
  残り41列は上乗せゼロ＝ライブ特徴パリティを作る労力に見合わない。
  → 消去順の人気→ML置換は**不採用**。app.py は現行(-人気)のまま変更しない。
  追試(scripts/elim_vh2_oof_backtest.py): 「vh2をout-of-fold化すれば」「comboをリークフリーに
  作り直せば」の2案とも改善せず(最良 -0.88pp)。ゲートに届く唯一の変種がリーク版combo入り
  ＝上の -1.23pp が本物でなかったことの裏付け。不採用で確定。

Phase 0(特徴パリティ設計・repo/opus_brief_elim_ml_ranking.md):
  `python scripts/elim_ml_ranking_backtest.py --phase0`
  Eの43列は「オフラインCSVにしか無い列」を含む。ライブ(消去フィルターのページ)で
  同じ値を作れる列だけに絞ってもゲート(-1.0pp)を維持できるかを、列グループの
  アブレーションで確かめる。2分割(標準 train≤2024/holdout2025+ と 代替 train≤2022/2023-24)。

Phase 0 診断:
  `python scripts/elim_ml_ranking_backtest.py --coverage`
  combo/vh2_scoreのカバレッジと学習窓を出す(上の結論の根拠)。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data  # noqa: E402

MIN_FIELD = 8
BORDER = 3

# 特徴: CSVストアのleak-free列。IDや結果系は除外
_EXCLUDE = {'race_key', 'day', 'jyo', 'race_num', 'ketto_num', 'umaban',
            'chakujun', 'top3', 'win', 'sire', 'bms', 'period'}
_MARKET = {'ninki', 'win_odds'}

# ── Phase 0: ライブ再現性による列の3分類 ──────────────────────────────
# live-easy: スクレイプ済みdf/metadataから直接取れる(DBアクセス不要)
LIVE_EASY = ['surface_code', 'kyori_int', 'field_size', 'waku_n', 'futan',
             'bataiju', 'zogen', 'sex_code', 'age', 'is_handi1']
# live-db: jravan.dbから馬/騎手/厩舎キーで計算できる(core/ltr_ranker.pyと同型)
LIVE_DB = ['h7_fig', 'h7_rank', 'h7_pct',
           'spurt_idx', 'spurt_race_pct', 'spurt_mean3',
           'prior_top3_rate', 'avg_chaku5', 'prior_margin', 'margin_best3',
           'days_since', 'dist_change', 'avg_pos3', 'pos_ratio3',
           'h_lap33', 'course_l33', 'lap_align', 'lap_fit_bin',
           'jockey_form_t3', 'jk_race_pct', 'jockey_jyo_win', 'jockey_dist_win',
           'trainer_jyo_t3', 'trainer_form_t3', 'elim_n']
# live-db(血統): horses(sire/bms)経由。indexはあるが大種牡馬は行数が多くコスト高
LIVE_BLOOD = ['sire_surf_t3', 'sire_dist_t3', 'bms_surf_t3', 'blood_race_pct',
              'sire_winroi']
# 血統pctを含む合成(ability_score = h7_pct/spurt_race_pct/blood_race_pct/jk_race_pctの平均)
LIVE_DERIVED = ['ability_score']
# live-hard: ライブ再現不能または市場情報混入
#   combo … data/vh2_combo_cache.json(2024+・7番人気以下のみ)= 学習期間(≤2024)でほぼ欠損
#   vh2_score … vh2モデル出力。内部にninki/log_oddsを含む=「市場なし」の建前が崩れる
LIVE_HARD = ['combo', 'vh2_score']


def cut_counts(n):
    """現行の実効消去数(下半分カット-ボーダー3)と、+2頭絞り込み版。"""
    keep = (n + 1) // 2
    cut = n - keep
    border_max = max(0, min(BORDER, cut - 1)) if n >= 6 else 0
    eff = max(0, cut - border_max)
    return eff, eff + 2


def evaluate(df, score_col, ascending):
    """score昇順(ascending=True)の下位から消す。こぼし率とlost3を返す。"""
    miss_eff = lost_eff = miss_more = lost_more = tot = 0
    n_cut_eff = n_cut_more = 0
    for _, g in df.groupby('race_key', sort=False):
        n = len(g)
        if n < MIN_FIELD:
            continue
        top3 = set(g.loc[g['chakujun'] <= 3, 'umaban'])
        if not top3:
            continue
        eff, more = cut_counts(n)
        if eff <= 0:
            continue
        order = g.sort_values(score_col, ascending=ascending)
        cut_e = set(order.head(eff)['umaban'])
        cut_m = set(order.head(min(more, n - 1))['umaban'])
        miss_eff += int(bool(top3 & cut_e))
        lost_eff += len(top3 & cut_e) / len(top3)
        miss_more += int(bool(top3 & cut_m))
        lost_more += len(top3 & cut_m) / len(top3)
        n_cut_eff += eff
        n_cut_more += len(cut_m)
        tot += 1
    if not tot:
        return None
    return {'miss_eff': miss_eff / tot, 'lost_eff': lost_eff / tot,
            'miss_more': miss_more / tot, 'lost_more': lost_more / tot,
            'cut_eff': n_cut_eff / tot, 'cut_more': n_cut_more / tot, 'races': tot}


def _load_base():
    """CSVストアを読み、着順/馬番が有効な行だけ返す(全モードで共通)。"""
    df = csv_data.load_horses()
    df['umaban'] = pd.to_numeric(df['umaban'], errors='coerce')
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    return df[df['chakujun'].notna() & df['umaban'].notna()]


PARAMS = dict(objective='binary', learning_rate=0.05, num_leaves=63,
              min_data_in_leaf=200, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=7)
NUM_ROUNDS = 400


def _fit_predict(tr, ev, feats):
    """train行で学習しeval行の予測を返す(パラメータはE検証と同一)。"""
    import lightgbm as lgb
    ds = lgb.Dataset(tr[feats].values.astype(np.float64), label=tr['top3'].values)
    model = lgb.train(PARAMS, ds, num_boost_round=NUM_ROUNDS)
    return model.predict(ev[feats].values.astype(np.float64))


def _split(df, mode):
    """mode='std': train≤2024 / eval=2025+2026(標準)。
       mode='alt': train≤2022 / eval=2023-24(再現性チェック用の別分割)。"""
    yr = pd.to_numeric(df['day'], errors='coerce') // 10000
    if mode == 'std':
        return df[yr <= 2024], df[yr >= 2025].copy()
    return df[yr <= 2022], df[(yr >= 2023) & (yr <= 2024)].copy()


def phase0():
    """ライブ再現可能な列だけでゲート(-1.0pp)を維持できるかのアブレーション。"""
    print("=" * 78)
    print("Phase 0: 特徴パリティ ―― ライブ再現可能な列だけでゲートを維持できるか")
    print("=" * 78)
    df = _load_base()
    num_cols = [c for c in df.columns
                if c not in _EXCLUDE and pd.api.types.is_numeric_dtype(df[c])]
    all43 = [c for c in num_cols if c not in _MARKET]
    live_full = LIVE_EASY + LIVE_DB + LIVE_BLOOD + LIVE_DERIVED
    live_noblood = LIVE_EASY + LIVE_DB
    missing = set(all43) - set(live_full) - set(LIVE_HARD)
    if missing:
        print(f"⚠ 未分類の列があります: {sorted(missing)}")
    variants = [
        ('E : 全43列(参照)', all43),
        ('E1: live(combo/vh2抜き)', live_full),
        ('E2: live(血統も抜き)', live_noblood),
        ('E3: live-easy のみ', LIVE_EASY),
        ('E4: live + vh2_score', live_full + ['vh2_score']),
        ('E5: live + combo', live_full + ['combo']),
        ('E6: vh2_score 単独', ['vh2_score']),
    ]
    for mode, label in (('std', '標準 train≤2024 → 2025+2026'),
                        ('alt', '代替 train≤2022 → 2023-24')):
        tr, ev = _split(df, mode)
        ev['neg_ninki'] = -pd.to_numeric(ev['ninki'], errors='coerce')
        base = evaluate(ev[ev['neg_ninki'].notna()], 'neg_ninki', ascending=True)
        print(f"\n--- {label}  train {len(tr):,}頭 / eval {len(ev):,}頭 ---")
        print(f"{'消去順':30s} {'こぼし率':>8s} {'lost3':>7s} {'対現行':>9s} {'列数':>5s}")
        print(f"{'A : 人気(現行)':30s} {base['miss_eff']*100:7.2f}% "
              f"{base['lost_eff']*100:6.2f}% {'—':>9s} {'—':>5s}")
        for lbl, feats in variants:
            ev['_p'] = _fit_predict(tr, ev, feats)
            r = evaluate(ev, '_p', ascending=True)
            d = (r['miss_eff'] - base['miss_eff']) * 100
            gate = '✅' if d <= -1.0 else '❌'
            print(f"{lbl:30s} {r['miss_eff']*100:7.2f}% {r['lost_eff']*100:6.2f}% "
                  f"{d:+8.2f}pp{gate} {len(feats):5d}")
    print("\n※ ゲート: 対現行 -1.0pp以上(両分割で維持)。E1/E2が通ればその列だけでライブ実装する。")


def coverage():
    """Phase 0の結論の根拠: Eの成績を作っている2列(combo/vh2_score)の素性を暴く診断。

    combo … data/vh2_combo_cache.json は2024年以降・7番人気以下しか作っていない。
            学習期(≤2024)ではほぼ欠損なのに評価期(2025+)では過半が有り＝
            train/evalでカバレッジが激変する列。LightGBMは「欠損=学習期」を
            学習してしまうため、この列の寄与は実力でなく分割の副産物。
    vh2_score … data/vh2_model.lgb は fit≤2023 / val2024。よって『代替分割
            (eval=2023-24)』はvh2にとって完全にin-sample＝評価が甘くなる。
            vh2_scoreを含む変種は標準分割(eval=2025+)だけが正味の成績。
    """
    df = _load_base()
    yr = pd.to_numeric(df['day'], errors='coerce') // 10000
    print('=' * 78)
    print('Phase 0 診断: combo / vh2_score のカバレッジと学習窓')
    print('=' * 78)
    print(f"{'期間':22s} {'頭数':>9s} {'combo有':>8s} {'vh2有':>7s}")
    for lbl, m in (('train ≤2024', yr <= 2024), ('eval 2025+', yr >= 2025),
                   ('alt-train ≤2022', yr <= 2022), ('alt-eval 2023-24', (yr >= 2023) & (yr <= 2024))):
        s = df[m]
        print(f"{lbl:22s} {len(s):9,} {s['combo'].notna().mean():7.1%} "
              f"{s['vh2_score'].notna().mean():6.1%}")
    print('\n年別 combo カバレッジ:')
    cov = df.groupby(yr)['combo'].apply(lambda x: x.notna().mean())
    print('  ' + '  '.join(f'{int(k)}:{v:.0%}' for k, v in cov.items()))
    print('\n→ combo は評価期にしか十分に存在しない列。E(全43列)の -1.23pp のうち')
    print('  vh2_score を超える分(≒0.6pp)はこのカバレッジ差の産物で、別分割では符号が反転する。')
    print('→ vh2_score は fit≤2023/val2024。代替分割(eval2023-24)はin-sampleなので')
    print('  vh2_scoreを含む変種の正味成績は標準分割(eval2025+)だけを読むこと。')


def main():
    import lightgbm as lgb
    print("=" * 78)
    print("消去順の高度化検証: 人気順 vs ML予測 (holdout=2025+2026)")
    print("=" * 78)
    df = csv_data.load_horses()
    df['umaban'] = pd.to_numeric(df['umaban'], errors='coerce')
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df = df[df['chakujun'].notna() & df['umaban'].notna()]

    num_cols = [c for c in df.columns
                if c not in _EXCLUDE and pd.api.types.is_numeric_dtype(df[c])]
    feats_mkt = [c for c in num_cols]                       # 市場込み
    feats_nomkt = [c for c in num_cols if c not in _MARKET]  # 市場なし
    tr = df[df['period'] == 'train']
    ho = df[df['period'].isin(['holdout', 'recent'])].copy()
    print(f"train {len(tr):,}頭 / holdout {len(ho):,}頭  特徴 {len(feats_mkt)}列")

    params = dict(objective='binary', learning_rate=0.05, num_leaves=63,
                  min_data_in_leaf=200, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=7)
    models = {}
    for name, feats in (('ML(市場込み)', feats_mkt), ('ML(市場なし)', feats_nomkt)):
        ds = lgb.Dataset(tr[feats].values.astype(np.float64),
                         label=tr['top3'].values)
        models[name] = (lgb.train(params, ds, num_boost_round=400), feats)
        print(f"  {name}: 学習完了")

    ho['pred_mkt'] = models['ML(市場込み)'][0].predict(
        ho[models['ML(市場込み)'][1]].values.astype(np.float64))
    ho['pred_nomkt'] = models['ML(市場なし)'][0].predict(
        ho[models['ML(市場なし)'][1]].values.astype(np.float64))
    ho['neg_ninki'] = -pd.to_numeric(ho['ninki'], errors='coerce')
    ho['neg_ability'] = -pd.to_numeric(ho['ability_score'], errors='coerce')  # 低い=良い→反転
    ho['vh2'] = pd.to_numeric(ho['vh2_score'], errors='coerce').fillna(-1)

    print(f"\n実効消去数(現行=下半分-ボーダー3)での比較 [holdout]")
    print(f"{'消去順':18s} {'こぼし率':>8s} {'lost3':>7s} {'こぼし率+2頭':>10s} {'平均消去':>8s}")
    rows = [('A: 人気(現行)', 'neg_ninki'), ('B: 能力スコア', 'neg_ability'),
            ('C: vh2スコア', 'vh2'), ('D: ML(市場込み)', 'pred_mkt'),
            ('E: ML(市場なし)', 'pred_nomkt')]
    base = None
    for lbl, col in rows:
        r = evaluate(ho[ho[col].notna()], col, ascending=True)
        if r is None:
            print(f"{lbl:18s}  データ不足")
            continue
        if base is None:
            base = r
        print(f"{lbl:18s} {r['miss_eff']*100:7.2f}% {r['lost_eff']*100:6.2f}% "
              f"{r['miss_more']*100:9.2f}% {r['cut_eff']:7.1f}頭"
              + ("" if r is base else
                 f"  (こぼしΔ {(r['miss_eff']-base['miss_eff'])*100:+.2f}pp)"))

    print("\n※ こぼし率 = 消した中に3着内馬がいたレース割合(小さいほど良い)")
    print("※ 現行UIのボーダー3頭は実効消去数に織込み済み(下半分-3頭を消す想定)")


if __name__ == '__main__':
    if '--phase0' in sys.argv:
        phase0()
    elif '--coverage' in sys.argv:
        coverage()
    else:
        main()
