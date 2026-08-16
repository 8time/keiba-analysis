---
name: verified-solid-race-inverse
description: 『堅い/鉄板レースの条件を逆転させれば荒れ精度が上がる』は既存エントロピー・ロジットにpriced-in。堅さ条件は単調だが上乗せAUC+0.0008/残差z+0.2で新規情報ゼロ。較正確認のみ・配線不要
metadata: 
  node_type: memory
  type: project
  originSessionId: 64a070b3-be5e-4051-a8b3-047fbb5b0c0c
---

インフォグラフィック『データで勝つ競馬』/PDF『The Rational Bettor's Blueprint』の
『堅いレース3条件』をユーザーが逆転の発想で荒れ検出に使えないか検証(2026-07-11)。

**Why(検証・scripts/solid_race_inverse_backtest.py・data/export/races.csv・holdout1年)**:
- 堅い条件を定量化: ①1番人気オッズ≤1.9 ②頭数≤12 ③断層(r21≥2.0/1強)。否定=3強(r31≥2.8離れ)。
- Q1較正: 充足数で arareA(3着内7番人気-)が単調低下=57.2%(0個)→45.1→40.7→30.1%(3個)。
  条件は本物で単調。だが**完全堅でも arareA 30.7%/大荒れ arareB 11.1%**=盤石は誇張。
- Q3核心: 既存荒れロジット(scanner_arare_logit・12特徴・AUC0.690)に堅さスコアを足しても
  **上乗せAUC=+0.0008(arareA)/+0.0000(arareB)=ゼロ**。堅さ単体AUCは0.60でロジット以下。
- Q3b残差: 完全堅レースをロジットは予測29.9%・実測30.7%(残差z+0.2)とすでにピタリ。
  非堅も予測57.6%/実測57.2%(z-0.4)。**取りこぼしゼロ=完全にpriced-in**。
- 理由: odds_entropy(主軸coef+0.90)がオッズ分布そのもの。fav1/断層/頭数はその関数で、
  『堅さの逆＝荒れ』は既存の荒れ軸と同一。5段階vlabelも既にこのロジット上に構築済み。

**How to apply(実装しない)**:
- 配線不要(上乗せゼロ)。既存の荒れロジット/vlabel/no_favorite_flagで既にカバー済み。
- ただし較正の副産物として有用: 『完全堅レースでも3割は7番人気以下が3着内に来る』
  =堅レースは軸信頼度/レース選択の道具であって"鉄板保証"ではないと表示上は言える。

関連: [[verified-arare-field-pricedin]](フィールド拮抗priced-in・logit AUC0.69が正本)
[[verified-arare-entropy]](オッズ本命不在=荒れ) [[verified-arare-conditions]](ハンデ/16頭のみ独立)
[[verified-antimarket-elim]](②オッズ断層直下は消し妙味・断層"下"側は別物)
