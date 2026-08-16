# -*- coding: utf-8 -*-
"""『補正Tトップ3 ∩ 人気トップ3』の重複数は"見送るレース"を当てられるか。

【結論(2026-07-23)】荒れ予測としては priced-in。ただし**軸信頼度の表示としては有効**。

  重複数別(holdout2025 / recent2026)
    重複0(13%) 荒れ61.4%/56.1%  本線25.5%/27.1%  1番人気複勝 55.2%/65.4%
    重複1(43%) 荒れ53.6%/48.8%  本線28.6%/27.4%  1番人気複勝 61.9%/63.9%
    重複2(38%) 荒れ45.2%/47.0%  本線35.5%/37.0%  1番人気複勝 68.4%/66.6%
    重複3( 6%) 荒れ41.3%/43.1%  本線43.9%/55.2%  1番人気複勝 74.1%/81.0%

  ① 荒れ予測としては**不採用**。オッズ予測との残差は holdout で +1.74/+1.84/-0.46/-0.32pp、
     recent で -1.21/-2.90/+0.04/-0.16pp と**単調でも有意でもない**(|z|<2)。
     つまり「重複が少ない=荒れる」はオッズが既に言っている([[verified_arare_field_pricedin]]
     の実力スプレッド系AUCゲイン≈0と同じ結論。トップ3重複という鋭い形でも超えない)。
  ② ただし**生の値は強く単調**で、1番人気の複勝率が 55%→62%→68%→74%(holdout)、
     65%→64%→67%→81%(recent)。本線決着率も 25%→29%→36%→44%(holdout)。
     **軸が信頼できるかの目安としては実用的**(オッズを超えないだけで、外れてもいない)。
  ③ 「重複≦1を見送る」運用は**見送り率55-58%と切りすぎ**。半分以上を捨てて
     荒れ率が55%→45%に下がるだけで、費用対効果が悪い。使うなら重複3(全体の6%)を
     「軸が特に信頼できるレース」として拾う方向。

  → 実装するなら**荒れ予報の特徴には足さない**(priced-in)。
    「軸の信頼度」表示としてなら価値がある。ユーザーの『見送りに使う』発案は
    方向としては正しいが、閾値を≦1に置くと切りすぎになる。


きっかけ: ユーザー提示の動画(地方競馬・佐賀)の手法
  「①同距離の過去5走ベストタイム上位3頭を書き出す ②その3頭が1〜3番人気以内に
   入っているか確認 ③揃っていれば"サービスレース"=狙うべきレース」
これは当アプリの補正T(CorrectedT)と同発想だが、動画は**馬選び**でなく
**レース選別**に使っている点が新しい。ユーザーの発案で「逆転の発想＝重複が
少ないレースを"見送る"のに使えないか」を検証する。

仮説: 実力(タイム)上位と市場(人気)上位が食い違うレース = 予測困難 = 見送るべき。

⚠ 検証の肝 ―― 既存の荒れ予報を超えるか:
  荒れ予報ロジット(オッズ12特徴・AUC0.690)が既に荒れを予測できている。
  よって「重複数が少ないと荒れる」だけでは無意味(オッズが既にそう言っている)。
  **凍結ロジットの予測を引いた残差**で測り、オッズを超える上乗せがあるかを見る。
  ([[verified_arare_field_pricedin]]で実力スプレッド系はAUCゲイン≈0と既に判明しており、
   本検証はその「トップ3重複数」という鋭い形での再挑戦にあたる)

測る対象(見送り判断に直結するもの):
  ① arareA   荒れ(3着内に7番人気以下が1頭以上) … 残差で測る
  ② honsen   本線決着(1・2番人気が両方3着内)   … 軸が素直に決まるか
  ③ fav_t3   1番人気の複勝率                    … 軸の信頼度そのもの

窓: train(≤2024) / holdout(2025) / recent(2026-03-21〜)。両窓一貫のみ採用。

Usage: python scripts/time_pop_overlap_backtest.py
"""
import os
import sys
import json
import math
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGIT = os.path.join(ROOT, 'data', 'scanner_arare_logit.json')


