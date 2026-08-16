---
name: verified-cross-table-structure
description: 人気×VHはρ=0.94で二重計上。top-5内ρ=0.16でVHは独立再順位付け。4軸クロスは3軸より劣化。VH範囲制限は不要
metadata: 
  node_type: memory
  type: project
  originSessionId: 72da3c77-2988-4dbb-a040-fdbe604e0282
  modified: 2026-08-12T10:22:02.196Z
---

「ダブルクロスルーレット」(複数軸の一致度で3着候補を選別)を競馬に応用する
必要性を6セクションで検証。scripts/cross_table_verify.py

## 主要発見

1. **人気×VHの相関**: Spearman ρ=0.94(全馬)→ 4軸クロスに両方入れると二重計上。
   ただし**top-5内ではρ=0.16** → VHは人気上位の中での品質再順位付けとして独立情報を持つ

2. **4軸(人気+Rank+VH+妙味) vs 3軸(人気+Rank+VH)**:
   4-cross 3着捕捉30.9% < 3-cross 44.8%。妙味軸を足すと悪化する

3. **最良の組み合わせ**: 人気◎+Rank◎+VH◎+妙味△(妙味は除外条件として使用) = 46.0%

4. **VH人気範囲**: 人気1-6に制限すると3着捕捉が8.8pp低下(68.1% vs 76.9%)。制限すべきでない。
   VH top-7の構成: 人気1-3=42.4% / 4-6=41.5% / 7-9=16.0% / 10+=0.1%

5. **Rankの特性**: 全ポジションで捕捉率は最低だが、異なる馬を選ぶ→高配当に繋がる

## 実装(2026-08-12)
consensus_view.integrate()にrank_pos(LTR降順)とvh_pos(vh2_score降順)を追加。
R≤5かつV≤5の馬に🔵マーカー(cross_rv)。app.pyの強適テーブルにR/V/R×V列を追加。
「R◎+V◎の交差点にいる3着馬の39%」とキャプションに明記。

**Why:** VHは人気と高相関だが、top-5内では独立した再順位付け機能を持つ。
この独立性を可視化する列がなかった。

**How to apply:** 4軸均等クロスは使わない。VH範囲を人気で制限しない。
妙味は軸選択ではなくレース選択(ゾーン)で使う。
[[project_consensus_view]] [[project_value_horse_hunter]]
