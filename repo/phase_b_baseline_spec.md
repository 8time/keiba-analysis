# Phase B Research Baseline Spec

## baseline_version

`phase_b_baseline_v1`（`research/splits.py`）

## データ

- 生成: `python scripts/export_features_csv.py`
- 馬行: `data/export/horse_races.csv`
- レース行: `data/export/races.csv`
- 払戻: `data/jravan.db` → `payouts`（join key = `race_key`）
- 標準 split: `research/splits.py`（TRAIN 2016–2023 / VALIDATION 2024 / HOLDOUT 2025+）

## 本番経路（import のみ・ロジック変更なし）

1. `formation_stats.zone_code(vscore)` — D/C/BA（50/70）
2. `bettype_selector.select` — Rule B 券種・playbook
3. `consensus_view.compute_cross_n` — **Projected Score 上位4 ∩ VH 上位4**
4. `playbook_tickets.build_tickets` — D 人気2点 / C LTR 2-3-6 or 2-4-7
5. `elim_engine` — 強適消去残馬（研究: `research/offline_elim.py` + JV 馬名）

## Rank / VH / cross_n / elim

| 要素 | 研究での再現 |
|------|----------------|
| LTR（券面） | **A** — `research/csv_ltr.py` + `data/ltr_model.lgb` |
| VH | **B** — CSV `vh2_score` |
| Projected Score | **C** — CSV 未収録。バッチ未実装 |
| cross_n | proj 無し時は本番同様 `cross_n_source=unavailable` → 0 |
| elim_keep | **部分** — `elim_engine` 実行（proj 無・学習残し OFF）。`elim_n` 列は使わない |

## stake

100円/点固定。Kelly なし。

## parity 判定

**PARTIAL** — LTR+VH+zone+playbook+elim 経路は core 呼び出し。Projected 欠如のため C ゾーンの cross_n / 券種分岐が本番 SRA 完走時と一致しない可能性がある。

## 禁止

- `ability_score` を LTR / Projected の代理にしない
- HOLDOUT を閾値探索に使わない（存在確認のみ）
- Phase A 監査・本番戦略ロジックの変更
