---
name: verified-arare-entropy
description: オッズ本命不在フラグ(コンピ大穴の等価再現)検証済み。2ティアとも2025/2026 holdout有意・ハンデ/16頭と独立。レース選択器(ROIエッジではない)
metadata: 
  node_type: memory
  type: project
  originSessionId: 2e1ab573-9c8a-4994-96f3-d38f0566d06f
---

## オッズ本命不在フラグ(大谷式コンピ大穴の等価再現) — 検証済み・採用

scripts/arare_entropy_backtest.py。train 2021-2024(13,498R)で閾値凍結→2025 holdout→2026確認。
荒れ定義=3着以内にオッズ順6位以下が混入。JRA(jyo 01-10)のみ。

| ティア | 閾値 | 2025 | 独立層(非ハンデ×10-15頭) | 2026 |
|---|---|---|---|---|
| ⚠荒れ寄り | fav1≥2.5 & odds3/odds1≤3.0 & live30≥8 | +18.7pp z10.9 (n=1203) | +17.6pp z6.5 | z8.0 |
| ●大穴(大谷等価) | fav1≥3.0 & odds3/odds1≤2.0 & live30≥10 | 荒れ83.4% +19.2pp z5.5 (n=199) | +22.5pp z3.5 | z5.2 |

- [[verified_arare_conditions]]のハンデ/16頭フラグと**独立**(層内でも有意)＝3本目の荒れ条件
- **限定**: オッズ由来なのでROIエッジ主張はしない。用途=穴相手戦略(末脚top3×人気薄/trio_lean②型)の適用先を選ぶレース選択器
- 配線先: core/value_scanner.py に no_favorite_flag() 追加→🔍Scanner荒れ予報(実装カード=fable_research_plan.md カード-1)
- NARは未検証(適用しない)

## jravan.db スキーマ実査の重要事実(2026-07-02)
- **馬主(banushi)列は無い**→馬主特徴はJV-Link UMマスタ再取込が前提
- **oddsテーブル(77M行)は確定スナップショットのみ・時刻列無し**→オッズ時系列検証は前向き収集が必要
- race_num列あり→当日前半/後半の日内分割検証は可能

**Why:** コンピ指数を買わずに大谷式大穴判定を単勝オッズから完全再現できると実証。荒れ予報の3本目の独立フラグ。

**How to apply:** Fableブリーフ運用の成功パターン=「設計だけでなくその場でholdout実走して決着させる」。閾値グリッドはtrainで選択→凍結→holdoutの順を厳守。
