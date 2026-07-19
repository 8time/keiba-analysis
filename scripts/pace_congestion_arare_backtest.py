# -*- coding: utf-8 -*-
"""『テン3F(前半スピード)混雑→展開崩壊→荒れ』は既存オッズ荒れモデルを超えて効くか?

ロジック置き場「レース予測難易度高精度化(前半のみ)」の検証。
仮説: 前傾/先行馬が多い(テン速上位が多い)レースはペースが速く崩壊し荒れやすい。

前傾混雑度は既に export_features_csv がレース単位で算出済み(leak-free・過去走脚質ベース):
  n_front  = avg_pos3<=3 の頭数(先行勢)
  n_hana   = pos_ratio3<=0.20 の頭数(逃げ勢)
  mean_posr= フィールド平均position ratio(低=前傾フィールド)
  front_ratio = n_front / field_size(頭数正規化)

検証(リーク無し・"オッズを超えるか"を厳密化):
  ベース = 凍結ロジット arare_prob(オッズ12特徴・data/scanner_arare_logit.json)の予測。
  残差 = 実荒れ(arareA) − 予測。オッズが説明する分を差し引き。
  train(period)で各混雑度の三分位しきい値を凍結、holdout/2025で
  「高混雑群の残差 − 低混雑群の残差」= D と z。
  仮説が正なら D>0・z>=2 一貫(オッズが取りこぼす荒れを混雑度が拾う)。
  z≈0なら「テン混雑もオッズ(市場)に織込み済み」= verified_arare_field_pricedin と同型。

使い方: python scripts/pace_congestion_arare_backtest.py
"""
import os
import sys
import json
import math
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd

LOGIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'data', 'scanner_arare_logit.json')


def load_logit():
    with open(LOGIT, encoding='utf-8') as f:
        return json.load(f)


def main():
    lg = load_logit()
    feats = lg['features']
    mu, sd, coef = lg['mu'], lg['sd'], lg['coef']
    icpt = float(lg['intercept'])
    print(f"凍結ロジット特徴({len(feats)}): {feats}")
    print(f"  holdout(既報): {lg.get('holdout_metrics')}\n")

    print("races.csv 読み込み...")
    need = list(feats) + ['n_front', 'n_hana', 'mean_posr', 'field_size',
                          'arareA', 'day']
    df = cd.load_races(cols=need)
    df = df[df['arareA'].notna()]
    for c in feats + ['n_front', 'n_hana', 'mean_posr', 'field_size']:
        df = df[df[c].notna()]
    print(f"  {len(df):,}レース\n")

    def logit_pred(row):
        z = icpt
        for f in feats:
            sdi = sd[f] if sd[f] else 1.0
            z += coef[f] * ((float(row[f]) - mu[f]) / sdi)
        try:
            return 1.0 / (1.0 + math.exp(-z))
        except OverflowError:
            return 0.0 if z < 0 else 1.0

    # サンプル化: (period, residual, n_front, n_hana, mean_posr, front_ratio)
    samples = []
    for row in df.itertuples(index=False):
        d = row._asdict()
        pred = logit_pred(d)
        resid = float(d['arareA']) - pred
        fs = float(d['field_size']) or 1.0
        samples.append((d['period'], resid, float(d['n_front']),
                        float(d['n_hana']), float(d['mean_posr']),
                        float(d['n_front']) / fs))

    # train凍結: 各混雑度の三分位
    tr = [s for s in samples if s[0] == 'train']
    print(f"  train {len(tr):,} / holdout {sum(1 for s in samples if s[0]=='holdout'):,}"
          f" / other {sum(1 for s in samples if s[0]=='other'):,}")
    print(f"  train平均残差(≈0なら校正OK): {sum(s[1] for s in tr)/len(tr):+.4f}\n")

    FEAT_IDX = {'n_front(先行数)': 2, 'n_hana(逃げ数)': 3,
                'mean_posr(平均位置・低=前傾)': 4, 'front_ratio(先行率)': 5}

    def terciles(idx):
        vals = sorted(s[idx] for s in tr)
        return vals[len(vals) // 3], vals[2 * len(vals) // 3]

    def analyze(period, fname, idx, invert=False):
        q1, q2 = terciles(idx)
        cell = defaultdict(lambda: [0.0, 0, 0.0])  # grp -> [sum_resid, n, sumsq]
        for s in samples:
            if s[0] != period:
                continue
            v = s[idx]
            grp = 'lo' if v < q1 else ('hi' if v > q2 else 'mid')
            if invert:  # mean_posr は 低い=前傾混雑 なので高低を反転
                grp = {'lo': 'hi', 'hi': 'lo', 'mid': 'mid'}[grp]
            c = cell[grp]
            c[0] += s[1]; c[1] += 1; c[2] += s[1] * s[1]

        def stat(g):
            s0, n, ss = cell[g]
            if n == 0:
                return 0.0, 0, 0.0
            m = s0 / n
            var = max(1e-9, ss / n - m * m)
            return m, n, var
        mh, nh, vh = stat('hi')
        ml, nl, vl = stat('lo')
        if nh >= 30 and nl >= 30:
            d = mh - ml
            se = math.sqrt(vh / nh + vl / nl)
            z = d / se if se else 0.0
            print(f"    {fname:<26} 混雑↑残差={mh:+.4f}(n{nh}) 混雑↓残差={ml:+.4f}(n{nl}) "
                  f"→ D={d:+.4f} z={z:+.2f}")

    for period in ('holdout', 'other'):
        print(f"  === {period} (残差=実荒れ−オッズ予測) ===")
        for fname, idx in FEAT_IDX.items():
            analyze(period, fname, idx, invert=(idx == 4))
        print()

    print("読み方: 『混雑↑群の残差 − 混雑↓群の残差』= D。")
    print("  D>0でz>=2が両期間一貫 → テン混雑はオッズが取りこぼす荒れを拾う=採用価値。")
    print("  z≈0 → テン混雑もオッズに織込み済み(priced-in)。")


if __name__ == '__main__':
    main()
