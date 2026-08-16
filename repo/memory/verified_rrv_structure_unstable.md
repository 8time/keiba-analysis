---
name: verified-rrv-structure-unstable
description: C中庸3連単でRank系>人気系は安定(15-20pp差)だが、RRV/RRR/NRV等の個別ファミリーは期間で入替。形の最適化は幻
metadata: 
  node_type: memory
  type: project
  originSessionId: 72da3c77-2988-4dbb-a040-fdbe604e0282
  modified: 2026-08-12T10:22:19.772Z
---

C中庸ゾーンの3連単で「RRV系という構造そのもの」に再現性があるかを
6セクションで検証。scripts/rrv_structure_verify.py

## ファミリー別ROI推移(C中庸 3連単)
| ファミリー | train≤2022 | val 2023-24 | holdout 2025 |
|---|---|---|---|
| RRR | **95%** (#1) | 72% (#3) | 79% (#3) |
| NRV | 89% (#2) | **97%** (#1) | 94% (#2) |
| RRV | 81% (#4) | 66% (#5) | **103%** (#1) |
| NRR | 88% (#3) | 87% (#2) | 73% (#5) |
| NNV | 71% (#5) | 68% (#4) | 81% (#4) |
| NNN | 63% (#6) | 59% (#6) | 57% (#6) |

**順位が完全にシャッフルされる** = 個別ファミリーの優劣は再現しない。

## 安定している境界
- **Rank系(RRR/NRV/RRV/NRR) vs 人気系(NNV/NNN)**: 15-20ppの差が全期間で安定
- NNN(人気×人気×人気)は常に最下位 = C中庸では人気順の買い方は構造的に不利

## 年別RRV ROI
ROI≥100%は10年中1年のみ。中央値81%。SD=15.4%で変動が大きすぎる。

## 判定: C(検証継続)
holdout 103%≥train 81%だがSD高すぎで確信不可。
「C中庸=Rank形」は正しいが「どのRank形」は雑音。

**Why:** ユーザーがpayout_structure_analysis.pyの結果でRRVに注目し最適化を望んだが、
形の固定は選抜バイアスの再来([[verified_formation_sweep_holdout]])。

**How to apply:** C中庸のフォーメーションはRank系ファミリーのどれかを使うが、
特定ファミリーに固定しない。buying_playbookの「C中庸=Rank形」は維持。
[[repo/buying_playbook_2026-08.md]] [[verified_vscore_zone_formation]]
