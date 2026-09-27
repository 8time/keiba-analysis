---
name: verified_uncertainty_layer_rejected
description: Rank確率の後段較正(Venn-Abers/Beta)・保守EV・予測幅はholdoutで馬券判断を改善せず。検証済み不採用・再検討条件なし。確率を賢くする研究は凍結
metadata:
  node_type: memory
  type: project
---

不確実性レイヤー3点を研究専用で同一holdout比較（2026-09-04・`scripts/uncertainty_layer_verify.py`）。**本番ロジックは未変更**（`core/value_hunter.py` / Rank / 買い目エンジン / JSON いずれも非配線）。成果物=`repo/analysis/uncertainty_layer/`。

設計: 現行エンジン → Rank softmax(`-ability_score`) → 既存買い目、の**後段だけ**を測る。「新しい予想ロジック」ではない。較正fit=2024（LTR val年）。holdout=2025+（2025 / 2026 単独も併記）。採用条件は ECE 等の見た目改善ではなく、ROI / 見送り / 大負けの改善。

**① Calibration → 見た目改善のみ。不採用**

holdout 2025+（67,885頭）:

| 方法 | ECE | Brier | Logloss |
|---|---|---|---|
| 現行 Rank softmax | 0.0083 | 0.0644 | 0.2458 |
| Venn-Abers | 0.0014 | 0.0637 | 0.2398 |
| Beta | 0.0036 | 0.0638 | 0.2409 |
| 市場（参考） | 0.0014 | **0.0565** | **0.2009** |

VAは現行より較正は良い。市場の情報量は超えない。通常EV（`p×オッズ≥1.00`）は ROI 69.9%→68.9%、見送り0%のまま。6人気+でも同型。2026単独は微プラス、2025は悪化、合算悪化。

**② 保守EV（VA下限p）→ 不採用**

点数/R は 9.06→8.44 と少し減る。見送りは増えない。最悪レースは −1500 のまま。ROIは維持ではなく低下。「ROIを維持したまま無駄打ちを減らす」は未達。

**③ 予測幅 → フィルター不能。不採用**

67,885頭中 **67,843頭が幅0〜5%**（平均幅0.0009）。Spearman(幅, |p−y|)=−0.21。幅5%超は42頭だけで、本命寄りの |p−y| が大きいだけ。不確実性フィルターにならない。

**閉じ方（再検討条件なし）**

- 状態: **検証済み・不採用・再検討条件なし**
- 「確率を後処理すれば馬券判断が良くなる」方向は凍結。Venn-Abers / Beta / 保守EV / 予測幅フィルターの再提案・再実装はしない
- 教訓: **確率を数学的に整えることと、馬券で勝てる判断を増やすことは別物**。後処理は市場 Brier/Logloss に届かない
- 残す研究は選択側: Rank=上位の能力評価、VH=市場からズレた穴候補。VH1強調などの情報設計（[[verified_vh_badge_selection]] / `repo/analysis/vh_monthly_analysis/vh_rank_market_residual.md`）

**How to apply**: `core/` に較正も幅も入れない。EV判定を下限pに差し替えない。「較正すればROIが上がるはず」で再開しない。次に掘るなら買い馬の残し方（VH1 / 表示折りたたみ）であり、確率モデルの後段ではない。
