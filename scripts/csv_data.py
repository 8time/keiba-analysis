# -*- coding: utf-8 -*-
"""CSV特徴ストア ローダー (scripts/csv_data.py)。

Fable案件②で生成した凍結DBスナップショット data/export/*.csv を読む薄いヘルパー。
「DB→毎回leak-free再計算(分)」を「CSV→数秒」に置き換え、仮説検証(verify-first)を高速化する。
全特徴(補正T h7_fig/末脚 spurt/血統 blood/33 lap33/騎手厩舎/位置/消去 elim_n/combo/vh2_score)は
既にleak-free(shift(1)厳守)で計算済み＝各スクリプトが再実装しないので**パリティずれも消える**。

⚠ 用途はオフライン研究・バックテスト専用(CSVは凍結DBのスナップショット・data/export/はgitignore)。
   ライブ推論には使わない(当日レースはアプリがスクレイプ+履歴からその場で計算)。
   CSV再生成: python scripts/export_features_csv.py (約6分)。53列に無い新特徴は再エクスポートが要る。

標準分割(このプロジェクトの慣例):
  train  = day<=2024年 (≤20241231)
  holdout= 2025年 (2025)
  recent = 直近3ヶ月 (>=20260321・DB凍結上限2026-06-21まで)
  (2026-01〜03-20は 'other'。必要なbacktestだけ拾う)
"""
import os
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HORSE_CSV = os.path.join(ROOT, 'data', 'export', 'horse_races.csv')
RACE_CSV = os.path.join(ROOT, 'data', 'export', 'races.csv')

RECENT_FROM = 20260321
HOLDOUT_YEAR = 2025
TRAIN_END = 2024


def available():
    return os.path.exists(HORSE_CSV) and os.path.exists(RACE_CSV)


def _assert_csv(path):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} が無い。先に `python scripts/export_features_csv.py` でCSVを生成(約6分)。")


def add_period(df, day_col='day'):
    """day(YYYYMMDD int)から period 列(train/holdout/recent/other)を付与して返す。"""
    d = pd.to_numeric(df[day_col], errors='coerce')
    yr = (d // 10000)
    period = pd.Series('other', index=df.index, dtype=object)
    period[yr <= TRAIN_END] = 'train'
    period[yr == HOLDOUT_YEAR] = 'holdout'
    period[d >= RECENT_FROM] = 'recent'
    df = df.copy()
    df['period'] = period
    return df


def load_horses(pop_min=None, pop_max=None, cols=None, with_period=True):
    """馬行CSV(251,629行×53列)を読む。
    pop_min/pop_max: ninkiで絞る(例 pop_min=7=7番人気以下)。ninki欠損/0は除外。
    cols: 読む列を絞ると高速(例 ['race_key','day','ninki','combo','top3'])。
    with_period: period列を付与。
    """
    _assert_csv(HORSE_CSV)
    if cols is not None:
        need = set(cols) | {'ninki', 'day'}
        df = pd.read_csv(HORSE_CSV, usecols=lambda c: c in need)
    else:
        df = pd.read_csv(HORSE_CSV)
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df = df[df['ninki'].notna() & (df['ninki'] > 0)]
    if pop_min is not None:
        df = df[df['ninki'] >= pop_min]
    if pop_max is not None:
        df = df[df['ninki'] <= pop_max]
    if with_period:
        df = add_period(df)
    return df.reset_index(drop=True)


def load_races(cols=None, with_period=True):
    """レース行CSV(18,243行×82列: オッズ構造/実力拮抗度/combo穴馬数/荒れラベル等)を読む。"""
    _assert_csv(RACE_CSV)
    df = pd.read_csv(RACE_CSV, usecols=cols) if cols else pd.read_csv(RACE_CSV)
    if with_period and 'day' in df.columns:
        df = add_period(df)
    return df.reset_index(drop=True)


def base_top3_by_ninki(df):
    """人気別ベース3着内率 {ninki:rate}。残差検証(人気統制)の基準に使う。"""
    g = df.groupby(df['ninki'].astype(int))['top3'].mean()
    return g.to_dict()


def resid_z(sub, base_map, target='top3'):
    """サブ集合の残差(人気統制)と z を返す (rate, expected, z, n)。"""
    n = len(sub)
    if n < 20:
        return None
    rate = sub[target].mean()
    exp = sub['ninki'].astype(int).map(base_map).mean()
    se = (0.15 * 0.85 / n) ** 0.5
    return rate, exp, (rate - exp) / se if se else 0.0, n