def build_overlap():
    """レースごとに『補正Tトップ3 ∩ 人気トップ3』の重複数(0-3)を作る。"""
    print('馬行CSV読み込み...', file=sys.stderr)
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'h7_rank',
                             'h7_fig', 'chakujun', 'top3'])
    h['umaban'] = pd.to_numeric(h['umaban'], errors='coerce')
    h['h7_rank'] = pd.to_numeric(h['h7_rank'], errors='coerce')
    h = h[h['umaban'].notna()]

    # 補正Tを持つ馬だけでレース内順位を取り直す(h7_rankはna_option='bottom'で
    # 図の無い馬にも順位が付くため、そのままtop3を取ると図無し馬が混じる)
    hh = h[h['h7_fig'].notna()].copy()
    hh['t_rank'] = hh.groupby('race_key')['h7_fig'].rank(method='min')

    rows = []
    for rk, g in hh.groupby('race_key', sort=False):
        t3 = set(g.loc[g['t_rank'] <= 3, 'umaban'])
        if len(t3) < 3:
            continue                       # 補正T持ちが3頭未満のレースは判定不能
        rows.append((rk, t3))
    tmap = dict(rows)

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        t3 = tmap.get(rk)
        if not t3:
            continue
        p3 = set(g.loc[pd.to_numeric(g['ninki'], errors='coerce') <= 3, 'umaban'])
        if len(p3) < 3:
            continue
        fav = g[pd.to_numeric(g['ninki'], errors='coerce') == 1]
        out.append({
            'race_key': int(rk),
            'overlap': len(t3 & p3),
            'n_cov': int(g['h7_fig'].notna().sum()),
            'field': len(g),
            'fav_t3': int(fav['top3'].iloc[0]) if len(fav) else None,
        })
    df = pd.DataFrame(out)
    print(f'  判定できたレース {len(df):,}', file=sys.stderr)
    return df


def logit_pred(row, lg):
    z = float(lg['intercept'])
    for f in lg['features']:
        sd = lg['sd'][f] or 1.0
        z += lg['coef'][f] * ((float(row[f]) - lg['mu'][f]) / sd)
    try:
        return 1.0 / (1.0 + math.exp(-z))
    except OverflowError:
        return 0.0 if z < 0 else 1.0


def main():
    with open(LOGIT, encoding='utf-8') as f:
        lg = json.load(f)
    ov = build_overlap()

    need = list(dict.fromkeys(list(lg['features'])
                              + ['race_key', 'day', 'arareA', 'honsen',
                                 'ninki_top3_logsum']))
    r = cd.load_races(cols=need)
    for c in lg['features'] + ['arareA', 'honsen']:
        r = r[r[c].notna()]
    df = r.merge(ov, on='race_key', how='inner')
    df['pred'] = [logit_pred(row, lg) for _, row in df.iterrows()]
    df['resid'] = df['arareA'].astype(float) - df['pred']
    print(f'\n結合後 {len(df):,}レース / 補正T被覆率 '
          f'{(df["n_cov"] / df["field"]).mean():.0%}')

    print('\n' + '=' * 88)
    print('『補正Tトップ3 ∩ 人気トップ3』の重複数 別')
    print('=' * 88)
    for period in ('train', 'holdout', 'recent'):
        d = df[df['period'] == period]
        if len(d) < 200:
            continue
        print(f'\n--- {period}  {len(d):,}レース ---')
        hdr = ('重複'.rjust(4) + 'レース数'.rjust(9) + '割合'.rjust(7)
               + '荒れ率'.rjust(8) + 'オッズ予測'.rjust(10) + '残差'.rjust(10)
               + 'z'.rjust(8) + '本線決着'.rjust(9) + '1番人気複勝'.rjust(11))
        print(hdr)
        for k in (0, 1, 2, 3):
            s = d[d['overlap'] == k]
            if len(s) < 30:
                print(f'{k:>4d} {len(s):>8,}  n<30')
                continue
            res = s['resid'].mean()
            se = s['resid'].std(ddof=1) / math.sqrt(len(s))
            z = res / se if se else 0.0
            fav = s['fav_t3'].dropna()
            print(f'{k:>4d} {len(s):>8,} {len(s) / len(d):>5.0%} '
                  f'{s["arareA"].mean():>6.1%} {s["pred"].mean():>7.1%} '
                  f'{res * 100:>+7.2f}pp {z:>+7.2f} {s["honsen"].mean():>7.1%} '
                  f'{fav.mean():>9.1%}')

    # 見送り運用の当たり判定: 重複0-1 を「見送り」にしたら何が起きるか
    print('\n' + '=' * 88)
    print('見送り運用シミュレーション: 重複≦1 を見送った場合')
    print('=' * 88)
    print(f'{"窓":10s} {"見送り率":>8s} {"見送り群の荒れ":>12s} {"残す群の荒れ":>12s} '
          f'{"見送り群 本線":>12s} {"残す群 本線":>12s}')
    for period in ('train', 'holdout', 'recent'):
        d = df[df['period'] == period]
        if len(d) < 200:
            continue
        skip = d[d['overlap'] <= 1]
        keep = d[d['overlap'] >= 2]
        if len(skip) < 30 or len(keep) < 30:
            continue
        print(f'{period:10s} {len(skip) / len(d):>7.0%} '
              f'{skip["arareA"].mean():>11.1%} {keep["arareA"].mean():>11.1%} '
              f'{skip["honsen"].mean():>11.1%} {keep["honsen"].mean():>11.1%}')

    print('\n採用ゲート: 残差が重複数に対して単調 かつ holdout/recent の両窓で |z|>=2。')
    print('※ 残差≈0なら「オッズが既にそう言っている」＝上乗せ無し(priced-in)。')


if __name__ == '__main__':
    main()
