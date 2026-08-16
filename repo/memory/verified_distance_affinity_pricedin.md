---
name: verified_distance_affinity_pricedin
description: 「その馬の得意なレース距離(同距離帯の過去3着内実績)」は人気織込み済みでエッジ無し=脚質/PCIと同型
metadata: 
  node_type: memory
  type: project
  originSessionId: ae626662-ddf7-4948-bcf9-cdf9f6a2e414
---

ロジック置き場「その馬の得意なレース距離」(saved_logic_notes.json)の検証(2026-07-19・ユーザー要望)。scripts/distance_affinity_backtest.py・CSV特徴ストア486k行→事前距離適性つき282,741サンプル。

**設計(リーク無し)**: 各馬の過去走(その日より前のみ)から `affinity = 同距離帯の過去top3率 − 全体の過去top3率`(総合力を差し引いた"この距離だけの上振れ")を算出。train(〜2023)で ninki→top3ベースと affinity三分位を凍結、holdout(2024)/2025で得意群/苦手群の人気補正残差を比較。距離帯=短≤1400/M1401-1800/中1801-2200/長2201+。

**結果=priced-in**: 得意−苦手 D は holdout2024 **z-0.06**(全人気)/**z-0.59**(6番人気以下)、2025 z+1.28(全)/z+0.27(6+)。符号が期間で逆転し買い妙味帯(穴馬)は両期間ゼロ。→ 距離適性は人気に織込み済み。[[verified_legtype_axis]](脚質priced-in)/[[verified_pci_pricedin]]と同型。

**How to apply**: 「距離が得意な馬を狙う/距離適性で軸選び」は単独エッジ非採用。距離情報はdist_change等で既にLTR/人気に入っている。俗説隔離(再提案されたら即「検証済み・織込み」と返す)。妙味は[[verified_spurt_index]]/[[project_value_scanner]]/combo系に集約。
