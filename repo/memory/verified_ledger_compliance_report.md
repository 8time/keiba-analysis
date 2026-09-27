---
name: verified_ledger_compliance_report
description: ledger.db から遵守率・逸脱コスト・見送り正答率を集計するレポート
metadata:
  node_type: memory
  type: project
---

## スクリプト
`scripts/ledger_compliance_report.py`

```powershell
python scripts/ledger_compliance_report.py           # 集計 + CSV
python scripts/ledger_compliance_report.py --schema  # スキーマのみ
python scripts/ledger_compliance_report.py --fetch   # skips 自動評価（任意・要ネット）
```

出力:
- 標準出力 … 人間可読サマリ
- `data/ledger_compliance_report.csv` … 指標一覧（0件でもヘッダのみ生成）

## 指標の定義

### 遵守率
`bets` のうち **検証済み Gate 条件に合致した購入** の割合。

合致（遵守）= すべて満たす:
- `gate_status` = `buy`（`scanner_play_status` の ✅買える。UI 記録の `buy(✅…)` も正規化）
- `has_danger` ≠ 1（危険人気馬を含まない）
- `deviation` が空 or `なし`

分母: `gate_status` が付いている bets（未タグのみの場合は全 bets）

**短期KPIとして優先**。サンプルが少なくても「ルール通り買えているか」は数えられる。

### 逸脱コスト
精算済み (`settled=1`) bets だけを対象。

- 遵守群 ROI = 上記合致 bets の `sum(payout)/sum(stake)×100`
- 逸脱群 ROI = それ以外の settled bets の ROI
- **逸脱コスト** = 遵守 ROI − 逸脱 ROI（pt）

各群の settled 件数が **5 未満** のときは `n不足` と表示し、差の解釈不可（断定しない）。

### 見送り正答率
`skips` のうち **見送って正しかった** 割合。

- 精算済み (`settled=1`) のみ集計
- 正答 = `would_hit=0`（買っていたら外れていた）
- 正答率 = 正答 / 精算済み skips × 100

精算済みが **5 未満** のときは参考値のみ。

#### `--fetch` 時の自動評価（任意）
1. 同一 `race_id` の `bets` があり配当取得できた → その買い目で的中シミュレーション
2. `bets` なし & `score_cache.read_gate` が `skip` → `would_hit=0`（Gate 一致見送り）
3. それ以外 → 未精算のまま（正答率分母に入れない）

## 落とし穴

1. **データが少ない** … 1〜2件で ROI 差や見送り正答率を「改善/悪化」と言わない。遵守率だけ先に見る。
2. **gate_status 未タグ** … Scanner スキャン前の購入は遵守率の分母・分子がブレる。SRA/Scanner 後の記録を推奨。
3. **全頭 Brier 記録** … 100円×全頭の較正用記録は「実購入」ではない。`stake` パターンで区別するか、実購入のみ運用する。
4. **二重記録** … 購入確定と「次のレースを追加」の両方で bets が増えると ROI が歪む（[[verified_ledger_write]] 参照）。
5. **見送り正答率は would_hit 依存** … 手動答え合わせ（BetSync 見送りタブ）が最も正確。`--fetch` は補助。
6. **的中率は見ない** … 本レポートは短期 KPI として遵守率を主役にしている（ユーザー方針）。

## スキーマ（正本: ledger.db）

### bets
`bet_id, ts, race_id, umaban, bamei, pred_prob, odds, stake, bet_type, settled, won, payout, gate_status, gate_lean, gate_severity, n_points, synth_odds, has_danger, has_value_ana, mood, deviation`

### skips
`skip_id, ts, race_id, reason, vscore, zone, mood, settled, would_hit, would_payout, note`

## 関連
- 記録配線: [[verified_ledger_write]]
- Gate 定義: `core/value_scanner.py` `scanner_play_status`
- 逸脱分類: `core/money.py` `Ledger.classify_loss`
