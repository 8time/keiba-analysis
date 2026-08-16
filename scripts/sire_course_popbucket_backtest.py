# -*- coding: utf-8 -*-
"""人気薄×父×コース条件に妙味はあるか（新潟直線1000mの観察を一般化して検証）。

きっかけ: 2026-08-02 アイビスSD(新潟芝1000m直線)で
  4番カウスリップ(10番人気)・11番ロードトレイル(14番人気)が2-3着。
  両馬とも父ロードカナロア＝「人気薄でも父が合えば来るのでは」という仮説。

⚠多重検定の罠: 種牡馬×コースの組合せは膨大で、闇雲に探すと必ず"効く"組合せが出る。
  過去に db-keiba の騎手条件で同じ罠にはまっている(集計期間だけz+8.9→両out-of-sample窓で符号反転)。
  そこで本スクリプトは
    ① 学習窓(〜2023)で候補を選び、②検証窓(2024-2026)で追試する
    ③ 候補数で補正した閾値(Bonferroni的)を使う
  という手順を踏み、"後から見つけた"組合せを採用しない。

Usage:
  python scripts/sire_course_popbucket_backtest.py                 # 新潟千直
  python scripts/sire_course_popbucket_backtest.py --all-sprint    # 芝1200m以下の全場
"""
import os
import sys
import io
import math
import argparse
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from core import jockey_jv as jj

POP_MIN = 6          # 「人気薄」の定義(6番人気以下)
MIN_N_TRAIN = 60     # 候補に上げる最低頭数
MIN_N_TEST = 25


def load(where):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    df = pd.read_sql(f"""
        SELECT r.race_key, r.umaban, r.chakujun, r.ninki, r.win_odds,
               h.sire, ra.year, ra.jyo, ra.kyori, ra.surface
        FROM results r
        JOIN races ra ON r.race_key = ra.race_key
        LEFT JOIN horses h ON r.ketto_num = h.ketto_num
        WHERE r.chakujun > 0 AND r.ninki > 0 AND r.win_odds > 0 AND {where}
    """, con)
    con.close()
    df['sire'] = df['sire'].fillna('').str.strip()
    return df[df['sire'] != '']


def resid(sub, exp_col='exp'):
    n = len(sub)
    if n == 0:
        return None
    act = (sub['chakujun'] <= 3).mean()
    exp = sub[exp_col].mean()
    r = (act - exp) * 100
    se = math.sqrt(max(exp * (1 - exp), 1e-9) / n) * 100
    roi = sub.loc[sub['chakujun'] == 1, 'win_odds'].sum() / n * 100
    return {'n': n, 'act': act * 100, 'r': r, 'z': r / se if se else 0, 'roi': roi}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all-sprint', action='store_true',
                    help='新潟千直でなく芝1200m以下の全場で見る')
    args = ap.parse_args()

    if args.all_sprint:
        where = "ra.surface LIKE '芝%' AND ra.kyori <= 1200"
        title = '芝1200m以下(全場)'
    else:
        where = "ra.jyo='04' AND ra.surface LIKE '芝%' AND ra.kyori=1000"
        title = '新潟 芝1000m(直線)'

    print(f'条件: {title}', file=sys.stderr)
    df = load(where)
    # オッズ帯で期待複勝率(人気/オッズ水準の効果を抜く)
    df['ob'] = pd.qcut(df['win_odds'], 20, labels=False, duplicates='drop')
    df['exp'] = df['ob'].map(df.groupby('ob')['chakujun'].apply(lambda s: (s <= 3).mean()))

    yi = df['year'].astype(int)
    tr = df[(yi <= 2023) & (df['ninki'] >= POP_MIN)]
    te = df[(yi >= 2024) & (df['ninki'] >= POP_MIN)]
    print(f'{title} 人気{POP_MIN}番以下: train(〜2023) {len(tr):,}頭 / test(2024-) {len(te):,}頭\n')

    # ── まずユーザー観察の当事者を名指しで見る ──
    print('■ 名指し確認: ロードカナロア産駒(人気薄)')
    for lbl, sub in (('train(〜2023)', tr), ('test(2024-)', te)):
        s = resid(sub[sub['sire'].str.contains('ロードカナロア', na=False)])
        if s:
            print(f'  {lbl}: n={s["n"]:>4}  複勝率{s["act"]:>5.1f}%  残差{s["r"]:>+6.2f}pp '
                  f'z={s["z"]:>+5.2f}  単ROI{s["roi"]:>5.0f}%')
        else:
            print(f'  {lbl}: 該当なし')

    # ── 総当たりで候補を出す(多重検定を意識) ──
    print('\n■ 全種牡馬を総当たり（trainで候補→testで追試）')
    cand = []
    for sire, g in tr.groupby('sire'):
        if len(g) < MIN_N_TRAIN:
            continue
        s = resid(g)
        if s and s['z'] >= 2.0:
            cand.append((sire, s))
    n_tested = tr['sire'].value_counts()
    n_tested = int((n_tested >= MIN_N_TRAIN).sum())
    # 候補数で補正した閾値(両側5%をBonferroniで割る)
    thr = 2.0 if n_tested <= 1 else abs(round(
        __import__('statistics').NormalDist().inv_cdf(1 - 0.025 / max(n_tested, 1)), 2))
    print(f'  検定した種牡馬: {n_tested}件 → 多重検定補正後の必要z = {thr:.2f}')
    print(f'  trainでz≥2.0だった候補: {len(cand)}件\n')

    if not cand:
        print('  候補なし。人気薄×父に効く組合せは見つかりませんでした。')
    else:
        print(f'{"種牡馬":22s}{"train n":>8}{"残差":>8}{"z":>7} │{"test n":>7}{"残差":>8}{"z":>7}{"ROI":>7}  判定')
        print('-' * 88)
        survived = []
        for sire, s in sorted(cand, key=lambda x: -x[1]['z']):
            t = resid(te[te['sire'] == sire])
            if not t or t['n'] < MIN_N_TEST:
                print(f'{sire[:20]:22s}{s["n"]:>8}{s["r"]:>+8.2f}{s["z"]:>7.2f} │{"標本不足":>7}')
                continue
            ok = t['z'] >= 2.0 and s['z'] >= thr
            keep = t['r'] > 0 and s['z'] >= thr
            v = '★追試も合格' if ok else ('△testは弱い' if t['r'] > 0 else '✗testで消滅')
            if ok:
                survived.append(sire)
            print(f'{sire[:20]:22s}{s["n"]:>8}{s["r"]:>+8.2f}{s["z"]:>7.2f} │'
                  f'{t["n"]:>7}{t["r"]:>+8.2f}{t["z"]:>7.2f}{t["roi"]:>6.0f}%  {v}')
        print(f'\n  両窓を通過: {survived if survived else "なし"}')

    print('\n※単勝ROIが100%未満なら「買い」でなく相手選びの情報。'
          '\n※候補は必ずtrainで選びtestで追試する。後から目についた組合せを採用しないこと。')


if __name__ == '__main__':
    main()
