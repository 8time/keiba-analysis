---
name: verified-arare-field-pricedin
description: フィールド実力の拮抗度は荒れ判別で織込み済み(AUCゲイン≈0)。真の改善=オッズエントロピー主軸の透明ロジット(AUC0.62→0.69・p@20%+8pp)。CSV基盤=data/export
metadata: 
  node_type: memory
  type: project
  originSessionId: 64a070b3-be5e-4051-a8b3-047fbb5b0c0c
---

Fable案件②(2026-07-06)。全シグナルをCSV化し「実力拮抗→荒れ」仮説を1年holdout
(2025-06-22〜2026-06-21)で検証した結果。

**Why(結論)**:
- フィールド特徴(補正T/末脚/血統/騎手/vh2のstd・top2差、combo穴数、展開型、市場×実力順位相関)を
  フル投入してもオッズ構造モデルからのAUCゲイン+0.0005〜0.006=ノイズ。**荒れやすさは市場が織込み済み**。
- 方向一貫の残差は3つだけ: ①n_combo2(combo≥2穴馬数)=荒れ寄り(train z+5.5/holdout+2.1)
  ②実力スプレッド大=堅い(holdout z-4級) ③mkt_ability_corr高=堅い(z-3.4/-2.3)。いずれも表示止まり。
- **現行race_value_score(手調整加点式)はAUC0.6243で、オッズ構造だけの透明ロジット12特徴
  (AUC0.6904・p@20% 65.2→73.3%)に大差で負ける**。主係数=odds_entropy+0.90。
  改善の本丸はフィールド特徴でなく「オッズ分布の集約方法」(案件①と同じ構図)。
- 副産物バグ: build_ltr_model.pyのis_handicap=(juryo=='3')は馬齢戦(JVはハンデ=1)。再学習時に修正。

**How to apply**:
- 荒れ予報の配線=data/scanner_arare_logit.json(係数凍結・git -f追跡要)を読むarare_prob()を
  core/value_scanner.pyに新設し、S-Dラベル並びを置換。trio_lean/no_favorite_flagは現行維持。
- フィールド拮抗系の「荒れ買い」提案は再検証不要(打ち切り)。堅い側の表示バッジのみ可。
- CSV基盤: scripts/export_features_csv.py → data/export/horse_races.csv(25万行・全シグナル)/
  races.csv(1.8万レース・82列)。検証は scripts/scanner_arare_v2.py(3秒)。
- ラベル: arareA=3着内に7番人気以下(base50%・[[project-value-horse-hunter]]の母集団と直結)。
  ②型27.9%/本線31.3%は既存condition_arare_backtestと一致確認済み。

関連: [[project-value-scanner]] [[verified-arare-entropy]] [[verified-arare-conditions]]
[[verified-tansho-roi-efficient]](スキャナー=レース選択器の位置づけ)
