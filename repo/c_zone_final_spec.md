# Cゾーン最終仕様（固定）

## 本番

```
Cゾーン
└─ ROI重視
     └─ 3連複 Rank2-3-6
          └─ 本番採用（変更なし）
```

- 選定ロジック・点数・見送り判定は `core/playbook_tickets.build_tickets` の現行どおり。
- `cross_n ≥ 3` の C セルのみ 2-3-6。

## Shadow（的中率重視）

```
Cゾーン
└─ 的中率重視
     └─ 3連複 Rank2-4-8
          └─ Shadow検証（本番に混ぜない）
```

- 実装: `core/playbook_shadow.py`
- 保存キー: `playbook_shadow_c248`（`data/newspaper/*.bets.json`）
- 予算: **700円/レース**（点数で均等配分。オフライン検証と同じ）
- 対象: C ゾーン & `cross_n ≥ 3` & 本番 playbook `c_ltr_trio_236`
- クロス少（3連単セル）には Shadow を出さない。

## 探索の終了

- 2-4-8 以外の C ゾーン形探索は行わない。
- 過去データの再最適化でルールを変えない。
- Shadow 結果を見ながら途中で Shadow ルールを変えない。

## 再評価

- Shadow 確定レースが **100〜300** 蓄積した時点で再判定。
- それまでは 2-4-8 を本番へ昇格させない。
- 報告: `python scripts/shadow_c248_report.py`
- UI: 📒プレイブック成績 → Shadow 折りたたみ

## SRA 表示（Single Race Analysis）

C ゾーンで本番が 2-3-6 のとき、**選択式にせず2種類を同時表示**する。

```text
Cゾーン
├─ 💰 ROI重視 / 2-3-6 / 【本番】
└─ 🎯 的中率重視 / 2-4-8 / 【Shadow】
```

- ラジオ・セレクト等の切替 UI は置かない
- Shadow は `build_shadow_rec(本番rec)` から表示のみ（本番ロジックは再実行しない）
- 新聞・保存・成績の本番は 2-3-6 のみ

## 禁止事項

- 2-3-6 本番ロジックの変更
- 2-4-8 条件の再探索
- Shadow を本番買い目に混ぜること
