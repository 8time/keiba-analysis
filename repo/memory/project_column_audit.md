---
name: project-column-audit
description: 強適テーブル43列を検証済み台帳と突合し、否定済み6列を既定非表示＋理由明示にした
metadata: 
  node_type: memory
  type: project
  originSessionId: 8193f2c8-eae5-432d-9103-99a37077d415
  modified: 2026-08-06T16:11:14.779Z
---

40件超の検証を経て「何を足すか」ではなく**「何を外すか」**の棚卸しを実施（2026-08-07）。
全文: `repo/column_audit_2026-08.md`

## 🔴 撤去候補6列（既定非表示にした）
| 列 | 否定の根拠 |
|---|---|
| PCILabel / AvgPCI / PCIType | [[verified_pci_pricedin]] **PCI完全終了**。n=162,353で残差-0.5pp・交互作用z0.20・再提案打ち切り |
| DensityScore / DensityPenaltyLabel | [[verified_pace_congestion_weak]] 実タイムで再挑戦しても超えず決着(31,849R)・再提案しない |
| TrainingEval | 調教は**時計/矢印/仕上りの3方向すべてゼロ** ([[verified_training_and_sire_popbucket]] [[verified_jrdb_kyi_fields]] [[verified_jrdb_cyb_training]]) |

## 実装方針: 消さずに「消し候補」と分かるようにした
app.py の `_DEPRECATED_COLS`（列名→否定理由の辞書）で管理。
1. `_canonical_default` から除外＝**「デフォルト」ボタンの戻し先に入らない**
2. ⚙列順設定の中に **「🔴 消し候補の列 6件」expander** を新設し、
   各列の表示状態と否定理由を明記。見たい人はチェックでONにできる
3. 列自体は残す＝「昔これを見ていた」履歴の手掛かりを消さない

⚠ユーザーの保存済み列順(27列)には元々6列とも含まれていなかったので、
既存の表示は一切変わらない。影響するのは「デフォルト」押下時と新規環境のみ。

## 🟡 残した（加点ゼロ化済みだが読み物として価値あり）
DeployScoreLabel / FrontCollapseEffect（[[verified_tenkai_priced_in]]でdeploy_bonusは
加点ゼロ化済み）、AvgPosition / Pos600m（展開マップの入力として内部的に必要）

## 🟢 根拠があり残すべき12列
CorrectedT(荒れ時z10.4) / LTR / SpurtIdx / Lap33 / JPower / OddsGap /
Bloodline / BloodStats / Stress / AxisMark / Signal / RiskFlags

## この棚卸しの意義
検証を重ねると「否定されたのに画面に残る列」が溜まる。
残っていると**誤った判断材料**になるうえ画面幅を食う。
今後も否定が確定したら `_DEPRECATED_COLS` に追記する運用にする。
