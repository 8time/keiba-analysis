# -*- coding: utf-8 -*-
"""危険人気馬の材料を1つずつ大規模再検証する。

背景(ユーザー指摘): 危険人気馬に出た馬がけっこう入着している。
現行 core/danger_gate.py は「軸から完全には外さない」設計で、その根拠が
コメント上「66R台帳で警告あり軸77.5%的中」＝標本が小さすぎる。
数万レース規模で材料ごとの実力を測り直し、効いていない材料を落とす。

測り方:
  ・対象は1〜3番人気(＝現行gateの適用範囲)のみ。
  ・単なる複勝率比較では人気の差で歪むので、**オッズ20分位で統制した残差**で見る。
    (同じオッズ帯の平均複勝率を期待値とし、実測との差をppで出す)
  ・train(〜2024) と holdout(2025+) の両方で符号と有意性が揃うものだけ本物とみなす。
  ・材料が「単独で軸を外せる強さ」か「注意止まり」かを、絶対複勝率でも併記する。

Usage:
  python scripts/danger_fav_audit.py
"""
import os
import sys
import io
import math
import sqlite3
from datetime import datetime
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from core import jockey_jv as jj

FADE_MONTHS = {12, 1, 2, 3, 4, 5}      # danger_gate._FADE_MONTHS 相当(牝×冬春)


def load():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    df = pd.read_sql("""
        SELECT r.race_key, r.ketto_num, r.umaban, r.chakujun, r.ninki, r.win_odds,
               r.sex, r.age, r.futan, r.bataiju, r.kyakushitsu,
               ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori,
               ra.baba_shiba, ra.baba_dirt
        FROM results r JOIN races ra ON r.race_key = ra.race_key
        WHERE CAST(ra.year AS INTEGER) >= 2016
          AND r.chakujun > 0 AND r.ninki > 0 AND r.win_odds > 0
    """, con)
    con.close()
    return df


def add_prev(df):
    """前走の着順・脚質・出走間隔を自己結合で付ける(すべてレース前に判る情報)。"""
    df['day'] = df['year'].astype(str) + df['monthday'].astype(str).str.zfill(4)
    df = df.sort_values(['ketto_num', 'day'])
    g = df.groupby('ketto_num', sort=False)
    df['prev_chaku'] = g['chakujun'].shift(1)
    df['prev_kyaku'] = g['kyakushitsu'].shift(1)
    prev_day = g['day'].shift(1)

    def _gap(a, b):
        try:
            return (datetime.strptime(b, '%Y%m%d') - datetime.strptime(a, '%Y%m%d')).days
        except Exception:
            return np.nan
    df['gap'] = [_gap(a, b) if isinstance(a, str) else np.nan
                 for a, b in zip(prev_day, df['day'])]
    return df


def add_flags(df):
    surf = df['surface'].astype(str)
    is_turf = surf.str.contains('芝')
    baba = np.where(is_turf, df['baba_shiba'].astype(str), df['baba_dirt'].astype(str))
    # JRA-VAN馬場コード: 1良 2稍 3重 4不良
    df['wet'] = pd.Series(baba, index=df.index).isin(['3', '4'])
    df['bad'] = pd.Series(baba, index=df.index).isin(['4'])
    df['month'] = df['monthday'].astype(str).str.zfill(4).str[:2].astype(int)

    f = {}
    f['🌧️重不良×1番人気'] = (df['ninki'] == 1) & (
        (is_turf & df['wet']) | (~is_turf & df['bad']))
    f['牝×冬春fade'] = (df['sex'].astype(str) == '2') & df['month'].isin(FADE_MONTHS)
    _kr = pd.to_numeric(df['futan'], errors='coerce') / pd.to_numeric(
        df['bataiju'], errors='coerce').replace(0, np.nan)
    f['斤量比≥12.6%'] = _kr >= 0.126
    f['半年休み明け'] = df['gap'] >= 180
    f['中9週+ローテ'] = (df['gap'] >= 63) & (df['gap'] < 180)
    f['前走逃げ'] = df['prev_kyaku'].astype(str) == '1'
    f['前走5着以下'] = pd.to_numeric(df['prev_chaku'], errors='coerce') >= 5
    for k, v in f.items():
        df[k] = v.fillna(False)
    return df, list(f.keys())


def residual(sub, exp_col='exp'):
    n = len(sub)
    if n < 100:
        return None
    act = (sub['chakujun'] <= 3).mean()
    exp = sub[exp_col].mean()
    r = (act - exp) * 100
    se = math.sqrt(max(exp * (1 - exp), 1e-9) / n) * 100
    return {'n': n, 'act': act * 100, 'resid': r, 'z': r / se if se else 0}


def main():
    print('読込中...', file=sys.stderr)
    df = load()
    df = add_prev(df)
    df, flags = add_flags(df)

    fav = df[(df['ninki'] >= 1) & (df['ninki'] <= 3)].copy()
    # オッズ20分位で期待複勝率を作る(人気だけでは同じ1番人気の1.2倍と4.0倍が混ざる)
    fav['ob'] = pd.qcut(fav['win_odds'], 20, labels=False, duplicates='drop')
    exp_map = fav.groupby('ob')['chakujun'].apply(lambda s: (s <= 3).mean())
    fav['exp'] = fav['ob'].map(exp_map)

    yi = fav['year'].astype(int)
    tr, ho = fav[yi <= 2024], fav[yi >= 2025]
    print(f'1-3番人気: train {len(tr):,} / holdout {len(ho):,}\n')
    print('■ 材料ごとの複勝残差（オッズ統制・マイナスほど危険）')
    print(f'{"材料":18s}{"train n":>9}{"残差":>8}{"z":>7} │{"holdout n":>10}{"残差":>8}{"z":>7}'
          f' │{"絶対複勝率":>9}  判定')
    print('-' * 92)
    verdict = {}
    for k in flags:
        a, b = residual(tr[tr[k]]), residual(ho[ho[k]])
        if not a or not b:
            print(f'{k:18s}{"標本不足":>9}')
            continue
        both = (a['z'] <= -2 and b['z'] <= -2)
        weak = (a['z'] <= -2) != (b['z'] <= -2)
        v = '★両窓で有効' if both else ('△片窓のみ' if weak else '✗効果なし')
        verdict[k] = (v, a, b)
        print(f'{k:18s}{a["n"]:>9,}{a["resid"]:>+8.2f}{a["z"]:>7.1f} │'
              f'{b["n"]:>10,}{b["resid"]:>+8.2f}{b["z"]:>7.1f} │'
              f'{b["act"]:>8.1f}%  {v}')

    print('\n■ 材料の重複数と複勝率（現行gateはsev>=2で「押さえ推奨」）')
    hard = [k for k in flags if verdict.get(k, ('',))[0] == '★両窓で有効']
    print(f'  両窓で有効だった材料: {hard if hard else "なし"}')
    if hard:
        ho2 = ho.copy()
        ho2['cnt'] = ho2[hard].sum(axis=1)
        print(f'\n{"重複数":>6}{"n":>9}{"複勝率":>9}{"残差":>9}')
        print('-' * 34)
        for c in sorted(ho2['cnt'].unique()):
            s = ho2[ho2['cnt'] == c]
            r = residual(s)
            if r:
                print(f'{int(c):>6}{r["n"]:>9,}{r["act"]:>8.1f}%{r["resid"]:>+9.2f}')
    print('\n※絶対複勝率が高い材料は「当たっても軸を外すと損」＝注意止まりが妥当。')


if __name__ == '__main__':
    main()
