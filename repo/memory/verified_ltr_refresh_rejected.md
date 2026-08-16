---
name: verified_ltr_refresh_rejected
description: LTRの学習窓を1年前進(train≤2024/val2025)しても2026で改善せず→現行維持。LTRの対人気優位は2026で+0.22ppまで薄まっている
metadata: 
  node_type: memory
  type: project
  originSessionId: 423e3727-3223-4cca-9421-07a73ee06686
  modified: 2026-07-21T23:37:24.545Z
---

「モデル鮮度更新」の検証(2026-07-22・scripts/refresh_ltr_model.py)。**現行維持が結論**。data/ltr_model.lgb は触っていない。

**なぜ"再学習"がそもそも意味を持つか**: jravan.dbは2026-06-21まであるのに、現行LTRは train≤2023 / val2024 / test2025+ で、**2024年の1年分が学習に使われていない**。ただし窓を前進させると2025年がクリーンなholdoutでなくなる＝再検証可能性を1年失う。この取引が割に合うかの判定。

**比較の設計(ここが肝)**: 現行(train≤2023/val2024)と候補(train≤2024/val2025)は**どちらも2026年を見ていない**ので、2026年(1-6月・1,804レース)だけが公平な土俵。2025年で比べてはいけない(候補にとってvalで、現行にとってのみ未知＝不公平)。

**結果(2026年 1,804レース)**:
| モデル | 勝ち馬recall@7 | 3着内recall@7 |
|---|---|---|
| 人気順(ベースライン) | 0.9191 | 0.8677 |
| 現行 train≤2023 | 0.9213 | 0.8695 |
| 候補 train≤2024 | 0.9224 | 0.8691 |

差分は 勝ち馬+0.11pp / 3着内-0.04pp と**符号が割れており誤差**。holdoutを1年失う対価に見合わない → 昇格せず。所要4.6分(パイプライン再構築込み)なので、DBが1年分伸びたら再実行して再判定するのが安い。

**副産物(重要)**: 2026年におけるLTRの人気順に対する優位は **勝ち馬+0.22pp / 3着内+0.18pp** しかない。ltr_meta.jsonの記録値(2025+で+0.81pp)より大幅に薄い。**LTRの上積みは年々効かなくなっている可能性**がある。[[project_kyoteki_score_rebuild]]のrecall@7目標を再定義するときの前提として持っておく。

**vh2は再学習不要**: data/vh2_model.lgb はライブでは使われておらず(消費者は scripts/export_features_csv.py のみ=オフライン研究用のCSV列)、ライブの妙味スコアは core/value_hunter.py→data/value_hunter_light.json で既に fit≤2024 と新しい。しかも[[verified_elim_ml_ranking_rejected]]でvh2のin-sample歪みは実害無しと判明済み。よって再学習の価値はほぼゼロ。

**How to apply**: 「モデルが古いから鮮度更新しよう」は、必ず「両モデルが見ていない年」で比較すること。窓前進は holdout を食う取引であり、差分が誤差なら現行維持が正解。候補は data/ltr_model_candidate.lgb + ltr_meta_candidate.json に残してある(昇格は `--promote`・自動では上書きしない)。
